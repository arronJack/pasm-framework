# 08 · 打包与运维

把应用交出去、并在出问题时快速定位。

## 1. 先跑体检

```bash
python -m pasm_framework doctor
```

它检查：Python 版本、`pasm-skills` 是否可用、插件库能否加载、
临时目录与知识库目录**可写性**、LLM 是否配置、`pyyaml` 是否存在。
**部署到新机器第一件事就跑它。**

## 2. 依赖与隔离

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install pasm-framework
```

只有两个必需依赖：`pasm-framework` 与 `pasm-skills`（会自动装）。
其余全是**可选增强**：

| 可选 | 用来做什么 | 不装的后果 |
| --- | --- | --- |
| `pyyaml` | 读 `.yaml` 配置 | 用 `.json` 即可 |
| `openai` | 官方 SDK | 不需要 —— 内置用标准库 `urllib` 调 API |
| `torch` / `numpy` | 引擎 `bionic` 档位的情绪能力 | 降级为 `light` 档（**降级不隐藏**，会体现在能力上） |

## 3. 打包成单体可执行（PyInstaller）

```bash
pip install pyinstaller
pyinstaller --noconfirm --onedir --name pasm-chat main.py \
  --add-data "kb:kb" \
  --hidden-import pasm_framework.plugins.builtins \
  --hidden-import pasm_framework.plugins.registry
