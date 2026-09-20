"""pasm-framework 插件子系统（即插即用）。

公共 API：
  · ``Message`` / ``PluginContext``      —— 链上消息与上下文
  · ``BasePlugin`` / ``Plugin``          —— 插件基类 / 契约
  · ``PluginManager``                   —— Hook 链编排
  · ``BackendConfig`` / ``build_manager``/ ``default_config`` —— 后端开关与装配
  · ``builtin_plugins`` / ``discover_plugins`` —— 内置与第三方插件发现

典型用法见 ``apps/customer_service.py`` 与仓库 README。
"""
from __future__ import annotations

from .core import (
    BackendConfig,
    BasePlugin,
    HOOKS,
    Message,
    Plugin,
    PluginContext,
    PluginManager,
    build_manager,
    default_config,
)
from .registry import (
    builtin_plugins,
    discover_plugins,
)

__all__ = [
    "Message",
    "PluginContext",
    "BasePlugin",
    "Plugin",
    "PluginManager",
    "BackendConfig",
    "build_manager",
    "default_config",
    "HOOKS",
    "builtin_plugins",
    "discover_plugins",
]
