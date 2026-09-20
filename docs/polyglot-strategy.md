# 多语言策略：C# / Java / PHP / Node 等如何"用上" pasm-framework

> 你问的是：「pasm-framework 目前是 Python 版，是否能添加 C#版、Java 版、PHP 版？」
> 这是本文的核心问题。结论先行，论证在后，最后给可运行的参考实现。

---

## 0. 结论

**不要把认知引擎移植成 C#/Java/PHP —— 正确做法是"协议优先 + 薄客户端"。**

三层拆开看，问题就清楚了：

| 层 | 是什么 | 该用什么语言 | 能不能换语言 |
| --- | --- | --- | --- |
| 认知引擎 | 记忆分层 / 情绪系统 / 学习 / 世界模型 | Python（已依赖 torch/numpy 生态） | ❌ 不换。换了要重写神经符号层，且两份实现会漂移 |
| 应用框架 | 插件链 / 能力路由 / 领域适配 / 会话 / 护栏 | Python（都在调用引擎对象） | ❌ 不换。换语言 = 每加一个插件要在 N 个语言里各写一遍 |
| **接入层** | HTTP / JSON 契约 | **任何语言** | ✅ 这就是给 C#/Java/PHP 的入口 |

所以答案是：**能做，但做的不是"Python 版的翻译"，而是"各语言的官方客户端 + 一份稳定契约"。**
C# / Java / PHP / Node / Go 的调用方拿到的是**一样的 API、一样的行为**，不需要理解 PASM 内部。

---

## 1. 为什么不能/不该移植认知引擎

| 论据 | 说明 |
| --- | --- |
| **依赖生态** | 引擎的 `bionic` 档位依赖 torch；数值/向量运算依赖 numpy。C#/Java/PHP 里没有等价且行为一致的实现，重写等于换一套算法 —— 那就不是 PASM 了 |
| **两份实现必然漂移** | 引擎是**持续演进**的（V1→V2 正在规划）。两份实现意味着每个 bug 修两遍、每个特性做两遍，最终行为不一致。桌面端已经吃过这个亏（`desktop/` 与 `pasm/cognitive/` 同名模块要靠 fork 铁律同步） |
| **防腐层的意义会被破坏** | `pasm-framework` 存在的全部意义是"引擎改动只动一个地方"。多语言重写会把"一个变动点"变成 N 个 |
| **投入产出比** | 全量移植约等于重做整个项目；协议优先约 1–2 天就能给 5 个语言可用客户端，且**后续零维护成本**（契约不变就不用改） |

> 唯一值得认真考虑原生移植的场景：**必须在端侧离线运行且无法带 Python 运行时**（见 §5）。

---

## 2. 三条路线对比

| 方案 | 做法 | 客户端体验 | 工作量 | 长期维护 | 结论 |
| --- | --- | --- | --- | --- | --- |
| A. 全量重写 | 用目标语言重写引擎+框架 | 原生最佳 | 极大（月～年级） | 每特性 ×N | ❌ 不做 |
| B. FFI / 嵌入式解释器 | C# 用 Python.NET、Java 用 Jython/GraalPy、PHP 用嵌入 CPython | 接近原生，但只有进程内调用 | 中～大 | 版本/ABI 兼容问题多，PHP 尤其差 | ❌ 仅特定内嵌场景考虑 |
| C. **协议优先 + 薄客户端** | 服务端跑 pasm-framework，暴露 HTTP/JSON；各语言给官方客户端 | 一行调用拿到回复；跨进程/跨机/跨云都行 | **小** | 契约稳定即零维护 | ✅ **推荐** |

方案 C 的额外好处：客户端语言与部署形态解耦 —— 同一个大脑可以同时被 C# 桌面端、
Java 后端、PHP 站点、Node BFF 调用，还能水平扩容。

---

## 3. 推荐架构

```
                    ┌─────────────────────────────────────┐
   C# / .NET ──────▶│                                     │
   Java / Spring ──▶│   pasm-framework 服务进程（Python）  │
   PHP / Laravel ──▶│   ├─ plugins: knowledge_base        │
   Node / Express ─▶│   │            sessions / safety    │
   Go / Gin ───────▶│   │            llm_responder / ...  │
   Python ─────────▶│   └─ web_gateway  (HTTP/JSON)       │
                    │        ▲ 契约单一真相源              │
                    │   docs/openapi.yaml                 │
                    └───────────────┬─────────────────────┘
                                    ▼
                    ┌─────────────────────────────────────┐
                    │ 认知引擎 pasm.*（记忆/情绪/学习）    │
                    └─────────────────────────────────────┘
```

启动服务（一条命令）：

```bash
PASM_HTTP_TOKEN=your-secret python -m pasm_framework serve --port 8080 --kb ./kb
```

或在代码里：

```python
from pasm_framework import load, SimpleApplication

cfg = load(preset_name="api", env=True,
           web_gateway={"enabled": True,
                        "config": {"host": "0.0.0.0", "port": 8080, "token": "your-secret"}})
app = SimpleApplication("brain", {"name": "小智", "role": "客服"}, backend_config=cfg)
app.teach([{"title": "退货政策", "content": "7 天内无理由退货。", "source": "faq"}])
app.serve()
```

