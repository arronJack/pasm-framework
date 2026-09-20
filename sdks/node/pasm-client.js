/**
 * pasm-framework Node.js 客户端（零依赖，用内置 fetch，需 Node 18+）。
 *
 * 用法：
 *   const { PasmClient, PasmError } = require("./pasm-client");
 *
 *   const c = new PasmClient("http://127.0.0.1:8080", "your-secret");
 *   console.log(await c.chat("怎么退货？", { sessionId: "user-1" }));
 *   await c.ingest([{ title: "退货政策", content: "7 天内无理由退货。", source: "faq" }]);
 *   console.log(await c.kbStats());
 *
 * 也可用作 Express/Koa 的 BFF 中间层，或 Electron/Tauri 桌面端的大脑客户端。
 */

class PasmError extends Error {
  constructor(message, status = 0, hint = "") {
    super(message);
    this.name = "PasmError";
    this.status = status;
    this.hint = hint;
  }
}

class PasmClient {
  /**
   * @param {string} baseUrl 例如 http://127.0.0.1:8080
   * @param {string|null} token 服务端配置的令牌；未配置则传 null
   * @param {number} timeout 超时毫秒
   */
  constructor(baseUrl = "http://127.0.0.1:8080", token = null, timeout = 30000) {
    this.baseUrl = String(baseUrl).replace(/\/+$/, "");
    this.token = token || "";
    this.timeout = timeout;
  }

  async _request(method, path, payload = undefined) {
    const headers = { Accept: "application/json" };
    const init = { method, headers };
    if (payload !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(payload);
    }
    if (this.token) headers.Authorization = "Bearer " + this.token;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let resp;
    try {
      resp = await fetch(this.baseUrl + path, { ...init, signal: controller.signal });
    } catch (err) {
      throw new PasmError(
        `无法连接 pasm-framework 服务：${err.message}`, 0,
        "确认服务已启动、地址与端口正确");
    } finally {
      clearTimeout(timer);
    }

    const text = await resp.text();
    let obj = {};
    try { obj = text ? JSON.parse(text) : {}; } catch { obj = { error: text.slice(0, 200) }; }
    if (!resp.ok) {
      throw new PasmError(obj.error || "请求失败", resp.status, obj.hint || "");
    }
    return obj;
  }

  /** 发一条消息，返回回复文本 */
  async chat(text, { sessionId = "default", userId = null, meta = null } = {}) {
    const payload = { text, session_id: sessionId };
    if (userId !== null) payload.user_id = userId;
    if (meta !== null) payload.meta = meta;
    const r = await this._request("POST", "/api/chat", payload);
    return r.reply || "";
  }

  /**
   * 流式发送，逐条产出事件对象（async generator）。
   *
   * 事件：{type:"delta",text} / {type:"replace",text} / {type:"done"} / {type:"error"}
   *
   * 用法：
   *   let acc = "";
   *   for await (const ev of c.chatStream("你好")) {
   *     if (ev.type === "delta") { acc += ev.text; process.stdout.write(ev.text); }
   *     else if (ev.type === "replace") acc = ev.text;   // 护栏改写过 → 整条替换
   *   }
   */
  async *chatStream(text, { sessionId = "default", userId = null, meta = null } = {}) {
    const payload = { text, session_id: sessionId };
    if (userId !== null) payload.user_id = userId;
    if (meta !== null) payload.meta = meta;
    const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
    if (this.token) headers.Authorization = "Bearer " + this.token;

    let resp;
    try {
      resp = await fetch(this.baseUrl + "/api/chat/stream", {
        method: "POST", headers, body: JSON.stringify(payload),
      });
    } catch (err) {
      throw new PasmError(
        `无法连接 pasm-framework 服务：${err.message}`, 0,
        "确认服务已启动、地址与端口正确");
    }
    if (!resp.ok) {
      const raw = await resp.text();
      let obj = {};
      try { obj = JSON.parse(raw); } catch { obj = { error: raw.slice(0, 200) }; }
      throw new PasmError(obj.error || "请求失败", resp.status, obj.hint || "");
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const chunk = line.slice(5).trim();
        if (!chunk) continue;
        try { yield JSON.parse(chunk); } catch { /* 跳过坏帧 */ }
      }
    }
  }

  /** 批量写入资料库，返回新增条数（需服务端启用 knowledge_base） */
  async ingest(items) {
    const r = await this._request("POST", "/api/ingest", { items });
    return r.added || 0;
  }

  async resetSession(sessionId) {
    const r = await this._request("POST", "/api/sessions/reset", { session_id: sessionId });
    return !!r.ok;
  }

  kbStats() { return this._request("GET", "/api/kb/stats"); }
  plugins() { return this._request("GET", "/api/plugins"); }
  summary() { return this._request("GET", "/api/summary"); }

  /** 健康检查（免鉴权） */
  health() { return this._request("GET", "/healthz"); }
}

module.exports = { PasmClient, PasmError };
