# 用 pasm-framework 做「站点智能客服」可行性研究

> 配套代码：`apps/customer_service.py`（开箱可用的参考实现）
> 关联插件：`knowledge_base` / `sessions` / `warmth` / `safety` / `observability` / `llm_responder` / `web_gateway`

## 1. 诉求拆解

用户诉求："通过站点相关数据自然形成资料库，从而**自学、记忆、成长**，有效回复客户，
达到**有情感、有温度、高效**的智能客服。"

| 诉求 | pasm-framework 对应能力 | 实现位置 |
| --- | --- | --- |
| 站点数据 → 资料库 | `knowledge_base.ingest(faq/docs)` 摄取 | 应用启动时同步一次 |
| 自学 / 成长 | `on_learn` 每次高质量问答沉淀 QA 对，KB 越用越厚 | `knowledge_base` 插件 |
| 记忆 | 情景记忆 `recall` + 领域 + KB 联合检索，回复有依据不瞎编 | `BaseApplication.recall` + `on_retrieve` |
| 有情感 / 有温度 | `warmth` 把 `emotion_system` 情绪与 persona 语气渲染进回复 | `warmth` 插件 |
| 高效 | 关键词检索 + 可选 LLM 生成 + 会话上下文 | `llm_responder` + `sessions` |
| 安全对外 | 注入拦截 + PII 脱敏 | `safety` 插件 |
| 可被站点接入（外部链接） | 零依赖 HTTP 网关（iframe / REST） | `web_gateway` 插件 |

**结论：完全可行，且天然契合 PASM 的"记忆 / 情绪 / 成长"基因**——这不是硬凑，
而是把 PASM 已有的三件套（记忆、情绪、自我成长）直接映射到客服场景。

## 2. 三种部署形态

### 形态 A：iframe 嵌入（最轻量，推荐起步）
站点加一行：
```html
<iframe src="http://<your-host>:8080/" width="380" height="600"
        frameborder="0" style="border:1px solid #e3e8f0;border-radius:12px"></iframe>
```
`web_gateway` 自带一个自包含聊天 Widget（`GET /`），无需前端开发。
CORS 由 `allowed_origins` 配置；生产建议设为站点域名而非 `*`。

### 形态 B：REST API 对接（已有前端 / 小程序）
```
POST /api/chat
{ "text": "怎么退货", "session_id": "cust-42", "user_id": "u88" }
→ { "reply": "...", "session_id": "cust-42" }
```
适合把客服能力接到自有 App / 微信小程序 / 工单系统。

### 形态 C：WebSocket（长连接、流式）
当前 `web_gateway` 是请求-响应式；若需"打字机流式输出"，在插件内把
`/api/chat` 升级为 WebSocket 即可（仍零依赖：`socket` 标准库），属于后续增强，
不影响现有契约。

## 3. 数据闭环（自学 / 记忆 / 成长）示意

```
站点 FAQ/文档 ──ingest──▶ 资料库(kb.jsonl)
                              │  on_retrieve
                              ▼
客户提问 ──▶ handle ──▶ 检索命中资料 ──▶ 回复（有依据）
                  │                      │
              on_learn ◀─────────────────┘
                  │
                  ▼
         沉淀 QA 对进资料库（成长）
                  │
     下次同类问题命中率↑、回答更准（记忆+自学）
```

关键机制：`knowledge_base.auto_learn`（默认开）。为避免噪声，只沉淀
"回复长度达标且资料库尚未覆盖"的问答；命中已有的高置信条目不重复存。

## 4. 安全与隐私（对外必读）

- **prompt 注入**：`safety` 默认 `mode="warn"`（标记不拦，避免误伤正常用户）；
  强监管场景设 `"mode":"block"` 直接拦截"忽略指令 / 泄露提示词"类越权。
- **PII 脱敏**：出站回复自动脱敏邮箱 / 手机号 / 密钥（`redact_pii` 默认开）。
- **数据合规**：资料库落在本机 `kb_dir`，不外传；若启用 LLM，问题文本会发往
  第三方（DeepSeek / OpenAI），需告知用户并取得同意；Ollama 可纯本地、零外发。
- **多租户**：`sessions` 按 `session_id` 隔离，但资料库是**全站共享**的——
  若需"每客户私有知识"，在 `knowledge_base` 增加 `tenant` 维度过滤即可（路线图中）。

## 5. 已知局限与路线图

| 局限 | 现状 | 路线 |
| --- | --- | --- |
| 检索精度 | 关键词 + 时效打分，无语义 | 接向量检索（替换 `knowledge_base.recall` 内部，对外契约不变） |
| 多语言 / 方言 | 依赖 LLM / 关键词 | 配置 persona 语言 + LLM 多语 |
| 复杂工单 | 单轮为主 | 接 `Capability` 做"转人工 / 查订单"动作 |
| 私有知识隔离 | 全站共享 KB | KB 增加 tenant 维度 |
| 流式输出 | 请求-响应式 | 升级 `/api/chat` 为 WebSocket |

## 6. 最小上手（5 行）

```python
from apps.customer_service import CustomerServiceAgent
cs = CustomerServiceAgent("shop-cs", kb_dir="./kb")
cs.ingest_faq([{"title":"退货","content":"7天无理由退货","source":"faq"}])
print(cs.ask("怎么退货？"))      # 基于资料回答
# cs.serve(port=8080)            # 站点 <iframe src="http://host:8080/">
```

> 本实现**不触碰引擎与 `CognitiveBackend` 协议**，纯应用层 + 插件层增量，
> 与"先完善再 V2.0"的约束一致。
