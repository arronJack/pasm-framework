"""llm_responder —— 可选 LLM 接入插件（零强制依赖，懒接入）。

让产品智能体"真正会说话"：在不改 ``BaseApplication`` 的前提下，
把自然语言回复交给外部 LLM（OpenAI 兼容 / DeepSeek / Ollama 本地）。

设计要点
--------
  · **零强制依赖**：用标准库 ``urllib`` 发 HTTP，装了 ``openai`` 也能用，
    两者都没有时本插件安全退场（``msg.reply`` 留空 → 回落 chat 模板）。
  · **默认关闭**：需要密钥 / 网络，故 ``_DEFAULT_ENABLED`` 里 ``False``；
    用户通过后端配置显式开启。
  · **永不崩**：任何异常都静默失败、保留模板兜底，不让线上服务挂掉。
  · **真流式**（v0.3.0）：``Message.stream_sink`` 非空时按上游 SSE 增量外推，
    首字延迟从"整段生成完"降到"首 token"。
  · **多轮工具调用**（v0.3.0）：应用的能力（``Capability``）自动暴露成
    function tools，支持 ``tool_calls → 本地执行 → 回填 → 再请求`` 的环；
    上游不支持 ``tools`` 时自动降级为纯对话。

后端配置
--------
  · ``provider``       ``openai`` / ``deepseek`` / ``ollama`` / 其它（视为 OpenAI 兼容）
  · ``base_url``       服务地址（缺省按 provider 取官方地址）
  · ``api_key``        密钥（也可用环境变量 ``PASM_LLM_API_KEY`` / ``OPENAI_API_KEY`` /
                       ``DEEPSEEK_API_KEY``）；``ollama`` 与 OpenAI 兼容本地服务可免
  · ``model`` / ``temperature`` / ``max_tokens`` / ``timeout`` / ``system_prompt``
  · ``tools``          bool，是否把应用能力暴露为 tools（默认 ``True``）
  · ``max_tool_rounds`` int，工具调用最大轮数（默认 ``3``；``0`` = 关闭工具）
  · ``stream``         bool，是否向上游请求流式（默认 ``True``）
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ..core import BasePlugin, Message, PluginContext


_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434",
}

#: OpenAI 规定 tool 名必须匹配 ^[a-zA-Z0-9_-]{1,64}$
_TOOL_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _tool_name(raw: str, index: int) -> str:
    """把能力名转成合法的 tool 名。

    中文能力名（如"广告设计"）不符合 OpenAI 的命名约束，故回退为
    ``cap_<序号>``；原始中文名会写进 tool 的 ``description``，
    模型依然能正确选择要调用哪个能力。
    """
    s = _TOOL_UNSAFE.sub("", raw or "").strip("-")
    if not s:
        s = "cap_%d" % index
    return s[:64]


def _iter_frames(resp: Any, provider: str) -> Iterator[Dict[str, Any]]:
    """逐帧解析上游流。

    · OpenAI 兼容：SSE（``data: {...}``，以 ``data: [DONE]`` 结束）
    · Ollama：NDJSON（每行一个 JSON 对象）
    """
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        if provider == "ollama":
            try:
                yield json.loads(line.decode("utf-8"))
            except Exception:
                continue
            continue
        if line.startswith(b":"):            # SSE 注释/心跳
            continue
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            yield json.loads(payload.decode("utf-8"))
        except Exception:
            continue


class LLMResponderPlugin(BasePlugin):
    """把自然语言回复交给外部 LLM（支持真流式与多轮工具调用）。"""

    name = "llm_responder"
    version = "0.3.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._provider: str = str(self.config.get("provider", "openai")).lower()
        self._base_url: str = str(self.config.get("base_url")
                                  or _DEFAULT_BASE.get(self._provider, ""))
        self._model: str = str(self.config.get("model", "gpt-4o-mini"))
        self._api_key: Optional[str] = (
            self.config.get("api_key")
            or os.environ.get("PASM_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
        )
        self._temperature: float = float(self.config.get("temperature", 0.7))
        self._max_tokens: int = int(self.config.get("max_tokens", 800))
        self._timeout: int = int(self.config.get("timeout", 30))
        self._tools_on: bool = bool(self.config.get("tools", True))
        self._max_tool_rounds: int = max(0, int(self.config.get("max_tool_rounds", 3)))
        self._stream_on: bool = bool(self.config.get("stream", True))
        self._system_prompt: str = str(self.config.get(
            "system_prompt",
            "你是{persona_name}，一位{persona_role}。请用自然、专业、有温度的中文回答用户。"
            "仅依据给定资料作答，资料没有的就如实说不知道，不要编造。"))
        self._last_error: Optional[str] = None
        self._tools_rejected = False         # 上游不支持 tools 时置位，避免反复试错
        self._stats: Dict[str, int] = {
            "requests": 0, "streamed_chars": 0, "tool_calls": 0, "errors": 0,
        }

    # ---- 请求构造 ----
    def _system(self, ctx: PluginContext) -> str:
        p = ctx.persona()
        name = p.get("name", "智能助手")
        role = p.get("role", "AI 助手")
        try:
            return self._system_prompt.format(persona_name=name, persona_role=role)
        except Exception:                            # 用户自定模板里的大括号写错也不该崩
            return self._system_prompt

    def _messages(self, ctx: PluginContext) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": self._system(ctx)}]
        # 注入检索到的资料（情景 + 领域 + 知识库）。
        facts = ctx.message.facts or []
        if facts:
            knowledge = "\n".join(
                "- %s：%s" % (f.get("title", ""), f.get("brief", ""))
                for f in facts[:8] if f.get("brief")
            )
            if knowledge:
                msgs.append({
                    "role": "system",
                    "content": "参考资料（请优先据此回答）：\n%s" % knowledge,
                })
        # 会话历史（sessions 插件注入）。
        hist = ctx.store.get("session_history") or []
        for m in hist[-10:]:
            role = "assistant" if m.get("role") == "assistant" else "user"
            msgs.append({"role": role, "content": str(m.get("text", ""))})
        # 当前用户问题。
        msgs.append({"role": "user", "content": ctx.message.text})
        return msgs

    # ---- 工具（把应用能力暴露成 function tools）----------------
    def _tool_specs(self, ctx: PluginContext) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """返回 (OpenAI tools 列表, tool名 → 能力名 映射)。"""
        app = ctx.app
        discover = getattr(app, "capabilities", None)
        if discover is None or not self._tools_on or self._tools_rejected:
            return [], {}
        specs: List[Dict[str, Any]] = []
        mapping: Dict[str, str] = {}
        try:
            names = list(discover.names())
        except Exception:
            return [], {}
        for i, cap_name in enumerate(names, 1):
            try:
                cap = discover.get(cap_name)
            except Exception:
                continue
            if cap is None:
                continue
            tname = _tool_name(cap_name, i)
            if tname in mapping:
                tname = "%s_%d" % (tname, i)
            mapping[tname] = cap_name
            desc = getattr(cap, "description", "") or ""
            specs.append({
                "type": "function",
                "function": {
                    "name": tname,
                    "description": ("应用能力「%s」%s" % (cap_name, ("：" + desc) if desc else ""))[:512],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "用户想要执行这件事的原话（尽量保留原始措辞）",
                            },
                        },
                        "required": ["text"],
                    },
                },
            })
        return specs, mapping

    def _run_tool(self, ctx: PluginContext, mapping: Dict[str, str],
                  call: Dict[str, Any]) -> str:
        """执行一次工具调用（落到应用能力上）。失败也返回文本，让模型继续。"""
        cap_name = mapping.get(call.get("name", ""))
        if not cap_name:
            return "错误：未知工具 %s" % call.get("name")
        try:
            cap = ctx.app.capabilities.get(cap_name)
        except Exception:
            cap = None
        if cap is None:
            return "错误：能力 %s 不存在" % cap_name
        args = call.get("args") or {}
        text = str(args.get("text") or ctx.message.text)
        try:
            out = cap.run(ctx.app, text)
        except Exception as ex:                      # noqa: BLE001
            return "错误：能力 %s 执行失败（%s）" % (cap_name, ex)
        self._stats["tool_calls"] += 1
        return str(out or "")

    # ---- HTTP ----
    def _endpoint(self) -> Tuple[Optional[str], Dict[str, str]]:
        base = self._base_url.rstrip("/")
        if not base:
            return None, {}
        headers = {"Content-Type": "application/json"}
        if self._provider == "ollama":
            url = base if base.endswith("/api/chat") else base + "/api/chat"
            return url, headers
        # openai / deepseek / 其它 OpenAI 兼容服务
        if self._provider in ("openai", "deepseek") and not self._api_key:
            return None, {}
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        if self._api_key:
            headers["Authorization"] = "Bearer %s" % self._api_key
        return url, headers

    def _payload(self, msgs: List[Dict[str, Any]], *,
                 tools: List[Dict[str, Any]], stream: bool) -> Dict[str, Any]:
        if self._provider == "ollama":
            p: Dict[str, Any] = {
                "model": self._model, "messages": msgs, "stream": stream,
                "options": {"temperature": self._temperature},
            }
            if tools:
                p["tools"] = tools
            return p
        p = {
            "model": self._model, "messages": msgs,
            "temperature": self._temperature, "max_tokens": self._max_tokens,
        }
        if stream:
            p["stream"] = True
        if tools:
            p["tools"] = tools
            p["tool_choice"] = "auto"
        return p

    def _consume_stream(self, resp: Any,
                        sink: Optional[Callable[[str], None]]) -> Dict[str, Any]:
        """读流式响应：内容增量实时外推，工具调用增量按 index 拼装。"""
        parts: List[str] = []
        slots: Dict[int, Dict[str, str]] = {}
        for obj in _iter_frames(resp, self._provider):
            piece = ""
            if self._provider == "ollama":
                piece = str((obj.get("message") or {}).get("content") or "")
            else:
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or choices[0].get("message") or {}
                piece = str(delta.get("content") or "")
                for tc in (delta.get("tool_calls") or []):
                    idx = int(tc.get("index", 0) or 0)
                    slot = slots.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = str(tc["id"])
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = str(fn["name"])
                    if fn.get("arguments"):
                        slot["arguments"] += str(fn["arguments"])
            if piece:
                parts.append(piece)
                self._stats["streamed_chars"] += len(piece)
                if sink is not None:
                    try:
                        sink(piece)
                    except Exception:                # 下游断开不该让生成崩掉
                        pass
        return {"content": "".join(parts), "calls": self._finalize_calls(slots)}

    @staticmethod
    def _finalize_calls(slots: Dict[int, Dict[str, str]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for idx in sorted(slots):
            s = slots[idx]
            try:
                args = json.loads(s["arguments"] or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {"text": str(args)}
            out.append({"id": s["id"] or ("call_%d" % idx),
                        "name": s["name"], "args": args})
        return out

    def _parse_full(self, body: str) -> Dict[str, Any]:
        try:
            obj = json.loads(body)
        except Exception:
            return {"content": "", "calls": []}
        if self._provider == "ollama":
            m = obj.get("message") or {}
            calls = []
            for c in (m.get("tool_calls") or []):
                fn = c.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"text": args}
                calls.append({"id": c.get("id") or "call_0",
                              "name": fn.get("name") or "", "args": args or {}})
            return {"content": str(m.get("content") or ""), "calls": calls}
        choices = obj.get("choices") or []
        if not choices:
            return {"content": "", "calls": []}
        m = choices[0].get("message") or {}
        calls = []
        for c in (m.get("tool_calls") or []):
            fn = c.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"text": args}
            calls.append({"id": c.get("id") or "call_0",
                          "name": fn.get("name") or "", "args": args or {}})
        return {"content": str(m.get("content") or ""), "calls": calls}

    def _round(self, payload: Dict[str, Any], url: str, headers: Dict[str, str],
               *, stream: bool, sink: Optional[Callable[[str], None]]) -> Dict[str, Any]:
        """发一次请求，返回 ``{"ok", "content", "calls", "bad_request"}``。"""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        self._stats["requests"] += 1
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if stream:
                    got = self._consume_stream(resp, sink)
                else:
                    got = self._parse_full(resp.read().decode("utf-8"))
            return {"ok": True, "bad_request": False, **got}
        except urllib.error.HTTPError as ex:
            detail = ex.read().decode("utf-8", "ignore")[:300]
            self._last_error = "HTTP %s: %s" % (ex.code, detail)
            self._stats["errors"] += 1
            # 400 多半是上游不认识 tools/stream → 交给上层降级重试。
            return {"ok": False, "bad_request": ex.code == 400,
                    "content": "", "calls": []}
        except Exception as ex:                      # noqa: BLE001
            self._last_error = str(ex)
            self._stats["errors"] += 1
            return {"ok": False, "bad_request": False, "content": "", "calls": []}

    # ---- Hook ----
    def on_reply(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        # 若已有回复（能力路由 or 其它插件生成），默认不再覆盖。
        if msg.reply and self.config.get("skip_if_reply", True):
            return
        url, headers = self._endpoint()
        if url is None:
            return

        sink = msg.stream_sink
        msgs = self._messages(ctx)
        specs, mapping = self._tool_specs(ctx)
        rounds = self._max_tool_rounds if specs else 0
        want_stream = bool(sink) and self._stream_on

        content = ""
        for i in range(rounds + 1):
            use_tools = specs if i < rounds else []
            payload = self._payload(msgs, tools=use_tools, stream=want_stream)
            got = self._round(payload, url, headers, stream=want_stream, sink=sink)

            if not got["ok"]:
                if got["bad_request"] and (use_tools or want_stream):
                    # 降级：上游不支持 tools / stream → 换纯对话再试一次。
                    if use_tools:
                        self._tools_rejected = True
                        specs = []
                    if want_stream:
                        self._stream_on = False
                        want_stream = False
                    payload = self._payload(msgs, tools=[], stream=want_stream)
                    got = self._round(payload, url, headers,
                                      stream=want_stream, sink=sink)
                if not got["ok"]:
                    return

            calls = got["calls"]
            if calls and use_tools:
                # 回填 assistant(tool_calls) + tool(结果)，进入下一轮。
                msgs.append({
                    "role": "assistant",
                    "content": got["content"] or "",
                    "tool_calls": [
                        {"id": c["id"], "type": "function",
                         "function": {"name": c["name"],
                                      "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                        for c in calls
                    ],
                })
                for c in calls:
                    msgs.append({"role": "tool", "tool_call_id": c["id"],
                                 "content": self._run_tool(ctx, mapping, c)})
                continue

            content = got["content"] or ""
            break

        if content:
            msg.set_reply(content.strip())

    # ---- 可观测 ----
    def stats(self) -> Dict[str, Any]:
        return dict(self._stats, provider=self._provider, model=self._model,
                    tools=self._tools_on and not self._tools_rejected,
                    stream=self._stream_on, last_error=self._last_error)
