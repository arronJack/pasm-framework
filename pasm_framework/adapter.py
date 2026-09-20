"""DomainAdapter —— 领域知识 / 规则注入的契约。

为什么单独抽一层
----------------
NPC / 老人陪伴 / 学习陪伴 三个产品智能体现在把"领域逻辑"写死在各自的
``BaseAgent`` 子类里（动作池语义、回复风格、约束规则全混在一起）。
一旦要换引擎或加第四个领域，这些逻辑只能靠"读懂旧子类再抄"来维持。

``DomainAdapter`` 把"这个领域知道什么、约束什么、怎么润色回复"抽成显式契约：
每个产品提供一个 ``DomainAdapter`` 实现，``BaseApplication`` 只认契约、不认具体领域。
这样领域逻辑可独立测试、可独立替换——又是一处 V1↔V2 不该动的稳定面。
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class DomainAdapter(Protocol):
    """领域适配契约（应用侧只读、可选实现）。

    所有方法都是可选的：框架用 ``getattr``/``hasattr`` 探测，缺失就走兜底。
    这样一个"最小领域适配器"只需要实现 ``knowledge_for`` 即可。
    """

    def knowledge_for(self, query: str) -> List[Dict[str, Any]]:
        """给定用户问句，返回该领域相关的结构化知识片段。

        返回结构与 ``CognitiveBackend.recall`` 对齐：
        ``[{title, brief, tags, sal, ...}, ...]``，方便合并进检索结果。
        """
        ...

    def constraints(self) -> Dict[str, Any]:
        """该领域的硬性约束（如"不允许承诺医疗诊断"、"动作池白名单"）。"""
        ...

    def augment_reply(self, text: str, reply: str, facts: List[Dict[str, Any]]) -> str:
        """在 ``_render_reply`` 产出后，再做一次领域级润色/兜底。"""
        ...


class NullDomainAdapter:
    """空领域适配器：什么都不注入。

    框架的默认实现——保证"没有领域知识也能跑"（与 BaseAgent 的离线优先一致）。
    它**不**实现 ``knowledge_for`` 等方法，因此框架探测到缺失时走兜底，
    而不是假装有知识。
    """

    is_core = False


class StaticDomainAdapter:
    """用一份静态知识表 + 简单关键词命中实现的最简 DomainAdapter。

    适合脚手架期快速验证"领域注入"链路，真实产品应替换为带检索的实现。
    """

    def __init__(self, knowledge: List[Dict[str, Any]], constraints: Dict[str, Any] | None = None):
        self._knowledge = list(knowledge or [])
        self._constraints = dict(constraints or {})

    def knowledge_for(self, query: str) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        hit = []
        for item in self._knowledge:
            blob = " ".join(str(item.get(k, "")) for k in ("title", "brief", "tags"))
            if any(tok and tok in blob for tok in q):
                hit.append(dict(item))
        return hit

    def constraints(self) -> Dict[str, Any]:
        return dict(self._constraints)

    def augment_reply(self, text: str, reply: str, facts: List[Dict[str, Any]]) -> str:
        # 默认不润色；子类可覆盖。
        return reply
