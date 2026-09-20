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
from typing import Any, Dict, List, Optional, Union

from pasm_skills.sdk.base import BaseAgent
from pasm_skills.sdk.backend import CognitiveBackend
from .adapter import DomainAdapter, NullDomainAdapter
from .discovery import Capability, CapabilityDiscovery
from .service import CognitiveAssembler
from .plugins.core import (
    BackendConfig, Message, PluginContext, PluginManager, build_manager,
)
from pasm_skills.sdk.backend import _now  # 复用基座时钟（与 BaseAgent 一致）


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
    plugins : PluginManager | None
        插件管理器（Hook 链）。缺省按 ``backend_config`` / 默认开关装配。
    backend_config : dict | BackendConfig | None
        **后端可选开关表**：控制哪些内置插件启用及其配置（即"用户可在后端选择是否使用"）。
        形如 ``{"knowledge_base": {"enabled": True, "config": {...}}, ...}``。
        传入后覆盖默认装配；与 ``plugins`` 二选一，``backend_config`` 优先。
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
        plugins: Optional[PluginManager] = None,
        backend_config: Optional[Union[Dict[str, Any], BackendConfig]] = None,
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

        # ---- 插件子系统（即插即用）----
        if backend_config is not None:
            cfg = backend_config if isinstance(backend_config, BackendConfig) \
                else BackendConfig(plugins=dict(backend_config))
            self.plugins: PluginManager = build_manager(cfg)
        elif plugins is not None:
            self.plugins = plugins
        else:
            self.plugins = build_manager(None)
        # 启动钩子：各插件 on_init（如 web_gateway 绑定 app 引用）。
        self.plugins.bootstrap(self)

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
                            it = dict(item)
                            # 标记来源：凡"有依据的知识"（领域/知识库）都带 source，
                            # 而纯对话记忆（episodic）不带 —— 便于区分"资料"与"闲聊"。
                            it.setdefault("source",
                                          "domain:%s" % type(self.domain).__name__)
                            hits.append(it)
            except Exception:
                pass
        return hits[:k] if k else hits

    # ---- 对话（覆盖基类，支持注入已检索事实）-----------------
    def chat(self, text: str, facts: Optional[List[Dict[str, Any]]] = None) -> str:
        """与基类同语义，但允许调用方传入已合并的检索事实（如插件检索到的资料库）。

        不传时与 ``BaseAgent.chat`` 完全一致（离线模板回复 + 写入记忆）。
        """
        f = facts if facts is not None else self.recall(text, k=3)
        mood = self.mood
        self.state.total_interactions += 1
        self.state.last_active = _now()
        self.observe(
            title="对话：%s" % text[:24],
            brief=text, tags=[text[:4]] if text else [],
            salience=2, category="对话",
        )
        return self._render_reply(text=text, facts=f, mood=mood)

    # ---- 统一入口：插件链 + 能力路由 → 回落 chat --------------
    def handle(
        self,
        text: str,
        *,
        session_id: str = "default",
        user_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """处理用户输入的统一入口（插件增强版）。

        管线：
          1. ``on_message_in``   安全扫描 / 会话绑定 / 语言；``stop`` 则短路返回；
          2. 能力路由：命中 ``Capability`` → 执行（动作类优先）；
          3. ``on_retrieve``     插件贡献资料（如知识库）→ 合并进 ``msg.facts``；
          4. 回复生成：能力未命中时跑 ``on_reply``（LLM/温度）→ 否则回落 ``chat``；
          5. ``on_learn``        插件自学习（知识库沉淀 / 会话落地 / 反馈）。

        不启用任何插件时，行为与 v0.1.0 完全一致（能力路由 → 回落 chat）。
        """
        msg = Message(role="user", text=text, session_id=session_id,
                      user_id=user_id, meta=meta or {})
        ctx = PluginContext(self, msg, {})

        # 1. 入站预处理
        self.plugins.run_hooks("on_message_in", ctx)
        if msg.stop:
            return msg.reply or "(已被安全策略拦截)"

        # 2. 能力路由（动作类显式触发优先）
        cap = None
        if msg.route_to:
            cap = self.capabilities.get(msg.route_to)
        else:
            cap = self.capabilities.match(text)

        # 3. 检索增强：插件贡献事实
        self.plugins.run_hooks("on_retrieve", ctx)
        base_facts = self.recall(text, k=5)
        seen = {f.get("title") for f in base_facts}
        for f in msg.facts:
            if f.get("title") not in seen:
                base_facts.append(f)
                seen.add(f.get("title"))
        msg.facts = base_facts

        # 4. 回复生成
        if cap is not None:
            try:
                reply = cap.run(self, text)
            except Exception:
                reply = ""
        else:
            reply = ""
        if not reply:
            # 让 on_reply 插件（LLM 响应器 / 温度润色）生成；否则回落模板 chat。
            self.plugins.run_hooks("on_reply", ctx)
            if msg.reply:
                reply = msg.reply
            else:
                # 没有"有依据的知识"（仅闲聊记忆不算），走模板兜底 ——
                # 标记"答不上来"，供 knowledge_base 自学习时跳过（不沉淀垃圾）。
                if not any(f.get("source") for f in base_facts):
                    msg.meta["no_answer"] = True
                reply = self.chat(text, facts=base_facts)
        msg.reply = reply

        # 5. 学习 / 落地
        self.plugins.run_hooks("on_learn", ctx)
        return reply

    # ---- 插件指标 / 健康 --------------------------------------
    def plugin_metrics(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "enabled": self.plugins.enabled_names(),
            "all": self.plugins.names(),
        }
        obs = self.plugins.get("observability")
        if obs is not None and self.plugins.is_enabled("observability"):
            try:
                out["observability"] = obs.metrics()
            except Exception:
                pass
        return out

    # ---- 对外服务（Web 网关）----------------------------------
    def serve(self, host: str = "127.0.0.1", port: int = 8080, **kw) -> None:
        """启动 HTTP 网关（需已启用 ``web_gateway`` 插件）。

        站点可用 ``<iframe src="http://<host>:<port>/">`` 嵌入智能客服，
        或用 ``POST /api/chat`` 对接。未启用网关插件时抛 ``FrameworkError`` 指引。
        """
        gw = self.plugins.get("web_gateway")
        if gw is None or not self.plugins.is_enabled("web_gateway"):
            from .errors import FrameworkError
            raise FrameworkError(
                "serve() 需要启用 'web_gateway' 插件："
                "在 backend_config 中设置 {'web_gateway': {'enabled': True}} 后重试。"
            )
        gw.start(self, host=host, port=port, **kw)

    def close(self) -> None:
        """优雅关闭：跑插件 on_shutdown（如停掉网关线程）。"""
        try:
            self.plugins.shutdown(self)
        except Exception:
            pass
        try:
            self.save()
        except Exception:
            pass

    # ---- 应用级快照（给 API / 调试用） ------------------------
    def app_summary(self) -> Dict[str, Any]:
        s = self.summary()
        s["domain"] = type(self.domain).__name__
        s["capabilities"] = self.capabilities.names()
        s["plugins"] = self.plugins.enabled_names()
        s["plugin_metrics"] = self.plugin_metrics()
        return s
