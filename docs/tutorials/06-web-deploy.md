# 06 · Web 部署与嵌入

把应用变成站点可用、外部可调的服务。

## 1. 启动

```python
app.serve()                                    # 用配置里的 host/port
app.serve(host="0.0.0.0", port=9000)            # 显式覆盖
```

`serve()` 只在启用了 `web_gateway` 插件时可用，否则抛 `FrameworkError`
并告诉你怎么开。

检查是否起在预期端口（**这是最常见的困惑**）：

```bash
python -m pasm_framework config --preset chatbot     # 看 web_gateway 的 host/port
curl http://127.0.0.1:8080/healthz
```

## 2. 三种接入方式

### 2.1 iframe 一行嵌入（最快）

```html
<iframe src="http://your-host:8080/" width="420" height="620"
        style="border:0;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.12)">
</iframe>
```

`GET /` 返回一个自包含的聊天界面（HTML + CSS + JS 全在一个响应里，无外部依赖）。

### 2.2 REST 调用（任意语言）

```bash
curl -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"text":"怎么退货？","session_id":"user-42"}'
# → {"reply":"商品签收后 7 天内可无理由退货…","session_id":"user-42"}
```

多语言客户端见 [09 多语言客户端](09-polyglot-clients.md)。

### 2.2b 流式调用（SSE，体验最好）

```bash
curl -N -X POST http://127.0.0.1:8080/api/chat/stream \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer your-secret' \
  -d '{"text":"怎么退货？","session_id":"user-42"}'
```
```
data: {"type":"delta","text":"商品签收"}
data: {"type":"delta","text":"后 7 天内"}
data: {"type":"delta","text":"可无理由退货。"}
data: {"type":"done","session_id":"user-42","chars":16}
```

前端（浏览器原生 EventSource 不支持 POST，用 `fetch` + `ReadableStream`；
内置 Widget 就是这么写的，可以直接照抄）：

```js
const resp = await fetch("/api/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json", "Authorization": "Bearer your-secret" },
  body: JSON.stringify({ text, session_id: sid }),
});
const rd = resp.body.getReader(), dec = new TextDecoder();
let buf = "", acc = "";
for (;;) {
  const { value, done } = await rd.read();
  if (done) break;
  buf += dec.decode(value, { stream: true });
  const parts = buf.split("\n\n"); buf = parts.pop();
  for (const p of parts) {
    if (!p.startsWith("data:")) continue;
    const ev = JSON.parse(p.slice(5).trim());
    if (ev.type === "delta")        { acc += ev.text; render(acc); }
    else if (ev.type === "replace") { acc = ev.text; render(acc); }  // 护栏改写过 → 替换
    else if (ev.type === "error")   { showError(ev.error); }
  }
}
```

> **`replace` 事件必须处理**。它是护栏/润色改写内容后的"纠正通知"——
> 忽略它意味着用户屏幕上会残留未脱敏的文本。
> 想知道为什么需要它，见 [05 教程 §8](05-llm-integration.md)。

### 2.3 把站点数据推进资料库

```bash
curl -X POST http://127.0.0.1:8080/api/ingest \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer your-secret' \
  -d '{"items":[{"title":"会员积分","content":"消费 1 元积 1 分，100 分抵 1 元。","source":"cms","tags":["积分"]}]}'
# → {"added":1,"total":8,"docs":8,"qa":0,"enabled":true}
```

这是"站点数据自然形成资料库"的**同步入口** —— 从 CMS/数据库/README
定时推送即可。

## 3. 完整接口

| 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/api/chat` | `{text, session_id?, user_id?, meta?}` → `{reply, session_id}` | 是 |
| POST | `/api/chat/stream` | 同上入参 → **SSE**（`delta`/`replace`/`done`/`error`） | 是 |
| POST | `/api/ingest` | `{items:[…]}` → `{added,total,docs,qa}` | 是 |
| POST | `/api/sessions/reset` | `{session_id}` → `{ok}` | 是 |
| GET | `/api/plugins` | 插件清单与启用状态 | 是 |
| GET | `/api/summary` | 应用快照 | 是 |
| GET | `/api/kb/stats` | 资料库统计 | 是 |
| GET | `/healthz` | 健康 + 指标 | **否**（探针用） |
| GET | `/` `/widget` | 可嵌入 Widget | 是 |

契约单一真相源：[`../openapi.yaml`](../openapi.yaml)。

## 4. 安全配置（公网必做）

```python
cfg = load(preset_name="api",           # api 预设：护栏 block + 不润色
           web_gateway={"enabled": True, "config": {
               "host": "0.0.0.0",
               "port": 8080,
               "token": "your-secret",       # Bearer 鉴权
               "rate_limit": 60,             # 每 IP 每分钟 60 次
               "max_body": 262144,           # 请求体上限 256KB
               "allowed_origins": "https://your-site.com",   # CORS 白名单
           }})
