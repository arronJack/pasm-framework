"""站点接入资产：一行式嵌入脚本 + 站点主人控制台（零依赖，纯静态）。

为什么单独一个模块
------------------
这两个产物是**静态资源**（一段 JS / 一个 HTML 页面），不是逻辑代码。
和大段 Python 混在一个文件里会让 web_gateway 难以阅读；拆出来后，
它俩可以被独立替换（比如以后换成 React 版挂件）而不动网关逻辑。

``EMBED_JS``
    给**任意语言写的站点**用的一行式挂件。站点主人只要贴：

        <script src="http://<host>:<port>/embed.js"
                data-pasm-token="…" data-title="在线客服"></script>

    就会在右下角出现一个客服气泡，点开即可对话。特点：

    * **零依赖**：原生 JS，不引入任何框架、不依赖宿主页面的 CSS；
    * **Shadow DOM 隔离**：宿主站点的样式**不会**污染挂件，反之亦然
      （这是嵌入式挂件最常见的翻车点）；
    * **流式**：走 ``/api/chat/stream``，回答逐字出现，不是干等一整段；
    * **会话粘性**：``sessionStorage`` 记住 session_id，刷新页面不会失忆；
    * **令牌来自标签属性**：脚本本身不含任何密钥，谁能贴代码谁才有令牌。

``CONSOLE_HTML``
    站点主人控制台（``GET /console``）。**刻意做成不含任何密钥的静态壳**：
    - 它本身免鉴权（浏览器地址栏导航没法带 ``Authorization`` 头），
      但里面**不嵌入**服务器令牌 —— 打开它的人只看到一个空控制台；
    - 令牌由使用者在页面里填一次，存 ``sessionStorage``，用于调用各 API。
    功能：看运行状态 / 资料库统计 / 会话数、复制嵌入代码、粘贴导入资料、快捷测试。
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# 一行式嵌入脚本（任意站点、任意后端语言）
# --------------------------------------------------------------------------
EMBED_JS = r"""(function () {
  "use strict";
  if (window.__pasmCS) { return; }
  window.__pasmCS = 1;

  var S = document.currentScript;
  if (!S) { var all = document.getElementsByTagName("script"); S = all[all.length - 1]; }

  function attr(n, d) {
    try { var v = S.getAttribute(n); return (v === null || v === "") ? d : v; }
    catch (e) { return d; }
  }

  var BASE = "";
  try { BASE = S.src.split("?")[0].replace(/\/embed\.js$/, ""); } catch (e) { BASE = ""; }

  var TOKEN = attr("data-pasm-token", "");
  var TITLE = attr("data-title", "在线客服");
  var GREET = attr("data-greeting", "你好！我是智能客服，有什么可以帮你？");
  var LABEL = attr("data-label", "在线咨询");
  var COLOR = attr("data-color", "#2563eb");
  var SIDE  = attr("data-position", "right");

  var KEY = "pasm_cs_sid", sid = null;
  try { sid = sessionStorage.getItem(KEY); } catch (e) {}
  if (!sid) {
    sid = "web-" + Math.random().toString(36).slice(2);
    try { sessionStorage.setItem(KEY, sid); } catch (e) {}
  }

  var CSS = [
    "*{box-sizing:border-box}",
    ".pw-btn{position:fixed;bottom:20px;z-index:2147483000;display:flex;align-items:center;gap:8px;",
    "border:0;border-radius:999px;padding:12px 18px;cursor:pointer;color:#fff;font-size:14px;",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;",
    "box-shadow:0 6px 20px rgba(0,0,0,.18)}",
    ".pw-panel{position:fixed;bottom:20px;z-index:2147483001;width:360px;height:520px;",
    "max-width:calc(100vw - 40px);max-height:calc(100vh - 40px);background:#fff;border-radius:16px;",
    "overflow:hidden;display:flex;flex-direction:column;box-shadow:0 12px 48px rgba(0,0,0,.22);",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;",
    "font-size:14px;color:#111}",
    ".pw-hd{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;color:#fff;font-weight:600}",
    ".pw-x{border:0;background:transparent;color:#fff;font-size:20px;line-height:1;cursor:pointer;padding:0 4px}",
    ".pw-log{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#f7f9fc}",
    ".pw-m{padding:8px 12px;border-radius:12px;max-width:82%;line-height:1.55;white-space:pre-wrap;word-break:break-word}",
    ".pw-u{align-self:flex-end;background:var(--pw-c);color:#fff}",
    ".pw-a{align-self:flex-start;background:#fff;border:1px solid #e5eaf2}",
    ".pw-in{display:flex;gap:8px;padding:10px;border-top:1px solid #e5eaf2;background:#fff}",
    ".pw-in input{flex:1;border:1px solid #d8dee9;border-radius:10px;padding:9px 11px;font-size:14px;outline:none}",
    ".pw-in input:focus{border-color:var(--pw-c)}",
    ".pw-in button{border:0;background:var(--pw-c);color:#fff;border-radius:10px;padding:9px 16px;cursor:pointer;font-size:14px}",
    ".pw-tip{font-size:11px;color:#94a3b8;text-align:center;padding:0 10px 8px;background:#fff}"
  ].join("");

  function mount() {
    if (!(document.body || document.documentElement)) { setTimeout(mount, 30); return; }

    var host = document.createElement("div");
    host.setAttribute("data-pasm-widget", "1");
    host.style.cssText = "all:initial";
    (document.body || document.documentElement).appendChild(host);

    var root = host;
    if (host.attachShadow) { try { root = host.attachShadow({ mode: "open" }); } catch (e) { root = host; } }

    var st = document.createElement("style");
    st.textContent = CSS;
    root.appendChild(st);

    var side = (SIDE === "left") ? "left:20px;" : "right:20px;";

    var btn = document.createElement("button");
    btn.className = "pw-btn";
    btn.style.cssText = side + "background:" + COLOR + ";";
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
      + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
      + '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.9 9.9 0 0 1-4-.8L3 21l1.9-4.2a8.3 8.3 0 0 1-1-4A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z"/></svg><span></span>';
    btn.querySelector("span").textContent = LABEL;
    root.appendChild(btn);

    var panel = document.createElement("div");
    panel.className = "pw-panel";
    panel.style.cssText = side + "display:none;--pw-c:" + COLOR + ";";
    panel.innerHTML =
      '<div class="pw-hd" style="background:' + COLOR + '"><span></span>'
      + '<button class="pw-x" type="button" aria-label="close">&times;</button></div>'
      + '<div class="pw-log"></div>'
      + '<div class="pw-in"><input type="text" placeholder="请输入您的问题…">'
      + '<button type="button">发送</button></div>'
      + '<div class="pw-tip">回复由 AI 生成，仅供参考</div>';
    panel.querySelector(".pw-hd span").textContent = TITLE;
    root.appendChild(panel);

    var log = panel.querySelector(".pw-log");
    var inp = panel.querySelector(".pw-in input");
    var opened = false;

    function add(cls, txt) {
      var d = document.createElement("div");
      d.className = "pw-m " + cls;
      d.textContent = txt || "";
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
      return d;
    }
    function open() {
      panel.style.display = "flex";
      btn.style.display = "none";
      if (!opened) { opened = true; if (GREET) { add("pw-a", GREET); } }
      try { inp.focus(); } catch (e) {}
    }
    function close() {
      panel.style.display = "none";
      btn.style.display = "flex";
    }

    var busy = false;
    function send() {
      var v = (inp.value || "").trim();
      if (!v || busy) { return; }
      inp.value = "";
      add("pw-u", v);
      var bub = add("pw-a", "");
      var h = { "Content-Type": "application/json" };
      if (TOKEN) { h["Authorization"] = "Bearer " + TOKEN; }
      busy = true;

      fetch(BASE + "/api/chat/stream", {
        method: "POST", headers: h,
        body: JSON.stringify({ text: v, session_id: sid })
      }).then(function (r) {
        if (!r.ok || !r.body) {
          return r.json().catch(function () { return {}; }).then(function (j) {
            bub.textContent = j.hint || j.error || "服务暂时不可用";
          }).then(function () { busy = false; });
        }
        var rd = r.body.getReader(), dec = new TextDecoder(), buf = "", acc = "";
        function pump() {
          return rd.read().then(function (c) {
            if (c.done) {
              if (!acc) { bub.textContent = "(无回复)"; }
              busy = false;
              return;
            }
            buf += dec.decode(c.value, { stream: true });
            var parts = buf.split("\n\n");
            buf = parts.pop() || "";
            for (var i = 0; i < parts.length; i++) {
              var line = parts[i].trim();
              if (line.indexOf("data:") !== 0) { continue; }
              var ev = null;
              try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
              if (ev.type === "delta") { acc += ev.text; bub.textContent = acc; }
              else if (ev.type === "replace") { acc = ev.text; bub.textContent = acc; }
              else if (ev.type === "error") { bub.textContent = "出错了：" + (ev.error || ""); }
            }
            log.scrollTop = log.scrollHeight;
            return pump();
          });
        }
        return pump();
      }).catch(function () {
        bub.textContent = "网络异常，请稍后再试";
        busy = false;
      });
    }

    btn.addEventListener("click", open);
    panel.querySelector(".pw-x").addEventListener("click", close);
    panel.querySelector(".pw-in button").addEventListener("click", send);
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") { send(); } });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
"""


# --------------------------------------------------------------------------
# 站点主人控制台（不含任何密钥的静态壳）
# --------------------------------------------------------------------------
CONSOLE_HTML = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>智能客服控制台</title><style>
:root{--c:#2563eb;--bd:#e5eaf2;--mut:#64748b}
*{box-sizing:border-box}
body{margin:0;background:#f5f7fb;color:#111;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
header{background:#0f172a;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
header h1{margin:0;font-size:17px;font-weight:600}
header .sub{font-size:12px;color:#94a3b8;margin-top:2px}
main{max-width:960px;margin:0 auto;padding:20px 24px 60px}
section{background:#fff;border:1px solid var(--bd);border-radius:12px;padding:18px;margin-bottom:16px}
h2{font-size:15px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
h2 .n{width:20px;height:20px;border-radius:50%;background:var(--c);color:#fff;font-size:12px;
 display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.card{background:#fff;border:1px solid var(--bd);border-radius:12px;padding:14px 16px}
.card .k{font-size:12px;color:var(--mut)}
.card .v{font-size:22px;font-weight:600;margin-top:2px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=text],textarea{width:100%;border:1px solid #d8dee9;border-radius:9px;padding:9px 11px;
 font-size:13px;font-family:inherit;outline:none;background:#fff}
input[type=text]:focus,textarea:focus{border-color:var(--c)}
textarea{min-height:150px;resize:vertical;line-height:1.6}
button{border:0;background:var(--c);color:#fff;border-radius:9px;padding:9px 16px;cursor:pointer;font-size:13px;font-family:inherit}
button.g{background:#eef2f7;color:#334155}
code,pre{font-family:ui-monospace,Consolas,Menlo,monospace;font-size:12px}
pre{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px 14px;overflow:auto;margin:8px 0 0;white-space:pre-wrap;word-break:break-all}
.hint{font-size:12px;color:var(--mut);margin:8px 0 0}
.tag{display:inline-block;background:#eef2f7;color:#475569;border-radius:6px;padding:1px 7px;font-size:11px;margin-left:6px}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:#0f172a;color:#fff;
 padding:9px 18px;border-radius:999px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
#toast.on{opacity:.94}
.ok{color:#15803d}.bad{color:#b91c1c}
.log{max-height:240px;overflow:auto;border:1px solid var(--bd);border-radius:10px;padding:10px;background:#fafcff}
.log div{padding:6px 9px;border-radius:9px;margin-bottom:6px;white-space:pre-wrap;font-size:13px}
.log .u{background:var(--c);color:#fff;margin-left:auto;max-width:80%}
.log .a{background:#fff;border:1px solid var(--bd);max-width:80%}
</style></head><body>
<header>
  <div><h1>智能客服控制台</h1><div class="sub">PASM 站点式插件 · 记忆 / 情感 / 自我成长</div></div>
  <div class="row">
    <input type="text" id="tok" placeholder="访问令牌（未设鉴权可留空）" style="width:220px">
    <button class="g" id="save">保存令牌</button>
    <button id="refresh">刷新</button>
  </div>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="k">服务状态</div><div class="v" id="c-status">—</div></div>
    <div class="card"><div class="k">资料库条目</div><div class="v" id="c-kb">—</div></div>
    <div class="card"><div class="k">会话数</div><div class="v" id="c-sess">—</div></div>
    <div class="card"><div class="k">已处理消息</div><div class="v" id="c-msg">—</div></div>
  </div>

  <section>
    <h2><span class="n">1</span>把客服挂到你的站点<span class="tag">任意语言</span></h2>
    <p class="hint">把下面一行贴进你的网页（HTML / PHP / Java 模板 / Vue / React 都可以），右下角就会出现客服气泡。
      它自带记忆与情感，并且会在有人提问时自动学习。</p>
    <pre id="snippet"></pre>
    <div class="row" style="margin-top:10px">
      <button id="copy">复制嵌入代码</button>
      <button class="g" id="copy2">复制 iframe 版</button>
    </div>
    <p class="hint">令牌会写进代码里，请只贴在你自己的站点上。</p>
  </section>

  <section>
    <h2><span class="n">2</span>喂养资料库<span class="tag">自学成长</span></h2>
    <p class="hint">把产品说明、FAQ、帮助文档直接粘进来。纯文本会按空行分段；
      若写成「问：… 答：…」的成对形式，则按问答对入库，命中更准。</p>
    <textarea id="doc" placeholder="示例：&#10;问：怎么退货？&#10;答：签收后 7 天内可无理由退货，需保持吊牌完整。&#10;&#10;问：多久发货？&#10;答：现货 24 小时内发出，偏远地区 3-5 天。"></textarea>
    <div class="row" style="margin-top:10px">
      <input type="text" id="src" value="console" style="width:170px" placeholder="来源标记">
      <button id="ingest">导入资料库</button>
      <button class="g" id="ingestFile">选择文件（.txt/.md/.json）</button>
      <input type="file" id="file" accept=".txt,.md,.json,.csv" style="display:none">
    </div>
    <p class="hint" id="ingestMsg"></p>
  </section>

  <section>
    <h2><span class="n">3</span>当场试一试</h2>
    <div class="row">
      <input type="text" id="q" placeholder="问点什么，比如「怎么退货」" style="flex:1;min-width:200px">
      <button id="ask">发送</button>
      <button class="g" id="clear">清空</button>
    </div>
    <div class="log" id="log" style="margin-top:12px"></div>
    <p class="hint">这里用的是独立测试会话，不会混进真实访客的对话历史。</p>
  </section>
</main>
<div id="toast"></div>
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var TOKKEY = "pasm_console_token";
  var TOKEN = "";
  try { TOKEN = sessionStorage.getItem(TOKKEY) || ""; } catch (e) {}
  // 支持 ?token=<管理令牌> 直接进入 —— 浏览器导航发不了请求头。
  // 读到后存进 sessionStorage，并**从地址栏抹掉**：避免令牌留在浏览历史 / 截图里。
  try {
    var q = new URLSearchParams(location.search).get("token");
    if (q) {
      TOKEN = q;
      try { sessionStorage.setItem(TOKKEY, q); } catch (e2) {}
      if (history.replaceState) { history.replaceState(null, "", location.pathname); }
    }
  } catch (e3) {}

  function toast(m) {
    var t = $("toast"); t.textContent = m; t.className = "on";
    setTimeout(function () { t.className = ""; }, 1900);
  }
  function hdr(extra) {
    var h = { "Content-Type": "application/json" };
    if (TOKEN) { h["Authorization"] = "Bearer " + TOKEN; }
    if (extra) { for (var k in extra) { h[k] = extra[k]; } }
    return h;
  }
  function api(method, path, body) {
    return fetch(path, {
      method: method, headers: hdr(),
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { throw new Error(j.hint || j.error || ("HTTP " + r.status)); }
        return j;
      });
    });
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function snippet(iframe) {
    var b = location.origin;
    if (iframe) {
      return '<iframe src="' + b + '/?token=' + (TOKEN || "") + '"\n'
        + '        style="width:400px;height:600px;border:1px solid #e5eaf2;border-radius:12px"\n'
        + '        title="智能客服"></iframe>';
    }
    return '<script src="' + b + '/embed.js"\n'
      + '        data-pasm-token="' + (TOKEN || "") + '"\n'
      + '        data-title="在线客服"\n'
      + '        data-greeting="你好！我是智能客服，有什么可以帮你？"\n'
      + '        data-color="#2563eb"><\/script>';
  }

  function copyText(txt) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(txt).then(function () { toast("已复制"); },
        function () { toast("复制失败，请手动选择"); });
    }
    var ta = document.createElement("textarea");
    ta.value = txt; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast("已复制"); } catch (e) { toast("复制失败"); }
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  function refresh() {
    api("GET", "/healthz").then(function (h) {
      $("c-status").innerHTML = h.status === "healthy"
        ? '<span class="ok">运行中</span>' : esc(h.status || "?");
      var m = h.metrics || {};
      $("c-msg").textContent = (m.messages_in == null ? "—" : m.messages_in);
    }).catch(function (e) { $("c-status").innerHTML = '<span class="bad">' + esc(e.message) + '</span>'; });

    api("GET", "/api/kb/stats").then(function (k) {
      if (k.enabled === false) { $("c-kb").textContent = "未启用"; return; }
      $("c-kb").textContent = (k.total == null ? "—" : k.total);
    }).catch(function () { $("c-kb").textContent = "—"; });

    api("GET", "/api/sessions").then(function (s) {
      $("c-sess").textContent = (s.count == null ? "—" : s.count);
    }).catch(function () { $("c-sess").textContent = "—"; });

    $("snippet").textContent = snippet(false);
  }

  // ---- 导入 ----
  function ingestText(text, source) {
    text = (text || "").trim();
    if (!text) { $("ingestMsg").textContent = "内容为空"; return; }
    $("ingestMsg").textContent = "正在导入…";
    api("POST", "/api/ingest/text", { text: text, source: source || "console" })
      .then(function (r) {
        $("ingestMsg").innerHTML = '<span class="ok">已导入 ' + r.added
          + " 条（文档 " + r.docs + " · 问答 " + r.qa + "）</span>";
        refresh();
      })
      .catch(function (e) { $("ingestMsg").innerHTML = '<span class="bad">导入失败：' + esc(e.message) + "</span>"; });
  }

  // ---- 对话 ----
  var busy = false;
  function ask() {
    var v = ($("q").value || "").trim();
    if (!v || busy) { return; }
    busy = true;
    $("q").value = "";
    var log = $("log");
    function push(cls, txt) {
      var d = document.createElement("div");
      d.className = cls; d.textContent = txt || "";
      log.appendChild(d); log.scrollTop = log.scrollHeight;
      return d;
    }
    push("u", v);
    var bub = push("a", "");
    fetch("/api/chat/stream", {
      method: "POST", headers: hdr(),
      body: JSON.stringify({ text: v, session_id: "console-test" })
    }).then(function (r) {
      if (!r.ok || !r.body) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          bub.textContent = j.hint || j.error || "服务不可用"; busy = false;
        });
      }
      var rd = r.body.getReader(), dec = new TextDecoder(), buf = "", acc = "";
      function pump() {
        return rd.read().then(function (c) {
          if (c.done) { busy = false; return; }
          buf += dec.decode(c.value, { stream: true });
          var parts = buf.split("\n\n");
          buf = parts.pop() || "";
          parts.forEach(function (p) {
            var line = p.trim();
            if (line.indexOf("data:") !== 0) { return; }
            var ev = null;
            try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { return; }
            if (ev.type === "delta") { acc += ev.text; bub.textContent = acc; }
            else if (ev.type === "replace") { acc = ev.text; bub.textContent = acc; }
            else if (ev.type === "error") { bub.textContent = "出错了：" + (ev.error || ""); }
          });
          log.scrollTop = log.scrollHeight;
          return pump();
        });
      }
      return pump();
    }).catch(function () { bub.textContent = "网络异常"; busy = false; });
  }

  // ---- 绑定 ----
  $("refresh").onclick = refresh;
  $("save").onclick = function () {
    TOKEN = ($("tok").value || "").trim();
    try { sessionStorage.setItem(TOKKEY, TOKEN); } catch (e) {}
    $("snippet").textContent = snippet(false);
    toast(TOKEN ? "令牌已保存" : "已清空令牌");
    refresh();
  };
  $("copy").onclick = function () { copyText(snippet(false)); };
  $("copy2").onclick = function () { copyText(snippet(true)); };
  $("ingest").onclick = function () { ingestText($("doc").value, $("src").value); };
  $("ingestFile").onclick = function () { $("file").click(); };
  $("file").onchange = function () {
    var f = $("file").files && $("file").files[0];
    if (!f) { return; }
    var rd = new FileReader();
    rd.onload = function () {
      var t = String(rd.result || "");
      if (/\.json$/i.test(f.name)) {
        try {
          var arr = JSON.parse(t);
          if (!Array.isArray(arr)) { arr = [arr]; }
          api("POST", "/api/ingest", { items: arr }).then(function (r) {
            $("ingestMsg").innerHTML = '<span class="ok">已导入 ' + r.added + " 条</span>";
            refresh();
          }).catch(function (e) { $("ingestMsg").innerHTML = '<span class="bad">' + esc(e.message) + "</span>"; });
          return;
        } catch (e) {
          $("ingestMsg").innerHTML = '<span class="bad">JSON 解析失败，按纯文本导入</span>';
        }
      }
      ingestText(t, f.name);
    };
    rd.readAsText(f, "utf-8");
    $("file").value = "";
  };
  $("ask").onclick = ask;
  $("q").addEventListener("keydown", function (e) { if (e.key === "Enter") { ask(); } });
  $("clear").onclick = function () { $("log").innerHTML = ""; };

  if (TOKEN) { $("tok").value = TOKEN; }
  refresh();
})();
</script></body></html>"""
