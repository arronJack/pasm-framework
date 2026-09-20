# 09 · 多语言客户端接入（C# / Java / PHP / Node / Go）

**先读一段结论**：不要把 pasm-framework 翻译成其它语言。
正确做法是"一个 Python 大脑 + 多语言薄客户端"。
完整论证见 [`../polyglot-strategy.md`](../polyglot-strategy.md)。

## 1. 先起服务

```bash
PASM_HTTP_TOKEN=your-secret python -m pasm_framework serve --port 8080 --kb ./kb
```

或用自己的应用：

```python
from pasm_framework import SimpleApplication, load

cfg = load(preset_name="api",
           web_gateway={"enabled": True, "config": {
               "host": "0.0.0.0", "port": 8080, "token": "your-secret"}})
app = SimpleApplication("brain", {"name": "小智", "role": "客服"}, backend_config=cfg)
app.teach([{"title": "退货政策", "content": "7 天内无理由退货。", "source": "faq"}])
app.serve()
```

## 2. 契约

所有语言共用同一份契约（[`../openapi.yaml`](../openapi.yaml)）：

```
POST /api/chat            {text, session_id?, user_id?, meta?} → {reply, session_id}
POST /api/ingest          {items:[{title,content,source?,tags?}]} → {added,total,...}
POST /api/sessions/reset  {session_id} → {ok}
GET  /healthz             健康（免鉴权）
GET  /api/kb/stats        资料库统计
鉴权：Authorization: Bearer <token>  或  X-Pasm-Token: <token>
```

## 3. C# / .NET

`sdks/csharp/PasmClient.cs`（零依赖，BCL 即可）：

```csharp
using Pasm;

using var c = new PasmClient("http://127.0.0.1:8080", "your-secret");

Console.WriteLine(await c.ChatAsync("怎么退货？", sessionId: "user-1"));

await c.IngestAsync(new[] {
    new IngestItem { Title = "会员积分", Content = "消费 1 元积 1 分。", Source = "cms" }
});

var health = await c.HealthAsync();
Console.WriteLine(health.GetProperty("status").GetString());
```

异常处理：

```csharp
try { await c.ChatAsync("hi"); }
catch (PasmException ex) when (ex.Status == 401) {
    Console.WriteLine("令牌不对：" + ex.Hint);
}
```

适用：WPF / WinForms / WinUI / MAUI / ASP.NET Core。

## 4. Java

`sdks/java/PasmClient.java`（JDK 11+，`java.net.http`，零第三方依赖）：

```java
import pasm.PasmClient;

try (var c = new PasmClient("http://127.0.0.1:8080", "your-secret")) {
    System.out.println(c.chat("怎么退货？", "user-1", null));

    c.ingest(java.util.List.of(
        PasmClient.item("会员积分", "消费 1 元积 1 分。", "cms")));

    System.out.println(c.kbStats());
}
```

```bash
javac -d out sdks/java/PasmClient.java
java -cp out pasm.PasmClient http://127.0.0.1:8080 your-secret
```

适用：Spring Boot / Vert.x / Android（API 26+）。

## 5. PHP

`sdks/php/PasmClient.php`（cURL 扩展）：

```php
require __DIR__ . '/sdks/php/PasmClient.php';

$c = new PasmClient('http://127.0.0.1:8080', 'your-secret');

echo $c->chat('怎么退货？', 'user-1');

$c->ingest([
    ['title' => '会员积分', 'content' => '消费 1 元积 1 分。', 'source' => 'cms'],
]);

print_r($c->kbStats());
```

```bash
php sdks/php/PasmClient.php http://127.0.0.1:8080 your-secret
```

适用：Laravel / ThinkPHP / WordPress 插件。

## 6. Node.js / TypeScript

`sdks/node/pasm-client.js`（内置 `fetch`，Node 18+）：

```js
const { PasmClient, PasmError } = require('./sdks/node/pasm-client');

const c = new PasmClient('http://127.0.0.1:8080', 'your-secret');

console.log(await c.chat('怎么退货？', { sessionId: 'user-1' }));

await c.ingest([{ title: '会员积分', content: '消费 1 元积 1 分。', source: 'cms' }]);

console.log(await c.kbStats());
```

适用：Express/Koa BFF、Electron/Tauri 桌面壳、Next.js API Route。

## 7. Go

`sdks/go/pasm_client.go`（标准库）：

```go
import "your-module/pasm"

c := pasm.NewClient("http://127.0.0.1:8080", "your-secret")

reply, err := c.Chat("怎么退货？", "user-1")
if err != nil {
    var pe *pasm.Error
    if errors.As(err, &pe) && pe.Status == 401 {
        log.Fatal("令牌不对：", pe.Hint)
    }
    log.Fatal(err)
}
fmt.Println(reply)

added, _ := c.Ingest([]pasm.IngestItem{
    {Title: "会员积分", Content: "消费 1 元积 1 分。", Source: "cms"},
})
health, _ := c.Health()
```

带 context 的版本（推荐在 HTTP 服务里用）：`c.ChatContext(ctx, text, sessionID, userID)`。

## 8. Python（跨进程调用）

同进程直接 `import pasm_framework` 更快、功能更全；
只有跨机/跨进程时才需要客户端：

```python
from pasm_client import PasmClient

c = PasmClient("http://127.0.0.1:8080", "your-secret")
print(c.chat("怎么退货？", session_id="user-1"))
```

## 9. 各语言的"最低接入成本"

| 语言 | 需要写多少 | 说明 |
| --- | --- | --- |
| C# | 拷 `PasmClient.cs` 到项目 | BCL 够用，无需 NuGet |
| Java | 拷 `PasmClient.java` | JDK 11+ 够用，无需 Maven 依赖 |
| PHP | 拷 `PasmClient.php` | 需 cURL 扩展（几乎都有） |
| Node | 拷 `pasm-client.js` | Node 18+ |
| Go | 拷 `pasm_client.go` 改 package 名 | 标准库 |

## 10. 客户端验证状态（诚实说明）

| 语言 | 状态 |
| --- | --- |
| **Python** | ✅ 已在本机对真实服务端跑通（chat / ingest / kbStats / 401 映射） |
| **Node.js** | ✅ 已在本机对真实服务端跑通（chat / ingest / kbStats / 401 映射） |
| C# | ⚠️ 代码已写，**本机无 .NET SDK，未做真机验证** |
| Java | ⚠️ 代码已写，**本机无 JDK，未做真机验证** |
| PHP | ⚠️ 代码已写，**本机无 PHP，未做真机验证** |
| Go | ⚠️ 代码已写，**本机无 Go，未做真机验证** |

**上线前请务必补一次真机冒烟**：起服务 → 各语言跑一遍 `chat` + `health`。
打包发布到包管理平台之前尤其要过这一关 —— 客户端库里"文档写了但跑不通"的代价很高。

> ⚠️ Java 客户端为避免强制引入 Jackson/Gson，内置了一个极简 JSON 字段提取器
> （只够解析本网关的扁平响应）。你的项目若已有 JSON 库，建议替换 `Json.pick()`。

## 11. 什么时候才该考虑"原生移植"

只有同时满足才值得讨论：必须端侧离线 ｜ 平台无法带 Python 运行时 ｜
认知能力可降级为固定档位 ｜ 能接受功能子集。
即便如此，更省力的仍是"端侧轻量规则层 + 联网时调完整大脑"。

## 下一步

- 论证与路线 → [`../polyglot-strategy.md`](../polyglot-strategy.md)
- 手机端怎么接 → [`../cross-platform-strategy.md`](../cross-platform-strategy.md)
