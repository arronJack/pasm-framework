"""命令行入口：pasm-framework selftest / version。

用法：
    python -m pasm_framework selftest
    python -m pasm_framework version
    pasm-framework selftest        # 安装后等价命令
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "selftest"
    if cmd in ("selftest", "test", "self-test"):
        from . import selftest
        ok = selftest()
        return 0 if ok else 1
    if cmd in ("version", "v", "--version"):
        from . import __version__
        print("pasm-framework %s" % __version__)
        return 0
    print("用法: pasm-framework [selftest|version]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
