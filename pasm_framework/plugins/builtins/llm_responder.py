"""llm_responder —— 可选 LLM 接入插件（零强制依赖，懒接入）。

让产品智能体"真正会说话"：在不改 ``BaseApplication`` 的前提下，
把自然语言回复交给外部 LLM（OpenAI 兼容 / DeepSeek / Ollama 本地）。

设计要点
--------
  · **零强制依赖**：用标准库 ``urllib`` 发 HTTP，装了 ``openai`` 也能用，
    两者都没有时本插件安全退场（msg.reply 留空 → 回落 chat 模板）。
  · **默认关闭**：需要密钥 / 网络，故 ``default_config`` 里 ``enabled=False``；
    用户通过后端配置显式开启。
  · **永不崩**：任何异常都静默失败、保留模板兜底，不让线上服务挂掉。
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext


_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434",
}


class LLMResponderPlugin(BasePlugin):
    """把自然语言回复交给外部 LLM。"""

    name = "llm_responder"
    version = "0.1.0"

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
        self._system_prompt: str = str(self.config.get(
            "system_prompt",
            "你是{persona_name}，一位{persona_role}。请用自然、专业、有温度的中文回答用户。"
            "仅依据给定资料作答，资料没有的就如实说不知道，不要编造。"))

    # ---- 请求构造 ----
    def _system(self, ctx: PluginContext) -> str:
        p = ctx.persona()
        name = p.get("name", "智能助手")
        role = p.get("role", "AI 助手")
        return self._system_prompt.format(persona_name=name, persona_role=role)

    def _messages(self, ctx: PluginContext) -> List[Dict[str, str]]:
        msgs: List[Dict[str, str]] = [{"role": "system", "content": self._system(ctx)}]
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

    def _post(self, payload: Dict[str, Any], url: str, headers: Dict[str, str]) -> Optional[str]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
            return self._parse(body)
        except urllib.error.HTTPError as ex:
            ctx_err = ex.read().decode("utf-8", "ignore")[:300]
            self._last_error = "HTTP %s: %s" % (ex.code, ctx_err)
        except Exception as ex:  # noqa: BLE001
            self._last_error = str(ex)
        return None

    def _parse(self, body: str) -> Optional[str]:
        try:
            obj = json.loads(body)
        except Exception:
            return None
        if self._provider == "ollama":
            return (obj.get("message") or {}).get("content")
        choices = obj.get("choices") or []
        if choices:
            return (choices[0].get("message") or {}).get("content")
        return None

    # ---- Hook ----
    def on_reply(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        # 若已有回复（能力路由 or 其它插件生成），默认不再覆盖。
        if msg.reply and self.config.get("skip_if_reply", True):
            return
        if not self._base_url:
            return
        if self._provider == "openai" and not self._api_key:
            return
        url = self._base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if self._provider in ("openai", "deepseek"):
            if not self._api_key:
                return
            headers["Authorization"] = "Bearer %s" % self._api_key
            url += "/chat/completions"
            payload = {
                "model": self._model,
                "messages": self._messages(ctx),
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            }
        elif self._provider == "ollama":
            url += "/api/chat"
            payload = {
                "model": self._model,
                "messages": self._messages(ctx),
                "stream": False,
                "options": {"temperature": self._temperature},
            }
        else:
            self._last_error = "未知 provider: %s" % self._provider
            return
        reply = self._post(payload, url, headers)
        if reply:
            msg.set_reply(reply.strip())
