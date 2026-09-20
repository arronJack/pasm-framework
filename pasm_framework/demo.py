"""开箱即用的演示应用 —— 让 ``pasm-framework serve`` 一条命令就能跑起来。

存在的意义
----------
"即插即用"最直观的证明是：装完包，一条命令，浏览器里就能对话。
本模块提供一个**零 LLM 也能回答**的智能客服实例（靠 ``knowledge_base``
就资料作答），供 CLI 的 ``serve`` 子命令与教程使用。

它不是生产代码 —— 生产请参考仓库 ``apps/customer_service.py`` 的完整形态。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import load
from .simple import SimpleApplication

#: 演示资料：故意覆盖"能答 / 答不上来"两类问题，方便观察护栏与兜底行为。
DEMO_FAQ: List[Dict[str, Any]] = [
    {"title": "退货政策",
     "content": "商品签收后 7 天内可无理由退货，需保持吊牌完整、不影响二次销售。",
     "source": "faq", "tags": ["退货", "退款", "售后"]},
    {"title": "换货流程",
     "content": "在订单详情页点「申请换货」，选择尺码/颜色后寄回，我们收到当天发出新品。",
     "source": "faq", "tags": ["换货", "售后"]},
    {"title": "配送时效",
     "content": "现货 24 小时内发货；偏远地区 3-5 天送达；支持顺丰加急。",
     "source": "faq", "tags": ["配送", "物流", "发货"]},
    {"title": "运费说明",
     "content": "单笔满 99 元包邮，未满收取 8 元运费；退货运费由我方承担。",
     "source": "faq", "tags": ["运费", "包邮"]},
    {"title": "发票",
     "content": "下单时可勾选电子发票，次日发送至注册邮箱；专票需联系客服登记。",
     "source": "faq", "tags": ["发票", "开票"]},
    {"title": "营业时间",
     "content": "在线客服时间为每天 9:00-21:00，节假日不休。",
     "source": "faq", "tags": ["时间", "客服"]},
]


class DemoAgent(SimpleApplication):
    """演示用智能客服（话术面向终端用户）。"""

    DEFAULT_UNKNOWN = "抱歉，我暂时没有查到相关资料。你可以换个说法再问我，或联系人工客服。"


def make_demo_app(
    *,
    kb_dir: Optional[str] = None,
    llm: Optional[Dict[str, Any]] = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    agent_id: str = "pasm-demo",
    preset_name: str = "chatbot",
    token: Optional[str] = None,
    teach: bool = True,
) -> DemoAgent:
    """构造演示应用（已导入 :data:`DEMO_FAQ`）。

    >>> from pasm_framework.demo import make_demo_app
    >>> app = make_demo_app(port=8099)
    >>> "退货" in app.ask("怎么退货？")
    True
    """
    gw: Dict[str, Any] = {"enabled": True, "config": {"host": host, "port": port}}
    if token:
        gw["config"]["token"] = token
    kb: Dict[str, Any] = {"enabled": True}
    if kb_dir:
        kb["config"] = {"kb_dir": kb_dir}
    cfg = load(
        preset_name=preset_name,
        knowledge_base=kb,
        web_gateway=gw,
        llm_responder={"enabled": bool(llm), "config": dict(llm or {})},
    )
    app = DemoAgent(
        agent_id,
        {"name": "小智", "role": "智能客服", "tone": "温暖、专业、耐心",
         "temper": 0.6, "energy": 0.5, "play": 0.4},
        backend_config=cfg,
    )
    if teach:
        app.teach(DEMO_FAQ)
    return app
