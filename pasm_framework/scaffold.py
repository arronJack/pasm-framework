"""项目脚手架 —— ``pasm-framework new`` 的实现。

目标：从"读文档 20 分钟"变成"一条命令拿到能跑的项目"。
生成的内容刻意保持**零第三方依赖**（只依赖 pasm-framework 本身），
所以 ``pip install pasm-framework`` 之后立刻就能 ``python main.py``。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from .errors import FrameworkError

KINDS = ("app", "chatbot", "game_npc")

_MAIN_APP = '''"""最小 AI 应用 —— pasm-framework 脚手架生成。

跑起来：python main.py            （离线，用内置知识库+模板回复）
接 LLM：PASM_LLM_API_KEY=sk-xxx PASM_LLM_PROVIDER=deepseek python main.py
"""
from pasm_framework import SimpleApplication, capability, load


class MyApp(SimpleApplication):
    """把每个能力写成一个方法，用 @capability 声明触发词。"""

    @capability(keywords=("帮助", "help"), description="显示帮助")
    def help(self, text):
        return "我能回答资料库里的问题。试着问我：营业时间 / 怎么退货"

    @capability(keywords=("时间", "几点"), description="营业时间")
    def hours(self, text):
        return "我们的营业时间是每天 9:00 - 21:00。"


def main():
    # preset 决定"开哪些插件"：minimal / default / chatbot / api / desktop
    cfg = load(preset_name="default", knowledge_base={
        "enabled": True, "config": {"kb_dir": "./kb"}})

    app = MyApp("my-app", {"name": "小智", "role": "智能助手"},
                backend_config=cfg)

    # 导入你的资料（一次性；之后落盘复用）
    app.teach([
        {"title": "退货政策", "content": "签收后 7 天内可无理由退货。",
         "source": "faq", "tags": ["退货"]},
    ])

    for q in ["怎么退货？", "你们几点下班？"]:
        print("我：%s" % q)
        print("AI：%s" % app.ask(q))
        print("-" * 40)


if __name__ == "__main__":
    main()
'''

_MAIN_CHATBOT = '''"""站点智能客服 —— pasm-framework 脚手架生成。

跑起来（控制台）：python main.py
跑起来（对外服务）：python main.py --serve     → 浏览器打开 http://127.0.0.1:8080/
嵌入站点：<iframe src="http://你的主机:8080/" width="420" height="620"></iframe>

接 LLM（可选）：PASM_LLM_API_KEY=sk-xxx PASM_LLM_PROVIDER=deepseek python main.py
"""
import sys

from pasm_framework import SimpleApplication, load


class CustomerService(SimpleApplication):
    """零 LLM 也能"就资料作答、查不到如实说不知道"。"""

    # 检索不到资料时的话术（面向用户，别写开发提示）
    DEFAULT_UNKNOWN = "抱歉，我暂时没有查到相关资料。你可以换个说法，或联系人工客服 400-000-0000。"


def build():
    cfg = load(
        preset_name="chatbot",                 # 护栏收紧 + 开 HTTP 网关
        knowledge_base={"enabled": True, "config": {"kb_dir": "./kb"}},
        web_gateway={"enabled": True, "config": {"host": "0.0.0.0", "port": 8080}},
    )
    app = CustomerService(
        "shop-cs", {"name": "小智", "role": "智能客服", "tone": "温暖、专业、耐心"},
        backend_config=cfg,
    )

    # ====== 把站点资料喂进来（FAQ / 帮助中心 / 商品说明）======
    # 真实项目里可以从 CMS/数据库/接口拉，然后调 app.teach(...)
    app.teach([
        {"title": "退货政策", "content": "商品签收后 7 天内可无理由退货，需保持吊牌完整。",
         "source": "faq", "tags": ["退货", "售后"]},
        {"title": "配送时效", "content": "现货 24 小时内发货，偏远地区 3-5 天送达。",
         "source": "faq", "tags": ["配送", "物流", "发货"]},
        {"title": "发票", "content": "下单时可勾选电子发票，次日发送至注册邮箱。",
         "source": "faq", "tags": ["发票"]},
        {"title": "营业时间", "content": "客服在线时间 9:00-21:00，节假日不休。",
         "source": "faq", "tags": ["时间"]},
    ])
    return app


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app = build()

    if "--serve" in argv:
        print("网关已启动：http://0.0.0.0:8080/  （Ctrl+C 退出）")
        print("嵌入站点：<iframe src='http://你的主机:8080/' width='420' height='620'></iframe>")
        try:
            app.serve()
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            app.close()
        return 0

    for q in ["怎么退货？", "多久能发货？", "你们几点上班？",
              "能开增值税专用发票吗？", "你们老板是谁？"]:
        print("客户：%s" % q)
        print("客服：%s" % app.ask(q, session_id="demo-1"))
        print("-" * 50)
    print("资料库统计：%s" % app.plugins.get("knowledge_base").stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_MAIN_NPC = '''"""游戏 NPC —— pasm-framework 脚手架生成（离线、零 LLM）。

PASM 的差异点在"身份"：NPC 有性格 / 情绪 / 记忆 / 会被玩家反馈塑形。
跑起来：python main.py

