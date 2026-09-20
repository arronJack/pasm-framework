"""命令行入口。

    pasm-framework                    自检 + 用法（等价 selftest）
    pasm-framework selftest           框架自检
    pasm-framework version            版本
    pasm-framework plugins            列出内置插件与默认开关
    pasm-framework config [--preset X | --file f.json] [--env]   查看解析后的开关表
    pasm-framework doctor             环境体检（能不能跑、缺什么）
    pasm-framework new <dir> [--kind app|chatbot|game_npc] [--force]   生成项目
    pasm-framework serve [--port 8080] [--host 0.0.0.0] [--kb ./kb]   起一个演示客服

设计约束：只用标准库 ``argparse``，不引入 CLI 框架 —— 保证"装完就能跑"。
"""
from __future__ import annotations

import argparse
import sys

USAGE = """pasm-framework —— PASM 应用开发框架

用法:
  pasm-framework selftest                        框架自检
  pasm-framework version                         版本
  pasm-framework plugins                         列出内置插件与默认开关
  pasm-framework config [--preset X] [--file f]  查看解析后的开关表
  pasm-framework doctor                          环境体检
  pasm-framework new <目录> [--kind ...]         生成项目脚手架
  pasm-framework serve [--port 8080]             跑一个演示智能客服

新手建议顺序: new → 改 main.py → doctor → serve
文档: docs/tutorials/（快速上手 / 插件 / 客服 / LLM / 部署 / 游戏 NPC / 多语言）"""


def _cmd_plugins(_args) -> int:
    from .plugins.registry import builtin_plugins, default_config
    cfg = default_config()
    print("内置插件（共 %d 个）:" % len(builtin_plugins()))
    for name, cls in builtin_plugins().items():
        on = "开" if cfg.entry(name).get("enabled") else "关"
        doc = (cls.__doc__ or "").strip().splitlines()
        brief = doc[0] if doc else ""
        print("  [%s] %-16s %s" % (on, name, brief))
    print("\n开关方式: pasm_framework.load(preset_name=..., **overrides)"
          " 或环境变量 PASM_PLUGINS / PASM_KB_DIR / PASM_HTTP_PORT ...")
    return 0


def _cmd_config(args) -> int:
    from .config import describe, load, to_dict
    cfg = load(args.file, preset_name=args.preset, env=args.env)
    print("解析后的开关表（预设=%s 文件=%s 环境变量=%s）:"
          % (args.preset, args.file or "-", "是" if args.env else "否"))
    print("\n".join(describe(cfg)))
    if args.json:
        import json
        print(json.dumps(to_dict(cfg), ensure_ascii=False, indent=2))
    return 0


def _cmd_doctor(_args) -> int:
    """环境体检：把"跑不起来"的原因说清楚，而不是丢一个 traceback。"""
    import platform
    import tempfile
    from pathlib import Path

    ok = True

    def line(good: bool, msg: str, hint: str = "") -> None:
        nonlocal ok
        if not good:
            ok = False
        print("  %s %s%s" % ("v" if good else "x", msg,
                             ("   → %s" % hint) if (hint and not good) else ""))

    print("pasm-framework doctor")
    print("[1] 运行环境")
    v = sys.version_info
    line(v >= (3, 10), "Python %d.%d.%d（要求 >= 3.10）" % (v.major, v.minor, v.micro),
         "升级 Python 到 3.10+")
    line(True, "%s %s" % (platform.system(), platform.release()))

    print("[2] 依赖")
    try:
        import pasm_skills  # noqa: F401
        from pasm_skills import __version__ as skv  # type: ignore
        line(True, "pasm-skills %s 可导入" % skv)
    except Exception as ex:  # noqa: BLE001
        line(False, "pasm-skills 不可导入（%s）" % ex,
             "pip install pasm-skills>=0.5.1")
    from . import __version__
    line(True, "pasm-framework %s" % __version__)

    try:
        from .plugins.registry import builtin_plugins, default_config
        n = len(builtin_plugins())
        line(n >= 7, "内置插件 %d 个可加载" % n, "重装 pasm-framework")
    except Exception as ex:  # noqa: BLE001
        line(False, "插件库加载失败（%s）" % ex, "检查安装是否完整")

    print("[3] 可写性")
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "probe.txt"
            p.write_text("ok", encoding="utf-8")
        line(True, "临时目录可写")
    except Exception as ex:  # noqa: BLE001
        line(False, "临时目录不可写（%s）" % ex, "检查磁盘与权限")
    try:
        from .plugins.builtins.knowledge_base import KnowledgeBasePlugin
        kd = Path(tempfile.mkdtemp()) / "kb"
        kb = KnowledgeBasePlugin({"kb_dir": str(kd)})
        kb.ingest([{"title": "probe", "content": "probe", "source": "doctor"}])
        line(kb.stats()["total"] == 1, "知识库可读写（%s）" % kd)
    except Exception as ex:  # noqa: BLE001
        line(False, "知识库不可用（%s）" % ex, "检查 PASM_KB_DIR 权限")

    print("[4] 可选能力")
    import os
    provider = os.environ.get("PASM_LLM_PROVIDER")
    key = (os.environ.get("PASM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY"))
    if provider or key:
        line(True, "LLM 已配置（provider=%s, key=%s）"
             % (provider or "openai", "已设置" if key else "未设置"))
    else:
        line(True, "LLM 未配置 —— 不影响运行（走模板/资料库回复）")
    try:
        import yaml  # noqa: F401
        line(True, "pyyaml 可用（可读 .yaml 配置）")
    except Exception:  # noqa: BLE001
        line(True, "pyyaml 未安装 —— 用 .json 配置即可")

    print("[5] 插件装配")
    try:
        from .plugins.core import BasePlugin, build_manager
        from .plugins.registry import discover_plugins

        eps = discover_plugins()
        line(True, "entry-point 第三方插件 %d 个（group=pasm_framework.plugins）" % len(eps))

        class _Probe(BasePlugin):
            name = "_doctor_probe"

            def on_reply_final(self, ctx):     # pragma: no cover - 仅探针
                pass

        pm = build_manager({"_doctor_probe": {"enabled": True, "class": _Probe}})
        line("_doctor_probe" in pm.names(),
             "内联自定义插件可注册（backend_config 里写 class=）",
             "检查 BackendConfig 用法")
        cfg_typo = build_manager({"knowlege_base": {"enabled": True}})
        line(bool(cfg_typo.unknown()),
             "拼错的插件名会被记录（示例：%s）" % (cfg_typo.unknown() or "-"),
             "这行应为 v；若不是，unknown() 机制失效")
    except Exception as ex:  # noqa: BLE001
        line(False, "插件装配探测失败（%s）" % ex, "检查 plugins 目录是否完整")

    print("\n体检结论: %s" % ("全部通过，可以开始开发" if ok else "存在问题，见上面 x 项"))
    if ok:
        print("下一步: pasm-framework new myapp --kind chatbot")
    return 0 if ok else 1


