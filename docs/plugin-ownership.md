# 插件归属决策：子目录 vs 独立仓

> 决策日期：2026-09-20 · 决策人：小志（授权代理拍板）· 状态：**已生效**

## 结论（先看这个）

| 插件类别 | 放哪里 | 为什么 |
| --- | --- | --- |
| **A. 内置插件**（官方维护、与内核同版本） | **子目录**：基座侧 `pasm-skills/plugins/`、框架侧现成的 `pasm-framework/pasm_framework/plugins/` | 它们直接调用内核内部 API，必须与内核**同版本发布**，独立仓必然版本漂移 |
| **B. 第三方 / 社区插件**（别人写的、独立发版） | **不建仓**，走 **entry-point** 自动发现 | 生态的正确答案是"插件可以住在任何 PyPI 包里"，不是"必须住进某个官方仓" |
| **C. 官方独立节奏的插件/应用包**（日后真有再说） | 建**一个** `pasm-plugins` 仓，内部分 `skills/` 与 `framework/` 两个目录 | **不建两个仓** —— 一个插件常同时用到两层，两个仓会把它劈成两半 |

**一句话**：现在**不新建 plugin 仓**。内置插件留在子目录；外部插件靠 entry-point；只有出现"官方维护但发版节奏独立"的插件时，才建**单个** `pasm-plugins`（而非 `pasm-skills-plugin` + `pasm-framework-plugin` 两个）。

## 1. 为什么不选"两个独立仓"

你给的两个选项我都评估了。选子目录 + 单仓兜底，而不是立即建两个仓，理由有三条，每条都能验证：

### 1.1 内置插件与内核是**同版本关系**，不是依赖关系

`pasm-framework` 的 7 个内置插件全都 `from ..core import BasePlugin, PluginContext` ——
它们用的是**内部 API**（下划线、私有字段、Hook 名）。

- 同仓：改内核时顺手改插件，`selftest` 一次跑完全部抓到。
- 分仓：插件锁 `pasm-framework==0.3.*`，内核一动插件就装不上；发版要发四次（两仓 × 两端），
  而且**很容易忘记同步** —— 用户装到"新插件 + 旧内核"就是 `ImportError`。

> 实测依据：本轮把 `safety` / `warmth` 从 `on_reply` 迁到 `on_reply_final`（新增钩子），
> 同仓改动只用了 3 处编辑 + 1 次 selftest；若分仓，这就是一次跨仓破坏性变更。

### 1.2 entry-point 机制**已经**是第三方插件的正解，且已落地

```toml
# 任何包都能这么声明，框架启动时自动发现，无需注册表
[project.entry-points."pasm_framework.plugins"]
my_plugin = "my_pkg.my_module:MyPlugin"
```

`build_manager(..., discover_entrypoints=True)` 已在跑。也就是说：
**"插件住在哪个包"从来不是限制**。再给外部插件指定一个官方仓，反而会传递错误暗示
——"只有官方仓里的才算插件"。

### 1.3 两个仓会让"跨层插件"无处安放

真实例子就是你要的智能客服：

| 它用到的东西 | 属于哪一层 |
| --- | --- |
| `knowledge_base` / `web_gateway` / 流式输出 | **框架层**（pasm-framework） |
| 记忆读写、情绪、成长（`BaseAgent`） | **基座层**（pasm-skills） |

一个插件同时横跨两层。硬塞进两个仓，就得把它劈成"半个插件放这边、半个放那边"，
两边还要互相声明依赖 —— 这是纯粹给自己制造的麻烦。

## 2. 落地的约定（照这个做就不会错）

### 2.1 放子目录的插件（A 类）

```
pasm-skills/
  plugins/                 ← 基座侧插件（扩展 BaseAgent / 动作池 / 验证器）
  pasm_skills/plugins/     ← 若要做成可 import 的包，放这里
pasm-framework/
  pasm_framework/plugins/          ← 框架侧内置插件（已存在，7 个）
  pasm_framework/plugins/builtins/ ← 内置实现，注册进 builtin_plugins()
```

硬要求：
1. 在 `builtins/__init__.py` 的 `builtin_plugins()` 里**注册**（不注册 = `build_manager` 看不到）；
2. 默认开关写进 `plugins/registry.py` 的 `_DEFAULT_ENABLED`；
3. 要在预设里出现 → `pasm_framework/config.py` 的 `PRESETS` 各补一条；
4. 读配置一律 `self.config.get(k, default)`（硬索引缺键会启动即崩且零提示）；
5. 跟着内核升版本号，**不单独发版**。

### 2.2 走 entry-point 的插件（B 类）

```
my-company-pasm-plugin/          ← 任何人都可以，自己的仓、自己的版本号
  pyproject.toml                 ← 只声明一条 entry-point
```
- **不依赖** `pasm_framework` 的内部模块（只用导出的稳定表面：`BasePlugin` / `PluginContext` / `Message`）；
- 自带测试，别指望官方守门替你测；
- 可以在 `backend_config` 里被用户自由开关，与内置插件一视同仁（`unknown()` 会记录拼错的名字）。

### 2.3 命名

- 内置：`snake_case`，如 `knowledge_base`；
- 第三方：建议加前缀避免撞名，如 `acme_crm`。

## 3. 什么条件下才建 `pasm-plugins` 仓

三条**同时**满足才建（否则就是给自己加维护负担）：

1. 该插件**官方维护**，但不是随内核发版；
2. 它有**独立的发布节奏**（例如依赖某个第三方 SaaS，版本跟着对方走）；
3. 它不愿意进 `pasm-agents`（因为它不是"成品智能体"，而是"可复用的插件/应用"）。

建的时候：**一个仓**，顶层 `skills/` 与 `framework/` 两个目录，各自一个 `pyproject.toml`
（多包单仓），CI 与守门复用现成脚本。

## 4. 现成参照

- 框架内置插件：`pasm-framework/pasm_framework/plugins/builtins/`（7 个，零强制依赖）
- 插件写法教程：`pasm-framework/docs/tutorials/03-plugins.md`
- Hook 链说明：`pasm-framework/docs/tutorials/README.md`
- 扩展守门打法：技能 `pasm-framework-extension`
