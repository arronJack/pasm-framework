# -*- coding: utf-8 -*-
"""认知 HTTP API 端到端验证 —— **真起 HTTP 服务**，真发请求，断言可观察结果。

为什么不满足于模块级自检
------------------------
`cognitive_api.selftest()` 只直接调 `dispatch()`，**覆盖不到**：
  · 网关的路由分派（`/api/cog/*` 有没有真的被接上）
  · 鉴权作用域（认知接口是否真的落在管理作用域）
  · JSON 编解码与状态码映射
  · 插件装配（`backend_config` 开没开得起来）

所以必须起真服务、按真实 HTTP 客户端发请求。判据只看**响应体与状态码**，
不看"函数返回了"。

用法::

    python tools/e2e_cognitive_api.py
    # 退出码 0 = 全部通过
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (str(REPO.parent / "pasm-skills"), str(REPO)):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

TOKEN = "e2e-secret-token"
OK = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print("  v %s" % name)
    else:
        FAIL += 1
        print("  x %s%s" % (name, ("  <- " + detail) if detail else ""))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(method: str, url: str, body=None, token: str | None = TOKEN):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"_raw": raw[:200]}


def main() -> int:                                    # noqa: C901
    print("认知 HTTP API 端到端验证")
    print("-" * 64)

    from pasm_framework import SimpleApplication

    port = free_port()
    tmp = tempfile.mkdtemp(prefix="pasm-cog-e2e-")
    app = SimpleApplication(
        agent_id="clinic",
        persona={"name": "分诊助手", "tone": "简洁"},
        persist_dir=os.path.join(tmp, "app"),
        backend_config={
            "knowledge_base": {"enabled": True,
                               "config": {"kb_dir": os.path.join(tmp, "kb")}},
            "web_gateway": {"enabled": True, "config": {
                "host": "127.0.0.1", "port": port, "token": TOKEN,
                "cognitive_persist_dir": os.path.join(tmp, "cog"),
            }},
        },
    )
    base = "http://127.0.0.1:%d" % port
    try:
        app.serve()
        print("  服务已起：%s\n" % base)

        # ---------- 公共探针（免鉴权）
        st, _ = req("GET", base + "/healthz", token=None)
        check("/healthz 免鉴权可访问", st == 200, "status=%s" % st)

        # ---------- 鉴权红线：认知接口必须落在管理作用域
        st, _ = req("GET", base + "/api/cog/status", token=None)
        check("★ 无令牌调认知接口 → 401（不是公开作用域）", st == 401,
              "status=%s" % st)
        st, _ = req("GET", base + "/api/cog/status", token="wrong")
        check("错误令牌 → 401", st == 401, "status=%s" % st)

        # ---------- 能力探测
        st, d = req("GET", base + "/api/cog/capabilities")
        check("capabilities 可探测且报告可用",
              st == 200 and d.get("available") is True, str(d)[:160])
        check("操作清单覆盖 13 项", len(d.get("operations", [])) == 13,
              str(d.get("operations")))

        # ---------- 写入 → 检索（真落盘）
        st, d = req("POST", base + "/api/cog/observe", {
            "agent_id": "p1", "title": "对青霉素过敏",
            "brief": "既往用药后出现皮疹", "tags": ["过敏", "青霉素"], "salience": 5})
        check("observe 写入成功", st == 200 and d.get("ok") is True, str(d)[:160])

        st, d = req("GET", base + "/api/cog/recall?agent_id=p1&query=%E8%BF%87%E6%95%8F&k=5")
        titles = [h.get("title") for h in d.get("hits", [])]
        check("recall 能检索到自己刚写的记忆",
              st == 200 and any("青霉素" in (t or "") for t in titles),
              "hits=%s" % titles)

        # ---------- 隔离反例：另一个 agent 不该看到 p1 的记忆
        req("POST", base + "/api/cog/observe",
            {"agent_id": "p2", "title": "对磺胺过敏", "tags": ["过敏"], "salience": 5})
        st, d2 = req("GET", base + "/api/cog/recall?agent_id=p2&query=%E8%BF%87%E6%95%8F")
        t2 = [h.get("title") for h in d2.get("hits", [])]
        check("★ 跨 agent 隔离：p2 看不到 p1 的记忆",
              any("磺胺" in (t or "") for t in t2)
              and not any("青霉素" in (t or "") for t in t2), "p2=%s" % t2)

        # ---------- 情绪 / 反馈 / 人格
        st, d = req("POST", base + "/api/cog/feel",
                    {"agent_id": "p1", "event": "被患者感谢", "valence": 0.9})
        check("feel 生效并返回 mood", st == 200 and isinstance(d.get("mood"), (int, float)),
              str(d)[:160])

        st, d = req("POST", base + "/api/cog/act",
                    {"agent_id": "p1", "candidates": ["listen", "ask"]})
        check("act 只从候选池里选", d.get("chosen") in ("listen", "ask"), str(d)[:160])
        st, d = req("POST", base + "/api/cog/feedback",
                    {"agent_id": "p1", "kind": "praise", "action": d.get("chosen")})
        check("feedback 带 action 时无警告",
              st == 200 and d.get("warning") is None, str(d)[:160])

        st, d = req("POST", base + "/api/cog/persona",
                    {"agent_id": "p1", "persona": {"name": "全科医生"}})
        check("persona 合并式更新", d.get("persona", {}).get("name") == "全科医生"
              and "tone" in d.get("persona", {}), str(d)[:160])

        # ---------- 状态
        st, d = req("GET", base + "/api/cog/status?agent_id=p1")
        check("status 含档位", st == 200 and "tier" in d, str(list(d))[:160])
        check("status 报告认知层已启用", bool(d.get("cognition", {}).get("enabled")),
              str(d.get("cognition"))[:160])

        # ---------- 参数错必须 400，不能静默 200
        st, _ = req("POST", base + "/api/cog/feel", {"agent_id": "p1", "event": ""})
        check("★ 缺 event → 400（不能把参数错当成功）", st == 400, "status=%s" % st)
        st, _ = req("POST", base + "/api/cog/feedback", {"agent_id": "p1", "kind": "xx"})
        check("非法 kind → 400", st == 400, "status=%s" % st)

        # ---------- 未知操作与既有路由
        st, d = req("GET", base + "/api/cog/nosuch")
        check("未知操作 → 404 且列出可用操作",
              st == 404 and "operations" in d, str(d)[:160])
        st, _ = req("GET", base + "/api/summary")
        check("原有 /api/summary 未被影响", st == 200, "status=%s" % st)
        st, _ = req("GET", base + "/api/kb/stats")
        check("原有 /api/kb/stats 未被影响", st == 200, "status=%s" % st)

        # ---------- 落盘
        st, d = req("POST", base + "/api/cog/save", {})
        check("save 落盘至少一个 agent", len(d.get("saved", [])) >= 1, str(d)[:160])
    finally:
        try:
            app.close()
        except Exception as ex:                        # noqa: BLE001
            print("  (close 异常：%s)" % ex)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 64)
    print("结果：%d 项通过，%d 项失败" % (OK, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