---

## 4. 契约（所有语言共用）

**单一真相源：[`docs/openapi.yaml`](openapi.yaml)**。改接口必须先改它。

| 方法 | 路径 | 说明 | 需要鉴权 |
| --- | --- | --- | --- |
| POST | `/api/chat` | `{text, session_id?, user_id?, meta?}` → `{reply, session_id}` | 是 |
| POST | `/api/ingest` | `{items:[{title,content,source?,tags?}]}` → `{added,total,...}` | 是 |
| POST | `/api/sessions/reset` | `{session_id}` → `{ok}` | 是 |
| GET | `/api/plugins` | 插件清单与启用状态 | 是 |
| GET | `/api/summary` | 应用快照（能力/插件/指标） | 是 |
| GET | `/api/kb/stats` | 资料库统计 | 是 |
| GET | `/healthz` | 健康 + 指标（探针用，**免鉴权**） | 否 |

鉴权：`Authorization: Bearer <token>` 或 `X-Pasm-Token: <token>`。
未配置 `token` 时开放（仅建议在本机/内网）。
错误：`400` 参数错、`401` 鉴权失败、`409` 资料库未启用、`413` 请求体过大、`429` 限流、`500` 内部错。

---

## 5. 各语言参考客户端

已放在仓库 `sdks/` 下，都是**零第三方依赖的薄封装**（标准 HTTP 库），可直接拷进项目：

| 语言 | 文件 | 依赖 | 用法 |
| --- | --- | --- | --- |
| C# / .NET | `sdks/csharp/PasmClient.cs` | `System.Net.Http`（BCL） | `await client.ChatAsync("怎么退货？")` |
| Java | `sdks/java/PasmClient.java` | `java.net.http`（JDK 11+） | `client.chat("怎么退货？")` |
| PHP | `sdks/php/PasmClient.php` | cURL 扩展 | `$c->chat("怎么退货？")` |
| Node / TS | `sdks/node/pasm-client.js` | 内置 `fetch`（Node 18+） | `await client.chat("怎么退货？")` |
| Go | `sdks/go/pasm_client.go` | `net/http` | `c.Chat("怎么退货？")` |
| Python | `sdks/python/pasm_client.py` | `urllib` | `c.chat("怎么退货？")` |

每个客户端都提供：`chat()` / `chatAsync()`、`ingest()`、`health()`、`kb_stats()`，
以及统一的错误类型（把 401/429/409 等映射成语义异常）。

> Python 项目通常**不需要**这个客户端 —— 直接 `import pasm_framework` 进程内调用更快
> （省掉 HTTP 往返，且能用 `Capability`/`DomainAdapter` 等高级表面）。客户端主要给非 Python 技术栈。

---

## 6. 什么时候才该考虑原生移植

只有满足**全部**条件才值得讨论：

1. 必须在**端侧离线**运行（无网、无服务端）；
2. 该平台**无法携带 Python 运行时**（如 iOS 原生 APP、Unity 打包进主机的逻辑）；
3. 认知能力可以**降级为固定档位**（不需要 torch 的情绪/神经符号部分）；
4. 能接受**功能子集**（只有记忆 + 规则 + 模板回复）。

即便如此，更省力的做法仍是：**端侧放轻量规则层，联网时同步/调用完整大脑**
（离线期间的记忆先本地排队，恢复网络后回灌 —— 与 `knowledge_base` 的自学习模型天然契合）。

---

## 7. 分阶段落地建议

| 阶段 | 做什么 | 产出 | 代价 |
| --- | --- | --- | --- |
| 已完成 | 单语言（Python）框架 + HTTP 网关 + 鉴权 + 6 套场景预设 | `web_gateway` v0.2.0 | — |
| 已完成 | 契约文档 + 5 语言参考客户端 | `docs/openapi.yaml` + `sdks/` | 小 |
| 下一步 | 给客户端补**流式接口**（SSE），并加各语言的真机冒烟测试 | `chat_stream()` | 中 |
| 下一步 | 各语言发到对应包管理（NuGet / Maven Central / Packagist / npm / Go module） | 官方包 | 小～中 |
| 之后 | 按需加 gRPC 通道（强类型、双向流、跨语言代码生成） | proto + 生成代码 | 中 |
| 暂不做 | 引擎原生移植 | — | 极大 |

**建议现在就做**：把 `sdks/` 里的 5 个客户端补一句"真机验证"（各语言跑一次 `chat` + `health`），
再决定是否发包 —— 避免发出"文档写了但跑不通"的包，这在客户端库里口碑代价很高。

---

## 8. 一句话回答你的问题

> **C# / Java / PHP 版"能做，但不是把 Python 翻一遍。**
> 用 HTTP/JSON 契约 + 各语言官方客户端，1–2 天就能全部接通，
> 而且引擎以后升级 V2.0 时，这 5 个客户端**一行都不用改** ——
> 这正是 `pasm-framework` 那套"唯一变动点"设计的价值所在。
