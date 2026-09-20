"""CapabilityDiscovery —— 应用"能力"的声明与发现。

为什么单独抽一层
----------------
产品智能体当前用一堆散落的 ``if chip == "ad"`` / ``_MAP`` / ``ADAPTERS`` 硬编码分支
来"识别用户想要什么能力"（广告设计、图文、视频…）。一个能力常有多套入口，
改一套 ≠ 改完（见项目记忆：广告设计至少三处入口）。

``CapabilityDiscovery`` 把"能力"变成一等公民：

  - 每个能力 = ``Capability(name, match, run)``，自带匹配规则与执行体；
  - 应用启动时报到注册，运行时按用户输入做**统一**的能力发现；
  - 匹配规则默认"句首 N 字 + 关键词"，但可逐能力覆盖。

这样新增/删除/排查能力都只动注册表，不动散落分支——又是一处稳定的框架面。
（注：默认"只匹配句首 12 字"是产品侧故意的设计，这里保留为可调参数，
不是 bug；见项目记忆。）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: F401


# 默认只匹配句首这么多字符——产品侧有意保留（防止长句里误命中）。
DEFAULT_HEAD_CHARS = 12


@dataclass
class Capability:
    """一个可被用户触发的"能力"。

    ``match`` 决定何时命中；``run(app, text) -> str`` 是执行体，
    接收应用实例与原始输入，返回回复文本。
    """

    name: str
    run: Callable[..., str]            # 执行体：run(app, text) -> str
    # 匹配规则（任选其一或全部）：关键词列表 / 自定义判定 / 句首字数。
    keywords: Tuple[str, ...] = ()
    head_chars: int = DEFAULT_HEAD_CHARS
    predicate: Optional[Callable[[str], bool]] = None
    description: str = ""


class CapabilityDiscovery:
    """能力注册表 + 统一发现。

    用法：
        cd = CapabilityDiscovery()
        cd.register(Capability("广告设计", run=my_ad, keywords=("广告", "海报")))
        cap = cd.match("帮我设计一张广告")   # -> 该 Capability 或 None
    """

    def __init__(self, capabilities: Optional[List[Capability]] = None) -> None:
        self._caps: Dict[str, Capability] = {}
        for c in (capabilities or []):
            self.register(c)

    def register(self, cap: Capability) -> None:
        if not isinstance(cap, Capability):
            raise TypeError("CapabilityDiscovery 只接受 Capability，收到 %r" % type(cap).__name__)
        self._caps[cap.name] = cap

    def names(self) -> List[str]:
        return list(self._caps.keys())

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str) -> Optional[Capability]:
        return self._caps.get(name)

    def match(self, text: str) -> Optional[Capability]:
        """按规则匹配能力。

        顺序：先 ``predicate``（精确判定），再 ``keywords``（句首 head_chars 命中）。
        命中多个时返回**最先注册**的那一个（确定性，避免随机）。
        """
        t = (text or "").strip()
        if not t:
            return None
        head = t[:DEFAULT_HEAD_CHARS]
        for cap in self._caps.values():
            if cap.predicate is not None and cap.predicate(t):
                return cap
        for cap in self._caps.values():
            if cap.keywords:
                span = t[: max(cap.head_chars, 1)]
                if any(k and k in span for k in cap.keywords):
                    return cap
        return None
