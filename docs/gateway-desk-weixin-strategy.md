# Kabuqina：消息网关接入说明（路线对比 · 个微深度 · 当前落地）

本文档说明：为什么 Desk 选用 **路线 C**（本地 Python worker + Tauri IPC）、**个人微信（Weixin / iLink）** 在上游中的位置，以及 **当前 Kabuqina 已交付** 的四类消息渠道实现。前半为设计对照，后半为与代码一致的产品/工程事实。

---

## 1. 背景：网关能力在上游哪里

- **运行时**：`hermes/gateway/` — 各平台适配器（`platforms/*.py`）、进程入口 `run.py` 等。
- **交互式配置（含扫码）**：`hermes/hermes_cli/gateway.py` 中的 `_setup_weixin`、`_setup_qqbot`、`_setup_feishu` 等；`hermes/hermes_cli/setup.py` 通过 `hermes gateway setup` 分发给各 `_setup_*`。
- **个人微信（个微）**：
  - 协议与扫码：`hermes/gateway/platforms/weixin.py` — `qr_login()`（腾讯 iLink：`get_bot_qrcode` / `get_qrcode_status`）。
  - CLI 向导：`hermes/hermes_cli/gateway.py` — `_setup_weixin()` 内 `asyncio.run(qr_login(...))`，成功后写入 `WEIXIN_ACCOUNT_ID`、`WEIXIN_TOKEN` 等。

Hermes **本地 Web**（`hermes_cli/web_server.py`）对网关的暴露主要是：

- `GET /api/status`：网关是否在跑、平台状态等（公开路径之一）。
- `GET/PUT /api/env`：读写与网关相关的环境变量（Desk 下实际落盘为 **`{数据目录}/hermes-home/.env`**，见 `desktop_entrypoint.py` 对 `HERMES_HOME` 的重定向；需会话 token）。

**没有**现成的 HTTP 接口用于「启动微信/QQ/飞书扫码 / 轮询绑定状态」——这些流程在上游主要在 **Python 异步逻辑 + CLI** 中完成，而非 REST。 Desk 因此走了 **路线 C**（见下文），而不是仅靠嵌 WebView 调现有 HTTP。

---

## 2. 在 Desk 侧接入网关的三条路线（设计对照）

| 路线 | 做法 | 优点 | 缺点 / 风险 |
| --- | --- | --- | --- |
| **A. 嵌 WebView，只调 Hermes 已有 HTTP** | Hermes React 控制台；`/api/env`、`/api/status` | 不改上游、无新 HTTP 面 | **无法**完成微信/QQ/飞书扫码绑定；手填密钥体验差 |
| **B. 改子模块，在 `web_server` 增薄 HTTP** | 包装 `qr_login`、QQ `create_bind_task`+`poll` 等 | Web 内体验统一 | 分叉/合并成本；新端点需鉴权与审计 |
| **C. Desk 调本地进程（bundle 内 Python）** | Tauri 起子进程，`import` 上游 `gateway.platforms.*` 等同 CLI 逻辑 | **少动** `web_server`；子模块易跟进 | 需 JSON/IPC；二维码接到壳 UI；打包路径固定 |

**维护角度**：路线 **C** 与「不扩大 Hermes 本机 HTTP 表面积」一致；路线 **B** 适合愿意维护分叉或向上游提 PR 的团队。

---

## 3. Kabuqina 当前结论（与实现对齐）

以下为 **已实现** 的聚合结论，取代旧版「第一阶段仅个微、不做 QQ/飞书」的排期表述。

1. **路线选型**：Desk 采用 **路线 C**。扫码类渠道由 **短时 Python worker**（`weixin_qr_worker.py`、`qqbot_qr_worker.py`、`feishu_qr_worker.py`）+ **Tauri command** 驱动；**不改** Hermes `web_server` 增加扫码 REST。
2. **长期网关进程**：与上游 `hermes gateway run` 等价，由 **`tauri/src/gateway_supervisor.rs`** spawn **第二个**嵌入式 Python 子进程（`python -m gateway.run`）。主进程里的 Hermes Web 仍通过 **`strip_shims`** 避免把 `gateway.run.main` 当入口执行；**磁盘上的 `hermes/gateway/` 完整存在**，仅进程边界不同 — 详见 **`docs/architecture.md`**。
3. **已交付的消息渠道（壳内引导 + 设置）**：
   - **微信（个微）**：Route C / iLink QR；`tauri/src/weixin_qr.rs`，`web/src/components/WeixinQrRouteCBlock.tsx`。
   - **QQ 机器人**：扫码绑定 OpenAPI v2；`tauri/src/qqbot_qr.rs`，`web/src/components/QqbotQrRouteBlock.tsx`。
   - **飞书 / Lark（自建应用）**：扫码创建/绑定应用；`tauri/src/feishu_qr.rs`，`web/src/components/FeishuQrRouteBlock.tsx`。
   - **Telegram**：`@BotFather` token 写入；`tauri/src/telegram_env.rs`，`web/src/components/TelegramSettingsBlock.tsx`（非扫码）。
4. **LLM Key**：网关进程与 Hermes Web 共用 **Credential Manager / `secret_loader`** 注入的供应商凭据，无需为各机器再配一套 Key UI。
5. **全浏览器绑定**：若未来希望 **仅** 在 Hermes Web 内完成扫码，仍可评估路线 **B** 或向上游提交薄 API；与当前 Desk 实现 **并行** 的是产品决策，而非本文件前提。

