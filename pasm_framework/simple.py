"""SimpleApplication —— 让"最小可用应用"从 30 行降到 3 行。

``BaseApplication`` 继承自 ``BaseAgent``，而 ``BaseAgent`` 是抽象基类，
要求子类实现 ``action_pool()`` 与 ``_render_reply()``。对"我就想快速做个
客服/问答/NPC"的人来说这是不必要的门槛 —— 本模块把这两个都给了默认实现，
并额外提供 ``@capability`` 装饰器，让"加一个能力"= 加一个方法。

三种用法，由简到繁
------------------
1. 最简（0 个方法）::

     from pasm_framework import SimpleApplication
     app = SimpleApplication("demo", {"name": "小智"})
     print(app.ask("你好"))

2. 自定义回复（传函数）::

     app = SimpleApplication("demo", {"name": "小智"},
                             reply=lambda text, facts, mood: "你说的是：" + text)

3. 加能力（装饰器）::

     class Shop(SimpleApplication):
         @capability(keywords=("退货", "退款"))
         def refund(self, text):
             return "退货请点这里：/refund"

     Shop("shop", {"name": "客服"}).handle("我要退货")   # → 能力命中
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .application import BaseApplication
from .config import BackendConfig, load
from .discovery import Capability

#: ``reply`` 回调签名：``(text, facts, mood) -> str``
ReplyFn = Callable[[str, List[Dict[str, Any]], float], str]


def capability(
    name: Optional[str] = None,
    keywords: Any = (),
    *,
    predicate: Optional[Callable[[str], bool]] = None,
    description: str = "",
    head_chars: int = 12,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """把实例方法标记为一个能力（动作）。

    被标记的方法签名应为 ``def m(self, text: str) -> str``。
    命中后 ``text`` 会作为第一个位置参数传入（即它等价于 ``Capability.run``）。

    ``keywords`` 只在**句首 head_chars 个字**内匹配（框架既有语义，防止
    "我在想退货这事到底……"这种长句被误触发）。
    """

    def deco(fn: Callable[..., str]) -> Callable[..., str]:
        fn.__pasm_capability__ = {  # type: ignore[attr-defined]
            "name": name or fn.__name__,
            "keywords": tuple(keywords) if not isinstance(keywords, str)
            else (keywords,),
            "predicate": predicate,
            "description": description,
            "head_chars": head_chars,
        }
        return fn

    return deco


class SimpleApplication(BaseApplication):
    """带默认回复实现的通用应用底座。

    参数
    ----
    reply : ReplyFn | None
        自定义回复生成器；缺省用"就资料作答、查不到就如实说"的内置策略。
    unknown : str | None
        检索不到资料时的兜底话术（**面向最终用户**，别写开发提示）。
    backend_config : dict | BackendConfig | None
        插件开关表；也可用 ``preset=`` 直接指定场景预设。
    preset : str | None
        场景预设名（见 :mod:`pasm_framework.config`）。给了 preset 才生效，
        与 ``backend_config`` 同时给时 ``backend_config`` 优先。
    """

    #: 检索不到资料时的默认话术（面向用户，不暴露"插件/配置"这类内部概念）。
    DEFAULT_UNKNOWN = "抱歉，我暂时没有查到相关资料。你可以换个说法再问我，或联系人工客服。"

    #: 子类由 ``__init_subclass__`` 自动填充：``[(method_name, spec), ...]``
    _PASM_AUTO_CAPS: List[tuple] = []

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        auto: List[tuple] = []
        for attr, obj in vars(cls).items():
            spec = getattr(obj, "__pasm_capability__", None)
            if isinstance(spec, dict):
                auto.append((attr, spec))
        if auto:
            cls._PASM_AUTO_CAPS = auto

    def __init__(
        self,
        agent_id: str,
        persona: Optional[Dict[str, Any]] = None,
        *,
        reply: Optional[ReplyFn] = None,
        capabilities: Optional[List[Capability]] = None,
        preset: Optional[str] = None,
        unknown: Optional[str] = None,
        backend_config: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        self._reply_fn = reply
        self._unknown = unknown or self.DEFAULT_UNKNOWN
        caps = list(capabilities or [])
        # 把 @capability 标记过的方法转成 Capability 对象。
        for method_name, spec in type(self)._PASM_AUTO_CAPS:
            caps.append(Capability(
                spec["name"],
                run=self._make_runner(method_name),
                keywords=spec["keywords"],
                predicate=spec["predicate"],
                description=spec["description"],
                head_chars=spec["head_chars"],
            ))
        if backend_config is None and preset is not None:
            backend_config = load(preset_name=preset)
        super().__init__(
            agent_id, persona or {"name": "助手"},
            capabilities=caps or None,
            backend_config=backend_config,
            **kwargs,
        )

    @staticmethod
    def _make_runner(method_name: str) -> Callable[..., str]:
        def run(app: Any, text: str) -> str:
            return getattr(app, method_name)(text)
        return run

    # ---- BaseAgent 抽象方法的默认实现 ----
    def action_pool(self) -> List[str]:  # noqa: D102
        return ["reply"]

    def _render_reply(  # noqa: D102
        self, text: str, facts: List[Dict[str, Any]], mood: float
    ) -> str:
        if self._reply_fn is not None:
            return self._reply_fn(text, facts, mood)
        # 默认策略：只依据"有来源的知识"作答，不编造。
        knowledge = [f for f in (facts or []) if f.get("source")]
        if knowledge:
            top = knowledge[0]
            body = (top.get("brief") or top.get("title") or "").strip()
            return body or self._unknown
        return self._unknown

    # ---- 便捷方法 ----
    def ask(self, text: str, session_id: str = "default",
            user_id: Optional[str] = None) -> str:
        """语义化别名：``handle`` 是框架内部叫法，``ask`` 是给人看的。"""
        return self.handle(text, session_id=session_id, user_id=user_id)

    def teach(self, items: List[Dict[str, Any]]) -> int:
        """把资料喂进知识库（需启用 ``knowledge_base``）。返回新增条数。"""
        kb = self.plugins.get("knowledge_base")
        if kb is None or not self.plugins.is_enabled("knowledge_base"):
            return 0
        return kb.ingest(items)
