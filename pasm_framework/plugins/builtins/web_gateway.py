"""web_gateway —— 零依赖 HTTP 网关插件（iframe / REST / 外部链接）。

让 pasm-framework 的 AI 应用"对外可接入"：站点用一行 ``<iframe>`` 即可嵌入
智能客服，或从任意语言（C#/Java/PHP/Node/Go…）用 REST 对接。
完全用标准库 ``http.server``，不引入任何 Web 框架。

接口
----
  · ``POST /api/chat``            ``{text, session_id?, user_id?, meta?}`` → ``{reply, session_id}``
  · ``POST /api/chat/stream``     同上入参，返回 **SSE**（``text/event-stream``）：
                                  ``{"type":"delta","text":…}`` /
                                  ``{"type":"replace","text":…}`` /
                                  ``{"type":"done",…}`` / ``{"type":"error",…}``
  · ``POST /api/ingest``          ``{items:[{title,content,source?,tags?}]}`` → ``{added}``
  · ``POST /api/sessions/reset``  ``{session_id}`` → ``{ok}``
  · ``GET  /healthz``             健康 + 指标（来自 observability 插件）
  · ``GET  /api/plugins``         已加载/已启用插件清单
  · ``GET  /api/summary``         应用快照（能力、插件、指标）
  · ``GET  /api/kb/stats``        资料库统计
  · ``GET  /`` 或 ``/widget``     自包含的可嵌入聊天 Widget

安全
----
  · ``token``          配置后所有接口（除 ``/healthz``）需带
                       ``Authorization: Bearer <token>`` 或 ``X-Pasm-Token``；
    · ``rate_limit``     每 IP 每分钟请求上限（0 = 不限流）；
  · ``max_body``       请求体字节上限（防超大 payload 打爆内存）；
  · ``allowed_origins`` CORS 白名单（``*`` 或具体来源）。

默认 ``enabled=False``（需要端口）；用户通过后端配置开启后调用 ``app.serve()``。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, PluginContext

# 模板里的 __TOKEN__ 会被替换为配置的令牌（未配置则留空 → 前端不带鉴权头）。
_WIDGET_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>智能客服</title><style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f7fb}
.box{display:flex;flex-direction:column;height:100vh;max-width:480px;margin:0 auto;border:1px solid #e3e8f0}
.hd{background:#3b82f6;color:#fff;padding:12px 16px;font-weight:600}
.log{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
.msg{padding:8px 12px;border-radius:12px;max-width:80%;line-height:1.5;white-space:pre-wrap}
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
const SID='web-'+Math.random().toString(36).slice(2);
const TOKEN='__TOKEN__';
function LOG(){return document.getElementById('log')}
function scroll(){LOG().scrollTop=1e9}
function add(c,m){const d=document.createElement('div');d.className='msg '+c;d.textContent=m||'';
LOG().appendChild(d);scroll();return d}
async function send(){const t=document.getElementById('t');const v=t.value.trim();if(!v)return;
add('u',v);t.value='';const bubble=add('a','');
const h={'Content-Type':'application/json'};if(TOKEN)h['Authorization']='Bearer '+TOKEN;
try{
const r=await fetch('/api/chat/stream',{method:'POST',headers:h,body:JSON.stringify({text:v,session_id:SID})});
if(!r.ok||!r.body){const j=await r.json().catch(()=>({}));bubble.textContent=j.error||'(无回复)';return}
const rd=r.body.getReader(),dec=new TextDecoder();let buf='',acc='';
for(;;){const c=await rd.read();if(c.done)break;
buf+=dec.decode(c.value,{stream:true});
const parts=buf.split('\n\n');buf=parts.pop()||'';
for(const p of parts){const line=p.trim();if(line.indexOf('data:')!==0)continue;
let ev;try{ev=JSON.parse(line.slice(5).trim())}catch(e){continue}
if(ev.type==='delta'){acc+=ev.text;bubble.textContent=acc;scroll()}
else if(ev.type==='replace'){acc=ev.text;bubble.textContent=acc;scroll()}
else if(ev.type==='error'){bubble.textContent='出错了：'+ev.error}}}
if(!bubble.textContent)bubble.textContent='(无回复)';
}catch(e){bubble.textContent='网络异常，请稍后再试'}}
</script></body></html>"""


class _RateLimiter:
    """每 IP 固定窗口限流（够用且零依赖；生产建议放到反向代理层）。"""

    def __init__(self, per_minute: int) -> None:
        self._limit = per_minute
        self._hits: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        now = time.time()
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if now - t < 60.0]
            if len(bucket) >= self._limit:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
        return True


