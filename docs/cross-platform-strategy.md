# 跨平台策略：pasm-qclaw 从 Windows 走向 Linux / macOS / 移动端

> 你问的是：「桌面应用 pasm-qclaw 是否除了 Windows 应用版，还能让 Linux、苹果系统
> 以及手机应用也实现？」
>
> 结论先行：**桌面三平台（Win/Linux/macOS）可行，主要是打包与平台适配工作；
> 手机端不能把现桌面端直接打包过去，必须换架构 —— 而换架构恰好有现成的答案。**

---

## 0. 结论速览

| 目标 | 可行性 | 当前实际状态 | 核心工作 | 难度 |
| --- | --- | --- | --- | --- |
| Windows 桌面 | ✅ 已实现 | 47 个 Gitee Release 全是它的 | — | — |
| Linux 桌面 | ✅ 可行 | **产物 0 个**；代码 93% 就绪，1 个文件硬拦启动 | 解硬拦 + 打包链 | 中 |
| macOS 桌面 | ✅ 可行 | **产物 0 个**；同上，另需签名公证 | 解硬拦 + 打包 + 签名公证 | 中～大 |
| 手机 APP（iOS/Android） | 🔶 **换架构可行** | 未启动（按你的决定暂缓） | 端侧 UI 重做，大脑放服务端或随包 | 中 |
| 手机"套壳"（WebView） | ✅ 最快 | 现有 Web 能力 + 壳 | 小 |

关键认知：**pasm-qclaw 是"界面 + 大脑"合一的桌面程序。跨到手机时，把这两半拆开，
一半留桌面、一半上云 —— 这不是妥协，而是唯一正确的架构。**

> Linux / macOS 版**不是"没做好"，而是"从未构建"** ——
> 详见 §1.0 的实测核查与 §1.0.1 的代码就绪度数据。

---

## 1. 桌面端跨平台（Windows → Linux / macOS）

### 1.0 现状核查：为什么你在发行版里找不到 Linux / macOS 版

**结论：它们从来没被构建过 —— 不是"发布了但你没找到"，而是"根本没有"。**
实测核查（2026-09-20，直接查两端 Release API）：

| 核查项 | 实测结果 |
| --- | --- |
| Gitee Release 总数 | **47** 条 |
| GitHub Release 总数 | **48** 条 |
| 带附件的 Release | **各端只有 1 条**（即最新版 v0.31.0）—— 其余是纯记录 |
| 附件实际后缀分布 | Gitee `{exe:1, bin:3}`、GitHub `{exe:1}`，**全部 Windows** |
| 非 Windows 安装包（`deb/rpm/dmg/AppImage/pkg/apk`） | **0 个** |
| `latest.json` 升级通道 | 只描述 Windows 安装包 |
| 打包脚本 | 只有 `desktop/installer.iss`（Inno Setup，**Windows 专用**）+ `desktop/build_windows.bat` |
| CI 配置 | 无（不存在跨平台构建流水线） |

> 附带发现：按你既定的"**只保留最新版安装包**"维护惯例，旧版 Release 的附件已被清理，
> 所以现在**能下载的只有 v0.31.0 一个版本**（那 3 个 `.bin` 是 Inno DiskSpanning 的切片）。
> 这是预期行为，不是丢失 —— 但如果有人想下历史版本，是下不到的。

原因很直接：**PyInstaller 不支持交叉编译** —— 在 Windows 上打不出 Linux/macOS 的包。
要出这两个平台的产物，必须在各自的操作系统上（或 CI 的对应 runner 上）各跑一次构建。
目前项目没有任何这样的构建机或 CI，所以产物自然不存在。

### 1.0.1 代码就绪度实测：其实比想象中好得多

对 `desktop/` 全部 **94 个 .py 模块**做了 AST 级扫描（区分"导入期"与"函数内"，
因为只有导入期执行才会让应用**启动即崩**）：

| 分档 | 模块数 | 占比 | 含义 |
| --- | --- | --- | --- |
| 完全无 Windows 依赖 | **87** | **93%** | 直接跨平台可用 |
| 仅函数内用到（可降级） | 6 | 6% | 不崩，但该功能不可用 |
| **导入期硬拦（启动即崩）** | **1** | **1%** | 必须先改 |

