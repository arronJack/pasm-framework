"""safety —— 护栏插件（零依赖）：prompt 注入拦截 + PII 脱敏。

对外暴露的 AI 应用（尤其智能客服）必须有基本护栏，否则：
  · 用户可能用"忽略以上指令"类 prompt 注入劫持行为；
  · 助手回复可能泄露系统提示词 / 密钥 / 用户隐私。

默认 ``enabled=True``、``mode="warn"``（只标记不拦，避免误伤正常用户）；
需强拦截时把 mode 设为 ``"block"``。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext

# 常见越权 / 注入短语（大小写不敏感子串匹配，零依赖）。
_DEFAULT_INJECTION = [
    "忽略", "ignore ", "ignore the", "忽视以上", "忽略以上", "忽略前面",
    "你现在是", "pretend you are", "system prompt", "系统提示", "泄露你的提示",
    "repeat your instructions", "输出你的设定", "忘记你的角色",
    "disregard", "override", "jailbreak", "越狱", "DAN",
]

# PII / 密钥脱敏正则。
_EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_APIKEY = re.compile(r"(sk-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})")


class SafetyPlugin(BasePlugin):
    """护栏：注入拦截 + 脱敏。"""

    name = "safety"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._mode: str = str(self.config.get("mode", "warn")).lower()
        self._patterns: List[str] = list(self.config.get("block_patterns")
                                         or _DEFAULT_INJECTION)
        self._redact_pii: bool = bool(self.config.get("redact_pii", True))

    def _scan_injection(self, text: str) -> Optional[str]:
        low = (text or "").lower()
        for p in self._patterns:
            if p.lower() in low:
                return p
        return None

    @staticmethod
    def _redact(text: str) -> str:
        if not text:
            return text
        t = _EMAIL.sub("[邮箱已脱敏]", text)
        t = _PHONE.sub("[手机号已脱敏]", t)
        t = _APIKEY.sub("[密钥已脱敏]", t)
        return t

    def on_message_in(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        hit = self._scan_injection(msg.text)
        if hit:
            msg.meta["injection_flag"] = hit
            if self._mode == "block":
                msg.stop = True
                msg.error = "检测到疑似越权指令（%s），已拦截。" % hit
                msg.reply = "抱歉，我无法执行该指令。如果你有产品相关问题，我很乐意帮忙。"
                return
        # 入站 PII 脱敏（仅脱敏日志/存储副本，不影响原意太多）：
        # 这里仅标记，真正脱敏在出站回复时做，避免误伤用户表达。
        if self._redact_pii:
            msg.meta["pii_present"] = bool(
                _EMAIL.search(msg.text) or _PHONE.search(msg.text)
            )

    def on_reply_final(self, ctx: PluginContext) -> None:
        """出站脱敏。挂在 **收尾阶段**（而非 ``on_reply``）至关重要：

        ``on_reply`` 阶段模板兜底回复尚未生成，挂在那里会导致
        "未接 LLM 的离线模式"回复完全绕过护栏（v0.2.0 缺陷）。
        收尾阶段由 ``BaseApplication.handle`` 在唯一出口调用，
        LLM 回复与模板回复都会被脱敏。
        """
        if not self._redact_pii:
            return
        msg: Message = ctx.message
        if msg.reply:
            msg.reply = self._redact(msg.reply)