class _Handler(BaseHTTPRequestHandler):
    server_version = "PasmGateway/0.2"
    protocol_version = "HTTP/1.1"

    # 关闭默认日志噪音
    def log_message(self, *args):  # pragma: no cover
        pass

    # ---- 工具 ----
    @property
    def _gw(self) -> "WebGatewayPlugin":
        return self.server.gateway  # type: ignore[attr-defined]

    def _cors(self) -> None:
        origins = self.server.allowed_origins  # type: ignore[attr-defined]
        self.send_header("Access-Control-Allow-Origin",
                         origins if origins and origins != "*" else "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, X-Pasm-Token")

    def _send(self, code: int, obj: Any, ctype: str = "application/json") -> None:
        body = obj if ctype != "application/json" else json.dumps(obj, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _sse_start(self) -> None:
        """开始 SSE 响应。

        不用 ``Content-Length``（长度未知）—— 改发 ``Connection: close``
        并置 ``close_connection``，让客户端以 EOF 判定流结束。
        比 chunked 少一层编码，且所有 HTTP 客户端都认。
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")   # 让 nginx 别缓冲
        self._cors()
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse_send(self, obj: Dict[str, Any]) -> None:
        payload = "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def _client_ip(self) -> str:
        return (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def _authorized(self, path: str) -> bool:
        token = self._gw.token
        if not token or path == "/healthz":
            return True
        got = self.headers.get("X-Pasm-Token", "")
        if not got:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        return got == token

    def _guard(self, path: str) -> bool:
        """鉴权 + 限流。返回 True 表示可以继续处理。"""
        if not self._authorized(path):
            self._send(401, {"error": "unauthorized",
                             "hint": "请在请求头带 Authorization: Bearer <token>"})
            return False
        if not self._gw.limiter.allow(self._client_ip()):
            self._send(429, {"error": "rate limited",
                             "hint": "请求过于频繁，请稍后再试"})
            return False
        return True

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            self._send(400, {"error": "bad content-length"})
            return None
        if length > self._gw.max_body:
            self._send(413, {"error": "payload too large",
                             "max_body": self._gw.max_body})
            return None
        if not length:
            return {}
        try:
            raw = self.rfile.read(length)
            obj = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send(400, {"error": "bad json"})
            return None
        if not isinstance(obj, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return None
        return obj

    # ---- HTTP 方法 ----
    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_GET(self):  # noqa: N802
        gw = self._gw
        path = self.path.split("?")[0]
        # 健康检查免鉴权（容器/反代探针常用），其余一律走守卫。
        if not self._guard(path):
            return
        if path in ("/", "/widget", "/index.html"):
            html = _WIDGET_HTML.replace("__TOKEN__", gw.token or "")
            self._send(200, html, "text/html")
        elif path == "/healthz":
            self._send(200, gw.health())
        elif path == "/api/plugins":
            self._send(200, gw.plugins_info())
        elif path == "/api/summary":
            self._send(200, gw.summary())
        elif path == "/api/kb/stats":
            self._send(200, gw.kb_stats())
        else:
            self._send(404, {"error": "not found", "paths": [
                "/", "/widget", "/healthz", "/api/chat", "/api/chat/stream",
                "/api/ingest", "/api/plugins", "/api/summary", "/api/kb/stats",
                "/api/sessions/reset"]})

    def do_POST(self):  # noqa: N802
        gw = self._gw
        path = self.path.split("?")[0]
        if not self._guard(path):
            return
        if path == "/api/chat":
            payload = self._read_json()
            if payload is None:
                return
            text = str(payload.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text required"})
                return
            sid = str(payload.get("session_id") or "default")
            uid = payload.get("user_id")
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
            try:
                reply = gw.handle(text, session_id=sid, user_id=uid, meta=meta)
                self._send(200, {"reply": reply, "session_id": sid})
            except Exception as ex:  # noqa: BLE001
                self._send(500, {"error": str(ex)})
        elif path == "/api/chat/stream":
            payload = self._read_json()
            if payload is None:
                return
            text = str(payload.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text required"})
                return
            sid = str(payload.get("session_id") or "default")
            uid = payload.get("user_id")
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
            self._sse_start()
            try:
                for ev in gw.stream(text, session_id=sid, user_id=uid, meta=meta):
                    self._sse_send(ev)
            except Exception as ex:  # noqa: BLE001
                # 已经开流，只能把错误作为事件下发（不能再改状态码）。
                try:
                    self._sse_send({"type": "error", "error": str(ex)})
                except Exception:
                    pass
        elif path == "/api/ingest":
            payload = self._read_json()
            if payload is None:
                return
            items = payload.get("items")
            if isinstance(payload.get("content"), str):     # 单条也接受
                items = [payload]
            if not isinstance(items, list):
                self._send(400, {"error": "items must be a list"})
                return
            added = gw.ingest(items)
            if added < 0:
                self._send(409, {"error": "knowledge_base 插件未启用",
                                 "hint": "在 backend_config 中开启 knowledge_base"})
                return
            self._send(200, {"added": added, **gw.kb_stats()})
        elif path == "/api/sessions/reset":
            payload = self._read_json()
            if payload is None:
                return
            sid = str(payload.get("session_id") or "").strip()
            if not sid:
                self._send(400, {"error": "session_id required"})
                return
            self._send(200, {"ok": gw.reset_session(sid), "session_id": sid})
        else:
            self._send(404, {"error": "not found"})


class WebGatewayPlugin(BasePlugin):
    """零依赖 HTTP 网关。"""

    name = "web_gateway"
    version = "0.3.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._host: str = str(self.config.get("host", "127.0.0.1"))
        self._port: int = int(self.config.get("port", 8080))
        self._allowed_origins: str = str(self.config.get("allowed_origins", "*"))
        self.token: str = str(self.config.get("token", "") or "")
        self.max_body: int = int(self.config.get("max_body", 256 * 1024))
        self.limiter = _RateLimiter(int(self.config.get("rate_limit", 0)))
        self._app: Optional[Any] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def on_init(self, ctx: PluginContext) -> None:
        self._app = ctx.app

    # ---- 供 handler 调用的能力 ----
    def handle(self, text: str, *, session_id: str = "default",
               user_id: Optional[str] = None,
               meta: Optional[Dict[str, Any]] = None) -> str:
        """把 HTTP 请求转成应用处理。"""
        if self._app is None:
            return "(网关未绑定应用)"
        return self._app.handle(text, session_id=session_id, user_id=user_id,
                                meta=meta)

    def stream(self, text: str, *, session_id: str = "default",
               user_id: Optional[str] = None,
               meta: Optional[Dict[str, Any]] = None):
        """流式版 ``handle``：逐条产出事件（供 SSE 下发）。

        应用没实现 ``stream`` 时**降级**为"整块当一次 delta"，保证接口永远可用。
        """
        if self._app is None:
            yield {"type": "error", "error": "网关未绑定应用"}
            return
        fn = getattr(self._app, "stream", None)
        if not callable(fn):
            yield {"type": "delta",
                   "text": self.handle(text, session_id=session_id,
                                       user_id=user_id, meta=meta)}
            yield {"type": "done", "session_id": session_id}
            return
        for ev in fn(text, session_id=session_id, user_id=user_id, meta=meta):
            yield ev

    def ingest(self, items: List[Dict[str, Any]]) -> int:
        """把外部（站点 CMS / 爬虫 / 客服后台）的数据推进资料库。"""
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        kb = pm.get("knowledge_base") if pm is not None else None
        if kb is None or not pm.is_enabled("knowledge_base"):
            return -1
        return kb.ingest(items)

    def kb_stats(self) -> Dict[str, Any]:
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        kb = pm.get("knowledge_base") if pm is not None else None
        if kb is None:
            return {"enabled": False}
        try:
            return dict(kb.stats(), enabled=True)
        except Exception:
            return {"enabled": True}

    def reset_session(self, session_id: str) -> bool:
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        sp = pm.get("sessions") if pm is not None else None
        if sp is None:
            return False
        try:
            sp.reset(session_id)
            return True
        except Exception:
            return False

    def plugins_info(self) -> Dict[str, Any]:
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        if pm is None:
            return {"all": [], "enabled": []}
        return {"all": pm.names(), "enabled": pm.enabled_names()}

    def summary(self) -> Dict[str, Any]:
        if self._app is None:
            return {}
        fn = getattr(self._app, "app_summary", None)
        return fn() if callable(fn) else {}

    def health(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": "healthy",
            "plugin": "web_gateway",
            "listening": self._server is not None,
            "host": self._host,
            "port": self._port,
            "auth_required": bool(self.token),
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

    # ---- 生命周期 ----
    def start(self, app: Optional[Any] = None, *, host: Optional[str] = None,
              port: Optional[int] = None) -> None:
        if self._server is not None:
            return
        if app is not None:
            self._app = app
        if host:
            self._host = host
        if port:
            self._port = port
        server = ThreadingHTTPServer((self._host, self._port), _Handler)
        server.gateway = self                        # type: ignore[attr-defined]
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
