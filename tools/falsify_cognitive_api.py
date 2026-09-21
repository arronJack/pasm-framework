# -*- coding: utf-8 -*-
"""反例对照：故意改坏认知 HTTP API，确认端到端脚本**真的抓得住**。

端到端 20 项全绿，也可能只是"断言恒真"。这里把最关键的几处改坏，逐个确认变红，
跑完无条件还原。

用法::

    python tools/falsify_cognitive_api.py
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

GATEWAY = REPO / "pasm_framework" / "plugins" / "builtins" / "web_gateway.py"
COGAPI = REPO / "pasm_framework" / "plugins" / "builtins" / "cognitive_api.py"

#: (要验的断言名, 目标文件, 原文锚点, 改坏后的文本)
CASES = [
    # 反例 1：把 GET 侧的认知路由摘掉 —— 网关根本不该认识这个前缀。
    ("capabilities 可探测且报告可用", GATEWAY,
     "        elif _COG_PREFIX.rstrip(\"/\") in path or path.startswith(_COG_PREFIX):\n"
     "            self._cog(\"GET\")\n",
     ""),
    # 反例 2：把参数错误的 400 改成 200 —— 调用方会把"参数漏了"当成"没数据"。
    ("缺 event → 400（不能把参数错当成功）", COGAPI,
     "        except ValueError as ex:                  # 参数错 → 400（客户端可自行纠错）\n"
     "            return 400, {\"error\": str(ex), \"op\": op}",
     "        except ValueError as ex:\n"
     "            return 200, {\"error\": str(ex), \"op\": op}"),
]


def run() -> tuple[str, int]:
    env = dict(os.environ)
    extra = [str(REPO.parent / "pasm-skills"), str(REPO)]
    env["PYTHONPATH"] = os.pathsep.join(extra + [env.get("PYTHONPATH", "")])
    p = subprocess.run([sys.executable, str(HERE / "e2e_cognitive_api.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=str(REPO))
    return (p.stdout or "") + (p.stderr or ""), p.returncode


def main() -> int:
    originals = {f: io.open(f, encoding="utf-8", newline="").read()
                 for f in {GATEWAY, COGAPI}}

    out, rc = run()
    if rc != 0 or "0 项失败" not in out:
        print("[中止] 基线不是全绿，先修好再谈反例。rc=%s" % rc)
        print(out[-600:])
        return 2
    print("[基线] 端到端全绿 ✓\n")

    bad = 0
    try:
        for name, target, old, new in CASES:
            base = originals[target]
            if old not in base:
                print("[跳过] 锚点没命中（代码改过？）: %s" % name)
                bad += 1
                continue
            io.open(target, "w", encoding="utf-8", newline="").write(
                base.replace(old, new, 1))
            out2, rc2 = run()
            caught = (rc2 != 0) and (name in out2)
            print("%s %s  -> rc=%s 被抓=%s"
                  % ("[PASS]" if caught else "[FAIL]", name, rc2, caught))
            if not caught:
                bad += 1
                for line in out2.splitlines():
                    if "x " in line or "结果" in line:
                        print("       " + line.strip())
            io.open(target, "w", encoding="utf-8", newline="").write(base)
    finally:
        for f, txt in originals.items():
            io.open(f, "w", encoding="utf-8", newline="").write(txt)

    out3, rc3 = run()
    restored = (rc3 == 0) and ("0 项失败" in out3)
    print("\n[还原] 回到全绿=%s" % restored)
    if not restored:
        print(out3[-600:])
        bad += 1

    print("\n结论：%s" % ("全部反例都被抓住 ✓" if bad == 0 else "%d 处没抓住 ✗" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
