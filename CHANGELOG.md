# 变更日志

本文件记录 pasm-framework 的重要变更。

## [0.3.0] — 2026-09-20

补齐能力矩阵复检中列出的两个 **P0 缺口**：流式输出、多轮工具调用。

### 新增：真流式输出（SSE）

- `Message.stream_sink`：生成类插件可把逐块结果实时外推。
- `BaseApplication.stream(text, …)`：产出事件字典
  （`delta` / `replace` / `done` / `error`），供 SSE / WebSocket 下发。
- `POST /api/chat/stream`：`text/event-stream`，零依赖
  （`Connection: close` + EOF 结束流，不依赖 chunked）。
- 内置 Widget 改用流式；Python / Node 客户端新增 `chat_stream` / `chatStream`。
- **护栏不会被流式绕过**：流式是在*生成中*外推的，而 `on_reply_final` 在*生成后*才跑。
  若收尾改写了内容（如脱敏），框架补发 **`replace` 事件**让客户端整条替换 ——
  「唯一出口」承诺因此对两条入口（`handle` / `stream`）同时成立。
- `handle()` 与 `stream()` 共用**同一个 `_run()`**，杜绝两条管线行为漂移。

### 新增：多轮工具调用（Function Calling）

- 应用的 `Capability` 自动暴露为 OpenAI 兼容 `tools`；
  中文能力名会转成合法 tool 名（`cap_1`…），原名保留在 `description` 里。
- 完整环：`tool_calls → 本地执行能力 → 回填 role=tool → 再请求`，
  轮数由 `max_tool_rounds` 控制（默认 3）。
- 流式下按 `index` 拼装 `delta.tool_calls` 增量。
- **自动降级**：上游对 `tools` / `stream` 返回 400 时，改纯对话重试一次，不会挂。

### 修复

- **`_render_reply` 参数名陷阱**：基座 sdk 用关键字传参，子类必须把参数名
  一字不差写成 `text/facts/mood`，否则运行时才炸 `TypeError`。
  `BaseApplication.chat` 改为**按位置传参**，任意参数名都能工作。
- **知识摄取入口三套名字、且失败静默**：`SimpleApplication.teach` /
  `CustomerServiceAgent.ingest_faq` / 插件 `ingest` 各叫各的，且未启用知识库时
  **静默返回 0**（"我喂了资料为什么答不上来"最难查）。
  现统一为 `BaseApplication.ingest()`，另两个名字降级为别名；
  未启用 `knowledge_base` 时**显式抛 `FrameworkError`** 并给出开启方法。

### 全量代码检测（静态分析）

- `pyflakes` 全仓扫描并清理：移除 4 处未用导入（`dataclasses.field` /
  `typing.Any` / `typing.List` / `BackendConfig`）、1 处死代码
  （`CapabilityDiscovery.match` 里算了却没用到的 `head`）、1 处未用导入
  （`web_gateway` 的 `Message`）。仅保留 2 处**刻意的**可选依赖探测导入
  （`pasm_skills` / `pyyaml`，均带 `noqa`）。
- 文档内链 44 处全部可解析；依赖方向核查无反向依赖（不依赖 `pasm_agents`）、
  无 `pasm.cognitive` 越层引用；敏感信息扫描无硬编码凭据。

### 文档

- `docs/openapi.yaml` 增补 `/api/chat/stream`（含事件流 schema）。
- 教程 05 / 06 补流式与工具调用；教程 04 补"摄取入口统一"说明；
  能力矩阵文档更新 P0 状态。

### 工程

- selftest 36 项 → **47 项**（流式事件序列、tool 名转换、SSE 帧解析、
  Widget 流式、统一摄取入口与显式失败）。
- 四套守门全绿；`CognitiveBackend` 协议与 `CognitiveAssembler` 唯一变动点零改动。

## [0.2.1] — 2026-09-20

### 修复：真实缺陷（均已配可证伪的反例测试）

