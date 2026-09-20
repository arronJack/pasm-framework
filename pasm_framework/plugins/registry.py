"""插件注册表 + 默认配置 + 第三方插件发现。

- :func:`builtin_plugins`  —— 内置 7 个插件的 name→class 映射；
- :func:`default_config`   —— 默认后端开关（安全/会话/知识库/温度/可观测开，
  LLM/网关关）；
- :func:`discover_plugins` —— 通过 ``importlib.metadata`` 的 entry-point
  （group=``pasm_framework.plugins``）自动发现第三方插件。
"""
from __future__ import annotations

from typing import Dict, List, Type

from .core import BackendConfig, BasePlugin

# 默认开关：哪些是"开箱即用的安全/基础能力"，哪些需要用户显式开启。
_DEFAULT_ENABLED = {
    "safety": True,
    "sessions": True,
    "knowledge_base": True,
    "warmth": True,
    "observability": True,
    "llm_responder": False,   # 需要密钥 / 网络
    "web_gateway": False,     # 需要端口
}


def builtin_plugins() -> Dict[str, Type[BasePlugin]]:
    """返回内置插件 name→类 映射。"""
    from .builtins import (  # 延迟导入，避免与 core 的早期循环
        KnowledgeBasePlugin, LLMResponderPlugin, ObservabilityPlugin,
        SafetyPlugin, SessionsPlugin, WarmthPlugin, WebGatewayPlugin,
    )
    return {
        "sessions": SessionsPlugin,
        "knowledge_base": KnowledgeBasePlugin,
        "llm_responder": LLMResponderPlugin,
        "warmth": WarmthPlugin,
        "safety": SafetyPlugin,
        "observability": ObservabilityPlugin,
        "web_gateway": WebGatewayPlugin,
    }


def default_config() -> BackendConfig:
    """默认后端配置：基础/安全能力默认开，LLM/网关默认关。"""
    plugins: Dict[str, Dict[str, object]] = {}
    for name, enabled in _DEFAULT_ENABLED.items():
        plugins[name] = {"enabled": enabled, "config": {}}
    return BackendConfig(plugins=plugins)


def discover_plugins() -> List[BasePlugin]:
    """通过 entry-point 发现第三方插件（group=``pasm_framework.plugins``）。

    第三方包在 ``pyproject`` 里声明：
        [project.entry-points."pasm_framework.plugins"]
        my_plugin = "my_pkg.my_module:MyPlugin"
    其中 ``MyPlugin`` 是 ``BasePlugin`` 的实例或可调用返回实例。
    """
    found: List[BasePlugin] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover
        return found
    try:
        eps = entry_points()
        group = eps.select(group="pasm_framework.plugins") if hasattr(eps, "select") \
            else eps.get("pasm_framework.plugins", [])
    except Exception:
        return found
    for ep in group:
        try:
            obj = ep.load()
            inst = obj() if isinstance(obj, type) else obj
            if isinstance(inst, BasePlugin):
                found.append(inst)
        except Exception:
            # 第三方插件加载失败不应影响框架启动。
            continue
    return found
