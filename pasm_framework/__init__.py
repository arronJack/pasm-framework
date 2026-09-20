"""pasm_framework —— PASM 应用开发框架（独立成仓，原 pasm_skills.framework）。

这是 PASM 的「应用开发框架」层，与 ``pasm_skills.agent``（**验证器**框架）是两回事：
前者给**产品智能体/应用**用，后者给**自检/守护智能体**用。两者都叫"框架"，但职责不同。

本层解决的核心问题
------------------
PASM V1→V2 升级时，**不重写 4 个产品智能体 + 3 个技能**。手段是建立一组**稳定表面**，
让应用只依赖表面、不依赖引擎内部；引擎大改时只动"唯一变动点"。

表面清单（本包导出）
--------------------
  · ``CognitiveAssembler`` / ``CognitiveService``  —— 引擎↔应用装配（**唯一变动点**）；
  · ``DomainAdapter``                              —— 领域知识/规则注入契约；
  · ``CapabilityDiscovery`` / ``Capability``       —— 能力声明与统一发现；
  · ``BaseApplication``                            —— 通用 AI 应用底座（建在 BaseAgent 上）；
  · ``BaseSkill`` / ``SkillManifest``              —— 技能包代码化底座。

依赖关系（单一方向，无环）
--------------------------
  ``pasm-agents`` (产品)  →  ``pasm_framework``  →  ``pasm_skills.sdk``  →  引擎(pasm.*)

换引擎时谁动、谁不动
--------------------
  动：``CognitiveAssembler.v2``（新增）+ ``PasmV2Backend``（实现 CognitiveBackend）。
  不动：``BaseApplication``、4 智能体、3 技能、DomainAdapter、CapabilityDiscovery、BaseSkill。

本包于 v0.1.0 从 ``pasm_skills.framework`` 独立成仓（详见基座 pasm-skills 的变更说明）。
``CognitiveBackend`` 协议的**单一真相源仍在基座** ``pasm_skills.sdk.backend``，本包只做重导出。
"""
from __future__ import annotations

__version__ = "0.1.0"

from .adapter import (  # noqa: F401
    DomainAdapter,
    NullDomainAdapter,
    StaticDomainAdapter,
)
from .application import BaseApplication  # noqa: F401
from .discovery import (  # noqa: F401
    Capability,
    CapabilityDiscovery,
)
from .errors import (  # noqa: F401
    BackendContractBroken,
    FrameworkError,
    SurfaceMissing,
)
from .service import (  # noqa: F401
    CognitiveAssembler,
    CognitiveService,
)
from .skill import (  # noqa: F401
    BaseSkill,
    SkillManifest,
)
from pasm_skills.sdk.backend import (  # noqa: F401  协议本体仍来自基座 sdk，保持单一真相源
    CognitiveBackend,
)

__all__ = [
    "__version__",
    "CognitiveAssembler",
    "CognitiveService",
    "CognitiveBackend",
    "DomainAdapter",
    "NullDomainAdapter",
    "StaticDomainAdapter",
    "Capability",
    "CapabilityDiscovery",
    "BaseApplication",
    "BaseSkill",
    "SkillManifest",
    "FrameworkError",
    "SurfaceMissing",
    "BackendContractBroken",
]


def selftest() -> bool:
    """框架自检：不依赖任何具体智能体/引擎，纯本地可跑。"""
    import tempfile

    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        if not cond:
            ok = False
            print("  x %s" % msg)
        else:
            print("  v %s" % msg)

    print("pasm-framework selftest v%s" % __version__)

    try:
        from pasm_skills.sdk.backend import CognitiveBackend as _CB
        from . import (
            BaseApplication, Capability, CapabilityDiscovery,
            CognitiveAssembler, CognitiveService, DomainAdapter,
            NullDomainAdapter, StaticDomainAdapter,
        )
        with tempfile.TemporaryDirectory() as td:
            # 装配器用 V1 默认路径装配出认知服务（core 优先、降级 light）。
            svc = CognitiveAssembler.v1(td, persona={"name": "自检"})
            check(isinstance(svc, CognitiveService),
                  "CognitiveAssembler.v1 装配出 CognitiveService")
            check(isinstance(svc, _CB),
                  "CognitiveService 仍满足 CognitiveBackend 协议（BaseAgent 可食）")

            # StaticDomainAdapter 注入领域知识，BaseApplication 能检索到。
            dom = StaticDomainAdapter(
                knowledge=[{"title": "节日促销", "brief": "双十一满减", "tags": ["促销"]}],
                constraints={"no_medical": True},
            )
            check(isinstance(dom, DomainAdapter),
                  "StaticDomainAdapter 满足 DomainAdapter 契约")

            # 能力发现：句首关键词命中。
            def _run(app, text):
                return "广告已生成"
            cd = CapabilityDiscovery([Capability("广告设计", run=_run, keywords=("广告",))])
            cap = cd.match("广告一张海报")
            check(cap is not None and cap.name == "广告设计",
                  "CapabilityDiscovery 句首关键词命中")
            check(cd.match("今天天气") is None,
                  "CapabilityDiscovery 未命中返回 None")

            # BaseApplication 统一入口：命中能力 → run；否则回落 chat。
            class _App(BaseApplication):
                def action_pool(self):
                    return ["a1", "a2"]

                def _render_reply(self, text, facts, mood):
                    return "chat:%s" % text
            app = _App(
                agent_id="_fw_app", persona={"name": "x"},
                domain=dom,
                capabilities=[Capability("广告设计", run=_run, keywords=("广告",))],
                persist_dir=td,
            )
            check(app.handle("广告一张海报") == "广告已生成",
                  "BaseApplication.handle 走能力路由")
            check(app.handle("你好").startswith("chat:"),
                  "BaseApplication.handle 回落 chat")
            check("广告设计" in app.app_summary()["capabilities"],
                  "BaseApplication 暴露能力清单")
    except Exception as ex:                          # noqa: BLE001
        check(False, "应用开发框架表面可装配（异常：%s）" % ex)

    print("pasm-framework selftest:", "通过" if ok else "失败")
    return ok
