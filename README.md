# pasm-framework

PASM 应用开发框架 —— 产品智能体 / 应用与认知引擎之间的**防腐层（Anti-Corruption Layer）**。
本包于 **v0.1.0** 从基座 [`pasm-skills`](https://gitee.com/arronzheng/pasm-skills) 的
`pasm_skills.framework` 子包独立成仓。

> 注意：本包是「**应用开发**框架」（给产品智能体 / 应用用）；
> `pasm-skills` 里还有一个同名概念「验证器框架」`pasm_skills.agent`（给自检 / 守护智能体用），
> 两者职责不同，请勿混淆。

## 它解决什么问题

PASM V1 → V2 升级时，**不重写 4 个产品智能体 + 3 个技能**。手段是建立一组**稳定表面**，
让应用只依赖表面、不依赖引擎内部；引擎大改时只动"唯一变动点"。

## 导出的稳定表面

| 表面 | 作用 |
| --- | --- |
| `CognitiveAssembler` / `CognitiveService` | 引擎 ↔ 应用装配（**V1↔V2 唯一变动点**） |
| `DomainAdapter` | 领域知识 / 规则注入契约 |
| `CapabilityDiscovery` / `Capability` | 能力声明与统一发现 |
| `BaseApplication` | 通用 AI 应用底座（建在 `BaseAgent` 上）；`handle()` / **`stream()`** / **`ingest()`** |
| `SimpleApplication` / `@capability` | 3 行起步的极简应用写法（v0.2.1） |
| `BaseSkill` / `SkillManifest` | 技能包代码化底座 |

`CognitiveBackend` 协议的**单一真相源仍在基座** `pasm_skills.sdk.backend`，本包只做重导出。

## 流式与工具调用（v0.3.0 新增）

**真流式（SSE）** —— `stream()` 与 `handle()` **共用同一条管线**，不会行为漂移：

```python
for ev in app.stream("怎么退货？", session_id="u1"):
    if ev["type"] == "delta":      # 增量片段，可直接追加显示
        print(ev["text"], end="", flush=True)
    elif ev["type"] == "replace":  # 护栏/润色改写过 → 整条替换
        print("\n[已修正]", ev["text"])
```

网关侧对应 `POST /api/chat/stream`（`text/event-stream`，零依赖）；
客户端有 `PasmClient.chat_stream()`（Python）与 `chatStream()`（Node）。

> **护栏不会被流式绕过**：流式是在*生成中*外推的，而护栏在*生成后*才跑。
> 若收尾改写了内容（例如脱敏），框架补发 `replace` 事件让客户端纠正 ——
> 所以"唯一出口"承诺对 `handle` 和 `stream` 同时成立。

**多轮工具调用** —— 应用的 `Capability` 自动暴露为 OpenAI 兼容 `tools`：

```python
app = BaseApplication(..., backend_config={
    "llm_responder": {"enabled": True, "config": {
        "provider": "deepseek", "api_key": "...",
        "tools": True,           # 把能力交给模型调用（默认开）
        "max_tool_rounds": 3,    # 工具环上限
    }}})
```

模型说"要调 `cap_1`" → 框架真的执行该能力 → 结果回填 `role=tool` → 再请求。
中文能力名会转成合法 tool 名（`cap_1`…），原名保留在 `description` 里。
上游对 `tools` / `stream` 返回 400 时**自动降级**为纯对话重试，不会挂。

## 插件库（v0.2.0 新增，即插即用）

框架自带 **7 个通用插件**，全部零强制外部依赖，**可在后端开关**（"用户选择是否使用"）：
通过 `BaseApplication(..., backend_config={...})` 控制启用与配置。

| 插件 | 作用 | 默认 |
| --- | --- | --- |
| `knowledge_base` | 站点数据 → 资料库，自学 / 记忆 / 成长（客服核心） | ✅ 开 |
| `sessions` | 会话 / 租户隔离，记住每个客户上下文 | ✅ 开 |
| `warmth` | 情绪驱动回复润色，做到"有温度" | ✅ 开 |
| `safety` | prompt 注入拦截 + PII 脱敏 | ✅ 开 |
| `observability` | 指标 + 健康（`/healthz`） | ✅ 开 |
| `llm_responder` | 可选 LLM 接入（OpenAI 兼容 / DeepSeek / Ollama） | ⬜ 关 |
| `web_gateway` | 零依赖 HTTP 网关（iframe / REST 外部链接） | ⬜ 关 |

Hook 链：`on_init → on_message_in → on_retrieve → on_reply → on_reply_final → on_learn → on_shutdown`。
**不启用任何插件时，`handle` 行为与 v0.1.0 完全一致**（能力路由 → 回落 chat）。

`on_reply_final` 是**唯一出口**：能力结果 / LLM 回复 / 模板兜底 / 被拦截，四条路径
出站前都经过它恰好一次 —— 护栏因此不可能被某条路径绕过。

### 用插件开关"定制应用"

```python
from pasm_framework import BaseApplication

class MyAgent(BaseApplication):
    def action_pool(self): return ["reply"]
    def _render_reply(self, text, facts, mood): return "答：%s" % text

agent = MyAgent(
    "demo", {"name": "小智"},
    backend_config={
        "knowledge_base": {"enabled": True, "config": {"kb_dir": "./kb"}},
        "llm_responder":  {"enabled": True, "config": {
            "provider": "deepseek", "api_key": "sk-...", "model": "deepseek-chat"}},
        "web_gateway":    {"enabled": True, "config": {"port": 8080}},
    },
)
agent.handle("你好", session_id="u1")     # 走插件链
agent.serve(port=8080)                    # 站点 <iframe src="http://host:8080/">
agent.close()                             # 跑 on_shutdown，停网关
```

### 写自己的插件

```python
from pasm_framework import BasePlugin, PluginContext

class SlaPlugin(BasePlugin):
    name, version = "sla", "0.1.0"
    def on_reply_final(self, ctx: PluginContext) -> None:
        # 收尾阶段：对已经定稿的回复做后处理
        if ctx.message.reply:
            ctx.message.reply += "\n（本次回复已记录）"
```

**注册方式一（推荐）：配置里内联，不用发包**

```python
app = MyApp("demo", {"name": "小智"}, backend_config={
    "sla": {"enabled": True, "class": SlaPlugin},
})
```

**注册方式二：发布成可发现包**，安装即被自动发现

```toml
[project.entry-points."pasm_framework.plugins"]
sla = "my_pkg.my_module:SlaPlugin"
```

⚠️ 插件名**拼错不会静默通过**：`app.plugins.unknown()`、`app.app_summary()["plugin_config_unknown"]`
以及 `pasm-framework doctor` 都会报告。

## 参考实现：站点智能客服

`apps/customer_service.py` 用插件组合出一个可上线的客服 Agent（零 LLM 也能回答）。
`docs/customer-service-plugin.md` 是可行性与部署形态研究（iframe / REST / WebSocket）。

```bash
python -m apps.customer_service           # 演示问答 + 自学习统计
python -m apps.customer_service --serve   # 起 HTTP 网关：http://0.0.0.0:8080/
```

## 依赖方向（单一、无环）

```
pasm-agents (产品)  →  pasm-framework  →  pasm_skills.sdk  →  引擎(pasm.*)
```

- 动：`CognitiveAssembler.v2`（V2.0 落地时新增）+ `PasmV2Backend`
- 不动：`BaseApplication`、4 智能体、3 技能、`DomainAdapter`、`CapabilityDiscovery`、`BaseSkill`

## 安装

```bash
pip install pasm-framework
# 基座会被自动作为依赖装上：pasm-skills>=0.5.1
```

## 配置系统（v0.2.1 新增）

开关表可以来自**预设 / 文件 / 环境变量 / 代码**，优先级由低到高：

```python
from pasm_framework import load

cfg = load("server.json",                  # 文件（.json / .yaml）
           preset_name="chatbot",          # 场景预设打底
           env=True,                       # 叠加 PASM_* 环境变量
           web_gateway={"config": {"port": 9000}})   # 代码覆盖一切

app = MyApp("demo", {"name": "小智"}, backend_config=cfg)
```

6 套场景预设：`minimal`（全关，退回 0.1.0 行为）· `default` ·
`chatbot`（护栏 block + 开网关）· `game_npc`（离线优先）·
`api`（回复不润色）· `desktop`（只监听本机）。

环境变量：`PASM_PLUGINS` / `PASM_KB_DIR` / `PASM_SAFETY_MODE` /
`PASM_LLM_PROVIDER` `PASM_LLM_MODEL` `PASM_LLM_API_KEY` /
`PASM_HTTP_HOST` `PASM_HTTP_PORT` `PASM_HTTP_TOKEN`。

## CLI

```bash
pasm-framework                    # 自检 + 用法
pasm-framework doctor             # 环境体检（出问题先跑这个）
pasm-framework new myapp --kind chatbot     # 生成可跑的项目
pasm-framework serve --port 8080            # 起一个演示客服
pasm-framework plugins                      # 看内置插件与默认开关
pasm-framework config --preset api --env    # 看最终解析出的配置
```

## 最小示例

最省事（v0.2.1 起，3 行起步）：

```python
from pasm_framework import SimpleApplication, capability, load

class MyApp(SimpleApplication):
    @capability(keywords=("帮助", "help"))
    def help(self, text):
        return "我能回答资料库里的问题。"

app = MyApp("demo", {"name": "小智"},
            backend_config=load(preset_name="chatbot"))
print(app.ask("帮助"))
```

需要完全控制时，继承 `BaseApplication`：

```python
from pasm_framework import BaseApplication, Capability

class MyApp(BaseApplication):
    def action_pool(self):
        return ["a1", "a2"]
    def _render_reply(self, text, facts, mood):
        return "reply:%s" % text

app = MyApp(agent_id="demo", persona={"name": "demo"}, persist_dir="/tmp/demo")
print(app.handle("你好"))          # → "reply:你好"（回落 chat）
```

## 快速自检

```bash
python -m pasm_framework selftest      # 44 项
python -m pasm_framework doctor        # 真装配一遍插件并报拼错的名字
python -m pasm_framework version
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/tutorials/`](docs/tutorials/README.md) | **开发教程**：快速上手 → 能力/插件 → 客服/LLM/部署 → 游戏 NPC → 多语言 |
| [`docs/capability-matrix-2026-09-20.md`](docs/capability-matrix-2026-09-20.md) | 能力就绪度复检：能做/不能做、剩余问题、性能实测 |
| [`docs/polyglot-strategy.md`](docs/polyglot-strategy.md) | C#/Java/PHP 怎么接入（协议优先，不移植引擎） |
| [`docs/cross-platform-strategy.md`](docs/cross-platform-strategy.md) | 桌面端跨 Linux/macOS、手机端换架构方案 |
| [`docs/customer-service-plugin.md`](docs/customer-service-plugin.md) | 智能客服可行性与部署形态研究 |
| [`docs/audit-2026-09-20.md`](docs/audit-2026-09-20.md) | v0.2.0 体检报告 |
| [`docs/openapi.yaml`](docs/openapi.yaml) | HTTP 契约（单一真相源） |
| [`sdks/`](sdks/README.md) | C# / Java / PHP / Node / Go / Python 客户端 |

## 许可证

MIT —— 与 `pasm-skills` / `pasm-agents` 一致。
