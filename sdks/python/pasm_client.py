"""pasm-framework Python 客户端（零依赖，标准库 urllib）。

**Python 项目通常不需要这个文件** —— 同进程直接
``from pasm_framework import SimpleApplication`` 更快，还能用到
``Capability`` / ``DomainAdapter`` 等高级表面。
本客户端用于：跨进程/跨机调用、或对接**别人的** pasm-framework 服务。

用法::

    from pasm_client import PasmClient, PasmError

    c = PasmClient("http://127.0.0.1:8080", token="your-secret")
    print(c.chat("怎么退货？", session_id="user-1"))
    c.ingest([{"title": "退货政策", "content": "7 天内无理由退货。", "source": "faq"}])
    print(c.kb_stats())
    print(c.health())
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class PasmError(Exception):
    """统一的调用错误。

    ``status`` 为 HTTP 状态码（网络层失败时为 0）；
    ``hint`` 是服务端给出的修复建议（若提供）。
    """

    def __init__(self, message: str, status: int = 0, hint: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover
        base = super().__str__()
        return "%s（HTTP %s）%s" % (base, self.status,
                                   ("  提示：%s" % self.hint) if self.hint else "")


class PasmClient:
    """pasm-framework HTTP 网关的客户端。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8080",
                 token: Optional[str] = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    # ---- 底层 ----
    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
            out = json.loads(body)
            return out if isinstance(out, dict) else {"data": out}
        except urllib.error.HTTPError as ex:
            raw = ex.read().decode("utf-8", "ignore") or "{}"
            try:
                obj = json.loads(raw)
            except Exception:
                obj = {"error": raw[:200]}
            raise PasmError(obj.get("error", "请求失败"), ex.code,
                            obj.get("hint", "")) from ex
        except urllib.error.URLError as ex:
            raise PasmError("无法连接 pasm-framework 服务：%s" % ex.reason, 0,
                            "确认服务已启动、地址与端口正确") from ex

    # ---- 业务 ----
    def chat(self, text: str, session_id: str = "default",
             user_id: Optional[str] = None,
             meta: Optional[Dict[str, Any]] = None) -> str:
        """发一条消息，返回回复文本。"""
        payload: Dict[str, Any] = {"text": text, "session_id": session_id}
        if user_id is not None:
            payload["user_id"] = user_id
        if meta is not None:
            payload["meta"] = meta
        return self._request("POST", "/api/chat", payload).get("reply", "")

    def chat_stream(self, text: str, session_id: str = "default",
                    user_id: Optional[str] = None,
                    meta: Optional[Dict[str, Any]] = None):
        """流式发送，逐条产出事件字典。

        事件：``{"type":"delta","text":…}`` / ``{"type":"replace","text":…}`` /
        ``{"type":"done",…}`` / ``{"type":"error",…}``。

        用法::

            acc = ""
            for ev in c.chat_stream("你好"):
                if ev["type"] == "delta":
                    acc += ev["text"]; print(ev["text"], end="", flush=True)
                elif ev["type"] == "replace":     # 护栏改写过内容 → 整条替换
                    acc = ev["text"]
        """
        payload: Dict[str, Any] = {"text": text, "session_id": session_id}
        if user_id is not None:
            payload["user_id"] = user_id
        if meta is not None:
            payload["meta"] = meta
        url = self.base_url + "/api/chat/stream"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "text/event-stream"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as ex:
            raw = ex.read().decode("utf-8", "ignore") or "{}"
            try:
                obj = json.loads(raw)
            except Exception:
                obj = {"error": raw[:200]}
            raise PasmError(obj.get("error", "请求失败"), ex.code,
                            obj.get("hint", "")) from ex
        except urllib.error.URLError as ex:
            raise PasmError("无法连接 pasm-framework 服务：%s" % ex.reason, 0,
                            "确认服务已启动、地址与端口正确") from ex
        # 逐行读 SSE（服务端以 EOF 结束流，不用 Content-Length）。
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk:
                    continue
                try:
                    yield json.loads(chunk)
                except Exception:
                    continue

    def ingest(self, items: List[Dict[str, Any]]) -> int:
        """批量写入资料库，返回新增条数（需服务端启用 knowledge_base）。"""
        return int(self._request("POST", "/api/ingest", {"items": items})
                   .get("added", 0))

    def reset_session(self, session_id: str) -> bool:
        return bool(self._request("POST", "/api/sessions/reset",
                                  {"session_id": session_id}).get("ok"))

    def kb_stats(self) -> Dict[str, Any]:
        return self._request("GET", "/api/kb/stats")

    def plugins(self) -> Dict[str, Any]:
        return self._request("GET", "/api/plugins")

    def summary(self) -> Dict[str, Any]:
        return self._request("GET", "/api/summary")

    def health(self) -> Dict[str, Any]:
        """健康检查（免鉴权）。"""
        return self._request("GET", "/healthz")


if __name__ == "__main__":  # 手工冒烟
    import sys
    cli = PasmClient(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080",
                     sys.argv[2] if len(sys.argv) > 2 else None)
    print("health:", cli.health().get("status"))
    print("reply :", cli.chat("怎么退货？"))
