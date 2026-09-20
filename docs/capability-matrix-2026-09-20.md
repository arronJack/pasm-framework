# pasm-framework 能力就绪度复检（v0.2.1）

> 复检日期：2026-09-20 ｜ 复检对象：`pasm-framework` v0.2.1（含本轮 v0.2.0→v0.2.1 的全部改动）
> 复检方式：逐文件通读 + 可执行验证（非文档推断）。所有结论都附"怎么验证的"。

---

## 0. 一句话结论

**能做**：站点/平台 AI 应用、智能客服、内部工具类 APP、有性格的游戏 NPC、桌面端"大脑服务"。
**暂时不能"开箱"直接做**：需要多端原生 UI 的完整 APP、高并发公网服务、需要 token 级流式输出的产品。
**不建议做**：用它替代游戏引擎（渲染/物理/帧循环），或替代 Web 框架做常规 CRUD。

关键判断依据是这一条：**pasm-framework 是「认知大脑 + 应用装配层」，不是「UI/渲染/传输框架」。**
它负责"记得住、有情绪、能自学、可换引擎"，不负责"画出来、跑得快、连得上"——后者交给
PySide6 / Flutter / Unity / 浏览器 / 反向代理，框架通过 HTTP 或进程内调用提供大脑能力。

---

## 1. 场景 × 能力矩阵

图例：✅ 开箱可用 ｜ 🔶 可用但需自己补一层 ｜ ❌ 当前不具备（且不建议由本框架承担）

| 场景 | 状态 | 框架已提供 | 还差什么 | 补齐代价 |
| --- | --- | --- | --- | --- |
| 站点智能客服 | ✅ | 知识库摄取/检索/自学、会话隔离、温度润色、护栏、HTTP 网关、鉴权、限流 | 工单升级、人工接管、多租户配额 | 中 |
| 企业知识问答 / 内部助手 | ✅ | 同上 + `SimpleApplication` 三行起步 | 权限过滤（按用户过滤资料）、审计日志 | 小 |
| 微信公众号 / 小程序客服 | 🔶 | REST `/api/chat` + `/api/ingest` | 平台消息加解密、access_token 管理 | 小（平台侧 SDK） |
| 网站 AI 挂件 | ✅ | `/` 自包含 Widget + `<iframe>` 一行嵌入 | 主题定制、悬浮球样式 | 很小 |
| 桌面应用（Windows） | ✅ | 进程内直接调 `handle()`、本机 HTTP（`127.0.0.1`） | 无（pasm-qclaw 已验证此路径） | — |
| 桌面应用（Linux/macOS） | 🔶 | 同 Windows，代码零改动 | 打包链 + 签名公证，见 `cross-platform-strategy.md` | 中 |
| 手机 APP | 🔶 | 云端大脑 + REST/SSE | 端侧 UI 与鉴权；**不可**把 Python 直接装进手机 | 中～大 |
| 游戏 NPC（对话/记忆/情绪） | ✅ | 记忆、情绪、`feedback` 塑形、离线零依赖 | 帧循环内的低延迟批量调度 | 小～中 |
| 游戏 NPC（战斗/寻路/动画） | ❌ | — | 请用 Unity/Unreal/Godot；本框架只做"人格与记忆"层 | 不适用 |
| 完整 CRUD 业务系统 | ❌ | — | Django/FastAPI/Spring；本框架不做路由/ORM/模板 | 不适用 |
| 高并发公网 API | 🔶 | 零依赖 HTTP 网关（标准库） | 前置 Nginx/Caddy 做 TLS、连接池、限流 | 小（运维层） |
| 流式对话体验 | ❌ | — | 需实现 SSE/WebSocket + LLM 流式解析（见 §5 P1-1） | 中 |
| 私有化 / 断网部署 | ✅ | 零外部依赖，不用 LLM 也能"就资料作答" | 无 | — |
| 多语言技术栈 | 🔶 | HTTP/JSON 契约 + 5 语言参考客户端 | 各语言按需自行封装（见 `polyglot-strategy.md`） | 小 |

---

## 2. v0.2.1 已具备的表面（全部有自检覆盖）

```
装配 / 防腐层   CognitiveAssembler · CognitiveService · CognitiveBackend(重导出)
领域与能力      DomainAdapter · StaticDomainAdapter · CapabilityDiscovery · Capability
应用底座        BaseApplication（全功能） · SimpleApplication（3 行起步）
插件子系统      PluginManager · BasePlugin · Plugin · Message · PluginContext · BackendConfig
配置系统        load · preset · save · to_dict · describe · PRESETS(6 套场景)
技能包          BaseSkill · SkillManifest
CLI             selftest · version · plugins · config · doctor · new · serve
```

插件库（7 个，全部零强制依赖，可后端开关）：

