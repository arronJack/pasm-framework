# 07 · 游戏 NPC

PASM 的差异点在**人格**：NPC 有性格、有情绪、有记忆、会被玩家反馈塑形。
这一篇做一个"记得住熟客、被夸更热情、被欺负会冷淡"的酒馆老板。

## 1. 完整实现

```python
from pasm_framework import SimpleApplication, capability, load


class Innkeeper(SimpleApplication):
    """酒馆老板：粗嗓门但热心；会记人、会生气、会变熟。"""

    HAPPY, ANGRY = 0.15, -0.15      # 情绪判定阈值

    @capability(keywords=("买", "酒", "来一"), description="买酒")
    def buy(self, text):
        self.observe(title="玩家买酒", brief=text, tags=["交易"], salience=3)
        self.feel("玩家买酒", 1.0)        # feel(事件, 情绪强度∈[-1,1])
        return "给你满上！" + ("今天算你便宜点。" if self.mood > self.HAPPY else "")

    @capability(keywords=("聊", "说说", "故事"), description="闲聊")
    def chat_about(self, text):
        hits = self.recall(text, k=5)    # 含记忆 + 领域 + 知识库
        lore = [h for h in hits if h.get("source")]     # 只取"设定资料"
        if lore:
            return "这个啊……我记得：%s" % lore[0].get("brief", "")
        return "唉，最近不太平，没什么好说的。"

    @capability(keywords=("打", "揍", "滚"), description="敌对行为")
    def hostile(self, text):
        self.feel("玩家挑衅", -1.0)
        self.feedback("scold", action="hostile")    # 反馈塑形（长期）
        self.observe(title="玩家挑衅", brief=text, tags=["敌意"], salience=4)
        if self.mood < self.ANGRY:
            return "……你再这样我就叫卫兵了。"
        return "别闹。"


def main():
    cfg = load(preset_name="game_npc")      # 离线优先：不接 LLM
    npc = Innkeeper("innkeeper-01", {
        "name": "老橡", "role": "酒馆老板",
        "tone": "粗嗓门但热心",
        "temper": 0.7, "energy": 0.4, "play": 0.6,
    }, backend_config=cfg)

    for line in ["打二两酒", "说说镇上的事", "揍你一顿", "打二两酒"]:
        reply = npc.ask(line, session_id="player-1")
        print("玩家：%s" % line)
        print("老橡：%s   （情绪 %.2f）" % (reply, npc.mood))
        print("-" * 50)


if __name__ == "__main__":
    main()
```

## 2. 为什么用 `game_npc` 预设

```python
load(preset_name="game_npc")
# → safety: warn    sessions: 12 条历史    knowledge_base: 开
# → warmth: 开      llm_responder: 关      observability: 关      web_gateway: 关
```

设计理由：

| 决定 | 为什么 |
| --- | --- |
| **不接 LLM** | 游戏要求低延迟、离线可用、成本可控。7B 本地模型在帧循环里不可接受 |
| `warmth` 开 | 情绪要能体现在措辞上（NPC 的"温度"就是这么来的） |
| `sessions` 历史短（12） | NPC 不需要记住 20 轮，但要记住**这个玩家** |
| `safety` warn（非 block） | 玩家说脏话是常态，不该被拦；只记录/脱敏 |
| 网关/可观测 关 | 单机游戏不需要 HTTP 服务与线上指标 |

## 3. 情绪与人格：`feel(event, valence)` / `mood` / persona

```python
npc.feel("玩家买酒", 1.0)   # 签名是 (事件名, 情绪强度)，不是只传强度
npc.mood                    # 当前情绪值，float
npc.persona                 # {"name": "老橡", "temper": 0.7, ...}
```

⚠️ **两个容易写错的签名**（我第一版就写错了，表现是"情绪永远不变"）：

| 想做的事 | ❌ 错的写法 | ✅ 对的写法 |
| --- | --- | --- |
| 改情绪 | `self.feel(0.2)` | `self.feel("事件名", 0.2)` |
| 给反馈 | `self.feedback(positive=True)` | `self.feedback("praise", action="buy")` |

`feedback` 的 `kind` 取值：`praise` / `scold` / `poke` / `hug` / `ignore`。
**强烈建议传 `action`** —— 不传时反馈会作用在"当前最偏好的动作"上，
长期会让行为分布极端化（这是引擎的长期验证智能体压出来的产品级要求）。

情绪变化幅度与档位有关：纯内置档每次约 `±0.1 × valence`；
装了引擎情绪模块时幅度由引擎决定。所以阈值别写太死，
上例用 `±0.15` 是两种档位下都能演示出差异的折中值。

`mood` 影响两件事：

