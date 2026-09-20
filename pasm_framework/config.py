"""配置系统 —— 让"后端选择是否使用某插件"能来自预设 / 文件 / 环境变量 / 代码。

为什么需要
----------
v0.2.0 的开关表只能写在 Python 代码里（``BaseApplication(backend_config={...})``），
部署时想改一个端口、换一个模型，都得改代码再发版。本模块让同一份应用可以：

  · 本地开发   —— ``load(preset="chatbot")``
  · 部署上线   —— ``load("server.json", env=True)`` 或直接给环境变量
  · 单元测试   —— ``load(preset="minimal")``（全关，行为退化为 v0.1.0）

合并优先级（后者覆盖前者）
--------------------------
    preset  <  file(source)  <  env  <  overrides(显式入参)

只依赖标准库；``yaml`` 是可选加速项（装了就能读 ``.yaml/.yml``，没装则提示改用 JSON）。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .errors import FrameworkError
from .plugins.core import BackendConfig

PLUGIN_NAMES: List[str] = [
    "safety", "sessions", "knowledge_base", "warmth",
    "observability", "llm_responder", "web_gateway",
]


def _all(enabled: bool, **cfg) -> Dict[str, Any]:
    return {"enabled": enabled, "config": dict(cfg)}


#: 场景预设。每个预设都**列全 7 个插件**——未列出的插件会被视为"关闭"，
#: 写全可以避免"我明明没关它，它却没了"的困惑。
PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    # 全关：行为退回 v0.1.0（能力路由 → 回落 chat）。测试与嵌入式场景用。
    "minimal": {n: _all(False) for n in PLUGIN_NAMES},

    # 与框架默认一致：基础/安全能力开，LLM 与网关关。
    "default": {
        "safety": _all(True, mode="warn"),
        "sessions": _all(True),
        "knowledge_base": _all(True),
        "warmth": _all(True),
        "observability": _all(True),
        "llm_responder": _all(False),
        "web_gateway": _all(False),
    },

    # 对外站点智能客服：护栏收紧为 block（面向公众，宁可拦错也别放行）。
    "chatbot": {
        "safety": _all(True, mode="block"),
        "sessions": _all(True, max_history=20),
        "knowledge_base": _all(True),
        "warmth": _all(True),
        "observability": _all(True),
        "llm_responder": _all(False),
        "web_gateway": _all(True, host="0.0.0.0", port=8080),
    },

    # 游戏 NPC：离线优先（不接 LLM），保留情绪润色与会话内记忆。
    "game_npc": {
        "safety": _all(True, mode="warn"),
        "sessions": _all(True, max_history=12),
        "knowledge_base": _all(True),
        "warmth": _all(True),
        "observability": _all(False),
        "llm_responder": _all(False),
        "web_gateway": _all(False),
    },

    # 纯 API 服务：回复要"干净"（不润色），护栏收紧，暴露 HTTP。
    "api": {
        "safety": _all(True, mode="block"),
        "sessions": _all(True, max_history=20),
        "knowledge_base": _all(True),
        "warmth": _all(False),
        "observability": _all(True),
        "llm_responder": _all(False),
        "web_gateway": _all(True, host="127.0.0.1", port=8080),
    },

    # 桌面应用内嵌：只监听本机，避免把服务暴露到局域网。
    "desktop": {
        "safety": _all(True, mode="warn"),
        "sessions": _all(True, max_history=30),
        "knowledge_base": _all(True),
        "warmth": _all(True),
        "observability": _all(False),
        "llm_responder": _all(False),
        "web_gateway": _all(True, host="127.0.0.1", port=8765),
    },
}


def preset(name: str) -> Dict[str, Dict[str, Any]]:
    """取一份场景预设的**副本**（改它不会污染全局预设）。"""
    if name not in PRESETS:
        raise FrameworkError(
            "未知预设 %r；可用：%s" % (name, ", ".join(sorted(PRESETS)))
        )
    return copy.deepcopy(PRESETS[name])


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """两层深合并：``{"a":{"enabled":True,"config":{"k":1}}}`` 级别的覆盖。

    只合并到 ``enabled`` / ``config`` 这一层，不再往下钻 ——
    这样"我只想改 config.port"不会把同插件其它 config 键抹掉。
    """
    out = copy.deepcopy(base)
    for name, spec in (over or {}).items():
        if not isinstance(spec, dict):
            continue
        cur = out.setdefault(name, {"enabled": False, "config": {}})
        if "enabled" in spec:
            cur["enabled"] = bool(spec["enabled"])
        cfg = spec.get("config")
        if isinstance(cfg, dict):
            merged = dict(cur.get("config") or {})
            merged.update(cfg)
            cur["config"] = merged
    return out


# ---------------------------------------------------------------- 文件

def from_file(path: Union[str, Path]) -> Dict[str, Dict[str, Any]]:
    """从 JSON / YAML 读取开关表。

    期望结构（``plugins`` 键可省略，直接给插件名也行）::

        {"plugins": {"web_gateway": {"enabled": true, "config": {"port": 9000}}}}
    """
    p = Path(path)
    if not p.exists():
        raise FrameworkError("配置文件不存在：%s" % p)
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except Exception as ex:  # noqa: BLE001
            raise FrameworkError(
                "读取 %s 需要 pyyaml（pip install pyyaml），或改用 .json 配置。" % p
            ) from ex
        data = yaml.safe_load(text) or {}
    else:
        try:
            data = json.loads(text or "{}")
        except Exception as ex:  # noqa: BLE001
            raise FrameworkError("配置文件不是合法 JSON：%s（%s）" % (p, ex)) from ex
    if not isinstance(data, dict):
        raise FrameworkError("配置文件顶层必须是对象：%s" % p)
    plugins = data.get("plugins")
    return plugins if isinstance(plugins, dict) else data


# ---------------------------------------------------------------- 环境变量

def from_env(prefix: str = "PASM_") -> Dict[str, Dict[str, Any]]:
    """把环境变量翻译成开关表覆盖。

    支持（值非空才生效）::

        PASM_PLUGINS=none|default|a,b,c      只启用列出的插件
        PASM_KB_DIR=/data/kb                 知识库目录
        PASM_SAFETY_MODE=warn|block
        PASM_LLM_PROVIDER=deepseek|openai|ollama
        PASM_LLM_MODEL=deepseek-chat
        PASM_LLM_BASE_URL=https://...        自建/代理网关
        PASM_LLM_API_KEY=sk-...              （也接受 OPENAI_API_KEY 等）
        PASM_HTTP_HOST=0.0.0.0
        PASM_HTTP_PORT=8080
        PASM_HTTP_TOKEN=***                  网关 Bearer 鉴权令牌
    """
    e = os.environ
    out: Dict[str, Dict[str, Any]] = {}

    def put(plugin: str, key: str, value: Any, *, enable: bool = False) -> None:
        spec = out.setdefault(plugin, {"config": {}})
        if enable:
            spec["enabled"] = True
        spec["config"][key] = value

    def g(name: str) -> Optional[str]:
        v = e.get(prefix + name)
        return v if v else None

    raw_plugins = g("PLUGINS")
    if raw_plugins is not None:
        if raw_plugins.strip().lower() in ("none", "off", ""):
            for n in PLUGIN_NAMES:
                out[n] = {"enabled": False}
        else:
            keep = {s.strip() for s in raw_plugins.split(",") if s.strip()}
            for n in PLUGIN_NAMES:
                out[n] = {"enabled": n in keep}

    if g("KB_DIR"):
        put("knowledge_base", "kb_dir", g("KB_DIR"), enable=True)
    if g("SAFETY_MODE"):
        put("safety", "mode", g("SAFETY_MODE"), enable=True)

    llm_provider = g("LLM_PROVIDER")
    llm_key = g("LLM_API_KEY")
    if llm_provider or llm_key or g("LLM_MODEL") or g("LLM_BASE_URL"):
        # 只要配了任一项，就认为用户想开 LLM（默认关是为了"没配就别联网"）。
        if llm_provider:
            put("llm_responder", "provider", llm_provider)
        if g("LLM_MODEL"):
            put("llm_responder", "model", g("LLM_MODEL"))
        if g("LLM_BASE_URL"):
            put("llm_responder", "base_url", g("LLM_BASE_URL"))
        if llm_key:
            put("llm_responder", "api_key", llm_key)
        out.setdefault("llm_responder", {"config": {}})["enabled"] = True

    if g("HTTP_HOST"):
        put("web_gateway", "host", g("HTTP_HOST"))
    if g("HTTP_PORT"):
        try:
            put("web_gateway", "port", int(g("HTTP_PORT") or 8080))
        except ValueError:
            raise FrameworkError("PASM_HTTP_PORT 必须是整数：%r" % g("HTTP_PORT"))
    if g("HTTP_TOKEN"):
        put("web_gateway", "token", g("HTTP_TOKEN"))
    if any(k in out.get("web_gateway", {}).get("config", {})
           for k in ("host", "port", "token")):
        out.setdefault("web_gateway", {"config": {}})["enabled"] = True

    return out


# ---------------------------------------------------------------- 统一入口

def load(
    source: Optional[Union[str, Path, Dict[str, Any]]] = None,
    *,
    preset_name: Optional[str] = None,
    env: bool = False,
    env_prefix: str = "PASM_",
    **overrides: Any,
) -> BackendConfig:
    """把预设 / 文件 / 环境变量 / 显式覆盖合成一个 :class:`BackendConfig`。

    参数
    ----
    source : dict | path | None
        开关表本体；传路径则按后缀读 JSON/YAML。
    preset_name : str | None
        场景预设名（``minimal`` / ``default`` / ``chatbot`` / ``game_npc`` /
        ``api`` / ``desktop``）。缺省 = ``default``。
    env : bool
        是否叠加环境变量。
    **overrides
        单个插件的覆盖，如 ``load("api", web_gateway={"enabled": True,
        "config": {"port": 9000}})``。

    用法::

        from pasm_framework import load
        cfg = load(preset_name="chatbot", env=True, web_gateway={
            "enabled": True, "config": {"port": 9000}})
        app = MyApp("demo", {"name": "小智"}, backend_config=cfg)
    """
    data = preset(preset_name or "default")
    if source is not None:
        file_data = source if isinstance(source, dict) else from_file(source)
        data = _deep_merge(data, file_data)
    if env:
        data = _deep_merge(data, from_env(env_prefix))
    if overrides:
        data = _deep_merge(data, overrides)
    return BackendConfig(plugins=data)


def to_dict(cfg: BackendConfig) -> Dict[str, Any]:
    """把 ``BackendConfig`` 还原成可序列化的 dict（落盘 / 展示用）。"""
    plugins: Dict[str, Any] = {}
    for name in PLUGIN_NAMES:
        e = cfg.plugins.get(name)
        if e is None:
            continue
        plugins[name] = {"enabled": bool(e.get("enabled", False)),
                         "config": dict(e.get("config") or {})}
    return {"plugins": plugins}


def save(cfg: BackendConfig, path: Union[str, Path]) -> Path:
    """写出一份 JSON 配置（可作为部署模板）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(to_dict(cfg), ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


def describe(cfg: BackendConfig) -> List[str]:
    """生成人类可读的开关清单（``doctor`` / CLI 用）。"""
    lines: List[str] = []
    for name in PLUGIN_NAMES:
        e = cfg.plugins.get(name) or {"enabled": False, "config": {}}
        on = "开" if e.get("enabled") else "关"
        cfgd = e.get("config") or {}
        detail = ""
        if cfgd:
            # 密钥类只显示"已设置"，不泄露内容
            safe = {k: ("***" if "key" in k or "token" in k else v)
                    for k, v in cfgd.items()}
            detail = "  " + json.dumps(safe, ensure_ascii=False)
        lines.append("  [%s] %-16s%s" % (on, name, detail))
    return lines
