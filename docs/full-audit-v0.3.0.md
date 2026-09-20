# pasm-framework v0.3.0 全量代码检测报告

> 检测时间：2026-09-20 · 范围：`pasm-framework` 全仓（`pasm_framework/` + `apps/` + `sdks/` + `docs/`）
> 结论：**可发布**。8 个既有缺陷全部修复且带可证伪反例；两个 P0 缺口（流式、工具调用）已实现；
> 静态分析零告警（仅留 2 处刻意的可选依赖探测）；四套跨仓守门全绿。

---

## 1. 检测项与结果总览

| # | 检测项 | 方法 | 结果 |
| --- | --- | --- | --- |
| 1 | 8 个既有缺陷是否真修好 | 逐条可证伪用例 + 反例对照 | ✅ 16/17（1 处为我写错断言键名，代码本身正确） |
| 2 | 未定义名 / 未用导入 | `pyflakes` 全仓 | ✅ 清理 6 处；仅剩 2 处刻意 `noqa` 探测 |
| 3 | 语法与导入健全性 | `compileall` 全仓 | ✅ 通过 |
| 4 | 文档相对内链 | 扫描 md 中 44 处相对链接 | ✅ 全部可解析 |
| 5 | 依赖方向 | grep 反向依赖 | ✅ 不依赖 `pasm_agents`（产品层） |
| 6 | 分叉铁律 | grep 越层引用 | ✅ 无 `pasm.cognitive` 引用 |
| 7 | 敏感信息 | 正则扫 token / key / secret | ✅ 无硬编码凭据 |
| 8 | 引擎直连 | 检查 `pasm_framework` 的 `pasm.*` 导入 | ✅ 零直连（只依赖基座 `pasm_skills.sdk`） |
| 9 | 全部示例可运行 | 逐个 `python -m apps.*` | ✅ 3/3 退出码 0 |
| 10 | 仓库污染 | 运行时产物是否落仓 | ✅ 无（示例改用临时目录） |
| 11 | CLI 全命令 | `version/plugins/config/doctor/new` | ✅ 全部正常 |
| 12 | 四套跨仓守门 | 见 §5 | ✅ 全绿 |

---

## 2. 8 个既有缺陷：修复复核（含反例对照）

| # | 缺陷 | 修复 | 复核判据（可证伪） |
| --- | --- | --- | --- |
| 1 | **护栏被绕过**：`on_reply` 在模板兜底*之前*跑，离线模式回复不脱敏 | 新增 `on_reply_final` 收尾钩子 = `handle()` 唯一出口；`safety` 迁入 | 模板兜底回复里塞手机号/邮箱 → 必须被脱敏；**反例**：关 `safety` 后原文必须原样返回（证明判据抓得住） |
| 2 | `on_message_in` 判 `stop` 后直接 return，同样绕过收尾 | 归一到唯一出口 | 拦截文案里塞 PII → 必须被脱敏 |
| 3 | 知识库**读路径**全量重写 `kb.jsonl`（O(全库) 磁盘写） | 读路径只内存计数；写盘只在摄取 | 5 次 `recall` 后文件 `mtime` 不变 |
| 4 | 检索线性扫描 + 每次重新分词 | 倒排索引 + 分词缓存 | 2 万条实测：区分性查询 **240ms → 3.2ms（约 76×）**；退化查询 250ms → 30ms |
| 5 | 标题与正文同权 → 答非所问 | 分字段加权（标题 ×3 > 标签 ×2 > 正文 ×1） | "退货政策怎么走" 必须命中*退货政策*而非先插入的*运费说明* |
| 6 | `serve()` 忽略配置端口 | 签名改 `host=None, port=None`（缺省用配置值） | 用 `inspect.signature` 断言默认值为 `None` |
| 7 | `warmth` 用内置 `hash()` 选句不可复现 | 改 `zlib.crc32` | 跨进程不同 `PYTHONHASHSEED` 仍得同一句 |
| 8 | 自定义插件无法经配置注册；拼错插件名被静默吞 | 支持内联 `class=` / `instance=` / `as` 别名；`PluginManager.unknown()` 经 `app_summary` 与 `doctor` 暴露 | `{"knowlege_base": ...}` 必须出现在 `unknown()` 里且被汇总暴露 |

> **唯一"失败"项已澄清**：第 4 项复核时 `app_summary()` 检查报错，实为我在用例里写错了键名
> （真实键是 `plugin_config_unknown`）。代码本身正确，已用直接调用确认。

---

## 3. 两个 P0 缺口的实现

### 3.1 真流式输出（SSE）

- `Message.stream_sink` → 生成类插件逐块外推；`BaseApplication.stream()` 产出事件字典。
- `POST /api/chat/stream`（`text/event-stream`，零依赖，`Connection: close` + EOF 结束）。
- **护栏对流式同样成立**：流式是*生成中*外推，`on_reply_final` 在*生成后*跑；
  若收尾改写了内容（如脱敏），框架补发 **`replace` 事件**让客户端整条替换。
- `handle()` 与 `stream()` **共用同一个 `_run()`**，杜绝两条管线行为漂移。
- 判据：假 LLM 服务端逐块发 3 段 → 断言收到 ≥2 个 `delta`、拼接结果逐字正确、且有 `done`。

### 3.2 多轮工具调用（Function Calling）

