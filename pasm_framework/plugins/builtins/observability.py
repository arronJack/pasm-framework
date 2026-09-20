"""observability —— 可观测插件（零依赖）：指标 + 健康。

给线上服务最基本的"看得见"能力：消息量、回复量、错误数、延迟分布、
插件异常。``health()`` / ``metrics()`` 供 web_gateway 的 ``/healthz`` 与
``app_summary()`` 调用。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext


class ObservabilityPlugin(BasePlugin):
    """指标采集。"""

    name = "observability"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._start = time.time()
        self._messages_in = 0
        self._replies = 0
        self._errors = 0
        self._latencies: List[float] = []
        self._plugin_errors = 0

    def on_message_in(self, ctx: PluginContext) -> None:
        self._messages_in += 1

    def on_learn(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        if msg.reply:
            self._replies += 1
        if msg.error:
            self._errors += 1
        lat = time.time() - msg.created_at
        self._latencies.append(lat)
        if len(self._latencies) > 1000:
            self._latencies = self._latencies[-1000:]
        errs = ctx.store.get("_plugin_errors") or []
        if errs:
            self._plugin_errors += len(errs)

    def metrics(self) -> Dict[str, Any]:
        n = len(self._latencies)
        avg = (sum(self._latencies) / n) if n else 0.0
        p95 = sorted(self._latencies)[int(n * 0.95) - 1] if n else 0.0
        return {
            "uptime_s": round(time.time() - self._start, 1),
            "messages_in": self._messages_in,
            "replies": self._replies,
            "errors": self._errors,
            "plugin_errors": self._plugin_errors,
            "avg_latency_s": round(avg, 3),
            "p95_latency_s": round(p95, 3),
        }

    def health(self) -> Dict[str, Any]:
        m = self.metrics()
        ok = m["errors"] <= m["messages_in"]  # 并非零错误才算健康
        return {"ok": bool(ok), "status": "healthy" if ok else "degraded", **m}
