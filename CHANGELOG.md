# 变更日志

本文件记录 pasm-framework 的重要变更。

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
