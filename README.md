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
