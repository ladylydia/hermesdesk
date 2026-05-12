# Kabuqina 测试方案

> 覆盖范围：Gateway 消息渠道、安全防护、前端交互、API/LLM、构建部署  
> 用途：供 AI 生成详细测试用例（given/when/then 格式），每项可独立展开

---

## 1. Gateway — 消息渠道连通性

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|-------------|
| P0 | Telegram bot 私聊：陌生人发消息 → 收到配对码 | 同一用户连续发 5 条 → 仅回复第一条（rate limit）；配对码过期（1h）后重发 |
| P0 | Telegram bot 私聊：已授权用户发消息 → 正常回复 | 回复包含图片/文档/长文本（>4096 chars）时格式正常 |
| P0 | Telegram 群聊：@mention bot → 回复 | 未 @mention → 不应回复（`TELEGRAM_REQUIRE_MENTION=true` 默认值） |
| P0 | 微信 bot 私聊：收发消息正常 | 微信回复超长文本截断；图片/语音消息处理 |
| P1 | 微信 Route C 扫码绑定流程 | 扫码超时、重复扫码、已绑定账号换绑 |
| P1 | QQ bot 私聊/群聊 | 沙盒模式 vs 生产模式差异 |
| P1 | 飞书 WebSocket 连接 | 断线重连（`_platform_reconnect_watcher`）；Webhook 模式签名验证 |
| P2 | Telegram 网络不通时 fallback IP | `telegram_network.py` DoH 解析 + seed IP 回退 |
| P3 | 钉钉 / WhatsApp / Discord / Mattermost 等 | 仅验证连接，不需深度测试 |

---

## 2. Gateway — 安全防护（10 条修复）