要点
----
· ``observe`` 写记忆，``feel`` 改情绪，``feedback`` 让行为被玩家塑形；
· 情绪会影响 NPC 的说话温度（warmth 插件）；
· 状态落盘在 persist_dir，重启后性格/关系还在。
"""
from pasm_framework import SimpleApplication, capability, load


class Innkeeper(SimpleApplication):
    """酒馆老板：记得熟客，被夸奖更热情，被欺负会冷淡。"""

    @capability(keywords=("买", "酒", "来一"), description="买酒")
    def buy(self, text):
        self.observe(title="玩家买酒", brief=text, tags=["交易"], salience=3)
        self.feel(0.2)
        return "给你满上！%s" % ("今天算你便宜点。" if self.mood > 0.3 else "")

    @capability(keywords=("聊", "说说", "故事"), description="闲聊")
    def chat_about(self, text):
        hits = self.recall(text, k=2)
        if hits:
            return "这个啊……我记得：%s" % hits[0].get("brief", "")
        return "唉，最近不太平，没什么好说的。"

    @capability(keywords=("打", "揍", "滚"), description="敌对行为")
    def hostile(self, text):
        self.feel(-0.5)
        self.observe(title="玩家挑衅", brief=text, tags=["敌意"], salience=4)
        return "……你再这样我就叫卫兵了。" if self.mood < -0.3 else "别闹。"


def main():
    cfg = load(preset_name="game_npc")          # 离线优先，不接 LLM
    npc = Innkeeper("innkeeper-01", {
        "name": "老橡", "role": "酒馆老板",
        "tone": "粗嗓门但热心", "temper": 0.7, "energy": 0.4, "play": 0.6,
    }, backend_config=cfg)

    script = ["打二两酒", "说说镇上的事", "揍你一顿", "打二两酒"]
    for line in script:
        reply = npc.ask(line, session_id="player-1")
        print("玩家：%s" % line)
        print("老橡：%s   （情绪 %.2f）" % (reply, npc.mood))
        print("-" * 50)


if __name__ == "__main__":
    main()
'''

_CONFIG_JSON = '''{
  "plugins": {
    "safety":         {"enabled": true,  "config": {"mode": "warn"}},
    "sessions":       {"enabled": true,  "config": {"max_history": 20}},
    "knowledge_base": {"enabled": true,  "config": {"kb_dir": "./kb"}},
    "warmth":         {"enabled": true,  "config": {}},
    "observability":  {"enabled": true,  "config": {}},
    "llm_responder":  {"enabled": false, "config": {}},
    "web_gateway":    {"enabled": false, "config": {"host": "127.0.0.1", "port": 8080}}
  }
}
'''

_README = """# {name}

由 `pasm-framework new` 生成（模板：**{kind}**）。

## 跑起来

```bash
pip install pasm-framework
python main.py{serve_hint}
```

## 换个配置

开关表在 `config.json`（也可用环境变量，见下）。代码里这样加载：

```python
from pasm_framework import load
cfg = load("config.json", env=True)
app = MyApp("my-app", {{"name": "小智"}}, backend_config=cfg)
```

环境变量（优先级高于 `config.json`）：

| 变量 | 作用 |
| --- | --- |
| `PASM_PLUGINS` | `none` / `default` / `safety,sessions,...` |
| `PASM_KB_DIR` | 知识库目录 |
| `PASM_SAFETY_MODE` | `warn` 或 `block` |
| `PASM_LLM_PROVIDER` / `PASM_LLM_MODEL` / `PASM_LLM_API_KEY` | 接入 LLM |
| `PASM_HTTP_HOST` / `PASM_HTTP_PORT` / `PASM_HTTP_TOKEN` | HTTP 网关与鉴权 |

## 下一步

- 教程：`docs/tutorials/`（从快速上手到多语言接入）
- 自检：`pasm-framework doctor`
- 看插件：`pasm-framework plugins`
"""

_REQ = """pasm-framework>=0.2.1
# 可选：接 LLM 时不需要额外依赖（内置用标准库 urllib）
# 可选：读 .yaml 配置时需要
# pyyaml>=6
"""

_TEMPLATES: Dict[str, Tuple[str, str]] = {
    "app": (_MAIN_APP, ""),
    "chatbot": (_MAIN_CHATBOT, " --serve"),
    "game_npc": (_MAIN_NPC, ""),
}


def render(kind: str, name: str) -> Dict[str, str]:
    """返回 ``{相对路径: 内容}``（纯函数，便于测试与预览）。"""
    if kind not in _TEMPLATES:
        raise FrameworkError(
            "未知模板 %r；可用：%s" % (kind, ", ".join(KINDS)))
    main_py, serve_hint = _TEMPLATES[kind]
    return {
        "main.py": main_py,
        "config.json": _CONFIG_JSON,
        "requirements.txt": _REQ,
        "README.md": _README.format(name=name, kind=kind, serve_hint=serve_hint),
    }


def create(target_dir: str, *, kind: str = "app", name: str = "",
           force: bool = False) -> List[str]:
    """在 ``target_dir`` 生成项目；返回写出的相对路径列表。

    ``force=False`` 时，若目录已存在同名文件 → 报错，不覆盖用户内容。
    """
    root = Path(target_dir)
    files = render(kind, name or root.name or "my-app")
    if root.exists() and not root.is_dir():
        raise FrameworkError("目标已存在且不是目录：%s" % root)
    if not force:
        clash = [rel for rel in files if (root / rel).exists()]
        if clash:
            raise FrameworkError(
                "目标目录已存在同名文件：%s（加 --force 覆盖）" % ", ".join(clash))
    root.mkdir(parents=True, exist_ok=True)
    (root / "kb").mkdir(exist_ok=True)
    written: List[str] = []
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written.append(rel)
    return written
