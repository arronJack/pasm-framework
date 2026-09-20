# PASM 七仓全盘审计报告

> 日期：2026-09-20 · 范围：`E:/AI/pasm/code/` 下七个仓 · 方法：全量静态扫描 + 四套守门 + 专项可证伪测试

## 0. 结论速览

| 仓库 | 编译 | pyflakes | 陈旧引用 | 敏感信息 | 卫生 | 远端同步 |
| --- | --- | --- | --- | --- | --- | --- |
| **PASM**（引擎主仓） | ✅ 186 文件 | 0 | 2 处（有意保留） | 无 | ✅ | ✅ 双端一致 |
| **pasm-skills**（基座） | ✅ 34 | 0 | 3 处（有意保留） | 无 | ✅ | ✅ 双端一致 |
| **pasm-agents**（成品） | ✅ 66 | 0 | 0 | 无 | ✅ | ✅ 双端一致 |
| **pasm-framework**（应用框架） | ✅ 29 | 0 | 2 处（有意保留） | 无 | ✅ | ⚠️ 本地领先（本轮推送） |
| **pasm-qclaw**（发行仓） | ✅ 96 | 0 | 2 处（有意保留） | 无 | ✅ | ✅ 双端一致 |
| **PASM-Lite**（教学版） | ✅ 7 | 0 | 0 | 无 | ✅ | ✅ 双端一致 |
| **pasm-mcp-server**（服务层） | ✅ 7 | 0 | 0 | 无 | ✅ | ✅ 双端一致 |

**没有发现新的结构性缺陷**；本轮发现的缺陷全部在 `pasm-framework`，已修（见 §2）。

## 1. 扫描口径

- **编译**：`python -m compileall -f`（强制重编，不信缓存），7 仓全部通过。
- **pyflakes**：全量源码（排除 `dist*` / `build` / `__pycache__`）→ **0 条**（严格模式，连 `noqa` 项也没有）。
- **陈旧引用**：扫描 4 类历史包袱 —— 已移除的 `pasm_skills.framework` 子包、旧发行仓名
  `pasm_qclaw_release`、已迁移的 `_CoreAdapter`。
- **敏感信息**：GitHub PAT / PyPI token / OpenAI key / 32 位疑似密钥字面量，并排除
  `test-key`、`your-secret`、`<token>` 等占位上下文。
- **仓库卫生**：根目录探针文件（4 字节 `blat`）、`*.egg-info` 构建残留。

## 2. 本轮修复的缺陷（全部在 pasm-framework，均配可证伪反例）

### 2.1 两个越权漏洞（安全）

| # | 缺陷 | 后果 | 修法 |
| --- | --- | --- | --- |
| 1 | `/console` 被放进公开路径 | 任何人不带令牌就能打开管理台界面 | 改为管理作用域；`?token=` 是站主唯一的浏览器入口 |
| 2 | `serve_token` 未配 `public_token` 时**回落管理令牌**，而该令牌会被写进访客可见的挂件页 | **等于把后台令牌送给每个打开网页的人** | `serve_token` 只返回 `public_token`；未配时挂件页本身也不再公开 |

> 反例对照（可复现）：把 `serve_token` 改回旧写法 → 判据报「挂件页源码含管理令牌」；
> 把 `/console` 放回公开路径 → 判据报「公开令牌进管理台未被拒」。还原后 21/21 全绿。

### 2.2 一个功能缺陷

`cs` 命令打印的嵌入代码用了 `data-token`，而 `embed.js` 读的是 `data-pasm-token`
→ 站主照抄一贴就是 401。已改正并补齐 `title/greeting/color`。

### 2.3 前序批次已修的（摘要）

- **唯一出口不变式**：新增 `on_reply_final`，护栏对「能力 / LLM / 模板兜底 / 拦截」四条路径全部生效
  （旧版离线模式的模板回复**完全绕过脱敏**）。
- **知识库性能**：读路径不再全量重写磁盘；倒排索引替代线性扫描（2 万条实测 240ms → 3.2ms）。
- **召回排序**：分字段加权 + 停用词 + `knowledge_facts()` 安全消费入口
  （避免把情景记忆当资料答给用户）。
- **NPC 召回**：`还记得河边那次吗` 这类自然问法此前一条都召不回（引擎 `_tokens` 截断问题），
  已在产品层加「回忆探询」二次检索。
- **构建库**：`clean_dist` 漏清 dist 根目录的 ZIP，导致新旧包混放（「发出去的还是上一版」）。

## 3. 跨仓一致性核查

| 检查项 | 结果 |
| --- | --- |
| 依赖方向（不得反向依赖产品层） | ✅ 无 `pasm_agents` 反向引用 |
| 分叉铁律（不得复制 `pasm.cognitive` 实现） | ✅ 无越层引用 |
| 三包版本一致性 | framework **0.3.0** / skills **0.5.2** / agents **0.4.11** |
| PyPI 实际可用 | framework 0.3.0 ✅ · skills 0.5.2 ✅ · agents 0.4.11 ✅（三层依赖可解析） |
| 守门覆盖 | framework selftest、skills selftest、surface-guard、product-verifier 全绿 |