**唯一的启动硬拦是 `desktop/audio.py`**：

```python
# audio.py 模块顶层（第 14、18 行）—— 导入期即执行
import winreg                              # ← Linux/macOS 无此模块 → ImportError
_ole32 = ctypes.OleDLL("ole32")            # ← POSIX 无 OleDLL 符号 → AttributeError
```

而 `pasm_companion.py:59` **在模块顶层** `import audio as audio_mod`，
所以整条启动链（实测 35 个模块）会在这里断掉 —— **应用连窗口都出不来**。

已用两种独立方式证实（可复现）：
- **静态**：AST 确认 `import winreg` 与 `ctypes.OleDLL` 位于模块顶层，不在函数内；
- **动态**：屏蔽 `winreg` 并摘掉 `ctypes.OleDLL` 后 `import audio` → 实测抛
  `AttributeError: module 'ctypes' has no attribute 'OleDLL'`。

> 修法很小（把两个顶层语句包进 `if os.name == "nt":` 并在非 Windows 下给空实现），
> 但**改了它只是"能启动"**，不等于"能用"。

启动链上的另外 6 个可降级模块（函数级用到 Windows API）：

| 模块 | Windows 用法 | 现状 |
| --- | --- | --- |
| `tts.py` | `ctypes.windll.winmm` / `winsound`（MCI 播放） | 播放/暂停处已有 `os.name == "nt"` 守卫 → **优雅降级**；但 `_mci_play` / `play_system_sound` 无守卫 |
| `autostart.py` | `winreg` 写 HKCU Run 键 | `import winreg` 在函数内 + `is_supported()` → **已经是跨平台范例，可照抄** |
| `asr.py` | `winsound`（提示音）/ `winreg`（检测语音引擎） | 无守卫，调用才炸 |
| `sysops.py` | `ctypes.windll`（回收站 / 桌面路径） | `desktop_dir()` 有守卫，`to_recycle_bin()` 无 |
| `logsetup.py` | `ctypes.windll.shell32` 取 APPDATA | 已在 `try/except` 内 → 会退回 `~` |
| `pasm_main.py` | `ctypes.windll.user32.MessageBoxW` 兜底弹窗 | 已在 `try/except` 内 |

### 1.0.2 ✅ 已落地的修复（2026-09-20，在 PASM 仓）

本文 §1.0.1 列出的"唯一导入期硬拦"**已经修掉**，并补上了跨平台操作层与三平台构建流水线：

| 项 | 状态 | 位置 |
| --- | --- | --- |
| `audio.py` 导入期硬拦（`winreg` + `ctypes.OleDLL/HRESULT/WINFUNCTYPE`） | ✅ 已修：专有成员 `getattr` 取 + 公开函数非 Windows 降级 + `is_supported()` | `PASM/desktop/audio.py` |
| `sysops.py` 顶层 `ctypes.wintypes` 依赖 | ✅ 改用固定宽度等价类型（不再隐式依赖） | `PASM/desktop/sysops.py` |
| 散落各处的 `os.startfile` / `explorer /select,` | ✅ 收敛进新模块，**15 处**已替换 | `PASM/desktop/platform_ops.py` |
| Linux 构建（tar.gz + 可选 .deb） | ✅ 脚本就绪（**未在真机跑过**） | `PASM/desktop/build_linux.sh` |
| macOS 构建（.app + .dmg） | ✅ 脚本就绪（**未在真机跑过**，且不做签名/公证） | `PASM/desktop/build_macos.sh` |
| 三平台 CI | ✅ 工作流就绪（手动 / `desktop-v*` tag 触发） | `PASM/.github/workflows/build-desktop.yml` |

验证方式（可证伪）：在进程内**屏蔽 `winreg` + 摘掉 Windows 专有 ctypes 成员 + 把 `sys.platform` 改成 `linux`**
再导入 —— 修前必崩，修后 8/8 通过；还原平台后 `is_supported()` 变回 `True`（证明判据真在测平台分支）。
另有 `platform_ops` 三平台模拟 17/17（Windows→`os.startfile` / macOS→`open -R` / Linux→`xdg-open`）。

