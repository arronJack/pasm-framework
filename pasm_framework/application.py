"""BaseApplication —— 通用 AI 应用底座（建立在 BaseAgent + 框架之上）。

定位
----
``BaseAgent``（sdk）解决"一个智能体如何记忆/情绪/动作/反馈"。
``BaseApplication`` 在它之上补上"一个**应用**"才有的 concerns：

  - 用 ``CognitiveAssembler`` 装配认知后端（V1↔V2 唯一变动点，对子类透明）；
  - 用 ``DomainAdapter`` 注入领域知识（NPC/Companion/Tutor 各自实现）；
  - 用 ``CapabilityDiscovery`` 做统一的能力路由（消灭散落的 ``if chip==`` 分支）；
  - 提供 ``handle()`` 统一入口：先能力路由，再回落 ``chat``。

迁移路径（V2.0 时）
-------------------
当前 4 个产品智能体直接 ``class X(BaseAgent)``。V2.0 把它们改成
``class X(BaseApplication)``，并实现 ``DomainAdapter`` + 报到 ``Capability``，
即可获得"换引擎零改动 + 能力可注册 + 领域可替换"三件套。
这一步是**一次性的 V2 迁移**，不是"每次引擎改动都要重写的副本"。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pasm_skills.sdk.base import BaseAgent
from pasm_skills.sdk.backend import CognitiveBackend
from .adapter import DomainAdapter, NullDomainAdapter
from .discovery import Capability, CapabilityDiscovery
from .service import CognitiveAssembler


class BaseApplication(BaseAgent):
    """通用 AI 应用底座。

    参数
    ----
    domain : DomainAdapter | None
        领域适配器（NPC/Companion/Tutor 各提供一个）；``None`` 走 ``NullDomainAdapter``。
    capabilities : list[Capability] | None
        该应用暴露的能力列表，启动时报到到 ``CapabilityDiscovery``。
    backend : CognitiveBackend | None
        注入式后端（测试 / V2 都用它）；缺省由 ``CognitiveAssembler.v1`` 自动装配。
    """

    def __init__(
        self,
        agent_id: str,
        persona: Dict[str, Any],
        *,
        domain: Optional[DomainAdapter] = None,
        capabilities: Optional[List[Capability]] = None,
        persist_dir: Optional[str | Path] = None,
        use_core: bool = True,
        backend: Optional[CognitiveBackend] = None,
    ) -> None:
        self.domain: DomainAdapter = domain or NullDomainAdapter()
        self.capabilities = CapabilityDiscovery(capabilities or [])

        # 装配认知后端：注入优先，否则走 V1 默认路径（V2 时只需把这里换成 .v2）。
        if backend is None:
            backend = CognitiveAssembler.v1(
                Path(persist_dir) if persist_dir is not None
                else (Path.home() / ".pasm-agents" / agent_id),
                persona, use_core=use_core, domain=self.domain,
            )
        super().__init__(
            agent_id, persona, persist_dir=persist_dir,
            use_core=use_core, backend=backend,
        )

    # ---- 领域增强检索 ------------------------------------------
    def recall(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        hits = super().recall(query, k=k)
        if hasattr(self.domain, "knowledge_for"):
            try:
                dom = self.domain.knowledge_for(query)  # type: ignore[attr-defined]
                if dom:
                    seen = {h.get("title") for h in hits}
                    for item in dom:
                        if item.get("title") not in seen:
                            hits.append(item)
            except Exception:
                pass
        return hits[:k] if k else hits

    # ---- 统一入口：能力路由 → 回落 chat ------------------------
    def handle(self, text: str) -> str:
        """处理用户输入的统一入口。

        1. 先问能力发现器是否命中某个能力；
        2. 命中 → 调该能力的 ``run(self, text)``；
        3. 未命中 → 回落 ``chat``（BaseAgent 的模板回复）。
        """
        cap = self.capabilities.match(text)
        if cap is not None:
            try:
                return cap.run(self, text)
            except Exception:
                # 能力执行失败不应让整个应用崩；回落通用对话。
                pass
        return self.chat(text)

    # ---- 应用级快照（给 API / 调试用） ------------------------
    def app_summary(self) -> Dict[str, Any]:
        s = self.summary()
        s["domain"] = type(self.domain).__name__
        s["capabilities"] = self.capabilities.names()
        return s