> 说明：PyPI 上 `pasm-framework` 目前是 **0.3.0**，而仓库 HEAD 已含本轮站点插件与安全修复
> —— 即**仓库领先于 PyPI**。要不要发 0.4.0 需你确认（见 §5）。

## 4. pasm-qclaw 发行版核查（你问的"Linux / 苹果系统有没有补上"）

**结论：没有，而且目前不可能有 —— 它们从未被构建过。**

实测两端 Release API（2026-09-20）：

| 端 | Release 总数 | 带附件的 | 附件 |
| --- | --- | --- | --- |
| GitHub `arronJack/pasm-qclaw` | 48 | 1（v0.31.0） | `PASMStudio-Setup-0.31.0.exe` 190.1 MB |
| Gitee `arronzheng/pasm-qclaw` | 47 | 1（v0.31.0） | `PASMStudio-Setup-0.31.0-gitee.exe` + 3 个 `.bin` 切片 |

- **Linux（.deb/.rpm/.AppImage）与 macOS（.dmg/.pkg）：0 个附件**。
- 仓库里也**没有任何**这类产物，打包脚本只有 `desktop/installer.iss`（Inno Setup，Windows 专用）
  + `build_windows.bat`，无 CI。

**根因**：PyInstaller **不能交叉编译** —— 在 Windows 上打不出 Linux/macOS 的包。要出这两个平台的产物，
必须在各自的操作系统（或 CI 的对应 runner）上各跑一次构建。当前项目既没有 mac/Linux 构建机，也没有 CI，
所以产物自然不存在。这不是"发了但你没找到"。

**代码就绪度**（AST 扫描 `desktop/` 全部 .py）：93% 完全无 Windows 依赖；6% 仅函数内使用（可降级）；
**1 个模块导入期硬拦**：`audio.py`（顶层 `import winreg` + `ctypes.OleDLL`），
而 `pasm_companion.py:59` 在顶层 import 它 → Linux/macOS 上会启动即崩。
`autostart.py` 已是正确的跨平台写法（函数内 import + `is_supported()`），可直接照抄。

**可行路径**（详见 `pasm-framework/docs/cross-platform-strategy.md`）：
① 修 `audio.py` 的平台守卫 → ② GitHub Actions 三平台矩阵构建
（`windows-latest` / `ubuntu-latest` / `macos-latest`）→ ③ 各自打包
（Inno / AppImage+deb / dmg+签名公证）→ ④ 更新通道按平台分文件。
**本机（Windows）无法独自完成第 ② 步之后的工作**，需要 CI 或另一台 mac。

## 5. 验证证据（本轮全量）

```
framework selftest .................. 55/55 通过
skills selftest ..................... 通过
产品 selftest ....................... companion 13/13 · npc 12/12 · tutor 12/12
surface-guard ....................... 33 ok / 0 fail
product-verifier .................... 33 ok / 0 fail
parity-guard ........................ SKIP（桌面已并入核心仓，无对照物，属预期）
站点插件端到端 ...................... 24/24
令牌作用域安全 ...................... 21/21（含反例对照）
cs 命令横幅 ......................... 8/8
run --all ........................... 仅 core-verifier 3 fail（本机无 numpy/torch 的环境问题，非代码缺陷）
```

## 6. 已知局限（不是缺陷，是尚未做的事）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 流式输出 | ✅ 已实现 | `BaseApplication.stream()` + `POST /api/chat/stream`，护栏对流式同样生效 |
| 多轮工具调用 | ✅ 已实现 | Capability 自动暴露为 OpenAI `tools`，`tool_calls` 回环 |
| 向量/语义召回 | ❌ 未做 | 当前是词 + 中文 bigram 的倒排索引；语义召回需嵌入模型（可选依赖） |
| 多租户 / 并发 | ❌ 未做 | 单进程，仍受 GIL 与内存态限制；高并发需外部化存储 |
| Linux/macOS 桌面版 | ❌ 未构建 | 见 §4，需 CI 或对应平台机器 |
| 移动端 | ❌ 暂不做 | 按你的指示跳过；正确形态是「框架当云端大脑 + 原生壳」 |

## 7. 环境层发现（不影响仓库，但值得知道）

本轮在 `pasm-framework` 根目录出现 **160 个 4 字节随机名文件（内容均为 `blat`）**。
已做决定性实验：**在干净目录跑同样的命令，一个都不产生** → 不是本仓代码所为，
是运行环境在工具的工作目录写入的探针文件。已全部**移出仓库隔离**（未删除），
仓库现已干净。若再次出现，属环境行为，直接再隔离即可。
