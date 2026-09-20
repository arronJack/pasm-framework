"""CognitiveAssembler + CognitiveService —— 框架与引擎之间的「唯一变动点」。

为什么这层必须存在（V1→V2 不重写智能体/技能的核心机制）
------------------------------------------------------
`pasm_skills.sdk.BaseAgent` 已经通过 ``CognitiveBackend`` 协议与引擎解耦（见
``pasm_skills/sdk/backend.py``）：它只认识协议，不认识 ``pasm.*``。

本模块在协议之上再架一层**装配层**，把"选哪个后端、怎么把它适配成应用可用的认知服务"
这件事彻底收口：

  · ``CognitiveBackend`` （来自基座 sdk）  —— 引擎侧稳定契约（episode_push/recall/feedback…）。
  · ``CognitiveService``                 —— 应用侧稳定契约：在后端外面套一层，
                                            附带 domain 适配器钩子，但**对外仍是
                                            CognitiveBackend**（这样 BaseAgent 无需改动）。
  · ``CognitiveAssembler``               —— 装配器：V1 调 :meth:`v1` 拿到 V1 后端；
                                            V2 只需新增 :meth:`v2` 返回 ``PasmV2Backend``，
                                            **上层（4 智能体 / 3 技能）一行不改**。

所以"唯一变动点"就是这里：引擎大改时，只有 ``CognitiveAssembler.v2``（以及
``PasmV2Backend``）需要写，应用层完全不动。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pasm_skills.sdk.backend import (
    CognitiveBackend,
    create_v1_backend,
)
from .adapter import DomainAdapter, NullDomainAdapter


# ============================================================ 认知服务（应用侧契约）

class CognitiveService:
    """包在 ``CognitiveBackend`` 外面的应用侧认知服务。

    它**实现** ``CognitiveBackend`` 协议（属性 + 方法齐全），因此可以直接作为
    ``BaseAgent(backend=...)`` 的入参；同时额外携带 ``domain`` 钩子，
    供 ``BaseApplication`` 在检索/回复时注入领域知识。

    V1→V2：本类不变。变的只是它内部委托的那个 ``_backend`` 是 V1 还是 V2。
    """

    def __init__(
        self,
        backend: CognitiveBackend,
        domain: DomainAdapter = NullDomainAdapter(),
    ) -> None:
        # 不变量：入参必须真满足协议，否则就是"变动点"被改坏了——
        # surface-guard 会抓这个（见框架 __init__ 的契约断言）。
        if not isinstance(backend, CognitiveBackend):
            raise TypeError(
                "CognitiveService 需要 CognitiveBackend 协议实现，收到 %r"
                % type(backend).__name__
            )
        self._backend = backend
        self.domain = domain

    # ---- CognitiveBackend 协议：全部委托给后端 ----

    @property
    def is_core(self) -> bool:
        return bool(getattr(self._backend, "is_core", False))

    @property
    def emotion_system(self) -> Optional[Any]:
        return getattr(self._backend, "emotion_system", None)

    def episode_push(self, *, title, brief, tags, category, salience) -> None:
        self._backend.episode_push(
            title=title, brief=brief, tags=tags,
            category=category, salience=salience,
        )

    def recall(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        # 基础检索走后端；领域知识注入留给 BaseApplication（避免污染协议签名）。
        return self._backend.recall(query, k=k)

    def feedback(self, kind: str, action: Optional[str] = None) -> Dict[str, float]:
        fn = getattr(self._backend, "feedback", None)
        if fn is not None:
            return fn(kind, action=action)
        return {}

    def learn_pick(self, candidates: List[str], base=None, **kw) -> str:
        fn = getattr(self._backend, "learn_pick", None)
        if fn is not None:
            try:
                return fn(candidates, base=base, **kw)
            except TypeError:
                try:
                    return fn(candidates)
                except Exception:
                    pass
            except Exception:
                pass
        import random
        pool = [c for c in candidates if c]
        return random.choice(pool) if pool else ""

    def counts(self) -> Dict[str, int]:
        fn = getattr(self._backend, "counts", None)
        if fn is not None:
            try:
                return fn()
            except Exception:
                return {}
        return {}


# ============================================================ 装配器（唯一变动点）

class CognitiveAssembler:
    """把后端装配成应用可用的 ``CognitiveService``。

    这是 V1↔V2 的唯一变动点：

      - ``CognitiveAssembler.v1(...)``  → 返回 V1 后端装配出的服务（当前默认）。
      - ``CognitiveAssembler.v2(...)``  → （V2.0 落地时新增）返回 V2 后端装配出的服务。
      上层 ``BaseApplication`` / 4 智能体 / 3 技能只调用装配器，**不直接碰后端类型**，
      因此换引擎 = 改这一处工厂方法。
    """

    @classmethod
    def wrap(
        cls,
        backend: CognitiveBackend,
        domain: Optional[DomainAdapter] = None,
    ) -> CognitiveService:
        """把任意 CognitiveBackend 包成 CognitiveService。"""
        return CognitiveService(backend, domain or NullDomainAdapter())

    @classmethod
    def v1(
        cls,
        persist_dir,
        persona: Optional[dict] = None,
        *,
        use_core: bool = True,
        stage: int = 0,
        domain: Optional[DomainAdapter] = None,
    ) -> CognitiveService:
        """默认路径：V1 后端（core 优先，降级 light）装配成服务。"""
        backend = create_v1_backend(
            persist_dir, persona, use_core=use_core, stage=stage
        )
        return cls.wrap(backend, domain)

    # —— V2.0 落地时在此新增（示例，先留接口不实现，避免提前引入 pasm_v2 依赖）：
    # @classmethod
    # def v2(cls, persist_dir, persona=None, *, domain=None) -> CognitiveService:
    #     from pasm_skills.contrib.v2 import create_v2_backend
    #     return cls.wrap(create_v2_backend(persist_dir, persona), domain)