> ⚠️ **产物仍未产出**：两端 Release 附件依旧只有 Windows。原因不是代码，而是**没有 Linux/macOS 构建机或 CI 跑过**。
> PyInstaller 不能交叉编译 —— 必须真跑一次那两条脚本（或让 CI 跑）。详见
> `PASM/desktop/BUILD-CROSSPLATFORM.md`。

### 1.1 技术栈本身是跨平台的 ✅

pasm-qclaw 技术底座是 **PySide6（Qt 6）+ PyInstaller**，两者都官方支持三平台：

| 组件 | Windows | Linux | macOS |
| --- | --- | --- | --- |
| PySide6 | ✅ | ✅ | ✅ |
| PyInstaller | ✅ | ✅ | ✅ |
| Ollama 本地模型 | ✅ | ✅ | ✅ |
| edge-tts（语音） | ✅ | ✅ | ✅ |
| ffmpeg（视频合成） | ✅ | ✅ | ✅ |

所以**核心逻辑不需要重写** —— 但下面这些"Windows 专属调用"必须逐个替换。

### 1.2 必须改的 Windows 专属点（通用核对清单）

> **§1.0.1 是实测结果，本表是通用参考。** 两者冲突时以 §1.0.1 为准 ——
> 本表按"常见 Windows 桌面程序的形态"列全，用于**对照检查有没有漏项**
> （例如某个能力当前没被用到、但以后加了会踩坑）。
> 每一项都属于"不换就会在 Linux/macOS 抛异常或行为不对"的类型。

