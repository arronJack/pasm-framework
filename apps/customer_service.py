"""智能客服参考实现 —— 用 pasm-framework 插件库拼出一个可上线的客服 Agent。

这个样例演示了用户最关心的诉求：**站点数据自然形成资料库 → 自学 / 记忆 / 成长 →
有情感有温度且高效地回复客户**。它把框架的 7 个内置插件按"后端开关"组合起来：

  · ``knowledge_base``  摄取站点 FAQ / 文档形成资料库，并在每次高质量问答后自学习沉淀；
  · ``sessions``       按 session_id 隔离每个客户，记住上下文；
  · ``warmth``         把情绪 / 语气渲染进回复，做到"有温度"；
  · ``safety``         拦截 prompt 注入、脱敏 PII，对外暴露才安全；
  · ``observability``  线上指标 + 健康自检；
  · ``llm_responder``  （可选）接入 DeepSeek / OpenAI / Ollama，让回复更自然；
  · ``web_gateway``    零依赖 HTTP 网关，站点用 ``<iframe>`` 或 REST API 接入。

零 LLM 也能跑：``_render_reply`` 会直接基于检索到的资料（含知识库）组织回复，
因此即使不开 LLM，客服也能"就资料回答、找不到就如实说不知道"。

用法
----
    from apps.customer_service import CustomerServiceAgent

    cs = CustomerServiceAgent("shop-cs", kb_dir="./kb")
    cs.ingest_faq([{"title": "退货政策", "content": "七天内无理由退货", "source": "faq"}])
    print(cs.ask("怎么退货？"))          # → 基于资料回答
    cs.serve(port=8080)                  # 站点 <iframe src="http://host:8080/">
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pasm_framework import BaseApplication


def _default_cs_config(
    kb_dir: Optional[str] = None,
    llm: Optional[Dict[str, Any]] = None,
    serve_port: int = 8080,
) -> Dict[str, Any]:
    """智能客服的后端开关表（即"在后端选择是否使用"哪些插件）。"""
    cfg: Dict[str, Any] = {
        # 安全 / 会话 / 知识库 / 温度 / 可观测：默认开（基础且零依赖）。
        "safety": {"enabled": True, "config": {"mode": "warn"}},
        "sessions": {"enabled": True, "config": {"max_history": 20}},
        "knowledge_base": {
            "enabled": True,
            "config": ({"kb_dir": kb_dir} if kb_dir else {}),
        },
        "warmth": {"enabled": True, "config": {}},
        "observability": {"enabled": True, "config": {}},
        # LLM / 网关：需显式配置才开。
        "llm_responder": {"enabled": bool(llm), "config": llm or {}},
        "web_gateway": {
            "enabled": True,
            "config": {"port": serve_port, "allowed_origins": "*"},
        },
    }
    return cfg


class CustomerServiceAgent(BaseApplication):
    """站点 / 平台智能客服（开箱可用的参考实现）。"""

    def __init__(
        self,
        agent_id: str,
        persona: Optional[Dict[str, Any]] = None,
        *,
        kb_dir: Optional[str] = None,
        llm: Optional[Dict[str, Any]] = None,
        serve_port: int = 8080,
        persist_dir: Optional[str] = None,
    ) -> None:
        self._serve_port = serve_port
        persona = persona or {
            "name": "小智", "role": "智能客服",
            "tone": "温暖、专业、耐心",
            "temper": 0.6, "energy": 0.5, "play": 0.4,
        }
        super().__init__(
            agent_id, persona,
            persist_dir=persist_dir,
            backend_config=_default_cs_config(kb_dir=kb_dir, llm=llm,
                                             serve_port=serve_port),
        )

    # —— 动作池 / 回复模板（离线可用，不依赖 LLM）——
    def action_pool(self) -> List[str]:
        return ["reply", "escalate"]

    def _render_reply(
        self, text: str, facts: List[Dict[str, Any]], mood: float
    ) -> str:
        """基于检索到的资料（含知识库）组织回复。

        没有资料就如实说不知道 —— 不编造，这是客服可信度的底线。
        （开了 LLM 时，这一步通常走不到，由 llm_responder 生成更自然的回复；
         但 LLM 失败时会回落到这里，保证永远有回应。）

        只依据"有来源的知识"（知识库 / 领域资料）作答，忽略纯对话记忆
        （episodic 闲聊不带 source，不应被当成客服用资料）。
        """
        knowledge = [f for f in facts if f.get("source")]
        if knowledge:
            top = knowledge[0]
            brief = (top.get("brief") or top.get("title") or "").strip()
            src = str(top.get("source", ""))
            answer = "关于您的问题，我们查到相关说明：%s" % brief
            if src.startswith("knowledge_base"):
                answer += "（资料来源：%s）" % src.split(":", 1)[-1]
            return answer
        return (
            "抱歉，我暂时没有查到关于这个问题的资料，已记录您的问题。"
            "您可以拨打我们的客服热线，或稍后再试，我们会尽快完善答案。"
        )

    # —— 业务便捷方法 ——
    def ingest_faq(self, items: List[Dict[str, Any]]) -> int:
        """把站点 FAQ / 文档喂进资料库（``ingest`` 的别名，一次即可、会落盘）。"""
        return self.ingest(items)

    def ask(
        self, text: str, session_id: str = "default",
        user_id: Optional[str] = None,
    ) -> str:
        """回答一个客户问题（等价于 ``handle``，语义更清晰）。"""
        return self.handle(text, session_id=session_id, user_id=user_id)

    def serve(self, host: str = "0.0.0.0", port: Optional[int] = None) -> None:
        """启动 HTTP 网关（站点 <iframe> / REST 接入）。"""
        super().serve(host=host, port=port or self._serve_port)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    kb_dir = "./cs_kb_demo"
    Path(kb_dir).mkdir(parents=True, exist_ok=True)
    cs = CustomerServiceAgent("demo-cs", kb_dir=kb_dir, serve_port=8080)

    # 1) 摄取站点资料（真实场景：从 CMS / 数据库 / 帮助中心同步）。
    cs.ingest_faq([
        {"title": "退货政策", "content": "商品签收后 7 天内可无理由退货，需保持吊牌完整。",
         "source": "faq", "tags": ["退货", "售后"]},
        {"title": "配送时效", "content": "现货 24 小时内发货，偏远地区 3-5 天送达。",
         "source": "faq", "tags": ["配送", "物流", "发货"]},
        {"title": "发票", "content": "下单时可勾选电子发票，次日发送至注册邮箱。",
         "source": "faq", "tags": ["发票", "财务"]},
    ])
    print("== 资料库已摄取，开始演示 ==")

    # 2) 模拟客户提问。
    for q in ["怎么退货？", "多久能发货？", "你们能开增值税发票吗？"]:
        print("客户：%s" % q)
        print("客服：%s" % cs.ask(q, session_id="cust-1"))
        print("-" * 40)

    # 3) 自学习验证：再问一次，资料库应已沉淀上一条 QA。
    kb = cs.plugins.get("knowledge_base")
    print("资料库统计：%s" % kb.stats())

    # 4) 可选：对外服务模式。
    if "--serve" in argv:
        print("启动网关：http://0.0.0.0:8080/ （Ctrl+C 退出）")
        try:
            cs.serve()
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            cs.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
