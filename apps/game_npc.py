"""游戏 NPC 示例 —— 有性格、有情绪、有记忆、会被玩家反馈塑形。

这是 pasm-framework 与"普通规则 NPC"最不一样的地方：
NPC 的**行为偏好会被长期交互改变**，而不只是按固定剧本走。

跑起来::

    python -m apps.game_npc

演示脚本：先买酒（升温）→ 闲聊（检索记忆）→ 挑衅（降温）→ 再买酒（观察差异）。
注意最后两轮回复的温度变化 —— 那就是情绪在起作用。
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from pasm_framework import SimpleApplication, capability, load

PERSONA: Dict[str, Any] = {
    "name": "老橡",
    "role": "酒馆老板",
    "tone": "粗嗓门但热心",
    "temper": 0.7,      # 脾气（越高越易怒）
    "energy": 0.4,
    "play": 0.6,
}


class Innkeeper(SimpleApplication):
    """酒馆老板。"""

    DEFAULT_UNKNOWN = "（老橡擦了擦杯子）……这个我还真不知道。"

    #: 判定"心情好"的阈值。注意情绪变化幅度与档位有关：
    #: 纯内置档每次约 ±0.1×valence，装了引擎情绪模块时幅度由引擎决定。
    HAPPY = 0.15
    ANGRY = -0.15

    @capability(keywords=("买", "酒", "来一", "打二两"), description="买酒")
    def buy(self, text: str) -> str:
        self.observe(title="玩家买酒", brief=text, tags=["交易", "酒"], salience=3)
        self.feel("玩家买酒", 1.0)              # 事件 + 情绪强度 [-1, 1]
        if self.mood > self.HAPPY:
            return "给你满上！今天算你便宜点。"
        return "给你满上。"

    @capability(keywords=("聊", "说说", "故事", "听说"), description="闲聊")
    def chat_about(self, text: str) -> str:
        # 优先用"有来源的设定资料"（lore / 知识库），而不是把玩家自己说过的话
        # 当成见闻回过去 —— 后者会答成"我记得：你真是个厉害的酒馆老板"。
        hits = self.recall(text, k=5)
        lore = [h for h in hits if h.get("source")]
        if lore:
            return "这个啊……我记得：%s" % lore[0].get("brief", "")
        if self.mood < self.ANGRY:
            return "……我现在没心情说这些。"
        return "唉，最近不太平，没什么好说的。"

    @capability(keywords=("打", "揍", "滚", "闭嘴"), description="敌对行为")
    def hostile(self, text: str) -> str:
        self.feel("玩家挑衅", -1.0)
        self.feedback("scold", action="hostile")   # 让"敌对"被长期记进行为偏好
        self.observe(title="玩家挑衅", brief=text, tags=["敌意"], salience=4)
        if self.mood < self.ANGRY:
            return "……你再这样我就叫卫兵了。"
        return "别闹。"

    @capability(keywords=("夸", "谢谢", "干得好", "厉害"), description="正反馈")
    def praise(self, text: str) -> str:
        self.feel("被夸奖", 1.0)
        self.feedback("praise", action="buy")      # 夸奖会塑造出更热情的行为偏好
        return "（咧嘴笑了）嘿，你这人挺会说话。"


def build(persist_dir: str, *, kb_dir: str | None = None) -> Innkeeper:
    """构造 NPC。

    ``persist_dir`` 决定存档位置：同一目录 + 同一 ``agent_id`` =
    同一个"它"（情绪、记忆、行为偏好都会延续）。由调用方显式给出 ——
    演示脚本用临时目录，避免在仓库里留下 ``npc_save/``。
    你自己的游戏里换成 ``./saves/<player_id>`` 之类的固定路径即可。
    """
    # game_npc 预设：离线优先（不接 LLM）、情绪润色开、会话历史短
    overrides: Dict[str, Any] = {}
    if kb_dir is not None:
        overrides["knowledge_base"] = {"enabled": True, "config": {"kb_dir": kb_dir}}
    cfg = load(preset_name="game_npc", **overrides)
    return Innkeeper("innkeeper-01", PERSONA, persist_dir=persist_dir,
                     backend_config=cfg)


def main(argv: List[str] | None = None) -> int:
    import tempfile

    argv = list(sys.argv[1:] if argv is None else argv)
    tmp = tempfile.mkdtemp(prefix="pasm-npc-")
    npc = build(persist_dir=tmp + "/save", kb_dir=tmp + "/kb")

    # 先让 NPC 记住镇上的事，便于演示"闲聊时检索记忆"
    npc.teach([
        {"title": "镇上的事", "content": "北边磨坊上个月着过火，现在还没修好。",
         "source": "lore", "tags": ["磨坊", "火灾", "镇上"]},
        {"title": "卫兵队长", "content": "卫兵队长叫卡尔，欠我三壶酒钱。",
         "source": "lore", "tags": ["卫兵", "卡尔"]},
    ])

    script = [
        ("玩家", "打二两酒"),
        ("玩家", "说说镇上的事"),
        ("玩家", "揍你一顿"),
        ("玩家", "打二两酒"),
        ("玩家", "你真是个厉害的酒馆老板"),
        ("玩家", "打二两酒"),
    ]
    for who, line in script:
        reply = npc.ask(line, session_id="player-1")
        print("%s：%s" % (who, line))
        print("%s：%s" % (PERSONA["name"], reply))
        print("        （情绪 %.2f）" % npc.mood)
        print("-" * 56)

    print("说明：挑衅后情绪转负 → 再买酒时不再给优惠；")
    print("      夸奖后情绪回升 → 又变热情。这就是「被玩家反馈塑形」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