| 位置/能力 | Windows 现状 | 跨平台替代 |
| --- | --- | --- |
| 用默认程序打开文件 | `os.startfile()` | macOS `open`、Linux `xdg-open`（`sys.platform` 分支或 `subprocess`） |
| 删除到回收站 | `SHFileOperationW`（ctypes） | macOS：`osascript` 移到废纸篓；Linux：`gio trash` / `trash-cli` |
| 路径拼接 | 混用 `\` 与 `os.path.join` | 统一 `pathlib.Path`，禁止手写反斜杠 |
| 配置/数据目录 | `%APPDATA%` / `%LOCALAPPDATA%` | macOS `~/Library/Application Support`、Linux `~/.config`（`platformdirs` 一格搞定） |
| 字体回退 | 微软雅黑 | macOS `PingFang SC`、Linux `Noto Sans CJK` |
| 托盘/通知 | Windows 托盘 | Linux 需 `libappindicator`（GNOME 默认不显示托盘图标）；macOS 用菜单栏项 |
| 高 DPI / 缩放 | Windows 缩放 | macOS Retina 需 `QT_ENABLE_HIGHDPI_SCALING`；Linux 各桌面环境不一 |
| 杀软/防火墙弹窗 | 已知现象 | Linux/macOS 无此问题 |
| 唤醒/后台保活 | Windows 计划任务 | Linux systemd user service、macOS launchd |
| 单实例锁 | Windows 互斥体 | 需换跨平台实现（文件锁 / `QLocalServer`） |

### 1.3 打包与分发（各平台不同）

| 平台 | 打包 | 安装包格式 | 更新通道 |
| --- | --- | --- | --- |
| Windows | PyInstaller → exe | **Inno Setup**（已支持增量更新、DiskSpanning 切片） | `latest.json`（现有） |
| Linux | PyInstaller → 可执行目录 | **AppImage**（免安装、最省事）/ `.deb` / Flatpak | AppImage 自更新或系统包管理 |
| macOS | PyInstaller → `.app` | 打成 `.dmg`（含 Applications 快捷方式） | Sparkle 或自有 `latest.json` |

⚠️ **三个平台必须各自打包**：PyInstaller 不支持交叉编译。也就是说
"Windows 上打不出 macOS 包" —— 需要 macOS 机器（或 CI 的 macOS runner）、
Linux 机器（或 Docker/CI）各跑一次。**这是跨平台成本的大头，不是代码而是构建与签名。**

### 1.4 签名与公证（容易被低估）

| 平台 | 要求 | 后果 |
| --- | --- | --- |
| Windows | 建议代码签名证书 | 无签名 → SmartScreen 警告"未知发布者" |
| macOS | **必须**签名 + **公证(notarization)** | 不公证 → 用户双击报"已损坏/无法验证开发者"，只能右键绕过 |
| Linux | 无需签名 | AppImage 需 `chmod +x` |

macOS 公证需要 **Apple Developer 账号（每年 $99）+ 构建机上配置证书**，
且公证是**联网提交 + 审核**（通常几分钟）。这是 macOS 支持里最"流程性"的一步。

### 1.5 桌面端工作量与风险（按实测数据修订）

代码侧只剩 **1 个文件**是启动硬拦、**6 个文件**是功能降级 —— 所以成本大头
**不在写代码，而在"构建 + 签名 + 分发"这三件事**：

| 项目 | 工作量 | 风险 | 说明 |
| --- | --- | --- | --- |
| 解除启动硬拦 | **小** | 低 | 只有 `audio.py`：把两个顶层语句包进平台判断，非 Windows 给空实现。改完应用能启动 |
| 打磨 6 个降级模块 | 小～中 | 低 | 照抄 `autostart.py` 已有的写法（函数内 import + `is_supported()`），逐项给替代实现 |
| Linux 打包 | 中 | 低 | PyInstaller + AppImage 脚本；GNOME 托盘是唯一"可能不显示"的坑 |
| macOS 打包 | 中 | 中 | 同上，额外要过签名 + 公证 |
| **CI 三平台构建** | 中 | 低 | GitHub Actions 有 windows/macos/ubuntu runner，天然适合；**这是绕开"必须有 mac 机器"的正解** |
| 自动更新三平台 | 中 | 中 | Inno 只服务 Windows，另两平台要各做一套（`latest.json` 可扩展） |
| ffmpeg/TTS 三平台下载源 | 小 | 低 | 现有 npmmirror 静态包按平台换文件名即可 |

**建议顺序**：先 Linux（成本最低、验证"平台解耦"是否彻底）→ 再 macOS（补签名流程）。

> ⚠️ **不要指望"在 Windows 上打出三平台包"**。PyInstaller 不能交叉编译，
> 必须各平台各构建一次。没有 mac 机器时，CI 的 macOS runner 是唯一出路。

---

## 2. 移动端（iOS / Android）

### 2.1 为什么不能把现有桌面端"打包"成手机 APP

| 障碍 | 说明 |
| --- | --- |
| **PySide6 不支持 iOS/Android** | Qt for Android/iOS 存在，但 **PySide6 官方不提供移动端轮子**，无法用 pip 装到手机 |
| **PyInstaller 不支持移动端** | 没有"Windows exe → APK"这条路 |
| **体积** | Python 运行时 + Qt + torch + 本地模型，安装包轻易上 GB，应用商店不接受 |
| **后台限制** | iOS 不允许常驻后台进程；本地大模型在手机上发热/耗电不可接受 |
| **上架合规** | 动态下载可执行代码、本地模型权重分发，均触碰商店政策 |

**结论：桌面端不可能"一键变手机 APP"，这条路不必尝试。**

### 2.2 手机端三条可行路线

| 路线 | 做法 | 优点 | 缺点 | 适用 |
| --- | --- | --- | --- | --- |
| **A. 云端大脑 + 原生前端**（推荐） | pasm-framework 跑服务器，手机用 Flutter / SwiftUI / Jetpack Compose / 小程序调 REST | 体验最好；大脑可升级无需发版；一台服务器服务所有端 | 需联网；要处理登录鉴权、离线缓存 | 正式产品 |
| **B. WebView 套壳** | 现有 Widget / Web 页面 → Capacitor / Tauri Mobile / 小程序 WebView 壳 | **最快**（几天）；复用现有前端 | 体验偏"网页"；推送/原生能力弱 | 先验证市场 |
| **C. 端侧轻量版** | 端上只跑规则+记忆（无 torch），联网时同步大脑 | 离线可用；隐私好 | 能力是子集；需重写一版轻量内核 | 强离线/隐私场景 |

### 2.3 路线 A 的落地形态（推荐）

```
iOS / Android APP (Flutter 或原生)
        │  HTTPS  REST/SSE
        ▼
  Nginx / Caddy（TLS、限流、鉴权）
        │
        ▼
  pasm-framework 服务（Python）
   ├ plugins: knowledge_base / sessions / safety / llm_responder
   └ web_gateway
        │
        ▼
   认知引擎（记忆 / 情绪 / 学习）