| # | 测试项 | 边界 / 异常 |
|---|--------|------------|
| 1 | `TELEGRAM_REQUIRE_MENTION` 默认 `true` → 群聊不 @mention 无回复 | 设置为 `false` 后所有群消息触发 |
| 2 | `/yolo` 命令：未在 `YOLO_ALLOWED_USERS` 中的用户执行 → 拒绝 | 在白名单中的用户正常开关 |
| 3 | 网关文件沙箱：agent 尝试写 `/etc/` 或 `C:\Windows\` → PermissionError | 读写工作目录外任意路径均被拦截 |
| 4 | `GATEWAY_SHELL_ENABLED` 未设置时 terminal / exec / browser / code_execution 工具集不可用 | 设置后恢复可用 |
| 5 | 飞书 Webhook 未配 `encrypt_key` → 启动打印 WARNING | 配置后不再警告 |
| 6 | `GATEWAY_OWNER_IDS` 限制：非 owner 执行 `/restart` `/model` `/personality` `/sethome` `/debug` `/update` `/reload-mcp` `/stop` → 拒绝 | 空字符串 = 不限制（兼容旧行为） |
| 7 | `GATEWAY_ALLOW_ALL_USERS` 激活 → 启动时打印 SECURITY 级别 WARNING | 关闭后无警告 |
| 8 | 网关启动时对 `.env` 执行 `chmod 0600`（POSIX） | Windows 上 no-op 不报错 |
| 9 | Webhook 含 `X-Webhook-Timestamp` → 超时请求被拒绝（默认 300s 容差） | 无 timestamp 头时正常通过（仅签名验证） |
| 10 | `thread_sessions_per_user` 默认 `True` → 群话题中不同用户 session 隔离 | 设置为 `False` 后共享 |

---

## 3. Gateway — 配对审批

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P0 | 设置页显示待审批配对请求列表 | 无请求时显示空状态；多条请求按时间排序 |
| P0 | 点击"批准"→ 用户立刻可正常对话 | 批准后配对码从 pending 移到 approved |
| P0 | 点击"撤销"→ 用户发消息重新收到配对码 | 撤销后 approved 列表无该用户 |
| P0 | 配对码过期（1h）→ 不在列表中显示 | 过期码被自动清除 |
| P1 | 同一用户 10 分钟内重复请求 → 仅回复第一条 | rate limit 生效 |
| P1 | 5 次错误审批尝试 → lockout | lockout 持续时间 1h |

---

## 4. Gateway — 进程生命周期

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P0 | 壳内点击"停止网关"→ 网关进程终止 | 锁文件被清理（模块级 `[hermes-desklock]` stderr 输出可见） |
| P0 | 停止后立即点击"启动网关"→ 新网关正常启动无锁冲突 | 快速连续 3 次停止 → 启动 |
| P0 | 网关 crash 后自动重启（reconnect watcher） | crash 期间消息不丢失（消息队列缓存） |
| P1 | `cargo tauri dev` 重启 → 旧进程被杀、新进程正常 | 不残留僵尸 PID、锁文件自动清 |
| P2 | `.\python\build_bundle.ps1` 后首次启动 | 验证 patch apply 成功、bundle 无 PyYAML 错误 |

---

## 5. 前端 — 壳内聊天

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P0 | 壳内聊天输入消息 → 发送 → 收到 AI 回复 | 空消息不能发送；API key 未配置时弹出引导 |
| P0 | 发送含附件的消息 | 附件 >12MB 被拒绝；>6 个附件截断 |
| P1 | 停止生成按钮 | `agent.interrupt()` 生效；停止后仍可继续对话 |
| P1 | 多轮对话上下文保持 | 第 3 轮仍记住第 1 轮内容 |
| P1 | 侧边栏会话列表 | 新建 / 删除 / 切换会话；会话标题自动生成 |

---

## 6. 前端 — 引导 + 设置

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P0 | 引导流程：选择 DeepSeek → 输入 API Key → 完成引导 | 跳过 API 配置后仍可完成引导 |
| P1 | 引导流程：展开"更多提供商"→ 选 **OpenRouter**（可选）或 **自定义** | 自定义页面提供商下拉框预填生效 |
| P1 | 设置页 → 字体大小切换 | 切换后即时生效、关闭重开保持 |
| P1 | 设置页 → 语言切换（中 / 英） | 所有页面全部翻译 |
| P2 | 设置页 → 深色模式 | 跟随系统设置 |

---

## 7. 前端 — Telegram / 微信 / QQ / 飞书配置

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P1 | Telegram 配置块：保存 Token → 重启 Hermes → 已配置状态 | Token 验证失败时显示错误 |
| P1 | 飞书 QR 扫码流程 | 扫码超时取消、重复扫码换绑 |
| P1 | QQ QR 扫码流程 | 同上 |
| P1 | 微信 Route C 扫码流程 | 同上 |
| P2 | 设置页 → 消息网关启动/停止 | 状态指示器正确（运行中 / 未运行 / 启动中） |

---

## 8. API / LLM — 模型调用

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P0 | DeepSeek v4 Flash reasoning=high → 正常回复无 400 | 多轮对话中 tool-calls-only 的回合不出 `reasoning_content missing` 错误 |
| P1 | API key 过期 → 返回友好错误提示而非 crash | 网关返回 401 不退出进程 |
| P1 | 模型切换 `/model` 命令 | Gateway 模式切换后新会话使用新模型 |
| P2 | 自定义 provider 配置（base_url + model + key） | 验证 url 格式错误、连接超时等异常 |

---

## 9. 构建 & 部署

| 优先级 | 测试项 | 边界 / 异常 |
|--------|--------|------------|
| P1 | `.\python\build_bundle.ps1` 干净构建 | 首次构建、增量构建（site-packages 已存在） |
| P1 | patch 已 apply 时 build 跳过 → 不报错 | patch 未 apply 时正常 apply |
| P2 | `.\scripts\sync_upstream.ps1 -DryRun` 所有检查通过 | hermes 有意外的脏文件时拒绝 |
| P2 | `cargo tauri dev` 冷启动（首次编译） | Rust 编译通过、Vite 热更新正常 |

---

## 10. 已知测试缺口（暂无自动化覆盖）

| 缺口 | 建议 |
|------|------|
| 所有 Gateway 平台适配器无集成测试 | 至少对 Telegram / 微信各加 1 个端到端手动用例 |
| `path_guard.py` 无独立单元测试 | 需要 mock workspace 目录测试边界路径 |
| `sync_upstream.ps1` 无 CI 集成 | 每次手动执行前先 `-DryRun` |
| 前端 ChatPage / Settings 无组件测试 | 可后续引入 vitest + React Testing Library |
| 锁清理逻辑无有效回归测试 | 手动停止 → 启动 3 次验证 `[hermes-desklock]` stderr 输出 |
| 10 条安全修复无专项安全测试 | 至少每条 1 个手动验证 |
| `build_bundle.ps1` patch 流程无回归测试 | 模拟脏工作树 + 干净工作树两种场景 |

---

## 执行汇总 (2026-05-01)

| 阶段 | 用例数 | 通过 | 失败 | 跳过 | 待实现 |
|------|--------|------|------|------|--------|
| §1 Gateway 消息渠道 | 12 | 0 | 0 | 12 | 0 |
| §2 Gateway 安全 | 10 | 2 | 0 | 8 | 0 |
| §3 Gateway 配对 | 6 | 0 | 0 | 6 | 0 |
| §4 Gateway 生命周期 | 6 | 4 | 0 | 1 | 1 |
| §5/6/7 前端 | 15 | 1 | 0 | 14 | 0 |
| §8 API/LLM | 6 | 3 | 0 | 3 | 0 |
| §9 构建 | 4 | 2 | 0 | 2 | 0 |
| **合计** | **59** | **12** | **0** | **46** | **1** |

**关键发现**：
- TC-GL-002 FAIL：网关首轮连接失败退出 → **已修复** `gateway/run.py:2774-2784` + `tauri/src/lib.rs`/`gateway_supervisor.rs`（文件清理）
- TC-GL-001/002/003 **已全部 PASS**
- TC-GL-004 NOT IMPL：Rust 侧无进程级 crash 重启
- 大量 SKIP 用例需要实际平台凭证（Telegram/微信/QQ/飞书 Token）
