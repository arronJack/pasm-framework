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
| `BaseApplication` | 通用 AI 应用底座（建在 `BaseAgent` 上） |
| `BaseSkill` / `SkillManifest` | 技能包代码化底座 |

`CognitiveBackend` 协议的**单一真相源仍在基座** `pasm_skills.sdk.backend`，本包只做重导出。

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

Hook 链：`on_init → on_message_in → on_retrieve → on_reply → on_learn → on_shutdown`。
**不启用任何插件时，`handle` 行为与 v0.1.0 完全一致**（能力路由 → 回落 chat）。

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

### 写自己的插件（可发布到 PyPI 被自动发现）

```python
from pasm_framework import BasePlugin, PluginContext

class MyPlugin(BasePlugin):
    name, version = "my_plugin", "0.1.0"
    def on_reply(self, ctx: PluginContext) -> None:
        if not ctx.message.reply:
            ctx.message.reply = "来自我的插件"

my_plugin = MyPlugin
```
在 `pyproject.toml` 声明 entry-point，框架启动时自动发现：
```toml
[project.entry-points."pasm_framework.plugins"]
my_plugin = "my_pkg.my_module:MyPlugin"
```

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

## 快速自检

```bash
python -m pasm_framework selftest
python -m pasm_framework version
```

## 最小示例

```python
from pasm_framework import BaseApplication, Capability, CapabilityDiscovery

class MyApp(BaseApplication):
    def action_pool(self):
        return ["a1", "a2"]
    def _render_reply(self, text, facts, mood):
        return "reply:%s" % text

app = MyApp(agent_id="demo", persona={"name": "demo"}, persist_dir="/tmp/demo")
print(app.handle("你好"))          # → "reply:你好"（回落 chat）
```

## 许可证

MIT —— 与 `pasm-skills` / `pasm-agents` 一致。
