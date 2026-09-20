"""web_gateway —— 零依赖 HTTP 网关插件（iframe / REST / 外部链接）。

让 pasm-framework 的 AI 应用"对外可接入"：站点用一行 ``<iframe>`` 即可嵌入智能客服，
或用 REST API / 脚本对接。完全用标准库 ``http.server``，不引入任何 Web 框架。

提供
----
  · ``POST /api/chat``   —— ``{text, session_id, user_id}`` → ``{reply, facts, session_id}``
  · ``GET  /healthz``    —— 健康 + 指标（来自 observability 插件）
  · ``GET  /`` 或 ``/widget`` —— 自包含的可嵌入聊天 Widget（HTML，向 /api/chat 发请求）

默认 ``enabled=False``（需要端口）；用户通过后端配置开启后调用 ``app.serve()`` 启动。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from ..core import BasePlugin, Message, PluginContext


_WIDGET_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>智能客服</title><style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f7fb}
.box{display:flex;flex-direction:column;height:100vh;max-width:480px;margin:0 auto;border:1px solid #e3e8f0}
.hd{background:#3b82f6;color:#fff;padding:12px 16px;font-weight:600}
.log{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
.msg{padding:8px 12px;border-radius:12px;max-width:80%%;line-height:1.5;white-space:pre-wrap}
.u{align-self:flex-end;background:#3b82f6;color:#fff}
.a{align-self:flex-start;background:#fff;border:1px solid #e3e8f0}
.in{display:flex;gap:8px;padding:10px;border-top:1px solid #e3e8f0}
.in input{flex:1;border:1px solid #d8dee9;border-radius:8px;padding:8px}
.in button{border:0;background:#3b82f6;color:#fff;border-radius:8px;padding:8px 14px;cursor:pointer}
</style></head><body><div class="box"><div class="hd">智能客服</div>
<div class="log" id="log"></div>
<div class="in"><input id="t" placeholder="请输入您的问题…" onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">发送</button></div></div>
<script>
const sid='web-'+Math.random().toString(36).slice(2);
async function send(){const t=document.getElementById('t');const v=t.value.trim();if(!v)return;
add('u',v);t.value='';
const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({text:v,session_id:sid})});const j=await r.json();add('a',j.reply||'(无回复)');}
function add(c,m){const d=document.createElement('div');d.className='msg '+c;d.textContent=m;
document.getElementById('log').appendChild(d);document.getElementById('log').scrollTop=1e9;}
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    # 关闭默认日志噪音
    def log_message(self, *args):  # pragma: no cover
        pass

    def _cors(self) -> None:
        origins = self.server.allowed_origins  # type: ignore[attr-defined]
        allow = origins if origins and origins != "*" else "*"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, obj: Any, ctype: str = "application/json") -> None:
        body = obj if ctype == "application/json" else obj
        if ctype == "application/json":
            body = json.dumps(obj, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        gw = self.server.gateway  # type: ignore[attr-defined]
        path = self.path.split("?")[0]
        if path in ("/", "/widget", "/index.html"):
            self._send(200, _WIDGET_HTML, "text/html")
        elif path == "/healthz":
            self._send(200, gw.health())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        gw = self.server.gateway  # type: ignore[attr-defined]
        path = self.path.split("?")[0]
        if path != "/api/chat":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send(400, {"error": "bad json"})
            return
        text = str(payload.get("text") or "")
        sid = str(payload.get("session_id") or "default")
        uid = payload.get("user_id")
        if not text:
            self._send(400, {"error": "text required"})
            return
        try:
            reply = gw.handle(text, session_id=sid, user_id=uid)
            self._send(200, {"reply": reply, "session_id": sid})
        except Exception as ex:  # noqa: BLE001
            self._send(500, {"error": str(ex)})


class WebGatewayPlugin(BasePlugin):
    """零依赖 HTTP 网关。"""

    name = "web_gateway"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._host: str = str(self.config.get("host", "127.0.0.1"))
        self._port: int = int(self.config.get("port", 8080))
        self._allowed_origins: str = str(self.config.get("allowed_origins", "*"))
        self._app: Optional[Any] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def on_init(self, ctx: PluginContext) -> None:
        self._app = ctx.app

    def handle(self, text, *, session_id: str = "default",
               user_id: Optional[str] = None) -> str:
        """把 HTTP 请求转成应用处理（供内部 handler 调用）。"""
        if self._app is None:
            return "(网关未绑定应用)"
        return self._app.handle(text, session_id=session_id, user_id=user_id)

    def health(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": "healthy",
            "plugin": "web_gateway",
            "listening": self._server is not None,
            "host": self._host,
            "port": self._port,
        }
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        obs = pm.get("observability") if pm is not None else None
        if obs is not None:
            try:
                h = obs.health()
                out["status"] = h.get("status", out["status"])
                out["metrics"] = h
            except Exception:
                pass
        return out

    def start(self, app: Optional[Any] = None, *, host: Optional[str] = None,
              port: Optional[int] = None) -> None:
        if self._server is not None:
            return
        if app is not None:
            self._app = app
        self._host = host or self._host
        self._port = port or self._port
        server = ThreadingHTTPServer((self._host, self._port), _Handler)
        server.gateway = self  # type: ignore[attr-defined]
        server.allowed_origins = self._allowed_origins  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self._thread = None

    def on_shutdown(self, ctx: PluginContext) -> None:
        self.stop()
