# 04 · 站点智能客服（自学 / 记忆 / 成长）

这一篇实现你最初描述的目标：**站点相关数据自然形成资料库，从而自学、记忆、成长，
有情感有温度且高效地回复客户**。

完整可运行实现见仓库 `apps/customer_service.py`；本篇讲清它为什么这样设计。

## 1. 三件事分别由谁负责

| 你的目标 | 实现者 | 机制 |
| --- | --- | --- |
| **自学** | `knowledge_base` | 每次高质量问答沉淀成 QA 对，资料库越用越厚 |
| **记忆** | `knowledge_base`（知识）+ `sessions`（对话）+ 引擎（情景记忆） | 分层存储，检索时合并 |
| **成长** | 上述两者 + 引擎的反馈塑形 | 资料变多、会话变准、人格被反馈调整 |
| **有温度** | `warmth` + persona | 情绪驱动的措辞 |
| **高效** | 倒排索引检索 + 零 LLM 兜底 | 2 万条资料检索 3.2ms（实测） |
| **安全** | `safety` | 注入拦截 + 出站脱敏 |

> **喂资料只有一个入口**：`app.ingest(items)`。`SimpleApplication.teach()` 与
> `CustomerServiceAgent.ingest_faq()` 都只是它的别名，三处叫法等价。
> 未启用 `knowledge_base` 时 `ingest()` 会**显式抛错**（不会静默吞），
> 避免"我明明喂了资料，为什么答不上来"。
> 通过 HTTP 可以用 `POST /api/ingest`，语义完全相同。

## 2. 完整实现

```python
from pasm_framework import SimpleApplication, load


class CustomerService(SimpleApplication):

    DEFAULT_UNKNOWN = ("抱歉，我暂时没有查到相关资料。"
                       "你可以换个说法，或联系人工客服 400-000-0000。")

    def ingest_faq(self, items):
        """从 CMS / 帮助中心 / 数据库同步资料。"""
        return self.ingest(items)          # ingest / teach 是同一个入口


def build(kb_dir="./kb"):
    cfg = load(
        preset_name="chatbot",                    # 护栏 block + 开 HTTP 网关
        knowledge_base={"enabled": True, "config": {
            "kb_dir": kb_dir,
            "auto_learn": True,                   # 允许自学
            "auto_learn_min_len": 12,             # 太短的回复不沉淀（防噪声）
            "top_k": 5,                           # 每次检索取几条
            # "min_score": 3.0,                   # 精度不够时可调高（默认 0=不启用）
        }},
        sessions={"config": {"max_history": 20}},
        warmth={"enabled": True},
        safety={"config": {"mode": "block"}},
        observability={"enabled": True},
    )
    app = CustomerService("shop-cs", {
        "name": "小智", "role": "智能客服",
        "tone": "温暖、专业、耐心",
        "temper": 0.6, "energy": 0.5, "play": 0.4,
    }, backend_config=cfg)

    app.ingest_faq([
        {"title": "退货政策",
         "content": "商品签收后 7 天内可无理由退货，需保持吊牌完整、不影响二次销售。",
         "source": "faq", "tags": ["退货", "退款", "售后"]},
        {"title": "配送时效",
         "content": "现货 24 小时内发货；偏远地区 3-5 天送达。",
         "source": "faq", "tags": ["配送", "物流", "发货"]},
        {"title": "发票",
         "content": "下单时可勾选电子发票，次日发送至注册邮箱。",
         "source": "faq", "tags": ["发票", "开票"]},
    ])
    return app


if __name__ == "__main__":
    cs = build()
    for q in ["怎么退货？", "多久能发货？", "能开发票吗？", "你们老板是谁？"]:
        print("客户：%s" % q)
        print("客服：%s" % cs.ask(q, session_id="cust-1"))
        print("-" * 50)
```

## 3. "自学"是怎么发生的（关键机制）

```
第 1 次问 "可以开发票吗？"
   → 检索命中「发票」资料 → 基于资料回答（有依据）
   → on_learn：因为已有正式资料(doc)覆盖，**不重复沉淀**

问一个资料没覆盖、但 LLM/能力答得好的问题
   → on_learn：回复够长、没有 no_answer 标记、检索无高置信命中
   → 沉淀为 QA 对（kind="qa"）

下次同类问题 → 检索到这条 QA（QA 有 1.15 倍加权）→ 答得更快更准
```