def _cmd_new(args) -> int:
    from .scaffold import KINDS, create
    try:
        written = create(args.dir, kind=args.kind, name=args.name or "", force=args.force)
    except Exception as ex:  # noqa: BLE001
        print("生成失败：%s" % ex)
        return 1
    print("已在 %s 生成项目（模板 %s）：" % (args.dir, args.kind))
    for rel in written:
        print("  + %s" % rel)
    print("  + kb/            （知识库目录）")
    print("\n下一步:")
    print("  cd %s" % args.dir)
    print("  python main.py" + (" --serve" if args.kind == "chatbot" else ""))
    print("\n其他模板: %s" % ", ".join(KINDS))
    return 0


def _cmd_serve(args) -> int:
    import time

    from .demo import make_demo_app
    llm = None
    if args.llm_provider:
        llm = {"provider": args.llm_provider}
        if args.llm_model:
            llm["model"] = args.llm_model
        if args.llm_key:
            llm["api_key"] = args.llm_key
    app = make_demo_app(kb_dir=args.kb, llm=llm, host=args.host, port=args.port,
                        token=args.token)
    print("演示智能客服已启动")
    print("  对话界面: http://%s:%d/" % (args.host if args.host != "0.0.0.0" else "127.0.0.1", args.port))
    print("  REST 接口: POST /api/chat   {\"text\": \"怎么退货？\"}")
    print("  健康检查: GET  /healthz  ｜  插件: GET /api/plugins")
    if args.token:
        print("  已开启鉴权: 请求需带 Authorization: Bearer <token>")
    print("  嵌入站点: <iframe src='http://你的主机:%d/' width='420' height='620'></iframe>" % args.port)
    print("  Ctrl+C 退出")
    try:
        app.serve()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n已停止。")
        app.close()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "selftest"

    if cmd in ("selftest", "test", "self-test"):
        from . import selftest
        ok = selftest()
        if not argv:
            print()
            print(USAGE)
        return 0 if ok else 1
    if cmd in ("version", "v", "--version"):
        from . import __version__
        print("pasm-framework %s" % __version__)
        return 0
    if cmd in ("help", "-h", "--help"):
        print(USAGE)
        return 0

    parser = argparse.ArgumentParser(prog="pasm-framework", add_help=True,
                                     description="PASM 应用开发框架 CLI")
    sub = parser.add_subparsers(dest="sub")

    sub.add_parser("plugins", help="列出内置插件与默认开关")
    sub.add_parser("doctor", help="环境体检")

    p_cfg = sub.add_parser("config", help="查看解析后的开关表")
    p_cfg.add_argument("--preset", default=None,
                       help="场景预设: minimal/default/chatbot/game_npc/api/desktop")
    p_cfg.add_argument("--file", default=None, help="配置文件 (.json/.yaml)")
    p_cfg.add_argument("--env", action="store_true", help="叠加 PASM_* 环境变量")
    p_cfg.add_argument("--json", action="store_true", help="同时打印 JSON")

    p_new = sub.add_parser("new", help="生成项目脚手架")
    p_new.add_argument("dir", help="目标目录")
    p_new.add_argument("--kind", default="app",
                       help="模板: app / chatbot / game_npc（默认 app）")
    p_new.add_argument("--name", default="", help="项目名（写进 README）")
    p_new.add_argument("--force", action="store_true", help="覆盖已存在的同名文件")

    p_srv = sub.add_parser("serve", help="跑一个演示智能客服")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8080)
    p_srv.add_argument("--kb", default=None, help="知识库目录（默认 ~/.pasm_framework/kb）")
    p_srv.add_argument("--token", default=None, help="HTTP 鉴权令牌")
    p_srv.add_argument("--llm-provider", default=None,
                       help="openai / deepseek / ollama（不填则离线模式）")
    p_srv.add_argument("--llm-model", default=None)
    p_srv.add_argument("--llm-key", default=None)

    try:
        ns = parser.parse_args(argv)
    except SystemExit as ex:            # argparse 的报错也是退出
        return int(ex.code or 2)

    handler = {
        "plugins": _cmd_plugins,
        "config": _cmd_config,
        "doctor": _cmd_doctor,
        "new": _cmd_new,
        "serve": _cmd_serve,
    }.get(ns.sub)
    if handler is None:
        print(USAGE)
        return 2
    return handler(ns)


if __name__ == "__main__":
    raise SystemExit(main())
