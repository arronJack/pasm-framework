# 05 · 接入 LLM（可选，但能明显提升体验）

前提认知：**pasm-framework 不依赖 LLM 也能工作**。LLM 是"让措辞更自然"的增强项，
不是必需品。这一点很重要 —— 它意味着 LLM 挂了、没配、超时了，你的客服**不会不可用**。

## 1. 最短路径（环境变量）

```bash
# DeepSeek
export PASM_LLM_PROVIDER=deepseek
export PASM_LLM_MODEL=deepseek-chat
export PASM_LLM_API_KEY=sk-xxxxxxxx

# 或 OpenAI
export PASM_LLM_PROVIDER=openai
export PASM_LLM_MODEL=gpt-4o-mini
export PASM_LLM_API_KEY=sk-xxxxxxxx

# 或本地 Ollama（无需密钥）
export PASM_LLM_PROVIDER=ollama
export PASM_LLM_MODEL=qwen2.5:7b
export PASM_LLM_BASE_URL=http://localhost:11434

python main.py
```

**只配 `PASM_LLM_*` 任一项，`llm_responder` 会自动开启。**

## 2. 代码里配置

```python
from pasm_framework import SimpleApplication, load

cfg = load(
    preset_name="chatbot",
    llm_responder={"enabled": True, "config": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "sk-xxxxxxxx",          # 生产建议用环境变量，别写进代码
        "temperature": 0.7,
        "max_tokens": 800,
        "timeout": 30,
        "system_prompt": (
            "你是{persona_name}，一位{persona_role}。"
            "仅依据给定资料作答；资料没有的就如实说不知道，不要编造。"
        ),
    }},
)
app = SimpleApplication("cs", {"name": "小智", "role": "智能客服"}, backend_config=cfg)
app.teach([{"title": "退货政策", "content": "7 天内无理由退货。", "source": "faq"}])
print(app.ask("怎么退货？"))
```

`system_prompt` 里的 `{persona_name}` / `{persona_role}` 会自动替换成 persona 的值。

## 3. LLM 拿到的是什么上下文

`llm_responder` 拼装的消息顺序：

```
1. system  —— system_prompt（含 persona）
2. system  —— "参考资料（请优先据此回答）：" + 检索到的 facts（最多 8 条）
3. 历史    —— 最近 10 轮会话（由 sessions 插件提供）
4. user    —— 当前问题
```

所以"有依据、不编造、记得住上下文"是**框架层**保证的，
你的 `system_prompt` 只需描述人格与语气。

## 4. 三层降级链（这是设计重点）

```
① 能力命中（capability）           ← 确定性动作，最高优先
② llm_responder 生成               ← 措辞自然
③ 模板兜底 _render_reply           ← 永远有回复，且"就资料作答"
```

`llm_responder` 的失败是**静默**的：超时、401、模型不存在、网络不通 ——
都只是让 `msg.reply` 保持为空，然后自然落到第 ③ 层。

```python
# 验证降级：把 base_url 指向一个不存在的端口
cfg = load(preset_name="chatbot", llm_responder={"enabled": True, "config": {
    "provider": "openai", "base_url": "http://127.0.0.1:1", "api_key": "x",
    "timeout": 2}})
app = SimpleApplication("cs", {"name": "小智"}, backend_config=cfg)
app.teach([{"title": "退货政策", "content": "7 天内无理由退货。", "source": "faq"}])
print(app.ask("怎么退货？"))     # 仍能回答（走模板），不会抛异常
```

## 5. 与知识库的配合（推荐生产形态）

```
用户提问
   ↓
knowledge_base 检索 ──→ 有命中 → 作为"参考资料"喂给 LLM → 自然措辞的有据回复
                   └─→ 无命中 → LLM 依 system_prompt 说"查不到"，不编造
```

这就是"**有情感有温度 + 高效 + 不胡说**"的组合：资料库保证准确性，LLM 保证表达。

## 6. 成本与延迟的实际考虑

| 关注点 | 建议 |
| --- | --- |
| 延迟 | `timeout` 设 15–30s；`max_tokens` 按需压（客服回复 300–500 足够） |
| 成本 | 先查资料库，命中高置信度时可以不调 LLM（用 `skip_if_reply` 机制 + 能力短路） |
| 隐私 | 用 `provider="ollama"` 跑本地模型，数据不出内网 |
| 稳定性 | 目前失败即降级到模板；多模型回退在路线图（P1-2） |
| 流式 | **尚未支持**（P0-1），长回复要等完整生成 |

## 7. 用 Ollama 跑本地模型（隐私优先）

```bash
ollama pull qwen2.5:7b
ollama serve

PASM_LLM_PROVIDER=ollama PASM_LLM_MODEL=qwen2.5:7b python main.py
```

`llm_responder` 对 Ollama 走 `/api/chat`，对 OpenAI 兼容端点走 `/chat/completions`，
自动区分响应格式。

## 验证

**用假服务端确认请求真的打到了正确路径**（别只看"有回复"就以为通了）：

```python
import json, threading, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pasm_framework import SimpleApplication, load

HITS = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        HITS.append({"path": self.path,
                     "auth": self.headers.get("Authorization"),
                     "body": json.loads(self.rfile.read(n).decode())})
        d = json.dumps({"choices": [{"message": {"content": "LLM 答复"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers(); self.wfile.write(d)

srv = ThreadingHTTPServer(("127.0.0.1", 8099), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = load(preset_name="minimal", llm_responder={"enabled": True, "config": {
    "provider": "openai", "base_url": "http://127.0.0.1:8099",
    "api_key": "test-key", "model": "m1", "timeout": 5}})
app = SimpleApplication("v", {"name": "小智", "role": "客服"},
                        backend_config=cfg,
                        reply=lambda t, f, m: "模板兜底")   # 兜底可识别

assert app.ask("你好") == "LLM 答复"                      # 真的走了 LLM
assert HITS[0]["path"] == "/chat/completions"            # 打到正确端点
assert HITS[0]["auth"] == "Bearer test-key"              # 鉴权头正确
assert HITS[0]["body"]["messages"][0]["role"] == "system"  # 有 system 提示
srv.shutdown()
```

## 下一步

- 对外发布 → [06 Web 部署与嵌入](06-web-deploy.md)
- 排查本地模型慢的问题 → 见技能 `local-llm-perf-tuning`
