"""认知 HTTP API —— 把 ``pasm_skills.cognition.Capabilities`` 挂到 HTTP 上。

为什么需要它
------------
`web_gateway` 原本只暴露「客服形态」的接口（chat / ingest / sessions / kb.stats）。
**记忆、情绪、成长**这套认知能力此前只在 MCP（stdio）通道上 ——
于是任何非 MCP 的客户端（Spring Boot、Vue 后端、桌面端、脚本）都拿不到它们。

本模块把认知能力补到 HTTP 上，让「认知服务」可以脱离 MCP 被任意语言调用。

三条设计约束
------------
1. **不新开端口、不新造鉴权**：本类不是插件，由 :class:`WebGatewayPlugin` 持有，
   复用同一台 HTTP 服务器与同一套令牌/限流 —— 否则认知接口会成为一个鉴权洼地。
2. **不做第二份实现**：一切逻辑转发给 ``Capabilities``（`pasm-skills` 里的唯一实现）。
   同源两份代码是这个项目踩过的坑，这里绝不再犯。
3. **降级要诚实**：认知层不可用时返回 503 + 明确的安装提示，绝不假装成功。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

#: 认知能力门面（pasm-skills >= 0.6.0）。装了就用，没装则整个前缀返回 503。
try:                                                              # pragma: no cover
    from pasm_skills.cognition import AgentRegistry, Capabilities
    _HAS_CAPS = True
except Exception:                                                 # pragma: no cover
    AgentRegistry = None                                          # type: ignore
    Capabilities = None                                           # type: ignore
    _HAS_CAPS = False


def _as_bool(v: Any, dflt: bool = True) -> bool:
    if v is None or v == "":
        return dflt
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _as_int(v: Any, dflt: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return dflt


class CognitiveAPI:
    """认知 API 的 HTTP 适配器。

    ``dispatch()`` 返回 ``(status, payload)``；``None`` 表示「不是本模块的路由」，
    交回网关继续处理（这样网关的路由表不必知道认知接口的细节）。
    """

    PREFIX = "/api/cog/"

    def __init__(self, persist_root: Optional[str] = None,
                 default_persona: Optional[Dict[str, Any]] = None,
                 agent_cls: Optional[Any] = None) -> None:
        self._err: Optional[str] = None
        self._caps: Optional[Any] = None
        if not _HAS_CAPS:
            self._err = ("未安装认知层：pip install -U 'pasm-skills>=0.6.0' "
                         "可启用 /api/cog/*")
            return
        try:
            kw: Dict[str, Any] = {}
            if persist_root:
                kw["persist_root"] = persist_root
            if default_persona:
                kw["default_persona"] = default_persona
            if agent_cls is not None:
                kw["agent_cls"] = agent_cls
            self._caps = Capabilities(AgentRegistry(**kw))
        except Exception as ex:                                   # noqa: BLE001
            self._err = "认知层初始化失败：%s" % ex

    # ---------------------------------------------------------- 元信息

    @property
    def available(self) -> bool:
        return self._caps is not None

    def error(self) -> Optional[str]:
        return self._err

    def operations(self) -> List[str]:
        return list(self._caps.operations()) if self._caps else []

    def capabilities_info(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "prefix": self.PREFIX,
            "operations": self.operations(),
            "error": self._err,
            "note": ("认知能力的共享实现位于 pasm_skills.cognition.Capabilities，"
                     "本 HTTP 表面与桌面/脚本表面都转发到它。"
                     "⚠️ pasm-mcp-server 目前仍是自己那份实现，尚未委托过来 —— "
                     "改认知语义时两处都要动，直到 MCP 侧完成迁移。"),
        }

    # ---------------------------------------------------------- 分派

    def dispatch(self, method: str, path: str, query: str,
                 body: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        """处理 ``/api/cog/*``。不是本前缀则返回 ``None``。"""
        if not path.startswith(self.PREFIX):
            return None

        op = path[len(self.PREFIX):].strip("/")

        # 元信息类：即使认知层缺席也要能答，方便客户端做能力探测。
        if op in ("", "capabilities"):
            return 200, self.capabilities_info()
        if op == "operations":
            return 200, {"available": self.available,
                         "operations": self.operations(), "error": self._err}

        if not self.available:
            return 503, {"error": "cognitive layer unavailable",
                         "hint": self._err,
                         "op": op}
        if op not in self.operations():
            return 404, {"error": "unknown cognitive op", "op": op,
                         "operations": self.operations()}

        q = {k: v[-1] for k, v in parse_qs(query or "").items() if v}
        merged: Dict[str, Any] = dict(q)
        merged.update(body or {})
        try:
            return 200, self._call(method, op, merged)
        except ValueError as ex:                  # 参数错 → 400（客户端可自行纠错）
            return 400, {"error": str(ex), "op": op}
        except Exception as ex:                   # noqa: BLE001
            return 500, {"error": "%s: %s" % (type(ex).__name__, ex), "op": op}

    def _call(self, method: str, op: str, a: Dict[str, Any]) -> Dict[str, Any]:
        caps = self._caps
        assert caps is not None
        aid = str(a.get("agent_id") or "default")

        if op == "context":
            return caps.context(aid, query=str(a.get("query") or ""),
                                k=_as_int(a.get("k"), 5))
        if op == "recall":
            return caps.recall(aid, query=str(a.get("query") or ""),
                               k=_as_int(a.get("k"), 5))
        if op == "semantic":
            return caps.semantic(aid, query=str(a.get("query") or ""),
                                 k=_as_int(a.get("k"), 5),
                                 use_focus=_as_bool(a.get("use_focus"), True),
                                 use_forgetting=_as_bool(a.get("use_forgetting"), True))
        if op == "focus":
            ents = a.get("entities")
            if isinstance(ents, str):
                ents = [x for x in ents.split(",") if x]
            return caps.focus(aid, topic=str(a.get("topic") or ""),
                              entities=ents or [],
                              weight=float(a.get("weight") or 1.0),
                              n=_as_int(a.get("n"), 3))
        if op == "status":
            return caps.status(aid)
        if op == "observe":
            tags = a.get("tags")
            if isinstance(tags, str):
                tags = [x for x in tags.split(",") if x]
            return caps.observe(aid, title=str(a.get("title") or ""),
                                brief=str(a.get("brief") or ""),
                                tags=tags or [],
                                salience=_as_int(a.get("salience"), 2),
                                category=str(a.get("category") or "日常"))
        if op == "feel":
            return caps.feel(aid, event=str(a.get("event") or ""),
                             valence=float(a.get("valence") or 0.0))
        if op == "act":
            cands = a.get("candidates")
            if isinstance(cands, str):
                cands = [x for x in cands.split(",") if x]
            return caps.act(aid, candidates=cands)
        if op == "feedback":
            action = a.get("action")
            return caps.feedback(aid, kind=str(a.get("kind") or ""),
                                 action=str(action) if action else None)
        if op == "consolidate":
            return caps.consolidate(aid, apply=_as_bool(a.get("apply"), False))
        if op == "chat":
            return caps.chat(aid, text=str(a.get("text") or ""))
        if op == "persona":
            patch = a.get("persona")
            return caps.persona(aid, patch if isinstance(patch, dict) else None)
        if op == "save":
            return caps.save(aid if a.get("agent_id") else None)
        raise ValueError("未实现的操作：%s" % op)          # pragma: no cover

    # ---------------------------------------------------------- 生命周期

    def save_all(self) -> List[str]:
        if not self.available:
            return []
        try:
            return self._caps.save(None).get("saved", [])     # type: ignore[union-attr]
        except Exception:                                     # noqa: BLE001
            return []


# ============================================================ 自检

def selftest() -> bool:
    """自检：不启服务器，直接走 dispatch()，并带反例。"""
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="pasm-cogapi-")
    ok = fail = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok, fail
        if cond:
            ok += 1
            print("  v %s" % name)
        else:
            fail += 1
            print("  x %s%s" % (name, ("  <- " + detail) if detail else ""))

    print("web_gateway.cognitive_api 自检")
    print("-" * 60)
    try:
        api = CognitiveAPI(persist_root=tmp)
        check("认知层可用", api.available, str(api.error()))

        # 非本前缀必须交回网关（返回 None），否则会抢掉别的路由
        check("非 /api/cog 前缀返回 None（不抢路由）",
              api.dispatch("GET", "/api/chat", "", {}) is None)

        st, info = api.dispatch("GET", "/api/cog/capabilities", "", {})   # type: ignore
        check("capabilities 可探测", st == 200 and info["available"] is True, str(info))

        st, r = api.dispatch("POST", "/api/cog/observe",
                             "", {"agent_id": "p1", "title": "高血压",
                                  "tags": ["慢病"], "salience": 4})       # type: ignore
        check("observe 写入成功", st == 200 and r.get("ok") is True, str(r))

        st, r = api.dispatch("GET", "/api/cog/recall",
                             "agent_id=p1&query=%E8%A1%80%E5%8E%8B", {})  # type: ignore
        check("query 走 URL 参数也能检索", st == 200 and r.get("count", 0) >= 1, str(r))

        # 反例：参数错必须 400，不能 200 + 空结果（否则调用方会把"参数漏了"当"没数据"）
        st, r = api.dispatch("POST", "/api/cog/feel",
                             "", {"agent_id": "p1", "event": ""})         # type: ignore
        check("缺 event → 400（不是静默 200）", st == 400, "%s %s" % (st, r))

        st, r = api.dispatch("POST", "/api/cog/feedback",
                             "", {"agent_id": "p1", "kind": "nope"})      # type: ignore
        check("非法 kind → 400", st == 400, "%s %s" % (st, r))

        st, r = api.dispatch("GET", "/api/cog/nosuchop", "", {})          # type: ignore
        check("未知操作 → 404 且列出可用操作",
              st == 404 and "operations" in r, str(r))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 60)
    print("结果：%d 项通过，%d 项失败" % (ok, fail))
    return fail == 0


if __name__ == "__main__":                                        # pragma: no cover
    import sys
    sys.exit(0 if selftest() else 1)
