"""warmth —— 回复温度 / 情感润色插件（零依赖，模板式）。

把 ``emotion_system`` 的情绪与 persona 的语气"渲染"进回复，
实现智能客服要的"有情感、有温度"。纯模板实现，不依赖 LLM，
因此即使离线 / 未开 llm_responder 也能生效。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext

# 负面情绪（mood<0）时的共情开场，按强度挑。
_EMPATHY_LOW = [
    "我理解这让你不太舒服，",
    "听起来你遇到了些困扰，别急，",
    "感受到你的焦急了，",
]
# 正面 / 中性时的温和开场。
_WARM_OPENERS = [
    "很高兴为你服务，",
    "好的，",
    "没问题，",
]
# 收尾柔和句（按 persona.tone 选）。
_CLOSERS = [
    "如果还有不清楚的地方，随时告诉我哦～",
    "希望这能帮到你，有任何问题我都在。",
    "还有什么我可以帮你的吗？",
]


class WarmthPlugin(BasePlugin):
    """情绪驱动的回复润色。"""

    name = "warmth"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._enabled = bool(self.config.get("enabled", True))
        self._max_len = int(self.config.get("max_len", 600))

    @staticmethod
    def _has_code_block(text: str) -> bool:
        return "```" in text or text.lstrip().startswith("<")

    def on_reply(self, ctx: PluginContext) -> None:
        if not self._enabled:
            return
        msg: Message = ctx.message
        reply = msg.reply
        if not reply or len(reply) > self._max_len:
            return
        # 结构化输出（代码 / HTML）不做润色，避免破坏格式。
        if self._has_code_block(reply):
            return
        mood = ctx.mood()
        opener = ""
        if mood < -0.15:
            opener = _EMPATHY_LOW[abs(hash(msg.text)) % len(_EMPATHY_LOW)]
        elif mood > 0.15:
            opener = _WARM_OPENERS[0]
        # 仅在回复较短、且未以标点/表情开头时加开场，避免过度堆叠。
        tail_punct = "，。！？、~～"
        if opener and (not reply) or (opener and reply[0] not in tail_punct):
            reply = opener + reply
        # 收尾：仅当原文没有明显问句结尾时补一句柔和收尾。
        if not reply.rstrip().endswith(("？", "?", "吗", "呢")):
            reply = reply.rstrip() + _CLOSERS[abs(hash(reply)) % len(_CLOSERS)]
        msg.reply = reply