| 插件 | 作用 | 默认 |
| --- | --- | --- |
| `knowledge_base` | 资料摄取 → 倒排索引检索 → 优质问答自学习沉淀 | 开 |
| `sessions` | 会话 / 租户隔离，记住每个客户上下文 | 开 |
| `llm_responder` | LLM 接入（OpenAI 兼容 / DeepSeek / Ollama），失败静默回落 | 关 |
| `warmth` | 情绪驱动的回复润色，确定性选句 | 开 |
| `safety` | 注入拦截 + 出站 PII 脱敏（覆盖所有回复路径） | 开 |
| `observability` | 指标 + 健康（`/healthz`） | 开 |
| `web_gateway` | HTTP 网关：鉴权 / 限流 / 摄取 / 嵌入 Widget | 关 |

---

## 3. 本轮（v0.2.0 → v0.2.1）修掉的真实缺陷

每条都配了**可证伪的反例**（先确认改坏的版本能被抓住，再确认修好）。

### 缺陷 1：离线模式绕过护栏（安全）—— 已修
`on_reply` 阶段模板兜底回复**尚未生成**，而 `safety` 的脱敏挂在 `on_reply` 上，
导致**不接 LLM 的离线路径回复完全不脱敏**。

- 反例：模板回复写死 `13812345678`，旧版输出原样手机号；新版输出 `[手机号已脱敏]`。
- 修法：拆出**收尾阶段** `on_reply_final`，由 `handle` 在唯一出口调用，
  对"能力命中 / LLM 生成 / 模板兜底"三条路径**恰好各跑一次**。
- 不变式测试：探针插件计数 `on_reply_final == 2`（两条路径各一次）。

### 缺陷 2：知识库每次检索都全量重写磁盘（性能）—— 已修
`recall()` 命中后调 `_save()` 重写整个 `kb.jsonl` → 每次问答 O(全库) 磁盘写。

- 反例：`recall` 5 次后断言文件 `mtime` 不变；旧版必变。
- 修法：读路径不落盘（`hits` 只是统计量），写入改 `_append_new()` 只追加新条目。

### 缺陷 3：检索线性扫描 + 每次重新分词（性能）—— 已修
每次查询对全库重新分词（O(n·m)）。改为**倒排索引 + 分字段分词缓存**。

实测（同机同数据，旧实现 vs 新实现）：

| 库规模 | 查询类型 | 旧 | 新 | 提速 |
| --- | --- | --- | --- | --- |
| 2,000 条 | 区分度高 | 24.2 ms | 0.27 ms | **89×** |
| 2,000 条 | 退化（命中全库） | 23.9 ms | 2.49 ms | 9.6× |
| 20,000 条 | 区分度高 | 240.0 ms | 3.17 ms | **76×** |
| 20,000 条 | 退化（命中全库） | 249.7 ms | 30.4 ms | 8.2× |

> 退化场景（查询词几乎每个文档都有）本质是"必须给所有候选打分"，索引帮不上；
> 真实语料里查询词通常是区分性的，因此实际提速接近 76–89×。

### 缺陷 4：标题命中与正文顺带提到同权 → 答非所问（相关性）—— 已修
问"怎么退货"时，**运费说明**条目（正文含一句"退货运费由我方承担"）得分反超
**退货政策**（标题就叫退货）——因为原打分只看总重叠数，且后来写入的条目
因时效项微高而"赢在毫秒上"。

- 反例：6 个问题逐一断言首条命中（改坏前后对比可复现差异）。
- 修法：**分字段加权**（标题 ×3 > 标签 ×2 > 正文 ×1）。修复后：

```
怎么退货？ → 退货政策 (13.5)      能换货吗 → 换货流程 (13.5)
多久能发货 → 配送时效 (6.8)       运费怎么算 → 运费说明 (13.2)
怎么开发票 → 发票 (13.2)          老板是谁 → 无命中（如实说不知道）
```

### 缺陷 5：`serve()` 忽略配置端口（易用性）—— 已修
配置里写 `port=9000`，`app.serve()` 却起在默认 8080。
改为 `serve(host=None, port=None)`：不传就用配置值，显式传才覆盖。

### 缺陷 6：`warmth` 用 `hash()` 选句 → 跨进程不可复现 —— 已修
CPython 对 str 的 `hash` 带每进程随机盐（PYTHONHASHSEED），同一句话
不同进程选到不同措辞：测试不可复现、线上表现随机。改用 `zlib.crc32`。

---

## 4. "更快更优"具体优化了什么

| 维度 | 优化前 | 优化后 |
| --- | --- | --- |
| 最小应用代码量 | 需实现 `action_pool` + `_render_reply`（约 30 行样板） | `SimpleApplication("id", {"name":"小智"})` 可用；加能力 = 加一个 `@capability` 方法 |
| 加一个能力 | 手写 `Capability(name, run=..., keywords=...)` 并注册 | 方法上打 `@capability(keywords=("退货",))` 自动注册 |
| 改配置 | 改 Python 代码再发版 | 6 套场景预设 + JSON/YAML 文件 + `PASM_*` 环境变量，优先级 preset<file<env<代码 |
| 起项目 | 从零搭目录 | `pasm-framework new myapp --kind chatbot` → 立即可跑 |
| 排查"跑不起来" | 自己读 traceback | `pasm-framework doctor` 逐项体检并给修复建议 |
| 看插件开关 | 读源码 | `pasm-framework config --preset api --env` |
| 对外接入 | 无 | `pasm-framework serve` 一条命令得到可嵌入的客服 |
| 检索延迟（2 万条） | 240 ms | 3.2 ms |

