"""web_gateway —— 零依赖 HTTP 网关插件（iframe / REST / 外部链接）。

让 pasm-framework 的 AI 应用"对外可接入"：站点用一行 ``<iframe>`` 即可嵌入
智能客服，或从任意语言（C#/Java/PHP/Node/Go…）用 REST 对接。
完全用标准库 ``http.server``，不引入任何 Web 框架。

接口
----
对话（公开作用域，可被访客浏览器调用）
  · ``POST /api/chat``            ``{text, session_id?, user_id?, meta?}`` → ``{reply, session_id}``
  · ``POST /api/chat/stream``     同上入参，返回 **SSE**（``text/event-stream``）：
                                  ``{"type":"delta","text":…}`` /
                                  ``{"type":"replace","text":…}`` /
                                  ``{"type":"done",…}`` / ``{"type":"error",…}``

站点接入资产（**任意语言写的站点都能用**，免鉴权，本身不含密钥）
  · ``GET  /embed.js``            一行式客服挂件：``<script src="…/embed.js"
                                  data-pasm-token="…" data-title="在线客服"></script>``
  · ``GET  /console``             站点主人控制台（看状态 / 导入资料 / 复制嵌入代码 / 试聊）
  · ``GET  /`` 或 ``/widget``     自包含聊天页（供 ``<iframe>`` 直接嵌入）

资料与运维（**管理作用域**，需管理令牌）
  · ``POST /api/ingest``          ``{items:[{title,content,source?,tags?}]}`` → ``{added}``
  · ``POST /api/ingest/text``     ``{text, source?, title?}`` → 长文自动切块入库；
                                  段落形如 ``问：…/答：…``（或 ``Q:/A:``）会按问答对沉淀
  · ``GET  /api/sessions``        ``{count, sessions:[{session_id,user_id,messages,…}]}``
  · ``POST /api/sessions/reset``  ``{session_id}`` → ``{ok}``
  · ``GET  /healthz``             健康 + 指标（来自 observability 插件）
  · ``GET  /api/plugins``         已加载/已启用插件清单
  · ``GET  /api/summary``         应用快照（能力、插件、指标）
  · ``GET  /api/kb/stats``        资料库统计

安全（两种令牌，作用域分离）
----
  · ``token``           **管理令牌**：配置后，管理类接口需带
                        ``Authorization: Bearer <token>`` 或 ``X-Pasm-Token``。
  · ``public_token``    **公开令牌**（可选）：只授权"对话"，可安全嵌到第三方站点。
    为什么需要它：浏览器挂件必须把令牌放在页面里，访问者都能看到 ——
    若直接嵌管理令牌，等于把"导入资料 / 重置会话"的权限公开了。
    配了 ``public_token`` 后，``/``、``/embed.js`` 下发的都是它，管理接口仍只认 ``token``。
    未配置时回落到 ``token``（行为与旧版完全一致）。
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
from urllib.parse import unquote

from ..core import BasePlugin, PluginContext
from ._web_assets import CONSOLE_HTML, EMBED_JS

#: 真正**不含任何密钥、可无条件公开**的路径：静态 JS 与健康探针。
#: 挂件页 / 管理台**不在此列** —— 它们要么注入令牌、要么是管理界面。
_PUBLIC_PATHS = ("/embed.js", "/healthz")

#: 只需「公开作用域」的路径：对话。其余一律要管理令牌。
_CHAT_PATHS = ("/api/chat", "/api/chat/stream")

#: 访客可见的挂件页。**仅当配了 ``public_token`` 时才允许公开作用域** ——
#: 否则 ``serve_token`` 会回落到管理令牌并写进页面源码，
#: 等于把管理令牌送给每一个打开该页的访客。
_WIDGET_PATHS = ("/", "/widget", "/index.html")

#: ``ingest_text`` 把长文切成多长的块（字符）。太大 → 检索命中后回复里塞满无关内容；
#: 太小 → 一句话被切断、语义破碎。800 字符约合中文 2–4 段，是"能独立成条"的量级。
_CHUNK_CHARS = 800

#: 短于此长度的段落视为"碎片"（小标题、单句），会被并入相邻段而不是独立成条 ——
#: 一个只有标题的块既是噪声、又几乎匹配不到任何问句。
_MIN_CHUNK = 24

#: 形如 ``问：…`` / ``Q: …`` 的行会被当作问答对的提问行。
_QA_Q_PREFIX = ("问：", "问:", "Q:", "q:", "Q：", "q：")
_QA_A_PREFIX = ("答：", "答:", "A:", "a:", "A：", "a：")


def _split_qa_units(para: str) -> List[str]:
    """段落里若含**多组** ``问：`` 开头的问答，按组拆开（一组一块）。

    站点主人常把整页 FAQ 连着贴下来、组与组之间没有空行；
    此时"一组问答"才是真正的语义单位，整段当一个块会让检索失准。
    只有一组时原样返回（不做无谓拆分）。
    """
    lines = [ln for ln in (para or "").split("\n") if ln.strip()]
    n_q = sum(1 for ln in lines if ln.strip().startswith(_QA_Q_PREFIX))
    if n_q < 2:
        return [para]
    units: List[str] = []
    buf: List[str] = []
    for ln in lines:
        if buf and ln.strip().startswith(_QA_Q_PREFIX):
            units.append("\n".join(buf))
            buf = []
        buf.append(ln)
    if buf:
        units.append("\n".join(buf))
    return units


def _split_chunks(text: str, limit: int = _CHUNK_CHARS) -> List[str]:
    """把长文切成若干块：**空行分段即语义边界，一段一块**。

    为什么不再"把小段贪心合并到 limit 以内"：那样会把作者已用空行分开的
    不同主题揉进同一个块。实测后果很直接 —— 把"退货 / 发货 / 积分 / 配送"
    四段合并成一块后，问"积分怎么算"返回的是**退货**的内容（因为该块以退货
    开头），检索精度整个塌掉。填空隙的收益远小于这个代价，所以取消跨段合并。

    仍保留两条必要的处理：

    - 段内含多组 ``问：/答：`` → 按问答组拆开（见 :func:`_split_qa_units`）；
    - 极短段（长不过 ``_MIN_CHUNK``，如光秃秃的小标题）→ 并入**下一段**，
      因为一个只有标题的块既是噪声、又几乎匹配不到任何问句；
      标题按写作习惯属于紧随其后的正文。

    超长段（> ``limit``）按字符硬切，避免单块过大把回复撑爆。
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:                                   # 没有空行 → 按单行分
        paras = [p.strip() for p in text.split("\n") if p.strip()]

    units: List[str] = []
    for p in paras:
        units.extend(_split_qa_units(p))

    chunks: List[str] = []
    pending = ""                                    # 太短、等并入下一段的碎片
    for u in units:
        if pending:
            u = pending + "\n" + u
            pending = ""
        # 完整的问答对**直接成块**，不参与"碎片并入下一段"的合并 ——
        # 一组问答本身就是语义完整的单位，短（"问：包邮吗？/答：满99包邮。"）
        # 不代表它不完整。若与其它问答合并，:func:`_as_qa_pair` 只会取到第一组，
        # 后面的问答就丢了。
        if _as_qa_pair(u) is not None:
            chunks.append(u)
            continue
        if len(u) < _MIN_CHUNK:                     # 碎片 → 攒着给下一段
            pending = u
            continue
        if len(u) > limit:                          # 单段超长 → 硬切
            for i in range(0, len(u), limit):
                chunks.append(u[i:i + limit])
            continue
        chunks.append(u)
    if pending:                                     # 末尾孤零零的碎片也不能丢
        chunks.append(pending)
    return chunks


