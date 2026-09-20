"""sessions —— 会话 / 租户隔离插件（零依赖）。

解决的问题：v0.1.0 的 ``BaseApplication`` 是"一个 agent_id 全局共享状态"，
多用户 / 多会话无法隔离。本插件把每次 ``handle`` 绑定到一个 ``session_id``，
维护每会话的历史与元信息，供 llm_responder / 客服场景使用。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext


class Session:
    """单个会话的轻量状态。"""

    def __init__(self, session_id: str, user_id: Optional[str] = None) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = time.time()
        self.last_active = time.time()
        self.messages: List[Dict[str, Any]] = []   # {"role","text","ts"}
        self.meta: Dict[str, Any] = {}

    def append(self, role: str, text: str) -> None:
        self.messages.append({"role": role, "text": text, "ts": time.time()})
        self.last_active = time.time()

    def trim(self, max_len: int) -> None:
        if max_len and len(self.messages) > max_len:
            self.messages = self.messages[-max_len:]

    def history(self, max_len: int = 0) -> List[Dict[str, Any]]:
        if max_len:
            return self.messages[-max_len:]
        return list(self.messages)


class SessionsPlugin(BasePlugin):
    """会话隔离：每个 session_id 一份历史 + 元信息。"""

    name = "sessions"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._max_history: int = int(self.config.get("max_history", 20))
        self._sessions: Dict[str, Session] = {}

    def _get(self, session_id: str, user_id: Optional[str]) -> Session:
        s = self._sessions.get(session_id)
        if s is None:
            s = Session(session_id, user_id=user_id)
            self._sessions[session_id] = s
        elif user_id and s.user_id is None:
            s.user_id = user_id
        return s

    def on_message_in(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        s = self._get(msg.session_id, msg.user_id)
        # 把会话状态交给同一次调用里的其它插件（如 llm_responder）。
        ctx.store["session"] = s
        ctx.store["session_history"] = s.history(self._max_history)
        s.meta.update(msg.meta or {})

    def on_learn(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        s = self._sessions.get(msg.session_id)
        if s is None:
            return
        s.append("user", msg.text)
        if msg.reply:
            s.append("assistant", msg.reply)
        s.trim(self._max_history)

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_sessions(self, limit: int = 0) -> List[Dict[str, Any]]:
        """按最近活跃倒序列出会话（供管理台 / 运营看板使用）。

        ``limit`` 为 0 表示不限条数。只暴露**概要**（不含消息正文），
        避免把客户对话内容整批吐给任何能打开管理台的人。
        """
        rows = [
            {
                "session_id": s.session_id,
                "user_id": s.user_id,
                "messages": len(s.messages),
                "created_at": round(s.created_at, 3),
                "last_active": round(s.last_active, 3),
            }
            for s in self._sessions.values()
        ]
        rows.sort(key=lambda r: r["last_active"], reverse=True)
        return rows[:limit] if limit else rows

    def count(self) -> int:
        return len(self._sessions)