```

手机端只需要三件事：**登录 → 调 `/api/chat` → 展示**。
而 `session_id` 天然对应"一台设备/一个用户"，`sessions` 插件已经在做会话隔离 ——
把 `session_id` 换成"用户+设备"即可。

⚠️ **移动端必须补的两件事**（当前框架未覆盖）：
1. **鉴权与多租户隔离** —— 现在的 `token` 是单一共享令牌，只适合内网；
   正式对外需要用户级鉴权 + 按租户过滤资料库（见 `capability-matrix-2026-09-20.md` §5 P0-3）。
2. **流式输出（SSE）** —— 手机上等 5 秒才出第一句话，体验明显差于逐字显示（同 §5 P0-1）。

---

## 3. 推荐总体架构：把"大脑"和"壳"永久拆开

这是本次分析最重要的架构建议：

| 层 | 放什么 | 谁来做 |
| --- | --- | --- |
| **大脑（Brain）** | 记忆、情绪、学习、知识库、护栏、LLM 编排 | **pasm-framework**（Python，一份） |
| **接入（Edge）** | TLS、鉴权、限流、路由 | Nginx / Caddy |
| **壳（Shell）** | 界面、交互、动画、语音、本地文件 | 各平台原生 / Flutter / PySide6 / 小程序 |

好处：

- **一份大脑服务所有端**（Windows/Linux/macOS/手机/网页/小程序），修 bug 一次到位；
- 端侧可以**独立换技术栈**，不影响认知能力；
- 与 `pasm-framework` 的既有设计完全一致 —— `web_gateway` + `sdks/` 已经把这层留好了；
- 未来 V2.0 换引擎时，**所有端零改动**（唯一变动点在 `CognitiveAssembler`）。

对桌面端也建议如此：**桌面端也通过 HTTP 调本机大脑进程**（`127.0.0.1`），
而不是把大脑嵌进 UI 进程。这样桌面端与手机端共用同一套接入代码，
且大脑可以独立重启/升级。代价是本地多一个进程 + 一次回环调用（可忽略）。

---

## 4. 建议的推进路线

| 阶段 | 目标 | 关键工作 | 风险 |
| --- | --- | --- | --- |
| **第 1 步** | 框架侧补齐对外能力 | 流式 SSE + 用户级鉴权/多租户 + `/metrics` | 低 |
| **第 2 步** | Linux 桌面版 | 平台 API 替换、AppImage、CI 构建 | 低 |
| **第 3 步** | macOS 桌面版 | 同上 + 签名公证（需 Apple 开发者账号） | 中 |
| **第 4 步** | 手机端（先套壳验证） | Capacitor/小程序壳 + 云端大脑 | 低 |
| **第 5 步** | 手机端原生（按市场反馈决定） | Flutter/原生前端 + 推送 + 离线缓存 | 中 |

**不要做的事**：不要试图把 PySide6 桌面程序"打包"进手机；不要为手机重写一套认知引擎。

---

## 5. 一句话回答你的问题

> **你在发行版里找不到 Linux / macOS 版，是因为它们从未被构建过** ——
> 仓库里 95 个 Release（Gitee 47 + GitHub 48）**各端只有 1 条带附件**，
> 附件后缀只有 `.exe`（+3 个 `.bin` 切片），**非 Windows 的安装包为 0 个**；
> 打包脚本也只有 Windows 专用的 Inno Setup。PyInstaller 不能交叉编译，
> 没有 macOS/Linux 构建机或 CI，产物就不会存在。
>
> **但代码侧离"能跑"比想象中近得多**：94 个模块里 93% 完全无 Windows 依赖，
> **只有 `audio.py` 一个文件会拦住启动**；其余 6 个模块是"功能降级"而非崩溃。
> 改掉那 1 个文件，应用就能在 Linux/macOS 上启动。
>
> **桌面：Linux 与 macOS 都能做**，真正的工作量在"打包 + 签名 + 更新通道"，
> 不在重写功能。macOS 还需要 Apple 开发者账号（$99/年）走公证。
>
> **手机：能做，但要换架构。** 正确形态是
> **「pasm-framework 当云端大脑 + 手机只做壳」**——
> 这也是唯一能让"一套认知能力服务所有终端"的架构，且与框架现有的
> HTTP 网关 / 流式 SSE / 多语言客户端设计完全吻合。
