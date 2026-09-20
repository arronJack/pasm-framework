# 03 · 插件与开关

这一篇讲清你说的"**用户可在后端选择是否使用**"到底怎么落地，
以及怎么写出自己的插件。

## 1. 一个开关表控制一切

```python
from pasm_framework import BaseApplication

app = MyApp("demo", {"name": "小智"}, backend_config={
    "knowledge_base": {"enabled": True,  "config": {"kb_dir": "./kb"}},
    "sessions":       {"enabled": True,  "config": {"max_history": 30}},
    "llm_responder":  {"enabled": True,  "config": {"provider": "deepseek",
                                                    "api_key": "sk-..."}},
    "warmth":         {"enabled": False},      # 关掉：回复要"干净"
    "safety":         {"enabled": True,  "config": {"mode": "block"}},
    "observability":  {"enabled": True},
    "web_gateway":    {"enabled": False},
})
```

没列出的插件**视为关闭**。所以要么列全，要么用预设打底：

```python
from pasm_framework import load

cfg = load(preset_name="chatbot",          # 7 个插件都列好了
           warmth={"enabled": False},      # 只覆盖我关心的那一个
           web_gateway={"config": {"port": 9000}})
```

## 2. 7 个内置插件速查

| 插件 | 关键配置 | 作用 |
| --- | --- | --- |
| `knowledge_base` | `kb_dir` `auto_learn` `top_k` `min_score` | 资料摄取/检索/自学 |
| `sessions` | `max_history` | 每 session 独立历史 |
| `llm_responder` | `provider` `base_url` `model` `api_key` `timeout` `system_prompt` | LLM 接入 |
| `warmth` | `max_len` | 情绪化润色（代码块会跳过） |
| `safety` | `mode`(warn/block) `block_patterns` `redact_pii` | 注入拦截 + 出站脱敏 |
| `observability` | — | 指标 + `/healthz` |
| `web_gateway` | `host` `port` `token` `rate_limit` `max_body` `allowed_origins` | HTTP 对外 |

看默认开关与说明：

```bash
python -m pasm_framework plugins
```

## 3. 配置的四个来源与优先级

```
preset  <  文件(.json/.yaml)  <  环境变量(PASM_*)  <  代码显式传的
```

```python
from pasm_framework import load

cfg = load("server.json", preset_name="chatbot", env=True,
           web_gateway={"config": {"port": 9000}})   # 代码覆盖一切
```

`server.json`：

```json
{
  "plugins": {
    "web_gateway": { "enabled": true, "config": { "host": "0.0.0.0", "port": 8080 } },
    "safety":      { "enabled": true, "config": { "mode": "block" } }
  }
}
```

环境变量（部署时最方便）：

```bash
PASM_PLUGINS=none                                  # 或逗号分隔的插件名（覆盖所有开关）
PASM_PLUGINS=safety,sessions,knowledge_base,web_gateway
PASM_KB_DIR=/data/kb
PASM_SAFETY_MODE=block
PASM_LLM_PROVIDER=deepseek PASM_LLM_MODEL=deepseek-chat PASM_LLM_API_KEY=sk-xxx
PASM_HTTP_HOST=0.0.0.0 PASM_HTTP_PORT=8080 PASM_HTTP_TOKEN=your-secret
```

> 配了 `PASM_LLM_*` 任一项，`llm_responder` 会**自动开启** —— 因为默认关是
> 为了"没配就别联网"，你配了就说明想用。

查看最终生效结果（排查配置问题第一命令）：

```bash
python -m pasm_framework config --preset chatbot --env
python -m pasm_framework config --file server.json --json
```

## 4. Hook 链：插件挂在哪些时机

```
on_init → on_message_in → on_retrieve → on_reply → on_reply_final → on_learn → on_shutdown
```

| Hook | 时机 | 典型用途 |
| --- | --- | --- |
| `on_init` | 应用启动（一次） | 绑定 app、建连接、预加载 |
| `on_message_in` | 收到消息，最先 | 鉴权、限流、安全扫描、会话绑定 |
| `on_retrieve` | 能力路由后 | 贡献资料（写 `msg.facts`） |
| `on_reply` | 还没有回复时 | **生成**回复（LLM） |
| `on_reply_final` | 回复已定稿 | **收尾**：脱敏、润色（正好跑一次） |
| `on_learn` | 返回给用户前 | 沉淀问答、写会话、上报指标 |
| `on_shutdown` | 关闭时 | 落盘、停线程 |

⚠️ 最容易搞混的是 `on_reply` 与 `on_reply_final`：

- `on_reply` 是**生成** —— 你的插件**产出**内容给 `msg.reply`；
- `on_reply_final` 是**收尾** —— 对别人产出的内容做后处理。
  它由框架在**唯一出口**调用，所以**四条**路径都会经过它、**恰好一次**：

  | 路径 | 说明 |
  | --- | --- |
  | 能力命中 | `Capability` 返回了确定性结果 |
  | LLM 生成 | `llm_responder` 产出了回复 |
  | 模板兜底 | 离线/未接 LLM 时 `_render_reply` 的回复 |
  | 被拦截 | `on_message_in` 里 `msg.stop = True` 时的拦截话术 |

