# 02 · 能力与领域知识

教程 01 的应用"会聊天"，但不会**做事**。这一篇让它可以执行明确动作，
并把你的业务事实与规则注入进去。

## 1. 能力（Capability）：一个方法 = 一个能力

```python
from pasm_framework import SimpleApplication, capability, load


class ShopApp(SimpleApplication):

    @capability(keywords=("退货", "退款", "退钱"), description="发起退货")
    def refund(self, text):
        # 真实项目里这里可以查订单、调内部 API
        return "退货入口：/refund（签收后 7 天内可自助申请）"

    @capability(keywords=("订单", "物流", "到哪"), description="查订单")
    def order(self, text):
        return "请把订单号发我，或在「我的订单」页面查看物流。"

    @capability(keywords=("人工", "转人工", "客服电话"),
                description="转人工")
    def human(self, text):
        return "正在为你转接人工客服，工作时间 9:00-21:00。电话 400-000-0000。"


app = ShopApp("shop", {"name": "小智", "role": "客服"},
              backend_config=load(preset_name="chatbot"))

for q in ["我要退货", "订单到哪了？", "转人工", "你们几点上班"]:
    print(q, "->", app.ask(q))
```

`@capability` 做的事：把你的方法登记成一个 `Capability`，
`app.handle()` 在**能力路由**阶段（流程第 2 步）命中它就调用它。

## 2. 关键词只在"句首 12 字"内匹配（重要！）

这是刻意的设计：避免用户在长句里随口提到一个词就被抢走。

| 输入 | 命中？ | 原因 |
| --- | --- | --- |
| `我要退货` | ✅ | "退货"在句首 |
| `退货怎么弄` | ✅ | 句首 |
| `我昨天买的东西想了想还是想退货` | ❌ | "退货"在第 13 个字之后 |

改动这个阈值（一般不建议）：

```python
@capability(keywords=("退货",), head_chars=30)
```

或者用 `predicate` 完全自己判断 —— 它优先级高于关键词：

```python
import re

@capability(predicate=lambda t: bool(re.search(r"(退|换)货", t)))
def after_sale(self, text):
    return "售后处理中，请提供订单号。"
```

## 3. 领域知识（DomainAdapter）：注入事实与规则

`@capability` 解决"做什么"，`DomainAdapter` 解决"依据什么、不许做什么"。

最常用的是内置的 `StaticDomainAdapter`：

```python
from pasm_framework import SimpleApplication, StaticDomainAdapter, load

domain = StaticDomainAdapter(
    knowledge=[
        {"title": "促销规则", "brief": "双十一满 300 减 50，不与优惠券叠加。",
         "tags": ["促销"]},
        {"title": "会员等级", "brief": "消费满 1000 元升银卡，满 5000 升金卡。",
         "tags": ["会员"]},
    ],
    constraints={"no_medical_advice": True, "refund_window_days": 7},
)

app = SimpleApplication("shop", {"name": "小智"}, domain=domain,
                        backend_config=load(preset_name="chatbot"))
print(app.ask("双十一有什么活动？"))     # 会检索到促销规则
print(app.domain.constraints)          # {'no_medical_advice': True, ...}
```

它做的事：`BaseApplication.recall()` 会把 `domain.knowledge_for(query)` 的结果
与记忆检索结果**合并去重**，来源标记为 `domain:StaticDomainAdapter`
（凡是带 `source` 的才算"有依据的知识"）。

## 4. 自己实现 DomainAdapter（接数据库/接口）

`DomainAdapter` 是一个 Protocol，实现你需要的部分即可：

```python
class CrmDomain:
    """从公司 CRM 实时取数。"""

    def __init__(self, crm_client):
        self.crm = crm_client

    def knowledge_for(self, query: str):
        # 返回 [{title, brief, tags, source?}, ...]
        rows = self.crm.search_faq(query, limit=3)
        return [{"title": r["q"], "brief": r["a"], "tags": r["tags"]} for r in rows]

    def constraints(self):
        return {"refund_window_days": 7, "require_order_id": True}

    def augment_reply(self, text: str, reply: str) -> str:
        # 可选：统一在回复里追加合规声明
        return reply + "\n（本回复由智能助手生成，如有疑问请联系人工客服）"


app = SimpleApplication("shop", {"name": "小智"}, domain=CrmDomain(my_crm),
                        backend_config=load(preset_name="chatbot"))
```

三个方法的职责：

| 方法 | 何时调用 | 返回 |
| --- | --- | --- |
| `knowledge_for(query)` | 每次检索 | `[{title, brief, tags?}]` |
| `constraints()` | 你的业务代码/插件按需读取 | `dict` |
| `augment_reply(text, reply)` | 需要做统一后处理时（由你调用或插件调用） | `str` |

## 5. 能力 vs 知识库 vs 领域知识 —— 怎么选

| 需求 | 用什么 | 理由 |
| --- | --- | --- |
| "用户说退货就返回退货入口" | **Capability** | 是确定性动作，不该靠检索碰运气 |
| "从 500 条 FAQ 里找答案" | **knowledge_base 插件** | 量大、要沉淀、要自学 |
| "公司规则、实时库存、账户信息" | **DomainAdapter** | 动态、要接已有系统 |
| "记住这个用户上次说了什么" | **sessions 插件**（默认开） | 会话隔离的职责 |

三者可以**同时用**，优先级是：能力命中 → 直接返回（不再走检索）。

## 验证

```python
app = ShopApp("verify", {"name": "x"}, backend_config=load(preset_name="minimal"))

# 1) 能力命中：返回能力的结果
assert "退货入口" in app.ask("我要退货")

# 2) 句首限制生效：长句不命中能力，走兜底
assert "退货入口" not in app.ask("我昨天买的东西想了想还是想退货")

# 3) 领域知识被检索到，且带来源标记
assert any(f.get("source", "").startswith("domain:") for f in app.recall("促销"))
```

## 下一步

- 想理解/自定义"开关" → [03 插件与开关](03-plugins.md)
- 想做完整客服 → [04 站点智能客服](04-knowledge-base-customer-service.md)