---

## 5. 仍然存在的问题（按优先级）

### P0 —— 影响"能上线"的，建议下一个版本做

1. **无流式输出（SSE / WebSocket）**
   现状：`/api/chat` 一次性返回，LLM 长回复要等完整生成。
   影响：用户感知延迟高（这也是你反馈过的"对话回复慢"的体验侧根因之一）。
   建议：`llm_responder` 支持 `stream=True` 逐块读 + 网关加 `GET /api/chat/stream`（SSE）。

2. **资料库无持久化向量检索 / 无语义召回**
   现状：关键词 + 中文 bigram。已发现真实局限：问"多久**发货**"对 FAQ 写"24 小时内**发出**"
   匹配不上（同义不同字）。
   影响：客服答不上来率偏高，需要人工堆同义词。
   建议：保留现有接口不变（`recall(query,k)`），内部加可选向量后端（本地 embedding 模型即可），
   并把 `knowledge_base` 的 `min_score`（已预留）用于精度调节。

3. **无权限 / 多租户数据隔离**
   现状：`session_id` 隔离会话，但**资料库是全局的**——A 租户的资料 B 租户也能检索到。
   影响：SaaS 场景直接不可用。
   建议：`Message.meta["tenant"]` → 检索时按 `tenant` 过滤；插件配置加 `tenant_field`。

4. **`observability` 指标仅内存、无导出**
   现状：`/healthz` 给瞬时值，进程重启即丢，无 Prometheus 格式。
   建议：加 `GET /metrics`（Prometheus 文本格式）。

### P1 —— 提升体验与工程化

1. **无真实流式的对话 UI**（Widget 是一次性 fetch）。
2. **LLM 回复无重试 / 无超时分级 / 无多模型回退**：目前失败即回落模板。
   建议：`llm_responder` 支持 `fallbacks: [模型A, 模型B]`、指数退避。
3. **`sessions` 历史仅内存**：进程重启会话全丢。建议按 `session_id` 落盘可选开启。
4. **无对话摘要/长会话压缩**：`max_history=20` 之外的信息被丢弃（旧话题记不住）。
5. **`warmth` 是模板式润色**：措辞固定，长时间使用会显得重复（已有确定性选句，但池子小）。
6. **网关无 TLS**：公网必须前置反向代理（文档已注明，但应给 Nginx/Caddy 样例配置）。
7. **无 OpenAPI 校验中间件**：契约文档已给（`docs/openapi.yaml`），但服务端不做校验。

### P2 —— 打磨

1. 无 i18n（回复模板与护栏短语是中文硬编码）。
2. `PluginManager.run_hooks` 吞异常只记在 `ctx.store`，未进标准日志。
3. `knowledge_base` 的 `_save()`（全量重写）只用于压缩，无自动压缩策略。
4. 无插件依赖声明（如 `web_gateway` 最好声明"建议与 `sessions` 同开"）。
5. `apps/` 下的参考应用未纳入包（`pip install` 后没有示例可跑）——已用 `pasm-framework serve` 补偿。

---

## 6. 明确"不该用 pasm-framework 做"的事

写清楚边界比堆功能更重要——避免以后走弯路：

| 需求 | 正确选择 |
| --- | --- |
| 渲染游戏画面 / 物理 / 帧同步 | Unity / Unreal / Godot（本框架只做 NPC 人格与记忆层） |
| 常规 CRUD、后台管理、ORM | Django / FastAPI / Spring Boot |
| 前端交互与状态管理 | Vue / React / Flutter / 小程序原生 |
| TLS 终止、连接池、CDN、WAF | Nginx / Caddy / 云负载均衡 |
| 大规模向量检索（千万级） | 专业向量库（Milvus / Qdrant / pgvector） |

---

## 7. 复检方法（可复现）

```bash
# 1) 框架自检（23 项）
PYTHONPATH=<pasm-skills> python -m pasm_framework selftest

# 2) 环境体检
python -m pasm_framework doctor

# 3) 场景预设解析
python -m pasm_framework config --preset api --env

# 4) 插件行为（护栏/检索/网关鉴权/限流/摄取）见 docs/tutorials/ 每篇末尾的"验证"小节
```

跨仓守门（本轮全绿）：

| 守门 | 结果 |
| --- | --- |
| `pasm_framework selftest` | 23 项全过 |
| `pasm_skills selftest` | 16 项全过 |
| `surface-guard` | 22 ok / 0 fail |
| `product-verifier` | 33 ok / 0 fail |

---

## 8. 下一步建议顺序

1. **P0-2 语义检索**（直接决定客服"答得上来"的比例，收益最大）
2. **P0-1 流式输出**（直接决定"感觉快不快"）
3. **P0-3 多租户隔离**（决定能不能做 SaaS）
4. P1 里挑：LLM 多模型回退、会话摘要、`/metrics`
5. 之后再启动 V2.0 引擎（`CognitiveAssembler.v2` + `PasmV2Backend`，唯一变动点已就位）