- **护栏绕过（安全）**：`on_reply` 阶段模板兜底回复尚未生成，而 `safety` 的脱敏挂在
  `on_reply` 上 → **不接 LLM 的离线路径回复完全不脱敏**。
  新增**收尾阶段** `on_reply_final`（Hook 链变为
  `on_init → on_message_in → on_retrieve → on_reply → on_reply_final → on_learn → on_shutdown`），
  由 `handle()` 在唯一出口调用。
  **「唯一出口」的确切含义**：能力命中 / LLM 生成 / 模板兜底 / 被拦截，四条路径
  出站前都必然经过该阶段 —— 护栏因此不可能被某条路径绕过。
  `safety` / `warmth` 迁入该阶段。
  ⚠️ **行为变更（重要）**：能力（`Capability`）的返回值语义是"确定性结果"，
  故**护栏仍然生效、风格润色默认跳过**。`warmth` 新增配置
  `polish_capabilities`（默认 `False`）—— 打开后连能力输出一起润色。
- **拦截路径绕过收尾钩子（安全）**：`handle()` 在 `on_message_in` 判定 `stop` 后
  **直接 `return msg.reply`**，跳过收尾阶段 → 任何插件塞进该回复的文本（含 PII）
  完全不脱敏。现在拦截路径同样走 `on_reply_final`。
- **自定义插件无法通过配置注册（能力缺失）**：`backend_config` 只能开关内置插件，
  用户自己的插件只能靠发布 entry-point 包才能接入 —— 对"通用底层框架"是硬伤。
  现支持在配置项里内联 `class`（类）或 `instance`（实例），并可 `as` 起别名做多实例。
- **拼错的插件名被静默忽略（可观测性）**：`{"knowlege_base": {...}}` 这类拼写错误
  原先毫无提示，用户会以为插件已生效。新增 `PluginManager.unknown()`，
  经 `app_summary()["plugin_config_unknown"]` 与 `pasm-framework doctor` 暴露。
- **知识库读路径全量落盘（性能）**：`recall()` 命中后 `_save()` 重写整个 `kb.jsonl`
  → 每次问答 O(全库) 磁盘写。改为读路径不落盘、写入用 `_append_new()` 只追加新条目。
- **检索线性扫描 + 每次重新分词（性能）**：新增**倒排索引** + **分字段分词缓存**。
  实测（2 万条）：区分性查询 240 ms → **3.2 ms（约 76×）**；退化查询 250 ms → 30 ms。
- **相关性：标题命中与正文同权 → 答非所问**：问"怎么退货"时「运费说明」
  （正文含"退货运费由我方承担"）得分反超「退货政策」。
  改为**分字段加权**（标题 ×3 > 标签 ×2 > 正文 ×1）。
- **`serve()` 忽略配置端口**：配置写 `port=9000`，`serve()` 却起在 8080。
  签名改为 `serve(host=None, port=None)`：不传即用配置值。
- **`warmth` 选句不可复现**：用内置 `hash()`（带每进程随机盐）选句 → 改用 `zlib.crc32`。

### 新增：开发效率

- `pasm_framework/simple.py`：`SimpleApplication`（**3 行起步**）+ `@capability` 装饰器，
  一个方法即一个能力，自动注册。
- `pasm_framework/config.py`：配置系统。`load(preset_name=..., env=True, **overrides)`，
  优先级 `preset < 文件 < 环境变量 < 代码`；6 套场景预设
  （`minimal`/`default`/`chatbot`/`game_npc`/`api`/`desktop`）；
  `preset`/`save`/`to_dict`/`describe`。
- `pasm_framework/scaffold.py`：项目脚手架，3 种模板（`app`/`chatbot`/`game_npc`）。
- `pasm_framework/demo.py`：开箱即用演示客服（`pasm-framework serve` 用）。
- CLI 扩展为 `selftest` / `version` / `plugins` / `config` / `doctor` / `new` / `serve`。

### 新增：网关生产化（`web_gateway` 0.2.0）

- **鉴权**：`token` 配置后要求 `Authorization: Bearer` 或 `X-Pasm-Token`
  （`/healthz` 免鉴权，供探针）；Widget 页面自动注入令牌。
- **限流**：`rate_limit`（每 IP 每分钟），超出返回 429。
- **体积保护**：`max_body`，超出返回 413。
- 新增 `POST /api/ingest`（站点数据推进资料库）、`GET /api/plugins`、
  `GET /api/summary`、`GET /api/kb/stats`、`POST /api/sessions/reset`。

### 变更：`recall()` 现在也合并知识库插件