防垃圾沉淀的三道闸门（都已在代码里）：

1. **`no_answer` 标记** —— 模板兜底说"没查到"时，`BaseApplication` 打标记，
   `on_learn` 直接跳过，不会把"我不会"沉淀成知识；
2. **最短长度** —— 少于 `auto_learn_min_len` 的回复不沉淀（默认 12 字）；
3. **去重** —— 已有同主题正式资料（`kind=doc` 且分数够），或检索最高分 ≥ 6，则跳过。

## 4. "记忆"是分层的

| 层 | 存什么 | 谁负责 | 何时用 |
| --- | --- | --- | --- |
| 资料库 | FAQ/文档/沉淀的 QA | `knowledge_base` | 每次检索（带 `source`） |
| 对话历史 | 本会话逐轮消息 | `sessions` | 给 LLM 拼上下文 |
| 情景记忆 | "交谈过什么" | 认知引擎 | 供人格/情绪参考 |

**重要区别**：只有带 `source` 的才是"有依据的知识"。纯对话记忆（情景记忆）
不带 `source`，所以客服的 `_render_reply` 里写的是
`knowledge = [f for f in facts if f.get("source")]` ——
**避免把"用户闲聊"当成公司政策来回答**。

## 5. 检索质量的调优（实战经验）

打分公式（简化）：`(标题重叠×3 + 标签重叠×2 + 正文重叠×1) × 2 + 精确度 × 2`，
再乘时效与 QA 加权。

由此得到几条实用建议：

1. **关键信息写进 `title`** —— 标题命中权重是正文的 3 倍。
   如果你只有大段文档，必要时拆成多条，每条一个明确的标题。
2. **把用户会说的词放进 `tags`** —— 标签权重居中，是"同义词"的最佳位置。
   例如标题「配送时效」+ tags `["发货","物流","几天到"]`。
3. **同义不同字匹配不上**（当前局限）：问"多久**发货**"对资料写"24 小时内**发出**"
   是匹配不上的。解决办法是把两种说法都写进 tags，或开启 LLM。
4. `min_score` 默认 0（不启用）。如果发现误命中多，试着调到 3～5。

## 6. 上线成可嵌入的客服

```python
cs = build()
cs.serve()          # 使用配置里的 host/port
```

站点里一行：

```html
<iframe src="http://your-host:8080/" width="420" height="620"
        style="border:0;border-radius:12px"></iframe>
```

详见 [06 Web 部署与嵌入](06-web-deploy.md)。

## 验证

```python
cs = build()
kb = cs.plugins.get("knowledge_base")

# 1) 就资料作答
assert "退货" in cs.ask("怎么退货？", "c1")
assert "发货" in cs.ask("多久能发货？", "c1")

# 2) 答不上来要诚实，不能编
assert "没有查到" in cs.ask("你们老板是谁？", "c1")

# 3) 会话隔离：不同客户互不影响
cs.ask("怎么退货？", "cust-A")
assert cs.plugins.get("sessions").get_session("cust-A") is not None
assert cs.plugins.get("sessions").get_session("cust-B") is None

# 4) 自学习：验证"答不上来"不会被沉淀（总量不该因为兜底回复而增长）
before = kb.stats()["total"]
cs.ask("你们老板是谁？", "c1")
assert kb.stats()["total"] == before, "兜底回复被误沉淀了"
```

## 已知局限（诚实说明）

- **无语义理解**：同义词匹配不上（见 §5.3）。要根本解决需开启 LLM 或等向量检索（路线图 P0-2）。
- **资料库是全局的**：当前多租户共享同一份资料库，SaaS 场景需等 P0-3。
- **无流式输出**：长回复要等完整生成（路线图 P0-1）。

## 下一步

- 让回复更自然 → [05 接入 LLM](05-llm-integration.md)
- 对外发布 → [06 Web 部署与嵌入](06-web-deploy.md)
