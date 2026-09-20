"""warmth —— 回复温度 / 情感润色插件（零依赖，模板式）。

把 ``emotion_system`` 的情绪与 persona 的语气"渲染"进回复，
实现智能客服要的"有情感、有温度"。纯模板实现，不依赖 LLM，
因此即使离线 / 未开 llm_responder 也能生效。

挂在**收尾阶段** ``on_reply_final``（不是 ``on_reply``）：润色对象是
"已经定稿的回复"，无论它来自 LLM 还是模板兜底，都会且只会被润色一次。
"""
from __future__ import annotations

import zlib
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext


def _pick(seq: List[str], key: str) -> str:
    """确定性选句。

    不用内置 ``hash()``：CPython 对 str 的 hash 带每进程随机盐
    （PYTHONHASHSEED），同一句话在不同进程会选到不同措辞 —— 既让
    测试不可复现，也让线上表现随机。改用 ``zlib.crc32`` 取稳定值。
    """
    if not seq:
        return ""
    return seq[zlib.crc32(key.encode("utf-8")) % len(seq)]

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
        # 是否润色"能力产出的确定性文本"。默认 False —— 能力返回的可能是
        # 精确字符串 / 链接 / 结构化内容，加语气词会破坏其语义（也会让
        # 开发者的断言失效）。需要时显式打开。
        self._polish_caps = bool(self.config.get("polish_capabilities", False))

    @staticmethod
    def _has_code_block(text: str) -> bool:
        return "```" in text or text.lstrip().startswith("<")

    def on_reply_final(self, ctx: PluginContext) -> None:
        if not self._enabled:
            return
        msg: Message = ctx.message
        reply = msg.reply
        if not reply or len(reply) > self._max_len:
            return
        # 能力产出是"确定性结果"，风格润色默认不碰它。
        # 注意：护栏（safety）不走这个开关 —— 安全对所有路径生效。
        if not self._polish_caps and str(
            msg.meta.get("generated_by", "")
        ).startswith("capability:"):
            return
        # 结构化输出（代码 / HTML）不做润色，避免破坏格式。
        if self._has_code_block(reply):
            return
        mood = ctx.mood()
        opener = ""
        if mood < -0.15:
            opener = _pick(_EMPATHY_LOW, msg.text)
        elif mood > 0.15:
            opener = _pick(_WARM_OPENERS, msg.text)
        # 仅在未以标点/表情开头时加开场，避免"，好的，..."这类堆叠。
        tail_punct = "，。！？、~～"
        if opener and reply[0] not in tail_punct:
            reply = opener + reply
        # 收尾：仅当原文没有明显问句结尾时补一句柔和收尾。
        if not reply.rstrip().endswith(("？", "?", "吗", "呢")):
            reply = reply.rstrip() + _pick(_CLOSERS, reply)
        msg.reply = reply