---

## 4. 个人微信：技术切片（已实现，可供审计）

下列条目在早期用于排期；**当前代码已覆盖**，保留为检查清单：

1. **`HERMES_HOME`**：与 Desk 约定一致 → `{HERMESDESK_DATA_DIR}/hermes-home`。
2. **Tauri**：`cmd_weixin_qr_start` / `status` / `cancel`，`cmd_weixin_env_status`；worker 见 `python/src/weixin_qr_worker.py`。
3. **前端**：`WeixinQrRouteCBlock` — 二维码 URL、轮询、成功后 **重启嵌入式 Hermes** 并尽量 **拉起网关**（`lib.rs` 中 `ensure_gateway_after_hermes_respawn`）。
4. **落盘**：`WEIXIN_*` 写入 `hermes-home/.env`；配对策略（如 `WEIXIN_DM_POLICY`）遵循 Hermes 语义，壳内 Settings 含排障文案与 **配对**命令（`tauri/src/pairing.rs`）。
5. **安全**：本机触发；日志避免明文 token；超时/取消路径在 worker 与 Tauri 侧实现。

---

## 5. 上游代码索引（便于跳转）

| 主题 | 路径 |
| --- | --- |
| 微信个微与 `qr_login` | `hermes/gateway/platforms/weixin.py` |
| CLI 微信向导 | `hermes/hermes_cli/gateway.py` → `_setup_weixin` |
| QQ 扫码绑定 | `hermes/gateway/platforms/qqbot/onboard.py`；CLI `_setup_qqbot`、`_qqbot_qr_flow` |
| 飞书向导（CLI） | `hermes/hermes_cli/gateway.py` → `_setup_feishu` 等 |
| 本地 Web API | `hermes/hermes_cli/web_server.py`（`/api/env`、`/api/status`） |

---

## 6. 文档维护

架构与路线图请以 **`docs/architecture.md`**、**`docs/ROADMAP.md`**、根目录 **`README.md`** 为准；本文侧重 **网关路线取舍** 与 **个微/iLink** 细节。

网关 **exit code 1**、runtime 与子模块不一致 → **`docs/troubleshooting.md` §12**、`python/build_bundle.ps1`。

**文档版本**：随仓库迭代；目录结构以子模块 **`hermes/`** 为准。

---

## 7. 验证执行（路线 C / iLink）

见 **[gateway-route-c-weixin-validation.md](gateway-route-c-weixin-validation.md)**：`get_bot_qrcode` 字段、打包解释器探测命令、与 Desk 原型对应关系。

---

## 8. Kabuqina 实现一览：网关子进程 · 扫码/token · 设置页

### 8.1 长期网关进程

除 **短时扫码 worker** 外，Desk 按需维持 **消息网关** OS 子进程（与上游 `hermes gateway run` 等价，实现见 `gateway_supervisor.rs`）。

| 项 | 说明 |
| --- | --- |
| **启动** | `bundle_dir/python/python.exe -m gateway.run`；`PYTHONPATH` 指向 `site-packages` + `hermes`；`HERMES_HOME` 指向 Desk 的 `hermes-home`（详见 `gateway_supervisor.rs`） |
| **`HERMES_HOME`** | `{HERMESDESK_DATA_DIR}/hermes-home`，与嵌入式 Web、worker 写 `.env` 一致 |
| **凭据** | `hermes-home/.env`（与 Hermes Keys `/api/env` 写入位置一致） |
| **壳 UI** | **设置 → 消息网关**：启停、冷启动自动拉起开关、`gateway_state.json` / `gateway.log` 诊断；`cmd_gateway_status` |
| **bundle 新旧** | 探测 `hermes/gateway/run.py` 是否含「首轮连接失败仍保活」类逻辑；前端字段 **`embeddedGatewayStartupSurvival`** |
| **Hermes 重启后** | 若 `.env` 已有消息凭据，尝试 **`ensure_gateway_after_hermes_respawn`** 拉启网关 |

**排障**：Keys 已配仍秒退 → 优先 **stale runtime**（未重跑 **`python/build_bundle.ps1`**）。见 **troubleshooting §12**。

### 8.2 各渠道与主要源文件

| 渠道 | Desk 交互 | Worker / Rust / 前端（主要入口） |
| --- | --- | --- |
| **微信（个微）** | Route C 扫码 | `weixin_qr_worker.py`，`weixin_qr.rs`，`WeixinQrRouteCBlock.tsx`；配对 `pairing.rs` |
| **QQ 机器人** | 扫码绑定 | `qqbot_qr_worker.py`，`qqbot_qr.rs`，`QqbotQrRouteBlock.tsx` |
| **飞书 / Lark** | 扫码绑定自建应用 | `feishu_qr_worker.py`，`feishu_qr.rs`，`FeishuQrRouteBlock.tsx` |
| **Telegram** | Token 表单 | `telegram_env.rs`，`TelegramSettingsBlock.tsx` |

**「已配置」语义（微信）**：`cmd_weixin_env_status` 仅表示 **`WEIXIN_ACCOUNT_ID` 与 `WEIXIN_TOKEN`** 同时在 **`hermes-home/.env`** 中非空；与 iLink 当下是否连通无关。缺一则 UI 提示凭据不完整。

**Telegram / 飞书 / QQ**：设置页对各变量集的检测逻辑见对应 **`telegram_env` / `feishu_env` / `qq_env`** 与组件文案；网关进程读取同一 `.env`。