能力/领域代码里写 `self.recall(query)` 原本**看不到知识库**（插件检索只在 `handle`
的 `on_retrieve` 阶段发生）。现在三者（引擎记忆 + 领域 + 知识库）统一合并、按 `title` 去重。

### 新增：文档与多语言

- `docs/tutorials/`：**9 篇开发教程** + 学习路径索引。
- `docs/capability-matrix-2026-09-20.md`：能力就绪度复检（场景矩阵 / 剩余问题 / 性能实测）。
- `docs/polyglot-strategy.md` + `docs/openapi.yaml` + `sdks/`
  （C# / Java / PHP / Node / Go / Python 参考客户端）。
- `docs/cross-platform-strategy.md`：桌面端跨 Linux/macOS、手机端换架构方案。
- `apps/minimal.py`、`apps/game_npc.py`：新增示例。

### 其它

- selftest 21 项 → **36 项**（新增收尾阶段不变式、护栏覆盖三条路径、自定义插件注册、
  配置系统与脚手架落盘测试）。
- `pasm_framework/py.typed` 保持；版本 0.2.0 → 0.2.1。
- 不改 `CognitiveBackend` 协议与 `CognitiveAssembler` 唯一变动点（防腐层承诺不变）。

## [0.2.0] — 2026-09-20

### 新增：插件子系统（即插即用）

- `pasm_framework/plugins/`：插件契约 + Hook 链 + 注册表 + entry-point 发现 + 后端开关。
  - `Message` / `PluginContext` / `BasePlugin` / `Plugin` / `PluginManager`。
  - `BackendConfig` / `build_manager` / `default_config`：**在后端选择是否使用**某插件。
  - Hook 链：`on_init → on_message_in → on_retrieve → on_reply → on_learn → on_shutdown`。
  - 第三方插件经 `pasm_framework.plugins` entry-point 自动发现。
- **7 个内置插件**（全部零强制外部依赖）：
  - `knowledge_base` 站点数据自学资料库（摄取 / 检索 / 沉淀 QA）
  - `sessions` 会话 / 租户隔离
  - `llm_responder` 可选 LLM（OpenAI 兼容 / DeepSeek / Ollama，标准库 urllib，失败静默回落）
  - `warmth` 情绪驱动回复润色
  - `safety` prompt 注入拦截 + PII 脱敏
  - `observability` 指标 + 健康
  - `web_gateway` 零依赖 HTTP 网关（`/api/chat` / `/healthz` / 可嵌入 Widget）

### 变更：`BaseApplication`

- 新增 `plugins` / `backend_config` 参数（后端开关表）。
- `handle(text, *, session_id, user_id, meta)`：接入插件 Hook 链；**不启用插件时行为与 0.1.0 一致**。
- 新增 `chat(text, facts=...)`：允许注入已合并的检索事实（知识库资料可直达模板回复）。
- 新增 `serve(host, port)` / `close()` / `plugin_metrics()`；`app_summary()` 增加插件与指标。
- `recall()`：领域/知识库事实统一带 `source` 标记，便于区分"资料"与"闲聊记忆"。

### 新增：参考实现与文档

- `apps/customer_service.py`：站点智能客服参考实现（零 LLM 可答，可选接 LLM）。
- `docs/customer-service-plugin.md`：智能客服可行性与部署形态研究（iframe / REST / WebSocket）。
- `docs/audit-2026-09-20.md`：框架全面体检报告与优先级矩阵。

### 工程

- `pyproject.toml`：版本 0.2.0；`packages` 收录 `plugins` 与 `plugins.builtins`；
  新增 `pasm_framework.plugins` entry-point 组。
- `selftest()` 从 8 项扩展到 21 项，覆盖插件装配 / 知识库 / 安全 / 会话 / 端到端 handle。

### 未改动（履行"防腐层"承诺）

- `CognitiveBackend` 协议、`CognitiveAssembler` 的 V1↔V2 唯一变动点、4 智能体 / 3 技能的迁移路径均**零改动**。

## [0.1.0] — 2026-09-20

- 从基座 `pasm-skills` 的 `pasm_skills.framework` 子包独立成仓。
- 导出稳定表面：`CognitiveAssembler` / `CognitiveService` / `DomainAdapter` /
  `CapabilityDiscovery` / `BaseApplication` / `BaseSkill`。