如果你把护栏写在 `on_reply` 里，离线模式（不接 LLM）的模板回复会**绕过护栏** ——
这是 v0.2.0 真实存在过的缺陷，v0.2.1 已用 `on_reply_final` 修掉。

⚠️ **护栏与润色在收尾阶段的分工不同**（别把它们当同一类）：

- **护栏类**（`safety`）：对**所有**路径生效，**包括能力输出** —— 安全不能有例外；
- **风格类**（`warmth`）：默认**跳过能力输出**，因为能力返回的可能是精确字符串 /
  链接 / 结构化内容，加语气词会破坏语义。需要时开
  `warmth.config.polish_capabilities = True`。

## 5. 写自己的插件

```python
from pasm_framework import BasePlugin, PluginContext, Message, PluginManager


class SlaPlugin(BasePlugin):
    """给回复加 SLA 提示，并统计超时次数。"""

    name = "sla"
    version = "0.1.0"

    def __init__(self, config=None):
        super().__init__(config)
        self._seconds = float(self.config.get("seconds", 3))
        self.timeouts = 0

    def on_init(self, ctx: PluginContext) -> None:
        # 启动时拿一次 app 引用（需要跨消息状态时用）
        self._app = ctx.app

    def on_message_in(self, ctx: PluginContext) -> None:
        ctx.store["sla_t0"] = __import__("time").time()

    def on_reply_final(self, ctx: PluginContext) -> None:
        import time
        t0 = ctx.store.get("sla_t0")
        if not t0:
            return
        used = time.time() - t0
        if used > self._seconds:
            self.timeouts += 1
            ctx.message.reply = (ctx.message.reply or "") + "\n（本次回复较慢，已为你记录）"


pm = PluginManager()
pm.register(SlaPlugin({"seconds": 2}))

app = MyApp("demo", {"name": "小智"}, plugins=pm)   # 直接注入插件管理器
print(app.plugins.enabled_names())                  # ['sla']
```

要点：

- 所有 Hook 都是**可选**的，只写你关心的（`BasePlugin` 有全部空实现）；
- 单个插件抛异常**不会**拖垮整条链（框架隔离并记录）；
- 想拿 `app` 的能力用 `ctx.recall()` / `ctx.observe()` / `ctx.mood()` / `ctx.persona()`，
  不要直接摸 `app` 内部；
- 插件自己的状态放 `self`；跨 Hook 传数据放 `ctx.store`。

### 5.1 注册的三种方式

| 方式 | 写法 | 适合 |
| --- | --- | --- |
| 注入管理器 | `MyApp(..., plugins=pm)` | 完全手工控制顺序 |
| **配置内联** | `backend_config={"sla": {"enabled": True, "class": SlaPlugin}}` | **最常见**：不用发包、不用改构造函数 |
| entry-point | `[project.entry-points."pasm_framework.plugins"]` | 对外发插件包，安装即被自动发现 |

配置内联是 v0.2.1 新增的能力 —— 一个 `class=` 就够：

```python
from pasm_framework import BaseApplication, load

cfg = load(preset_name="chatbot", sla={"enabled": True, "class": SlaPlugin})
app = MyApp("demo", {"name": "小智"}, backend_config=cfg)
```

同一插件要多实例时用 `as` 起别名：

```python
backend_config={
    "slow_log": {"enabled": True, "class": SlaPlugin, "as": "sla_slow",
                 "config": {"seconds": 5}},
    "fast_log": {"enabled": True, "class": SlaPlugin, "as": "sla_fast",
                 "config": {"seconds": 1}},
}
```

⚠️ **拼错插件名不会静默通过**。写错成 `knowlege_base` 时框架不做无提示忽略，
而是记进 `PluginManager.unknown()`：

```python
app.plugins.unknown()                     # ['knowlege_base']
app.app_summary()["plugin_config_unknown"]  # 同上
pasm-framework doctor                      # [5] 插件装配 会报告
```

## 6. 把插件发布成可发现包（entry point）

第三方包在 `pyproject.toml` 声明：

```toml
[project.entry-points."pasm_framework.plugins"]
sla = "my_pkg.sla:SlaPlugin"
```

安装后框架**自动发现**并注册（受开关表控制）。这就是"插件库生态"的入口。

## 验证

```python
from pasm_framework import load, SimpleApplication

# 1) 全关 → 行为退回最朴素形态
app = SimpleApplication("v1", {"name": "x"}, backend_config=load(preset_name="minimal"))
assert app.plugins.enabled_names() == []

# 2) 只开一个
cfg = load(preset_name="minimal", observability={"enabled": True})
app2 = SimpleApplication("v2", {"name": "x"}, backend_config=cfg)
assert app2.plugins.enabled_names() == ["observability"]

# 3) on_reply_final 恰好跑一次（探针计数）
```

对应的探针测试写法见 `pasm_framework/__init__.py` 的 `selftest()` 末段
（"on_reply_final 对每条路径恰好跑一次"）。

## 下一步

- 做完整客服（自学/记忆/成长）→ [04 站点智能客服](04-knowledge-base-customer-service.md)
- 让回复更自然 → [05 接入 LLM](05-llm-integration.md)