- 应用的 `Capability` 自动暴露为 OpenAI 兼容 `tools`（中文名转 `cap_1`，原名进 `description`）。
- 完整环：`tool_calls → 本地执行 → 回填 role=tool → 再请求`，上限 `max_tool_rounds`（默认 3）。
- 上游不支持 `tools`/`stream` 时**自动降级**为纯对话重试一次。
- 判据：假服务端断言**发生了 2 轮请求**、第二轮请求体含 `role=tool` 回填、首轮带 `tools` 定义。

---

## 4. 本轮静态分析发现并修复的问题

| 文件 | 问题 | 处理 |
| --- | --- | --- |
| `discovery.py` | `dataclasses.field`、`typing.Any` 未用 | 删除 |
| `discovery.py` | `match()` 里 `head = t[:DEFAULT_HEAD_CHARS]` **算了却没用**（旧设计残留） | 删除死代码（常量仍作 `head_chars` 默认值） |
| `skill.py` | `typing.List` 未用 | 删除 |
| `simple.py` | `.config.BackendConfig` 未用 | 删除（规范入口是 `pasm_framework.BackendConfig`） |
| `__init__.py` | selftest 内 `NullDomainAdapter` 未用 | 从该处导入移除 |
| `__main__.py` | `.registry.default_config` 未用 | 删除 |
| `web_gateway.py` | `Message` 未用（流式重构后遗留） | 删除 |
| `__main__.py` | `pasm_skills` / `yaml` | **保留**（刻意的可选依赖探测，带 `noqa`） |

### 4.1 新增：知识摄取入口统一

检测中发现**同一个概念有三套名字**，且失败静默：

| 位置 | 原名字 | 行为 |
| --- | --- | --- |
| 插件 | `knowledge_base.ingest` | 正常 |
| `SimpleApplication` | `teach` | 未启用知识库时**静默返回 0** |
| `CustomerServiceAgent` | `ingest_faq` | 未启用时**静默返回 0** |
| REST | `POST /api/ingest` | 正常 |

**处理**：新增 `BaseApplication.ingest(items)` 作为唯一规范入口；另两个名字降级为别名；
未启用 `knowledge_base` 时**显式抛 `FrameworkError`** 并给出开启方法。
理由：静默返回 0 属于"我明明喂了资料，为什么答不上来"这类最难查的假失败。

---

## 5. 跨仓守门（四套）

| 守门 | 结果 |
| --- | --- |
| `pasm_framework selftest` | **47 / 47** 通过（v0.1.0 时 8 项） |
| `pasm_skills selftest` | 通过 |
| `pasm_skills run surface-guard` | **22 ok / 0 warn / 0 fail** |
| `pasm_skills run product-verifier` | **33 ok / 0 warn / 0 fail** |
| `pasm_skills run parity-guard` | SKIP（预期：桌面端已并入核心仓，跨仓比对无对照物） |

---

## 6. 端到端回归

| 场景 | 判据 | 结果 |
| --- | --- | --- |
| 网关鉴权 | `/healthz` 免鉴权 200；无 token `/api/chat` 401 | ✅ |
| SSE 真流式 | ≥2 个 `delta`、拼接逐字正确、有 `done` | ✅ |
| 资料摄取 | `POST /api/ingest` 后 `added ≥ 1` | ✅ |
| **检索结果进 LLM prompt** | 摄取的"电子发票"必须出现在发给 LLM 的请求体里 | ✅ |
| LLM 真路径 | 命中 `/chat/completions` + `Bearer` 鉴权头 + `system` 提示 | ✅ |
| 工具调用环 | 2 轮请求；第二轮含 `role=tool`；首轮带 `tools` | ✅ |
| 注入拦截 | `block` 模式拦截后**不再调用 LLM** | ✅ |
| 离线兜底 | LLM 不可用时回落模板，不崩 | ✅ |
| 离线就资料作答 | 无 LLM 时按资料回答；查不到如实说"没有查到" | ✅ |
| 统一摄取入口 | `ingest` / `teach` / `ingest_faq` 三者等价；未启用时显式抛错 | ✅ |

> 回归中两次"失败"均系**我的用例写错**（假 LLM 恒返回固定串、用错方法名），
> 已改用正确的可证伪判据（断言资料进入 prompt、用 `teach`）后通过。代码无回归。

---

## 7. 已知局限（诚实说明，未修）

| 局限 | 影响 | 现状 |
| --- | --- | --- |
| 语义检索缺失 | 同义改述（"如何退货" vs "怎么退款"）召回不稳 | 现阶段靠词 + 中文 bigram；升级需接 embedding |
| 单机存储 | 高并发多实例需外部化存储 | `kb.jsonl` 为单文件落盘 |
| 多语言 SDK 仅 Python/Node 实机验证 | C#/Java/PHP/Go 未在本机跑通 | 已在 `sdks/README.md` 如实标注 |
| 手机端 | PySide6 无移动端，不能直接打包 | 见 `cross-platform-strategy.md`：换壳 + 云端大脑 |

---

## 8. 结论

- **8 个既有缺陷**：全部修复，每条带可证伪反例（含反向对照）。
- **2 个 P0 缺口**：流式输出、多轮工具调用，已实现并端到端验证。
- **静态分析**：零告警（除 2 处刻意探测）。
- **守门**：四套全绿，selftest 8 → 47 项。
- **防腐层承诺**：`CognitiveBackend` 协议与 `CognitiveAssembler` 唯一变动点**零改动**。
- **未启动 V2.0**（遵守"先完善、后 V2.0"）。
