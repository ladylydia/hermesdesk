<div align="center">

# HermesDesk

**A friendly Windows desktop AI assistant** — double-click install, guided setup, your own API key.  
Powered by the open-source [**Hermes Agent**](https://github.com/NousResearch/hermes-agent).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D4?logo=windows&logoColor=white)](https://github.com/ladylydia/hermesdesk)
[![Status](https://img.shields.io/badge/status-early%20alpha-orange)](https://github.com/ladylydia/hermesdesk)

[English](#english) · [简体中文](#简体中文)

</div>

---

## English

### At a glance

| | |
| :--- | :--- |
| **Who it’s for** | People who want a **native Windows app**, not a terminal or a browser tab |
| **How you pay for AI** | **BYO key** — onboarding helps you connect OpenRouter, OpenAI, Anthropic, or a custom base URL |
| **Where files live** | A **single workspace folder** (safe-by-default mental model) |
| **What’s inside** | **Tauri 2** shell + **embedded Python** running a **pruned Hermes** + Hermes’ own **React** UI in **WebView2** |

> **Status: early alpha** — fine for developers **dogfooding from source**. The `.msi` path exists but expect rough edges. Full architecture: [**docs/architecture.md**](docs/architecture.md).

### What this is

- One **`.msi`**-style Windows install story (per-user, no admin for day-to-day use — see docs)
- **Tray + window** that feels like an app
- Short **onboarding wizard** with minimal jargon
- **Safe by default**: workspace jail, risky tools **off** until you enable **power user** mode
- **L1 “Recipes”** (built-in helpers) for quick local tasks — whitelisted, no arbitrary `code_execution` for that path

### What this is NOT

- **Not** the full upstream Hermes power surface (RL, multi-platform gateway, cron, MCP, etc.) — use [**Hermes Agent**](https://github.com/NousResearch/hermes-agent) upstream for that.
- **Not** a hosted SaaS — we don’t run your inference; you bring credentials.

### Architecture (one screen)

```
┌──────────────────────────────────┐
│  Tauri 2 (Rust + WebView2)       │  ← small shell .exe
│  tray · window · DPAPI secrets  │
│  loopback bridge (approve shell) │
└───────────────┬──────────────────┘
                │ supervises
                ▼
┌──────────────────────────────────┐
│  Embedded Python 3.11            │  ← bundled runtime
│  Hermes (stripped) + overlays    │
│  serves http://127.0.0.1:RANDOM  │
└───────────────┬──────────────────┘
                │ HTTP + WS
                ▼
┌──────────────────────────────────┐
│  React dashboard (Hermes web/)   │  ← chat, settings, Skills…
└──────────────────────────────────┘
```

<details>
<summary><strong>Expand: repo layout</strong></summary>

```
hermesdesk/
  tauri/        Tauri 2 shell
  python/       Bundle scripts, overlays, L1 helpers, tests
  web/          Shell onboarding + settings (Hermes UI lives under hermes/web)
  hermes/       git submodule → Hermes Agent
  patches/      Small upstream applies during bundle
  docs/         Architecture, safety, skills, troubleshooting
```

</details>

### Build from source

**Needs:** Rust **1.80+**, Node **20+**, PowerShell **7+**, and the repo **with submodules**.

```powershell
git clone --recursive https://github.com/ladylydia/hermesdesk.git
cd hermesdesk

# Python runtime bundle (downloads standalone CPython the first time)
.\python\build_bundle.ps1

# Optional: L1 helper unit tests (needs hermes/ submodule)
Set-Location python; python -m unittest discover -s tests -p "test_*.py" -v; Set-Location ..

# Shell web (onboarding / settings)
cd web; npm ci; npm run build; cd ..

# Run the desktop shell against the bundle
cd tauri; cargo tauri dev
```

- **Signed installer:** [docs/code-signing.md](docs/code-signing.md)  
- **When something breaks:** [docs/troubleshooting.md](docs/troubleshooting.md) (loopback, proxy/VPN, WebView2, etc.)

### Security & skills story

- [**docs/skills-security.md**](docs/skills-security.md) — trust model for Skills / Recipes / built-in helpers  
- [**docs/skills-design-decision.md**](docs/skills-design-decision.md) — tiered exposure (L1 / L2 / L3)

### License

**MIT** — see [LICENSE](LICENSE).  
Hermes Agent is **MIT** as well; credit to [**Nous Research**](https://nousresearch.com) for the agent, skills, and tool ecosystem.

---

## 简体中文

### 一句话

**HermesDesk** 是在 **Windows** 上用的 **桌面版 AI 助手**：像普通软件一样安装打开，自带引导配置 **自己的大模型 API Key**，底层跑开源的 [**Hermes Agent**](https://github.com/NousResearch/hermes-agent)。

### 适合谁

| | |
| :--- | :--- |
| **目标用户** | 想要 **本机窗口 +托盘**，不想折腾终端、也不想长期挂在浏览器标签里 |
| **费用模型** | **自备 Key（BYO）** — 向导里可配 OpenRouter、OpenAI、Anthropic 或自定义 **Base URL** |
| **文件边界** | 默认围绕 **一个工作区文件夹** 做事，降低误操作面 |
| **技术形态** | **Tauri 2** 壳 + **内嵌 Python** 跑裁剪后的 **Hermes**，界面用 **WebView2** 加载 Hermes 自带的 **React** 仪表盘 |

> **当前阶段：early alpha（早期内测）** — 适合 **从源码自己编译体验**；安装包链路已有，但边角可能粗糙。架构说明见 [**docs/architecture.md**](docs/architecture.md)。

### 能做什么 · 不做什么

**能做什么**

- Windows **安装/分发**思路清晰（按用户安装，日常不必管理员 — 细节见文档）
- **原生感**：托盘、窗口、系统凭据（DPAPI）保存密钥相关逻辑
- **短引导**：尽量不用黑话的 onboarding
- **默认更安全**：工作区隔离；高风险能力默认关闭，需要再开 **Power user**
- **L1 快捷指令（Recipes）**：内置、白名单的本地小任务（不走任意代码执行那条路）

**不做什么**

- **不是**上游 Hermes 的「全家桶」能力（RL、多端网关、定时任务、MCP 等）——要完整能力请直接用上游 [**Hermes Agent**](https://github.com/NousResearch/hermes-agent)。
- **不是**我们托管的云服务 — **推理账单在你选的供应商**，本项目只帮你把桌面与运行时拼好。

### 架构一图

与上方 English 小节中的 ASCII 图相同：**Tauri 壳 → 内嵌 Python（Hermes + overlays）→ 本地随机端口上的 Web UI（WebView2）**。

<details>
<summary><strong>展开：目录结构</strong></summary>

```
hermesdesk/
  tauri/        桌面壳（Rust + Tauri 2）
  python/     打包脚本、运行时 overlay、L1 helpers、测试
  web/        壳侧引导与设置（Hermes 仪表盘在 hermes/web）
  hermes/     git 子模块：Hermes Agent
  patches/    打包时对上游的小补丁
  docs/       架构、安全、Skills、排障等
```

</details>

### 从源码构建（Windows）

**准备：** Rust **1.80+**、Node **20+**、PowerShell **7+**，并且克隆时带上 **子模块**。

```powershell
git clone --recursive https://github.com/ladylydia/hermesdesk.git
cd hermesdesk

# 打 Python 运行时包（首次会下载独立 CPython）
.\python\build_bundle.ps1

# 可选：L1 内置助手相关单元测试（需要 hermes/ 子模块）
Set-Location python; python -m unittest discover -s tests -p "test_*.py" -v; Set-Location ..

# 壳上的 Web（引导页 / 设置等）
cd web; npm ci; npm run build; cd ..

# 启动桌面壳（开发模式）
cd tauri; cargo tauri dev
```

- **代码签名 / 安装包：** [docs/code-signing.md](docs/code-signing.md)  
- **常见问题（白屏、卡住、代理抢 loopback 等）：** [docs/troubleshooting.md](docs/troubleshooting.md)

### 安全与 Skills 设计

- [**docs/skills-security.md**](docs/skills-security.md) — 对 Skills / 快捷指令 / 内置助手的信任说明  
- [**docs/skills-design-decision.md**](docs/skills-design-decision.md) — L1 / L2 / L3 分层与暴露策略（ADR）

### 开源协议

**MIT**，见 [LICENSE](LICENSE)。  
子模块 Hermes Agent 亦为 **MIT**；核心 agent 与工具生态致谢 [**Nous Research**](https://nousresearch.com)。