```

| 配置 | 作用 | 建议 |
| --- | --- | --- |
| `token` | 要求 `Authorization: Bearer <token>` 或 `X-Pasm-Token` | 公网**必须**设 |
| `rate_limit` | 每 IP 每分钟请求上限（0=关） | 内网 0，公网 30–120 |
| `max_body` | 请求体字节上限 | 默认 256KB，够用 |
| `allowed_origins` | CORS 允许来源 | 别用 `*`，写具体域名 |

状态码语义：`400` 参数错 ｜ `401` 鉴权失败 ｜ `409` 知识库未启用 ｜
`413` 请求体过大 ｜ `429` 被限流 ｜ `500` 内部错。

设了 `token` 后，Widget 页面也会要求鉴权，并把令牌注入到自己的 JS 里
（所以能正常对话，但别人无法直接访问 `/api/chat`）。

## 5. 反向代理（生产必备）

框架自带的网关是**零依赖的兜底**，生产请在前面放 Nginx/Caddy 处理
TLS、连接池、压缩、更强的限流。

**Caddy**（自动 HTTPS，最省事）：

```caddyfile
chat.your-domain.com {
    encode gzip
    reverse_proxy 127.0.0.1:8080
}
```

**Nginx**：

```nginx
server {
    listen 443 ssl http2;
    server_name chat.your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/chat.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chat.your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;          # LLM 回复慢，别用默认 60 以下的短超时
    }

    location /healthz { proxy_pass http://127.0.0.1:8080/healthz; access_log off; }
}
```

> `X-Forwarded-For` 会被网关用于限流取真实 IP，代理里记得带上。

## 6. 常驻运行

**systemd**（Linux）：

```ini
# /etc/systemd/system/pasm-chat.service
[Unit]
Description=pasm-framework customer service
After=network.target

[Service]
Type=simple
User=pasm
WorkingDirectory=/opt/pasm-chat
Environment="PASM_HTTP_TOKEN=your-secret"
Environment="PASM_KB_DIR=/var/lib/pasm/kb"
Environment="PASM_LLM_PROVIDER=deepseek"
Environment="PASM_LLM_API_KEY=sk-xxx"
ExecStart=/opt/pasm-chat/venv/bin/python main.py --serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Docker**：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pasm-framework
COPY main.py .
ENV PASM_KB_DIR=/data/kb PASM_HTTP_HOST=0.0.0.0 PASM_HTTP_PORT=8080
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["python", "main.py", "--serve"]
```

> 资料库目录（`kb_dir`）**必须挂卷**，否则容器重建后自学成果全丢。

## 7. 上线前检查清单

- [ ] `token` 已设置，且不是默认值
- [ ] `rate_limit` 已开启（公网）
- [ ] `allowed_origins` 写的是具体域名
- [ ] 反向代理已配 TLS，且传了 `X-Forwarded-For`
- [ ] `kb_dir` 已持久化（卷/主机目录）
- [ ] `/healthz` 已接入探针
- [ ] 用 `safety` 的 `mode="block"`（公网宁可拦错）
- [ ] 已验证 LLM 不可用时会降级（不会 500）
- [ ] 资料库里没有敏感信息（脱敏只作用于**回复出站**，不作用于资料本身）

## 验证

```bash
# 1) 免鉴权健康检查
curl -s http://127.0.0.1:8080/healthz | python -m json.tool

# 2) 未带令牌应 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' -d '{"text":"hi"}'
# → 401

# 3) 带令牌应 200
curl -s -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer your-secret' \
  -d '{"text":"怎么退货？"}'

# 4) 限流：连打 5 次（rate_limit=3 时后两次应 429）
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w '%{http_code} ' -X POST http://127.0.0.1:8080/api/chat \
    -H 'Content-Type: application/json' -H 'Authorization: Bearer your-secret' \
    -d '{"text":"hi"}'
done; echo
```

## 下一步

- 换语言接入 → [09 多语言客户端](09-polyglot-clients.md)
- 观测与排查 → [08 打包与运维](08-packaging-and-ops.md)
