# 01 · 快速上手

目标：**三条命令**得到一个能对话、能查资料的应用。

## 1. 安装并体检

```bash
pip install pasm-framework
python -m pasm_framework doctor
```

期望看到：

```
[1] 运行环境
  v Python 3.13.x（要求 >= 3.10）
[2] 依赖
  v pasm-skills 0.5.1 可导入
  v pasm-framework 0.2.1
  v 内置插件 7 个可加载
...
体检结论: 全部通过，可以开始开发
```

## 2. 生成项目

```bash
python -m pasm_framework new myapp --kind chatbot
cd myapp
python main.py
```

会看到：

```
客户：怎么退货？
客服：商品签收后 7 天内可无理由退货，需保持吊牌完整。如果还有不清楚的地方，随时告诉我哦～
```

到这里已经有一个能回答 FAQ 的客服了 —— **没有联网、没有装模型**。

## 3. 起个网页版

```bash
python main.py --serve
# 浏览器打开 http://127.0.0.1:8080/
```

或者直接一条命令跑内置演示（不用建项目）：

```bash
python -m pasm_framework serve --port 8080
```

## 4. 手写最简应用（不生成项目）

新建 `demo.py`：

```python
from pasm_framework import SimpleApplication, load

app = SimpleApplication(
    "demo",                              # 应用 id（也用于状态落盘目录名）
    {"name": "小智", "role": "智能助手"},   # persona：人格
    backend_config=load(preset_name="chatbot",
                        knowledge_base={"config": {"kb_dir": "./kb"}}),
)

app.teach([                              # 喂资料（一次性，会落盘）
    {"title": "退货政策", "content": "签收后 7 天内可无理由退货。",
     "source": "faq", "tags": ["退货"]},
    {"title": "营业时间", "content": "每天 9:00-21:00，节假日不休。", "source": "faq"},
])

print(app.ask("怎么退货？"))
print(app.ask("你们几点上班？"))
```

```bash
python demo.py
```

## 5. 发生了什么（值得理解的一遍）

```python
app.ask("怎么退货？")
```

1. `on_message_in` —— `sessions` 绑定会话、`safety` 扫一遍注入；
2. **能力路由** —— 没有注册能力，跳过；
3. `on_retrieve` —— `knowledge_base` 检索到「退货政策」，写进 `msg.facts`；
4. `on_reply` —— `llm_responder` 默认**关闭**，没有产出；
   于是走模板兜底（`SimpleApplication._render_reply`），它只依据**有来源的知识**作答；
5. `on_reply_final` —— `safety` 脱敏、`warmth` 补一句温暖收尾；
6. `on_learn` —— 因为答案来自正式资料（`kind=doc`），**不**重复沉淀。

## 6. 换个场景预设

`preset` 决定"开哪些插件"，这是最省事的起步方式：

```python
from pasm_framework import load

load(preset_name="minimal")     # 全关 → 行为退回最朴素的"能力路由+模板"
load(preset_name="default")     # 默认：安全/会话/知识库/温度/可观测
load(preset_name="chatbot")     # 客服：护栏收紧为 block + 开 HTTP 网关
load(preset_name="game_npc")    # NPC：离线优先，不接 LLM
load(preset_name="api")         # 纯 API：回复不润色（要干净文本）
load(preset_name="desktop")     # 桌面内嵌：只监听 127.0.0.1
```

看某个预设最终长什么样：

```bash
python -m pasm_framework config --preset chatbot
```

## 验证（确认你真的做对了）

1. `python -m pasm_framework doctor` 全 `v`；
2. `python main.py` 能正确回答 FAQ 里的问题；
3. 问一个资料里**没有**的问题（如"你们老板是谁"）→ 应得到"没有查到"的诚实回复，
   而不是编造 —— 这是本框架的底线行为。

## 下一步

- 想让应用"会做事"（下单、查订单、退货流程）→ [02 能力与领域知识](02-capabilities-and-domain.md)
- 想搞懂"开关"到底控制了什么 → [03 插件与开关](03-plugins.md)
