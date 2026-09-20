"""插件子系统核心 —— pasm-framework 的「即插即用」骨架。

为什么需要这一层
----------------
v0.1.0 的 ``BaseApplication`` 把所有 concern（会话、检索增强、回复生成、护栏…）
都写死在类里，用户无法"在后端选择是否使用某项功能"。本模块把应用拆成一条
**Hook 链**，每个通用能力做成一个**插件（Plugin）**，挂在链上：

  - ``Message``        —— 在链上流动的结构化消息（用户/助手/系统）；
  - ``PluginContext``  —— 插件可调用的共享上下文（app + message + 配置 + 工具方法）；
  - ``BasePlugin``     —— 插件基类（所有 Hook 默认空实现，子类按需覆盖）；
  - ``PluginManager``  —— 按注册顺序跑 Hook 链，支持 enable/disable；
  - ``BackendConfig``  —— 后端配置（dict），控制每个插件"是否启用 + 配置"；
  - ``build_manager``  —— 从 ``BackendConfig`` 装配出 ``PluginManager``。

设计铁律（不破坏防腐层）
----------------------
1. **零依赖**：本模块与 7 个 builtin 插件都不强制任何外部包；
   ``llm_responder`` 用标准库 ``urllib`` 发请求，缺包也不崩。
2. **可发现**：除 builtin 外，支持 ``importlib.metadata`` 的 entry-point
   （group = ``pasm_framework.plugins``）自动发现第三方插件。
3. **向后兼容**：不启用任何插件时，``BaseApplication.handle`` 行为与 v0.1.0 完全一致
   （能力路由 → 回落 chat）。

两个回复阶段的区别（v0.2.1 起，别混用）
--------------------------------------
  · ``on_reply``       —— **生成**阶段：谁来产出 assistant 文本（``llm_responder``）。
    只有"还没有回复"时才被期待产出内容；此时 ``msg.reply`` 通常为空。
  · ``on_reply_final`` —— **收尾**阶段：对**已经定稿**的回复做后处理
    （``safety`` 脱敏、``warmth`` 润色）。由 ``BaseApplication`` 在
    "所有回复路径汇合之后的唯一出口"调用，因此**恰好跑一次**。

为什么需要 ``on_reply_final``：v0.2.0 把护栏/润色挂在 ``on_reply`` 上，
而模板兜底回复（未开 LLM 的离线路径）在 ``on_reply`` **之后**才生成，
导致兜底回复绕过了护栏。拆出收尾阶段后，LLM 回复与模板回复走同一条出口。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, List, Optional, Protocol, runtime_checkable,
)


# ============================================================ 结构化消息

@dataclass
class Message:
    """在插件链上流动的结构化消息。

    字段分三类：
      · 输入（应用填写）：``role`` / ``text`` / ``session_id`` / ``user_id`` / ``meta``；
      · 插件可写的中间态：``facts``（检索到的知识） / ``reply``（助手回复） /
        ``route_to``（指定走哪个能力）/ ``stop``（短路）/ ``error``（安全拦截原因）；
      · 只读元信息：``created_at``。
    """

    role: str = "user"                     # "user" | "assistant" | "system"
    text: str = ""
    session_id: str = "default"
    user_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    # —— 插件可写中间态 ——
    facts: List[Dict[str, Any]] = field(default_factory=list)
    reply: str = ""
    route_to: Optional[str] = None         # 指定走某个能力名（绕过关键词匹配）
    stop: bool = False                     # 置 True 则跳过后续阶段（如安全拦截）
    error: Optional[str] = None            # 安全/校验失败原因

    created_at: float = field(default_factory=time.time)

    def add_fact(self, fact: Dict[str, Any]) -> None:
        if isinstance(fact, dict) and fact:
            self.facts.append(fact)

    def set_reply(self, text: str) -> None:
        if text:
            self.reply = text


# ============================================================ 插件上下文

class PluginContext:
    """插件在每个 Hook 调用时拿到的共享上下文。

    插件应当只通过本对象与宿主交互（不直接碰 ``BaseApplication`` 内部），
    保证解耦与可替换。
    """

    def __init__(
        self,
        app: Any,
        message: Message,
        config: Dict[str, Any],
    ) -> None:
        self.app = app
        self.message = message
        self.config = config or {}
        # 插件私有运行时存储（不持久化；需要持久化请在插件内自己落盘）。
        self.store: Dict[str, Any] = {}

    # —— 便捷工具（全部委托给 app，保持插件无状态）——
    def recall(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        return self.app.recall(query, k=k)

    def observe(self, title: str, brief: str = "", tags: Optional[List[str]] = None,
                *, salience: int = 1, category: str = "日常") -> None:
        self.app.observe(title=title, brief=brief, tags=tags,
                         salience=salience, category=category)

    def mood(self) -> float:
        return float(getattr(self.app, "mood", 0.0) or 0.0)

    def persona(self) -> Dict[str, Any]:
        return dict(getattr(self.app, "persona", {}) or {})


# ============================================================ 插件契约

@runtime_checkable
class Plugin(Protocol):
    """插件契约（运行时协议）。

    所有 Hook 都是**可选**的：框架用 ``hasattr`` 探测，缺失就跳过。
    这样"最小插件"只需实现它关心的那一个 Hook。
    """

    name: str
    version: str

    def on_init(self, ctx: PluginContext) -> None: ...
    def on_message_in(self, ctx: PluginContext) -> None: ...
    def on_retrieve(self, ctx: PluginContext) -> None: ...
    def on_reply(self, ctx: PluginContext) -> None: ...
    def on_reply_final(self, ctx: PluginContext) -> None: ...
    def on_learn(self, ctx: PluginContext) -> None: ...
    def on_shutdown(self, ctx: PluginContext) -> None: ...


class BasePlugin:
    """插件基类：所有 Hook 默认空实现，子类按需覆盖。

    比 Protocol 更适合 builtin 插件（少写样板，且能放共享构造逻辑）。
    """

    #: 子类覆盖
    name: str = "base"
    version: str = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = dict(config or {})

    # —— Hook 默认空实现（子类覆盖）——
    def on_init(self, ctx: PluginContext) -> None:
        pass

    def on_message_in(self, ctx: PluginContext) -> None:
        pass

    def on_retrieve(self, ctx: PluginContext) -> None:
        pass

    def on_reply(self, ctx: PluginContext) -> None:
        """生成阶段：产出 assistant 回复（如 LLM）。"""
        pass

    def on_reply_final(self, ctx: PluginContext) -> None:
        """收尾阶段：对定稿回复做后处理（护栏 / 润色）。恰好跑一次。"""
        pass

    def on_learn(self, ctx: PluginContext) -> None:
        pass

    def on_shutdown(self, ctx: PluginContext) -> None:
        pass

    def __repr__(self) -> str:  # pragma: no cover
        return "<%s v%s>" % (self.name, self.version)


# ============================================================ 插件管理器

# 链上的 Hook 顺序（执行顺序即列表顺序）。
# 注意 on_reply（生成）与 on_reply_final（收尾）是**两个不同阶段**，
# 由 BaseApplication.handle 在各自的时间点分别触发，不要合并。
HOOKS: List[str] = [
    "on_init",
    "on_message_in",
    "on_retrieve",
    "on_reply",
    "on_reply_final",
    "on_learn",
    "on_shutdown",
]


class PluginManager:
    """按注册顺序编排插件 Hook 链。

    用法：
        pm = PluginManager()
        pm.register(SafetyPlugin())
        pm.run_hooks("on_message_in", ctx)
    """

    def __init__(self) -> None:
        self._plugins: List[BasePlugin] = []
        self._enabled: Dict[str, bool] = {}
        self._bootstrapped = False
        # 配置里出现、但既不是内置插件也没有 class/instance 的名字。
        # 多半是拼写错误 —— 静默忽略会让人以为"插件生效了"，故显式记录。
        self._unknown: List[str] = []

    def unknown(self) -> List[str]:
        """返回"配置里有、但没匹配到任何插件"的名字（疑似拼写错误）。"""
        return list(self._unknown)

    def register(self, plugin: BasePlugin, *, enabled: bool = True) -> None:
        if not hasattr(plugin, "name"):
            raise TypeError("插件必须有 name 属性")
        self._plugins.append(plugin)
        self._enabled[plugin.name] = enabled

    def names(self) -> List[str]:
        return [p.name for p in self._plugins]

    def enabled_names(self) -> List[str]:
        return [p.name for p in self._plugins if self._enabled.get(p.name, True)]

    def enable(self, name: str) -> None:
        if name in self._enabled:
            self._enabled[name] = True

    def disable(self, name: str) -> None:
        if name in self._enabled:
            self._enabled[name] = False

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    def get(self, name: str) -> Optional[BasePlugin]:
        for p in self._plugins:
            if p.name == name:
                return p
        return None

    def run_hooks(self, hook: str, ctx: PluginContext) -> None:
        """跑某个 Hook 的所有已启用插件。

        短路规则：若 ``ctx.message.stop`` 已在某插件被置 True，
        则后续插件的**同一批**（当前 hook 内）仍会跑完（便于多插件协作），
        但 ``BaseApplication`` 会在阶段边界检查 ``stop`` 决定是否进入下一阶段。
        各插件内部可自行判断 ``ctx.message.stop`` 选择是否提前返回。
        """
        if hook not in HOOKS:
            raise ValueError("未知 hook: %s" % hook)
        for p in self._plugins:
            if not self._enabled.get(p.name, True):
                continue
            fn = getattr(p, hook, None)
            if fn is None:
                continue
            try:
                fn(ctx)
            except Exception as ex:  # noqa: BLE001
                # 单个插件失败不应拖垮整条链；记录但不抛出。
                # 可观测插件会捕获该异常并计入错误计数。
                ctx.store.setdefault("_plugin_errors", []).append(
                    {"plugin": p.name, "hook": hook, "error": str(ex)}
                )

    def bootstrap(self, app: Any, message: Optional[Message] = None) -> None:
        """应用启动时调用一次：跑所有 on_init。

        ``message`` 可为空（初始化阶段还没有具体消息），
        插件应容忍 ``ctx.message`` 为占位对象。
        """
        if self._bootstrapped:
            return
        msg = message or Message(role="system", text="")
        for p in self._plugins:
            if not self._enabled.get(p.name, True):
                continue
            try:
                p.on_init(PluginContext(app, msg, p.config))
            except Exception:  # noqa: BLE001
                pass
        self._bootstrapped = True

    def shutdown(self, app: Any) -> None:
        msg = Message(role="system", text="")
        for p in self._plugins:
            if not self._enabled.get(p.name, True):
                continue
            try:
                p.on_shutdown(PluginContext(app, msg, p.config))
            except Exception:  # noqa: BLE001
                pass


# ============================================================ 后端配置

@dataclass
class BackendConfig:
    """后端配置（即"用户可在后端选择是否使用"的开关表）。

    ``plugins`` 是一个 dict：键是插件名，值是
    ``{"enabled": bool, "config": {...}}``。未列出的插件走 ``defaults``。
    """

    plugins: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    defaults: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def entry(self, name: str) -> Dict[str, Any]:
        if name in self.plugins:
            return self.plugins[name]
        return self.defaults.get(name, {"enabled": False, "config": {}})

    def enabled(self, name: str) -> bool:
        return bool(self.entry(name).get("enabled", False))

    def config_of(self, name: str) -> Dict[str, Any]:
        return dict(self.entry(name).get("config", {}) or {})


def build_manager(
    config: Optional[BackendConfig] = None,
    *,
    include_builtins: bool = True,
    discover_entrypoints: bool = True,
) -> PluginManager:
    """从 ``BackendConfig`` 装配出 ``PluginManager``。

    三条来源，按顺序：
      1. **内置插件** —— :func:`pasm_framework.plugins.registry.builtin_plugins`；
      2. **entry-point 插件** —— group=``pasm_framework.plugins`` 自动发现；
      3. **内联自定义插件** —— 配置项里写 ``class`` 或 ``instance``：

         .. code-block:: python

             backend_config = {
                 "my_rule": {"enabled": True, "class": MyRulePlugin},
                 "knowledge_base": {"enabled": True, "config": {...}},
             }

         这样用户不发布包也能接入自己的插件（框架是"通用底层"，必须留这个口）。

    若 ``config`` 为 None，使用 :func:`default_config` 的默认开关。

    配置里出现但没有任何插件匹配的名字，会记进 ``pm.unknown()`` 而不是被
    静默丢弃 —— 拼错插件名是最常见的"以为开了其实没开"来源。
    """
    from .registry import builtin_plugins, discover_plugins, default_config

    # 宽容：允许直接传 dict（与 BaseApplication(backend_config={...}) 保持一致）。
    if config is not None and not isinstance(config, BackendConfig):
        config = BackendConfig(plugins=dict(config))
    cfg = config or default_config()
    pm = PluginManager()

    if include_builtins:
        for name, plugin_cls in builtin_plugins().items():
            entry = cfg.entry(name)
            enabled = entry.get("enabled", False)
            plugin = plugin_cls(config=entry.get("config", {}))
            pm.register(plugin, enabled=enabled)

    if discover_entrypoints:
        for plugin in discover_plugins():
            name = getattr(plugin, "name", None)
            if name is None:
                continue
            if pm.get(name) is not None:      # 同名的内置插件优先，避免重复挂链
                continue
            entry = cfg.entry(name)
            enabled = entry.get("enabled", False)
            pm.register(plugin, enabled=enabled)

    # ---- 内联自定义插件 ----
    for name, raw in cfg.plugins.items():
        if pm.get(name) is not None:
            continue
        spec = raw if isinstance(raw, dict) else {}
        obj = spec.get("instance")
        if obj is None:
            cls = spec.get("class")
            if cls is None:
                pm._unknown.append(name)      # 既不是内置、也没给类 → 疑似拼错
                continue
            try:
                obj = cls(config=spec.get("config", {}))
            except TypeError:
                # 宽容：也接受只收一个位置参数的构造函数。
                obj = cls(spec.get("config", {}))
        if not isinstance(obj, BasePlugin):
            pm._unknown.append(name)
            continue
        # 允许配置名与插件自带 name 不同（便于同一插件多实例）。
        if isinstance(raw, dict) and raw.get("as"):
            obj.name = str(raw["as"])
        pm.register(obj, enabled=bool(spec.get("enabled", True)))

    return pm


def default_config() -> BackendConfig:
    """默认后端配置：安全 / 会话 / 知识库 / 温度 / 可观测默认开；
    LLM 响应器与 Web 网关默认关（需显式开启，因为要密钥 / 端口）。"""
    from .registry import default_config as _dc
    return _dc()
