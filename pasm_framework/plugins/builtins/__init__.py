"""pasm-framework 内置插件库（即插即用）。

7 个 builtin 插件，全部零强制外部依赖，可在后端配置中按名开关：
  · ``sessions``        会话 / 租户隔离
  · ``knowledge_base``  站点数据自学资料库（智能客服核心）
  · ``llm_responder``   可选 LLM 接入（OpenAI / DeepSeek / Ollama）
  · ``warmth``          回复温度 / 情感润色
  · ``safety``          护栏（注入拦截 + PII 脱敏）
  · ``observability``   可观测（指标 + 健康）
  · ``web_gateway``     零依赖 HTTP 网关（iframe / REST / SSE）

另有一个**不是插件**的模块也在这里导出：
  · ``CognitiveAPI``    认知 HTTP 适配器（``/api/cog/*``）。它由 ``web_gateway``
    持有并复用同一台服务器与同一套令牌 —— **不是一个独立插件**，
    因为认知接口能写记忆、改人格，绝不能自成一个鉴权洼地。
"""
from __future__ import annotations

from .cognitive_api import CognitiveAPI
from .knowledge_base import KnowledgeBasePlugin
from .llm_responder import LLMResponderPlugin
from .observability import ObservabilityPlugin
from .safety import SafetyPlugin
from .sessions import SessionsPlugin
from .warmth import WarmthPlugin
from .web_gateway import WebGatewayPlugin

__all__ = [
    "SessionsPlugin",
    "KnowledgeBasePlugin",
    "LLMResponderPlugin",
    "WarmthPlugin",
    "SafetyPlugin",
    "ObservabilityPlugin",
    "WebGatewayPlugin",
    "CognitiveAPI",
]