```

⚠️ **两个真实的坑**（踩过）：

1. **函数内 import 的模块不会被自动收集** —— 插件是延迟导入的，
   必须显式写 `--hidden-import pasm_framework.plugins.builtins`
   （以及你自己插件里延迟导入的模块）。漏了的症状是"开发能跑、打包后功能静默失效"。
2. **打包后的路径与源码不同** —— `kb_dir` 用相对路径会指到临时解包目录。
   生产请用**绝对路径**或环境变量：

```python
import os
kb_dir = os.environ.get("PASM_KB_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "kb")
```

打包后验证（**别只看打包成功就发**）：

```bash
./dist/pasm-chat/pasm-chat --serve &
curl -s http://127.0.0.1:8080/healthz
curl -s -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' -d '{"text":"怎么退货？"}'
```

## 4. 观测

### 指标

启用 `observability` 后，`/healthz` 会带上指标：

```bash
curl -s http://127.0.0.1:8080/healthz | python -m json.tool
```

```json
{
  "status": "healthy",
  "listening": true,
  "auth_required": false,
  "metrics": {
    "uptime_s": 128.4,
    "messages_in": 37,
    "replies": 37,
    "errors": 0,
    "plugin_errors": 0,
    "avg_latency_s": 0.021,
    "p95_latency_s": 0.086
  }
}
```

| 指标 | 该关注什么 |
| --- | --- |
| `plugin_errors` | **大于 0 说明有插件在静默报错**（框架隔离了异常，但这里能看到） |
| `p95_latency_s` | 明显升高通常是接 LLM 后超时变多 |
| `errors` | 被 `safety` 拦截的注入尝试次数 |

应用内快照：

```python
import json
print(json.dumps(app.app_summary(), ensure_ascii=False, indent=2))
# 含 domain / capabilities / plugins / plugin_metrics
```

资料库健康度：

```python
kb = app.plugins.get("knowledge_base")
print(kb.stats())      # {'total': 42, 'docs': 30, 'qa': 12}
```

> `qa` 数量是"自学习"的直观指标 —— 它涨说明应用在成长。

## 5. 排查手册（按症状）

| 症状 | 先查 | 常见原因 |
| --- | --- | --- |
| 服务起不来 | `python -m pasm_framework doctor` | 依赖缺失、目录不可写 |
| 端口连不上 | `python -m pasm_framework config --preset X` | **`serve()` 用了配置端口**（v0.2.1 起不传参就用配置值）；或防火墙/绑定 `127.0.0.1` 而客户端在别的机器 |
| 全部 401 | 是否设了 `token` | 客户端没带 `Authorization: Bearer` |
| 突然 429 | `rate_limit` 配置 | 压测或爬虫触顶 |
| 回归"答不上来" | `kb.stats()`、`/api/kb/stats` | 资料没摄取、`kb_dir` 换了路径、容器没挂卷 |
| 答非所问 | 资料标题是否含用户会说的词 | 标题权重是正文 3 倍；同义词放 `tags` |
| 回复"很官方/很干" | `warmth` 是否被关 | `api` 预设会关掉润色 |
| 回复带奇怪后缀 | `warmth` 在追加开场/收尾 | 想完全干净：`warmth={"enabled": False}` |
| 打包后功能失效 | `--hidden-import` | 延迟导入的模块没被收集 |
| 中文乱码 | 终端编码 | 用 `python -u`、设 `PYTHONIOENCODING=utf-8` |
| 某个能力不触发 | 关键词位置 | 只在**句首 12 字**内匹配 |
| LLM 没生效 | 环境变量 / `plugins` 列表 | `llm_responder` 默认关；配了 `PASM_LLM_*` 才自动开 |
| 想确认 LLM 是否真的被调用 | 起假服务端断言路径 | 见 [05 教程的验证小节](05-llm-integration.md) |

## 6. 数据与备份

| 数据 | 位置 | 怎么备份 |
| --- | --- | --- |
| 资料库 | `kb_dir/kb.jsonl` | 直接拷文件（**纯文本 JSONL**，可 diff、可手工修） |
| 应用状态/记忆 | `persist_dir`（默认 `~/.pasm-agents/<agent_id>`） | 拷目录 |
| 会话历史 | 内存（`sessions` 插件） | 重启即失；需要持久化请落盘（见路线图 P1-3） |

`kb.jsonl` 每行一条，格式：

```json
{"id": 1, "title": "退货政策", "content": "7 天内无理由退货。", "source": "faq", "tags": ["退货"], "kind": "doc", "ts": 1789880135.6, "hits": 0}
```

因为是纯文本，运维很省事：`grep` 就能排查"资料到底进去了没有"。

> 删除单条资料目前要手工编辑该文件并重启（`id` 与 `_seq` 需保持一致）。

## 7. 性能预期（实测参考）

| 场景 | 数据 |
| --- | --- |
| 知识库检索（2 万条） | 3.2 ms/次（倒排索引，区分性查询） |
| 知识库检索（2 千条） | 0.27 ms/次 |
| 摄取 2 万条 | 0.16 s（追加写，非全量重写） |
| 不接 LLM 的单轮 `handle` | 纯本地计算，毫秒级 |
| 接 LLM 的单轮 | 取决于模型；**当前无流式**，需等完整生成 |

## 8. 容量与扩容建议

| 规模 | 建议 |
| --- | --- |
| 单机、<1 万资料、<10 QPS | 当前形态直接够用 |
| 1–10 万资料 | 够用；把 `kb_dir` 放 SSD |
| >10 万资料 / 高并发 | 换向量检索（路线图 P0-2）+ 多进程 + 前置 Nginx |
| 多租户 SaaS | **需先补多租户隔离**（路线图 P0-3），否则资料库是共享的 |

## 9. 降级与容错清单

上线前逐条确认过一遍：

- [ ] LLM 不可用时**有降级**（应回落模板，不 500）
- [ ] 单个插件异常**不拖垮服务**（看 `plugin_errors`）
- [ ] 资料库目录不可写时**启动仍成功**（只是检索为空）
- [ ] `safety` 在公网用 `block`，内网可 `warn`
- [ ] `/healthz` 已接探针，且 `Restart=always`
- [ ] `kb_dir` 已持久化、已纳入备份

## 下一步

- 换语言接入 → [09 多语言客户端](09-polyglot-clients.md)
- 了解下一步框架会补什么 → [`../capability-matrix-2026-09-20.md`](../capability-matrix-2026-09-20.md)
