# HermesDesk

**A friendly Windows desktop AI assistant** — double-click install, guided setup, your own API key.  
Powered by the open-source **[Hermes Agent](https://github.com/NousResearch/hermes-agent)**.

[License: MIT](LICENSE)
[Platform](https://github.com/ladylydia/hermesdesk)
[Status](https://github.com/ladylydia/hermesdesk)

[English](#english) · [简体中文](#简体中文)

**App version (packaged):** `0.1.0` (see `tauri/tauri.conf.json`, `web/package.json`).

---

## English

### At a glance


|                        |                                                                                                                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Who it’s for**       | People who want a **native Windows app**, not a terminal or a browser tab                                                                                                            |
| **How you pay for AI** | **BYO key** — onboarding helps you connect OpenRouter, OpenAI, Anthropic, or a custom base URL                                                                                       |
| **Where files live**   | A **single workspace folder** (safe-by-default mental model)                                                                                                                         |
| **What’s inside**      | **Tauri 2** shell (onboarding, **in-shell chat**, settings, **messaging-gateway controls**) + **embedded Python** for **Hermes web** (`desktop_entrypoint`) **and** a **second child** for **`gateway.run`** + **Hermes React** dashboard in **WebView2** when you open the console |


> **Status: alpha (0.1+)** — the **end-to-end desktop path** is in place: onboarding → saved key → **shell chat** and/or full Hermes web UI, optional **multi-channel messaging gateway**, with workspace safety and **power user** gating. Expect ongoing polish. Architecture: **[docs/architecture.md](docs/architecture.md)**. Roadmap: **[docs/ROADMAP.md](docs/ROADMAP.md)**.

**Messaging gateway (shipping):** HermesDesk supervises Hermes’ **`python -m gateway.run`** alongside the web assistant. Four adapters are wired through onboarding / Settings with desk-tested flows:

- **Weixin (personal)** — QR login (iLink); writes `WEIXIN_ACCOUNT_ID` + `WEIXIN_TOKEN` to `hermes-home/.env`. Pairing policy follows Hermes env (DMs open vs pairing mode — see gateway troubleshooting strings in-app).
- **QQ Bot** — scan-to-bind; writes `QQ_APP_ID` + `QQ_CLIENT_SECRET`.
- **Feishu / Lark** — scan-to-bind custom app; writes `FEISHU_APP_ID` + `FEISHU_APP_SECRET` (plus optional encrypt/verification keys from the developer console).
- **Telegram** — paste **BotFather** token in-app; writes `TELEGRAM_BOT_TOKEN` (optional allowlists via Hermes Keys).

The gateway process loads the LLM API key from the same Windows Credential Manager path as the desk assistant (`secret_loader`), so bots reuse your configured provider without a second key UI. Controls: **Settings → Messaging Gateway** (start/stop, auto-start when credentials exist, on-disk diagnostics).

**Design notes (history / Weixin Route C):** [docs/gateway-desk-weixin-strategy.md](docs/gateway-desk-weixin-strategy.md) · [docs/gateway-route-c-weixin-validation.md](docs/gateway-route-c-weixin-validation.md).

**Highlights in this line (0.1.x):**

- **In-shell chat** (`/chat`) in the Tauri host: sessions, copy on assistant messages, i18n (en/zh) for the shell UI.  
- **Settings**: workspace copy differs for **normal** vs **power** users; toggling **power user** **restarts** the embedded Python child so `terminal` / `browser` / `code` tools match the switch.  
- **Agent policy**: when power tools are off, a **system-prompt** overlay tells the model to **point users at Settings** instead of hallucinating shell access (see `python/overlays/desk_system_prompt.py`).  
- **Branding**: `logo.png` / `logo.svg` at the repo root; Tauri `cargo tauri icon` generates `tauri/icons/`* (on Windows, if a file is locked, generate to a **temp** `-o` folder and copy — see [docs/troubleshooting.md](docs/troubleshooting.md) for loopback/AV issues).  
- **Control "Desk chat"** (in `hermes/web`) includes a **Copy** action on the assistant block for the embedded dashboard.
- **Messaging gateway**: Weixin, QQ Bot, Feishu/Lark (QR binds), Telegram (token); second Python process; LLM key from credential store.

### What this is

- One `**.msi`**-style Windows install story (per-user, no admin for day-to-day use — see docs)
- **Tray + window** that feels like an app
- Short **onboarding wizard** with minimal jargon, then **chat in the shell** or **open the Hermes console** in the same webview
- Optional **messaging gateway** for **Weixin / QQ Bot / Feishu·Lark / Telegram** — bind credentials and start/stop the adapter process from **Settings**
- **Safe by default**: workspace jail, risky tools **off** until you enable **power user** mode (enforced in the child process, not just a UI flag)
- **L1 “Recipes”** (built-in helpers) for quick local tasks — whitelisted, no arbitrary `code_execution` for that path

### What this is NOT

- **Not** a drop-in replica of **every** upstream Hermes capability and adapter on day one — reinforcement-learning workflows, scheduler/cron depth, the full MCP ecosystem, and adapters beyond the four channels bundled and QA’d here still map to **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** upstream when you need them.
- **Not** a hosted SaaS — we don’t run your inference; you bring credentials.

### Architecture (one screen)

```
┌──────────────────────────────────┐
│  Tauri 2 (Rust + WebView2)       │  ← small shell .exe
│  tray · window · DPAPI secrets   │
│  optional gateway_supervisor     │
│  loopback bridge (approve shell) │
└───────────────┬──────────────────┘
                │ supervises
                ▼
┌──────────────────────────────────┐
│  Embedded Python 3.11 (×2)       │  ← bundled runtime
│  Hermes web + gateway.run       │
│  (stripped core + overlays)     │
└───────────────┬──────────────────┘
                │ HTTP + WS
                ▼
┌──────────────────────────────────┐
│  Shell web (Vite) + /chat        │  ← onboarding, chat, settings
├──────────────────────────────────┤
│  Or: Hermes React (hermes/web)   │  ← full dashboard, Skills, desk chat…
└──────────────────────────────────┘
```

**Expand: repo layout**

```
hermesdesk/
  tauri/        Tauri 2 shell
  python/       Bundle scripts, overlays, L1 helpers, tests
  web/          Shell onboarding + settings (Hermes UI lives under hermes/web)
  hermes/       git submodule → Hermes Agent
  patches/      Small upstream applies during bundle
  docs/         Architecture, safety, skills, troubleshooting
```

### Build from source

**Needs:** Rust **1.80+**, Node **20+**, PowerShell **7+**, and the repo **with submodules**.

```powershell
git clone --recursive https://github.com/ladylydia/hermesdesk.git
cd hermesdesk

# Python runtime bundle (downloads standalone CPython the first time)
.\python\build_bundle.ps1
# After any `hermes/` submodule update (especially `hermes/gateway/`), re-run the line above
# so `python/dist/runtime/hermes/` matches git — otherwise "Start gateway" may exit with code 1
# even when Keys shows messaging credentials (e.g. WEIXIN_*); see docs/troubleshooting.md §12 and docs/gateway-desk-weixin-strategy.md §8.

# Optional: L1 helper unit tests (needs hermes/ submodule)
Set-Location python; python -m unittest discover -s tests -p "test_*.py" -v; Set-Location ..

# Shell web (onboarding / in-shell chat / settings). `npm run build` uses `tsc --noEmit`
# (not `tsc -b`) so `tsconfig.tsbuildinfo` locking on Windows does not break CI — see
# [docs/troubleshooting.md](docs/troubleshooting.md).
cd web; npm ci; npm run build; cd ..

# Run the desktop shell against the bundle
cd tauri; cargo tauri dev

# Release / `.msi` (from repo root). Sidecar/embedded Python ships from
# `hermes/artifacts/desktop-python/`. On Windows, prefer **cmd.exe** or **Developer
# PowerShell** so MSVC / SDK env vars (e.g. `VCToolsVersion`) are set for vcpkg /
# `pydantic-core` wheels; see [docs/embedded-python-bundled.md](docs/embedded-python-bundled.md).
# Optional: `cd tauri` then `cargo tauri icon ..\logo.png` to refresh `tauri\icons\`
# (if Windows says the file is in use, `cargo tauri icon` with `-o` to a temp dir, then copy).
# cargo tauri build
# Output (typical): `target\release\bundle\msi\`, `target\release\*.exe`, sidecar + wheelhouse.
```

- **Signed installer:** [docs/code-signing.md](docs/code-signing.md)  
- **When something breaks:** [docs/troubleshooting.md](docs/troubleshooting.md) (loopback, proxy/VPN, WebView2, **messaging gateway exit 1 / stale bundle §12**, etc.)
- **Documentation index:** [docs/README.md](docs/README.md)

### Security & skills story

- **[docs/skills-security.md](docs/skills-security.md)** — trust model for Skills / Recipes / built-in helpers  
- **[docs/skills-design-decision.md](docs/skills-design-decision.md)** — tiered exposure (L1 / L2 / L3)

### License

**MIT** — see [LICENSE](LICENSE).  
Hermes Agent is **MIT** as well; credit to **[Nous Research](https://nousresearch.com)** for the agent, skills, and tool ecosystem.

---

## 简体中文

### 一句话

**HermesDesk** 是在 **Windows** 上用的 **桌面版 AI 助手**：像普通软件一样安装打开，自带引导配置 **自己的大模型 API Key**，底层跑开源的 **[Hermes Agent](https://github.com/NousResearch/hermes-agent)**。

### 适合谁


|          |                                                                                                                                 |
| -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **目标用户** | 想要 **本机窗口 +托盘**，不想折腾终端、也不想长期挂在浏览器标签里                                                                                            |
| **费用模型** | **自备 Key（BYO）** — 向导里可配 OpenRouter、OpenAI、Anthropic 或自定义 **Base URL**                                                           |
| **文件边界** | 默认围绕 **一个工作区文件夹** 做事，降低误操作面                                                                                                     |
| **技术形态** | **Tauri 2 外壳**（引导、壳内 `/chat`、设置、**消息网关控制**）+ **内嵌 Python**：一路跑 **Hermes Web**（`desktop_entrypoint`），另一路 **`gateway.run`** 承载消息适配器；**WebView2** 中可开 **Hermes React**（`hermes/web`）为完整控制台 |


> **阶段：内测 / 0.1+** — **端到端桌面**已通：引导 → 保存 key → **壳内对话** 与/或 **全功能 Hermes 界面**，可选 **多通道消息网关**，工作区与 **超级用户** 分权。安装包能跑，功能会持续打磨。架构见 **[docs/architecture.md](docs/architecture.md)**；**路线图**见 **[docs/ROADMAP.md](docs/ROADMAP.md)**。

**消息网关（已落地）：** HermesDesk 在本地 **同时托管** Hermes 的 **`python -m gateway.run`** 子进程（与桌面 Web 助手分离）。当前在引导/设置里走通 Desk 测试的 **四条** 渠道：

- **微信（个微）** — 扫码登录（iLink）；写入 `WEIXIN_ACCOUNT_ID`、`WEIXIN_TOKEN` 至 `hermes-home/.env`。是否需首次配对取决于 Hermes 环境变量（如 `WEIXIN_DM_POLICY`），以应用内排障文案为准。
- **QQ 机器人** — 扫码绑定；写入 `QQ_APP_ID`、`QQ_CLIENT_SECRET`。
- **飞书 / Lark** — 扫码创建并绑定自建应用；写入 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`（以及与开放平台一致的加密/校验项，若启用事件订阅）。
- **Telegram** — 在应用中粘贴 **@BotFather** 的 bot token；写入 `TELEGRAM_BOT_TOKEN`（可选白名单等在 Hermes Keys 中维护）。

网关进程通过 `secret_loader` 与 **同一套 Windows Credential Manager** 读取 LLM API key，与各平台机器人共用已配置供应商。控制入口：**设置 → 消息网关**（启动/停止、凭据存在时自动启动、磁盘侧诊断）。

**设计说明（历史方案与路线 C）：** [docs/gateway-desk-weixin-strategy.md](docs/gateway-desk-weixin-strategy.md) · [docs/gateway-route-c-weixin-validation.md](docs/gateway-route-c-weixin-validation.md)。

**本大版本（0.1.x）能力摘要：**

- **壳内 /chat**：会话、**助手消息复制**、壳 UI 中/英。  
- **设置**：普通/超级用户 **工作区文案** 不同；**超级用户** 会 **重启** 内嵌 Python 子进程，让 `terminal` / `browser` / `code` 等工具有无与开关一致。  
- **智能体策略**：关超级用户时，**系统提示**（`python/overlays/desk_system_prompt.py`）引导用户去**设置**开启，避免假装有 shell。  
- **品牌与图标**：根目录 `logo.png` / `logo.svg`；`cargo tauri icon` 生成 `tauri\icons\`；文件被占用时用临时 `-o` 再合并（[docs/troubleshooting.md](docs/troubleshooting.md)）。  
- **控制台 Desk 对话**（`hermes/web`）助手区带 **复制**。
- **消息网关**：微信、QQ、飞书/Lark（扫码绑定）、Telegram（Token）；独立子进程；LLM key 走系统凭据。

**打包版本（建议与仓库维护一致）：** `0.1.0`（见 `tauri/tauri.conf.json`、`web/package.json`）。

### 能做什么 · 不做什么

**能做什么**

- Windows **安装/分发**思路清晰（按用户安装，日常不必管理员 — 细节见文档）
- **原生感**：托盘、窗口、系统凭据（DPAPI）保存密钥相关逻辑
- **短引导** + 之后可在 **壳内 /chat 对话** 或 **在 WebView2 打开** Hermes 全功能页
- 可选 **消息网关**（**微信 / QQ / 飞书·Lark / Telegram**）— 在 **设置** 中完成凭据与网关启停
- **默认更安全**：工作区隔离；高风险能力在子进程里与 **超级用户** 一致，不仅是 UI
- **L1 快捷指令（Recipes）**：内置、白名单的本地小任务（不走任意代码执行那条路）

**不做什么**

- **不是**上游 Hermes **每一种**能力与适配器的 1:1 镜像——例如强化学习整条链路、定时/调度纵深、完整 MCP 生态，以及本文未列作「已打包 Desk 测试」的其它适配器；要啃全量面请直接用上游 **[Hermes Agent](https://github.com/NousResearch/hermes-agent)**。
- **不是**我们托管的云服务 — **推理账单在你选的供应商**，本项目只帮你把桌面与运行时拼好。

### 架构一图

与 English 中 ASCII 图一致：**Tauri 壳**（监管两条 Python 子进程）→ **`desktop_entrypoint` + `gateway.run`**（Hermes + overlays，本地随机 HTTP/WS）→ **壳内 Vite + `/chat`** 或 **Hermes React（`hermes/web`）** 在 **WebView2** 中加载。

**展开：目录结构**

```
hermesdesk/
  tauri/        桌面壳（Rust + Tauri 2）
  python/     打包脚本、运行时 overlay、L1 helpers、测试
  web/        壳侧引导与设置（Hermes 仪表盘在 hermes/web）
  hermes/     git 子模块：Hermes Agent
  patches/    打包时对上游的小补丁
  docs/       架构、安全、Skills、排障等
```

### 从源码构建（Windows）

**准备：** Rust **1.80+**、Node **20+**、PowerShell **7+**，并且克隆时带上 **子模块**。

```powershell
git clone --recursive https://github.com/ladylydia/hermesdesk.git
cd hermesdesk

# 打 Python 运行时包（首次会下载独立 CPython）
.\python\build_bundle.ps1
# 更新 hermes 子模块（尤其 gateway）后务必再执行上一行，使 python/dist/runtime/hermes/ 与仓库一致；
# 否则设置里「启动网关」可能立刻 exit code 1，而 Keys 里已有消息凭据（如 WEIXIN_*）。见 docs/troubleshooting.md §12、
# docs/gateway-desk-weixin-strategy.md §8。

# 可选：L1 内置助手相关单元测试（需要 hermes/ 子模块）
Set-Location python; python -m unittest discover -s tests -p "test_*.py" -v; Set-Location ..

# 壳上 Web（引导、壳内 /chat、设置）。`npm run build` 使用 `tsc --noEmit`（非 `tsc -b`），
# 避免 Windows 上 `tsconfig.tsbuildinfo` 锁导致构建失败，见 [docs/troubleshooting.md](docs/troubleshooting.md)。
cd web; npm ci; npm run build; cd ..

# 开发：启动桌面壳
cd tauri; cargo tauri dev

# 发布 / 打 `.msi`（在仓库根目录；侧载 Python 来自 `hermes/artifacts/desktop-python/`）。
# Windows 上建议在 **cmd** 或 **Developer PowerShell** 中构建，以便 MSVC / SDK 环境供 vcpkg
# 与 `pydantic-core` 轮子；详见 [docs/embedded-python-bundled.md](docs/embedded-python-bundled.md)。
# 可选：`cd tauri` 后 `cargo tauri icon ..\logo.png` 更新 `tauri\icons\`；若报文件占用，可 `-o` 到临时目录再拷贝。
# cargo tauri build
# 常见产物：`target\release\bundle\msi\`、可执行与 sidecar + wheelhouse。
```

- **代码签名 / 安装包：** [docs/code-signing.md](docs/code-signing.md)  
- **常见问题（白屏、卡住、代理抢 loopback、消息网关 exit 1 / 未重建 runtime §12 等）：** [docs/troubleshooting.md](docs/troubleshooting.md)  
- **文档索引：** [docs/README.md](docs/README.md)

### 安全与 Skills 设计

- **[docs/skills-security.md](docs/skills-security.md)** — 对 Skills / 快捷指令 / 内置助手的信任说明  
- **[docs/skills-design-decision.md](docs/skills-design-decision.md)** — L1 / L2 / L3 分层与暴露策略（ADR）

### 开源协议

**MIT**，见 [LICENSE](LICENSE)。  
子模块 Hermes Agent 亦为 **MIT**；核心 agent 与工具生态致谢 **[Nous Research](https://nousresearch.com)**。