1. **`warmth` 插件的措辞** —— `mood < -0.15` 时用共情开场、`> 0.15` 时用温和开场；
2. **你自己的分支** —— 如上面 `buy()` 里 `self.mood > 0.3` 给折扣。

persona 里的 `temper` / `energy` / `play` 是性格维度，会在内部影响
动作选择权重（`_fallback_weights`），让不同 NPC 表现出不同偏好。

## 4. 记忆：`observe` 与 `recall`

```python
npc.observe(title="玩家买酒", brief="打二两酒", tags=["交易"], salience=3)
hits = npc.recall("酒", k=2)      # → [{"title":..., "brief":..., "salience":...}]
```

| 参数 | 含义 |
| --- | --- |
| `title` | 简短标题（检索时权重高） |
| `brief` | 细节 |
| `tags` | 标签，用于检索命中 |
| `salience` | 重要度（1–5），越高越不容易被遗忘 |
| `category` | 分类，如"对话"/"交易" |

NPC 的"记得熟客"就是靠这个：每次交互 `observe` 一条，下次 `recall` 说得出来。

## 5. 被玩家反馈塑形（"成长"）

```python
npc.feedback("praise", action="buy")    # 玩家夸奖 → 强化"买酒"这个动作
npc.feedback("scold",  action="hostile")  # 玩家不满 → 削弱"敌对"这个动作
```

反馈会影响**动作权重** —— 你夸它，相关行为就更容易再次出现；
你凶它，就收敛。这是 PASM 与"普通规则 NPC"的核心区别：
**行为偏好会被长期塑形**，而不是永远按固定剧本走。

一个完整例子：

```python
class Guard(SimpleApplication):
    """卫兵：初始冷淡；玩家礼貌交互多了会变友好。"""

    @capability(keywords=("你好", "问候", "敬礼"))
    def greet(self, text):
        self.feedback("praise", action="greet")
        self.feel("被礼貌对待", 1.0)
        return "……嗯。" if self.mood < 0.2 else "你好，公民。需要帮忙吗？"

    @capability(keywords=("滚", "别挡道"))
    def rude(self, text):
        self.feedback("scold", action="rude")
        self.feel("被辱骂", -1.0)
        return "注意你的言辞。"
```

## 6. 状态持久化

```python
npc = Innkeeper("innkeeper-01", persona, persist_dir="./npcs/innkeeper-01",
                backend_config=load(preset_name="game_npc"))
# ... 玩一局 ...
npc.close()          # 落盘（含情绪、记忆、动作权重）
```

下次用**同一个 `agent_id` 和 `persist_dir`** 构造，NPC 就"还是那个它"。

> `agent_id` 是身份，`persist_dir` 是存档位置。想做"多存档"，给不同
> `persist_dir` 即可。

## 7. 和游戏引擎怎么接

pasm-framework **不做渲染、物理、帧循环** —— 那是 Unity/Unreal/Godot 的事。
推荐两种接法：

| 接法 | 做法 | 适用 |
| --- | --- | --- |
| **进程内**（推荐） | 引擎里嵌 Python 解释器（Unity 用 Python.NET / Godot 用 GDExtension），直接调 `npc.ask()` | 单机、延迟敏感 |
| **本机 HTTP** | NPC 服务跑 `127.0.0.1:8765`（`preset="desktop"`），引擎用 HTTP 调 | 引擎不便嵌 Python、或 NPC 要独立升级 |

延迟预期：不接 LLM 时，`ask()` 是纯本地计算 + 文件 IO，
**没有网络与模型推理开销** —— 这是离线优先设计的直接收益。

## 验证

```python
npc = Innkeeper("verify-npc", {"name": "老橡", "temper": 0.7},
                persist_dir="./tmp_npc", backend_config=load(preset_name="game_npc"))

# 1) 能力命中：买酒
assert "满上" in npc.ask("打二两酒", session_id="p1")

# 2) 情绪可被改变
m0 = npc.mood
npc.ask("揍你一顿", session_id="p1")
assert npc.mood < m0, "敌对交互应降低情绪"

# 3) 记忆可检索
assert any("酒" in (h.get("brief") or "") or "酒" in (h.get("title") or "")
           for h in npc.recall("酒", k=5)), "买酒事件应被记住"

# 4) 会话隔离：另一个玩家不会带上一个玩家的历史
npc.ask("打二两酒", session_id="p2")
assert npc.plugins.get("sessions").get_session("p1") is not None
assert npc.plugins.get("sessions").get_session("p2") is not None
```

## 下一步

- 上线运维 → [08 打包与运维](08-packaging-and-ops.md)
- 把 NPC 放到手机/多端 → 见 [`../cross-platform-strategy.md`](../cross-platform-strategy.md)