def _as_qa_pair(chunk: str) -> Optional[tuple]:
    """把 ``问：X`` / ``答：Y`` 形态的段落识别成问答对；不是则返回 ``None``。

    只认"提问行在前、回答行在后、且都在同一段落里"这一种紧凑写法 ——
    刻意保守，避免把正常文档误判成问答而丢掉上下文。
    """
    lines = [ln.strip() for ln in (chunk or "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return None
    q = a = ""
    for ln in lines:
        if not q and ln.startswith(_QA_Q_PREFIX):
            q = ln[2:].strip()                  # 所有前缀都是 2 字符（"问：" / "Q:"）
        elif q and not a and ln.startswith(_QA_A_PREFIX):
            a = ln[2:].strip()
    if q and a:
        return (q, a)
    return None

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

    def _presented_token(self) -> str:
        """取出调用方出示的令牌。

        支持三种携带方式（按优先级）：
          1. ``X-Pasm-Token`` 头；
          2. ``Authorization: Bearer <token>`` 头；
          3. URL 查询参数 ``?token=`` —— **浏览器直接导航发不了请求头**，
             站主要能「点开链接就进管理台」，所以必须支持这一种。
        """
        got = self.headers.get("X-Pasm-Token", "")
        if not got:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        if not got:
            _, _, query = self.path.partition("?")
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "token" and v:
                    got = unquote(v)
                    break
        return got

    def _authorized(self, path: str, *, admin: bool = True) -> bool:
        """作用域感知的鉴权。

        ``admin=True``（默认）→ 只认管理令牌；
        ``admin=False``        → 认管理令牌，若配了 ``public_token`` 也认它（仅对话用）。

        无条件放行的只有两类：
          · ``_PUBLIC_PATHS``：本身不含任何密钥；
          · 配了 ``public_token`` 时的挂件页：它注入的就是那个**本就公开**的令牌
            （站主会把它写进自己站点源码），所以页面可以给访客。
            没配 ``public_token`` 时挂件页**不公开** —— 否则只能注入管理令牌。
        """
        token = self._gw.token
        pub = self._gw.public_token
        if not token and not pub:
            return True                       # 完全没设令牌 = 开放模式（本机开发）
        if path in _PUBLIC_PATHS:
            return True
        if pub and path in _WIDGET_PATHS:
            return True                       # 公开令牌本就公开 → 挂件页对访客开放
        got = self._presented_token()
        if token and got == token:
            return True                       # 管理令牌在任何作用域下都通行
        if not admin and pub and got == pub:
            return True
        return False

    def _guard(self, path: str, *, admin: bool = True) -> bool:
        """鉴权 + 限流。返回 True 表示可以继续处理。"""
        if not self._authorized(path, admin=admin):
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
        # 作用域判定全部收在 `_authorized` 里：
        #   · /embed.js、/healthz 无条件放行；
        #   · 配了 public_token 时挂件页对访客开放（注入的就是公开令牌）；
        #   · 其余（管理台、各类管理 API）一律管理作用域。
        if not self._guard(path):
            return
        if path in ("/", "/widget", "/index.html"):
            # 注入**公开令牌**（serve_token 只返回 public_token，绝不含管理令牌）。
            # 该页面是要给访客看的：源码里能读到什么，访客就能读到什么。
            html = _WIDGET_HTML.replace("__TOKEN__", gw.serve_token)
            self._send(200, html, "text/html")
        elif path == "/embed.js":
            # 一行式挂件脚本：不含密钥（令牌由站主的 <script> 标签属性传入）。
            self._send(200, EMBED_JS, "application/javascript")
        elif path == "/console":
            # 站点主人控制台：**管理作用域**。浏览器导航发不了请求头，
            # 所以这里支持 ?token=<管理令牌>，页面会把它存进 sessionStorage。
            self._send(200, CONSOLE_HTML, "text/html")
        elif path == "/healthz":
            self._send(200, gw.health())
        elif path == "/api/plugins":
            self._send(200, gw.plugins_info())
        elif path == "/api/summary":
            self._send(200, gw.summary())
        elif path == "/api/kb/stats":
            self._send(200, gw.kb_stats())
        elif path == "/api/sessions":
            self._send(200, gw.sessions_info())
        else:
            self._send(404, {"error": "not found", "paths": [
                "/", "/widget", "/embed.js", "/console", "/healthz",
                "/api/chat", "/api/chat/stream", "/api/ingest", "/api/ingest/text",
                "/api/plugins", "/api/summary", "/api/kb/stats",
                "/api/sessions", "/api/sessions/reset"]})

    def do_POST(self):  # noqa: N802
        gw = self._gw
        path = self.path.split("?")[0]
        # 对话走「公开作用域」（可用 public_token），资料/会话管理走管理作用域。
        if not self._guard(path, admin=(path not in _CHAT_PATHS)):
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
        elif path == "/api/ingest/text":
            payload = self._read_json()
            if payload is None:
                return
            text = str(payload.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text required"})
                return
            res = gw.ingest_text(
                text,
                source=str(payload.get("source") or "console"),
                title=str(payload.get("title") or ""),
            )
            if res is None:
                self._send(409, {"error": "knowledge_base 插件未启用",
                                 "hint": "在 backend_config 中开启 knowledge_base"})
                return
            self._send(200, res)
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
        # 公开令牌：只授权对话，可安全嵌进第三方站点（不配则沿用 token，行为同旧版）。
        self.public_token: str = str(self.config.get("public_token", "") or "")
        self.max_body: int = int(self.config.get("max_body", 256 * 1024))
        self.limiter = _RateLimiter(int(self.config.get("rate_limit", 0)))
        self._app: Optional[Any] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def serve_token(self) -> str:
        """下发给浏览器的令牌（挂件页 / 嵌入代码用）。

        **只返回 ``public_token``；没配就返回空串 —— 绝不回落到 ``token``。**
        挂件页与嵌入代码是给访客看的，一旦回落，源码里就能读到管理令牌，
        等于把整个后台送给任何一个打开网页的人。
        没配 ``public_token`` 时该页面本身也改为管理作用域，站长自己看没问题。
        """
        return self.public_token

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

    def sessions_info(self, limit: int = 50) -> Dict[str, Any]:
        """会话概览（**只给概要，不含对话正文**）。

        管理台能列出"最近有哪些人来聊过、聊了几轮"，但看不到具体内容 ——
        客户对话属于敏感数据，不该因为打开一个网页就整批暴露。
        """
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        sp = pm.get("sessions") if pm is not None else None
        if sp is None or not pm.is_enabled("sessions"):
            return {"enabled": False, "sessions": []}
        try:
            rows = sp.list_sessions(limit=limit)
            return {"enabled": True, "count": sp.count(), "sessions": rows}
        except Exception:
            return {"enabled": True, "count": 0, "sessions": []}

    def ingest_text(self, text: str, *, source: str = "console",
                    title: str = "") -> Optional[Dict[str, Any]]:
        """把**一整篇文本**（粘贴的 FAQ、帮助文档、产品说明）喂进资料库。

        与 ``ingest(items)`` 的区别：那个要调用方自己切好条目，这个负责切。
        切法是"**空行分段即语义边界，一段一块**"，段内多组 ``问：/答：`` 按组拆开；
        问答对会被存成问答对（检索时享有更高权重，命中更准）。

        返回 ``None`` 表示知识库未启用（调用方据此回 409）。
        """
        pm = getattr(self._app, "plugins", None) if self._app is not None else None
        kb = pm.get("knowledge_base") if pm is not None else None
        if kb is None or not pm.is_enabled("knowledge_base"):
            return None

        chunks = _split_chunks(text)
        added = qa = 0
        for i, ck in enumerate(chunks):
            pair = _as_qa_pair(ck)
            if pair is not None:
                kb.ingest_qa(pair[0], pair[1], source=source)
                qa += 1
                added += 1
                continue
            # 标题：整篇给了 title 就加序号（便于来源可溯）；否则取该块首行。
            if title:
                t = "%s（%d）" % (title, i + 1) if len(chunks) > 1 else title
            else:
                t = (ck.split("\n", 1)[0] or "资料")[:60]
            n = kb.ingest([{"title": t, "content": ck, "source": source}])
            added += n
        return {"added": added, "qa": qa, "chunks": len(chunks), **self.kb_stats()}

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
