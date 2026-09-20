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

    # ---- 领域 / 知识库增强检索 ---------------------------------
    def recall(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """跨层检索：引擎记忆 + 领域适配器 + 知识库插件。

        为什么要把知识库插件也并进来：能力（``Capability``）与领域代码里
        很自然会写 ``self.recall(query)``，但插件检索原本只在 ``handle`` 的
        ``on_retrieve`` 阶段发生 —— 于是"在能力里查资料库"总是查不到。
        这里统一合并，让 ``self.recall()`` 在任何上下文都看得到全部知识。

        去重按 ``title``；凡"有依据的知识"（领域 / 知识库）都带 ``source``，
        纯对话记忆（episodic）不带 —— 应用可据此区分"资料"与"闲聊"。
        """
        hits = super().recall(query, k=k)
        seen = {h.get("title") for h in hits}

        if hasattr(self.domain, "knowledge_for"):
            try:
                dom = self.domain.knowledge_for(query)  # type: ignore[attr-defined]
                for item in (dom or []):
                    if item.get("title") in seen:
                        continue
                    it = dict(item)
                    it.setdefault("source",
                                  "domain:%s" % type(self.domain).__name__)
                    hits.append(it)
                    seen.add(it.get("title"))
            except Exception:
                pass

        # 知识库插件：注意用插件自己的 recall（不是本方法），避免递归。
        plugins = getattr(self, "plugins", None)
        if plugins is not None:
            kb = plugins.get("knowledge_base")
            if kb is not None and plugins.is_enabled("knowledge_base"):
                try:
                    for item in kb.recall(query, k=k):
                        if item.get("title") in seen:
                            continue
                        hits.append(item)
                        seen.add(item.get("title"))
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
          4. 回复生成：能力未命中时跑 ``on_reply``（LLM）→ 否则回落 ``chat``；
          4b. ``on_reply_final`` 收尾（护栏脱敏 / 温度润色）—— **唯一出口**；
          5. ``on_learn``        插件自学习（知识库沉淀 / 会话落地 / 反馈）。

        「唯一出口」的含义：无论回复来自能力 / LLM / 模板兜底 / 被拦截，
        出站前都必然经过 ``on_reply_final``。护栏因此不可能被某条路径绕过。

        不启用任何插件时，行为与 v0.1.0 完全一致（能力路由 → 回落 chat）。
        """
        msg = Message(role="user", text=text, session_id=session_id,
                      user_id=user_id, meta=meta or {})
        ctx = PluginContext(self, msg, {})

        # 1. 入站预处理
        self.plugins.run_hooks("on_message_in", ctx)
        if msg.stop:
            # 被拦截也要走收尾阶段 —— 否则"唯一出口"承诺不成立：
            # 某个插件塞进 msg.reply 的文本（可能含 PII）会绕过脱敏。
            if not msg.reply:
                msg.reply = "(已被安全策略拦截)"
            self.plugins.run_hooks("on_reply_final", ctx)
            return msg.reply

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
                if reply:
                    # 标记来源：能力产出的是"确定性结果"（可能是一段精确文本、
                    # 一个链接、一段结构化内容），风格类插件（如 warmth）默认
                    # 不应去改写它；而护栏类插件（如 safety 脱敏）仍然必须生效。
                    msg.meta["generated_by"] = "capability:%s" % cap.name
            except Exception:
                reply = ""
        else:
            reply = ""
        if not reply:
            # 生成阶段：让 on_reply 插件（LLM 响应器）产出内容。
            self.plugins.run_hooks("on_reply", ctx)
            reply = msg.reply or ""
        if not reply:
            # 仍无生成来源 → 模板兜底。
            # 没有"有依据的知识"（仅闲聊记忆不算）时标记"答不上来"，
            # 供 knowledge_base 自学习时跳过（不沉淀垃圾）。
            if not any(f.get("source") for f in base_facts):
                msg.meta["no_answer"] = True
            reply = self.chat(text, facts=base_facts)
        msg.reply = reply

        # 4b. 收尾阶段（唯一出口）：护栏脱敏 / 温度润色对**所有**路径生效。
        #     注意：必须放在模板兜底**之后**，否则离线路径会绕过护栏。
        self.plugins.run_hooks("on_reply_final", ctx)
        reply = msg.reply or reply

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
    def serve(self, host: Optional[str] = None, port: Optional[int] = None,
              **kw) -> None:
        """启动 HTTP 网关（需已启用 ``web_gateway`` 插件）。

        站点可用 ``<iframe src="http://<host>:<port>/">`` 嵌入智能客服，
        或用 ``POST /api/chat`` 对接。未启用网关插件时抛 ``FrameworkError`` 指引。

        ``host`` / ``port`` 缺省为 ``None`` —— 表示"用插件配置里的值"
        （即 ``backend_config["web_gateway"]["config"]``）。只有在显式传入时
        才覆盖配置，避免"配置里写了 9000，``serve()`` 却起了 8080"的困惑。
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
        # 配置里写了但没匹配到插件的名字（多半拼错）—— 暴露出来，别让它静默。
        unknown = self.plugins.unknown()
        if unknown:
            s["plugin_config_unknown"] = unknown
        s["plugin_metrics"] = self.plugin_metrics()
        return s
