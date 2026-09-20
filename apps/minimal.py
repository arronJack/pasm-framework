"""最小应用示例 —— 展示 pasm-framework 的最低上手成本。

对比一下"不用框架"要写什么：会话隔离、检索、护栏、脱敏、指标、HTTP 服务…
这里全部由后端开关提供，业务代码只有能力 + 资料两部分。

跑起来::

    python -m apps.minimal                # 控制台对话
    python -m apps.minimal --serve        # 起 HTTP 服务（http://127.0.0.1:8080/）
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from pasm_framework import SimpleApplication, capability, load

FAQ: List[Dict[str, Any]] = [
    {"title": "营业时间", "content": "每天 9:00-21:00，节假日不休。",
     "source": "faq", "tags": ["时间", "几点", "上班"]},
    {"title": "退货政策", "content": "签收后 7 天内可无理由退货，需保持吊牌完整。",
     "source": "faq", "tags": ["退货", "退款", "售后"]},
    {"title": "配送时效", "content": "现货 24 小时内发货，偏远地区 3-5 天送达。",
     "source": "faq", "tags": ["发货", "物流", "配送"]},
]


class MinimalApp(SimpleApplication):
    """业务代码就这么多：两个能力 + 一份资料。"""

    @capability(keywords=("人工", "转人工", "客服电话"), description="转人工")
    def human(self, text: str) -> str:
        return "正在为你转接人工客服（工作时间 9:00-21:00）。"

    @capability(keywords=("投诉", "差评"), description="投诉受理")
    def complaint(self, text: str) -> str:
        self.observe(title="客户投诉", brief=text, tags=["投诉"], salience=4)
        return "非常抱歉给你带来不好的体验，已记录你的反馈，会有专人跟进。"


def build(kb_dir: str, *, port: int = 8080,
          persist_dir: str | None = None) -> MinimalApp:
    """构造应用。

    ``kb_dir`` / ``persist_dir`` 由调用方显式给出 —— 演示脚本（``main``）
    用临时目录，避免在仓库里留下 ``minimal_kb/`` 这类运行时产物。
    你自己的项目里换成 ``./kb`` 之类的固定路径即可。
    """
    cfg = load(
        preset_name="chatbot",
        knowledge_base={"enabled": True, "config": {"kb_dir": kb_dir}},
        web_gateway={"enabled": True, "config": {"host": "127.0.0.1", "port": port}},
    )
    app = MinimalApp(
        "minimal-app",
        {"name": "小智", "role": "智能助手", "tone": "简洁、友好"},
        persist_dir=persist_dir,
        backend_config=cfg,
    )
    app.teach(FAQ)
    return app


def main(argv: List[str] | None = None) -> int:
    import tempfile

    argv = list(sys.argv[1:] if argv is None else argv)
    tmp = tempfile.mkdtemp(prefix="pasm-minimal-")
    app = build(kb_dir=tmp + "/kb", persist_dir=tmp + "/agent")

    if "--serve" in argv:
        print("服务已启动：http://127.0.0.1:8080/  （Ctrl+C 退出）")
        try:
            app.serve()
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            app.close()
        return 0

    for q in ["你们几点上班？", "怎么退货？", "我要投诉", "转人工", "你们老板是谁？"]:
        print("我：%s" % q)
        print("AI：%s" % app.ask(q, session_id="demo"))
        print("-" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
