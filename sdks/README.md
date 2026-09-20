# pasm-framework 客户端 SDK

给**非 Python 技术栈**接入 pasm-framework 的薄客户端。

## 为什么是"客户端"而不是"移植"

pasm-framework 的认知能力（记忆分层 / 情绪 / 学习）跑在 Python 上，依赖
torch/numpy 生态；把它翻译成 C#/Java/PHP 既不现实也没有必要。
正确做法是**协议优先**：一个大脑（Python 服务），多语言客户端（HTTP/JSON）。
详见 [`../docs/polyglot-strategy.md`](../docs/polyglot-strategy.md)。

契约的单一真相源是 [`../docs/openapi.yaml`](../docs/openapi.yaml)。

## 客户端一览

| 语言 | 文件 | 依赖 | 最低版本 |
| --- | --- | --- | --- |
| Python | `python/pasm_client.py` | 无（标准库 `urllib`） | 3.8+ |
| Node.js | `node/pasm-client.js` | 无（内置 `fetch`） | 18+ |
| C# / .NET | `csharp/PasmClient.cs` | 无（`System.Net.Http`） | .NET 6+ |
| Java | `java/PasmClient.java` | 无（`java.net.http`） | JDK 11+ |
| PHP | `php/PasmClient.php` | cURL 扩展 | 7.4+ |
| Go | `go/pasm_client.go` | 无（`net/http`） | 1.18+ |

每个客户端覆盖：`chat` / `ingest` / `health` / `kb_stats`，并把
`401 / 409 / 413 / 429` 映射成语义化异常（而不是让你去判断状态码）。

**流式**（v0.3.0）：Python 有 `chat_stream()`、Node 有 `chatStream()`，
逐条产出 `delta` / `replace` / `done` / `error` 事件。
其余语言接 `POST /api/chat/stream` 即可（SSE 文本流，任何语言十行内可解析）。
`replace` 必须处理 —— 它是护栏改写内容后的纠正通知。

## 先起服务

```bash
pip install pasm-framework
PASM_HTTP_TOKEN=your-secret python -m pasm_framework serve --port 8080 --kb ./kb
```

或写一个自己的应用：

```python
from pasm_framework import load, SimpleApplication

cfg = load(preset_name="api", web_gateway={
    "enabled": True,
    "config": {"host": "0.0.0.0", "port": 8080, "token": "your-secret"}})
app = SimpleApplication("brain", {"name": "小智", "role": "客服"}, backend_config=cfg)
app.teach([{"title": "退货政策", "content": "7 天内无理由退货。", "source": "faq"}])
app.serve()
```

## 各语言最小示例

```bash
# Python
python -c "from pasm_client import PasmClient; \
  print(PasmClient('http://127.0.0.1:8080','your-secret').chat('怎么退货？'))"

# Node
node -e "const {PasmClient}=require('./node/pasm-client'); \
  new PasmClient('http://127.0.0.1:8080','your-secret').chat('怎么退货？').then(console.log)"

# PHP
php -r "require 'php/PasmClient.php'; \
  echo (new PasmClient('http://127.0.0.1:8080','your-secret'))->chat('怎么退货？');"
```

Java / C# / Go 的用法见各自文件顶部的注释。

## 验证状态（诚实说明）

| 语言 | 状态 | 验证内容 |
| --- | --- | --- |
| **Python** | ✅ 已真机验证 | `chat` / `ingest` / `kb_stats` / `plugins` / `health` / 401 错误映射 |
| **Node.js** | ✅ 已真机验证 | 同上（含 `PasmError` 类型与状态码） |
| C# | ⚠️ **未真机验证** | 开发机无 .NET SDK，仅完成代码 |
| Java | ⚠️ **未真机验证** | 开发机无 JDK，仅完成代码 |
| PHP | ⚠️ **未真机验证** | 开发机无 PHP，仅完成代码 |
| Go | ⚠️ **未真机验证** | 开发机无 Go，仅完成代码 |

**发包前请务必补齐真机冒烟**（起服务 → 各语言跑 `chat` + `health`）。

## 注意

- 这些是**参考实现**，旨在把契约固化成可运行代码。要发到
  NuGet / Maven Central / Packagist / npm / Go module 前，先按上表补齐验证。
- Java 客户端为避免强制引入 Jackson/Gson，内置了一个极简 JSON 字段提取器
  （只够解析本网关的扁平响应）。项目里若已有 JSON 库，建议替换 `Json.pick()`。
- **流式输出（SSE）尚未提供** —— 见 `../docs/capability-matrix-2026-09-20.md` §5 P0-1。
  客户端会在该特性落地后统一补 `chat_stream()`。
- 生产环境请在前面加反向代理（TLS、连接池、限流），网关自身的限流只是兜底。
