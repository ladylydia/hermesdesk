# Gateway — 消息渠道连通性 + 安全防护 + 配对审批

> 对应 test-plan.md §1 / §2 / §3
> 优先级：P0 > P1 > P2 > P3（P0 为冒烟测试，必须全部通过方可进入下一轮）

---

## 环境前置条件（所有用例共享）

| 项 | 要求 |
|----|------|
| OS | Windows 10/11（测试网关进程管理） |
| Kabuqina | 最新安装包或 `cargo tauri dev` 启动 |
| 网络 | 可访问 Telegram API / 微信服务器 / 飞书服务器 / QQ 服务器 |
| 测试账号 | `[待填写: Telegram Test Bot Token]` |
| | `[待填写: 微信 Route C Test QR 绑定账号]` |
| | `[待填写: QQ Bot Test 账号]` |
| | `[待填写: 飞书 Test App ID & App Secret]` |
| | `[待填写: DeepSeek API Key]` |
| 配置文件 | `hermes-home/.env` 已备份，测试后可还原 |

---

## 一、消息渠道连通性

### TC-GM-001 [P0] Telegram Bot 私聊 — 陌生人首次发消息 → 收到配对码

| 属性 | 内容 |
|------|------|
| **Given** | Kabuqina 已启动，网关已启动，Telegram Bot Token 已配置；用户 A 从未与 Bot 交互过 |
| **When** | 用户 A 在 Telegram 私聊中向 Bot 发送任意消息（如 `"Hello"`） |
| **Then** | Bot 回复一条包含配对码（pairing code）的消息；配对码格式为 6 位数字；同时 Kabuqina 设置页 → 配对审批列表出现该用户的待审批请求 |

**手工执行步骤：**
1. 确保 Kabuqina 壳内设置页 → Telegram 区块已保存有效的 Bot Token
2. 点击"启动网关"，等待状态变为"运行中"
3. 使用一个全新的 Telegram 账号（从未与该 Bot 私聊过）发送 `"Hello"`
4. 验证 Bot 是否在 5 秒内回复了包含 6 位配对码的消息
5. 切换回 Kabuqina 设置页 → 配对审批，验证列表中出现该用户的新请求

**自动化模板：**
```python
# Pseudocode — 需 Telegram Test Bot + 模拟用户 client
simulate_telegram_user_sends("Hello")
wait_for(condition=lambda: get_last_bot_reply().contains("pairing code"), timeout=5)
assert pairing_code_matches_format(r"\d{6}")
assert hermesdesk_pending_list_contains(new_user_id)
```

---

### TC-GM-002 [P0] Telegram Bot 私聊 — 已授权用户发消息 → 正常回复

| 属性 | 内容 |
|------|------|
| **Given** | 用户 B 已完成配对审批（状态为 approved）；Bot 已配置 LLM Provider（DeepSeek） |
| **When** | 用户 B 发送消息 `"What is the weather today?"` |
| **Then** | Bot 在 10 秒内回复一条有意义的文本消息；回复内容不应包含配对码 |

**手工执行步骤：**
1. 确保用户 B 在已批准列表中（如不在，先执行 TC-GM-003 批准流程）
2. 用户 B 发送测试消息
3. 验证回复是否为正常的 AI 对话内容（非配对码提示）
4. 记录响应时间（应 < 10s）

**边界验证（同一次会话）：**
- 发送附件（图片/文档）→ 消息中应包含文件引用信息
- 发送超过 4096 字符的长文本 → Bot 正常分段回复，格式不乱码

---

### TC-GM-003 [P0] Telegram 群聊 — @mention Bot → 回复

| 属性 | 内容 |
|------|------|
| **Given** | Bot 已被添加到某个 Telegram 群组；`TELEGRAM_REQUIRE_MENTION=true`（默认值） |
| **When** | 群成员发送消息 `@BotUsername hello` |
| **Then** | Bot 回复该消息；回复内容为正常的 AI 对话 |

**手工执行步骤：**
1. 将 Bot 加入一个测试群组
2. 群成员 A 发送 `@BotUsername 你好`
3. 验证 Bot 是否回复且内容合理
4. 发送一条不带 @mention 的普通消息 → **验证 Bot 不应回复**

---

### TC-GM-004 [P0] Telegram 群聊 — 未 @mention → 不应回复

| 属性 | 内容 |
|------|------|
| **Given** | 同上；`TELEGRAM_REQUIRE_MENTION=true` |
| **When** | 群成员发送一条普通消息，不含 @BotUsername |
| **Then** | Bot **不回复**任何内容；网关日志中应记录 `mention required, ignoring` 级别为 DEBUG |

---

### TC-GM-005 [P0] 微信 Bot 私聊 — 收发消息正常

| 属性 | 内容 |
|------|------|
| **Given** | 微信 Route C 扫码绑定已完成；`.env` 中包含微信相关凭证 |
| **When** | 用户通过微信私聊向 Bot 发送消息 `"测试消息"` |
| **Then** | Bot 正常回复；消息收发延迟 < 10s |

**手工执行步骤：**
1. 确保微信扫码绑定流程已完成（参见 TC-FE-013）
2. 使用绑定的微信账号发送测试消息
3. 验证收到 Bot 回复

**边界验证：**
- 超长文本（>2000 字符）→ 微信自动截断，Bot 应分段发送
- 发送图片/语音 → Bot 回复中包含对媒体内容的引用或处理提示

---

### TC-GM-006 [P1] 微信 Route C 扫码绑定流程

| 属性 | 内容 |
|------|------|
| **Given** | Kabuqina 设置页已打开；微信 Route C 选项可见 |
| **When** | 点击"扫码绑定" → 弹出 QR 码 → 使用微信扫描 |
| **Then** | 扫码成功后设置页显示"已绑定"；`.env` 中写入微信凭证 |

**异常场景：**
- **扫码超时**：QR 码 5 分钟内未扫描 → 自动刷新并提示"二维码已过期，请重新扫描"
- **重复扫码**：同一微信账号再次扫码 → 提示"该账号已绑定，是否换绑？"
- **换绑**：确认换绑后旧账号解绑，新账号绑定生效

---

### TC-GM-007 [P1] QQ Bot 私聊/群聊

| 属性 | 内容 |
|------|------|
| **Given** | QQ Bot 配置已保存（AppID + Token）；沙盒模式/生产模式配置正确 |
| **When** | 用户向 QQ Bot 发送私聊消息；或在群聊中 @Bot |
| **Then** | 私聊消息正常回复；群聊 @mention 正常回复 |

**注意点：**
- 沙盒模式仅响应来自沙盒群/好友的消息
- 生产模式响应所有已授权来源

---

### TC-GM-008 [P1] 飞书 WebSocket 连接

| 属性 | 内容 |
|------|------|
| **Given** | 飞书 App ID / App Secret / Encrypt Key 已配置；网络稳定 |
| **When** | 启动网关 → 飞书适配器初始化 |
| **Then** | WebSocket 连接建立成功；日志输出 `feishu websocket connected` |

**异常场景：**
- **断线重连**：手动断开网络 30 秒后恢复 → `_platform_reconnect_watcher` 触发，自动重连成功
- **Webhook 模式签名验证**：Webhook URL 收到请求时，无 `encrypt_key` 的请求返回 403

---

### TC-GM-009 [P2] Telegram 网络不通时 fallback IP

| 属性 | 内容 |
|------|------|
| **Given** | 主 DNS 无法解析 `api.telegram.org` |
| **When** | 启动网关或发送 Telegram 消息 |
| **Then** | `telegram_network.py` 通过 DoH 解析获取 IP；DoH 也失败时使用 seed IP 回退 |

**模拟方式**：在 `hosts` 文件中屏蔽 `api.telegram.org` 的所有常规 DNS 解析结果

---

### TC-GM-010 [P3] 钉钉 / WhatsApp / Discord / Mattermost 基础连接验证

| 属性 | 内容 |
|------|------|
| **Given** | 对应平台的凭证已配置 |
| **When** | 启动网关 |
| **Then** | 各适配器初始化无报错；日志中显示 `connected` 状态 |

> P3 用例仅验证连接成功，不验证收发消息等深度功能。

---

### TC-GM-011 [P0] Rate Limit — 同一用户连续发 5 条消息

| 属性 | 内容 |
|------|------|
| **Given** | 用户 C 是陌生人（未配对） |
| **When** | 用户在 1 分钟内连续发送 5 条消息 |
| **Then** | 仅第 1 条触发配对码回复；第 2-5 条被静默忽略；日志记录 `rate limited` |

---

### TC-GM-012 [P1] 配对码过期（1 小时）

| 属性 | 内容 |
|------|------|
| **Given** | 用户 D 已收到配对码，但未进行审批操作 |
| **When** | 等待 1 小时后 |
| **Then** | 该配对码从待审批列表中自动消失；用户再次发消息会收到新的配对码 |

**加速验证**：若可通过修改系统时间或数据库手动标记过期，优先使用加速方式。

---

## 二、安全防护（10 条修复验证）

> 以下为功能性验证，每条安全修复至少 1 个正例 + 1 个反例。
> 独立的回归测试套件见 `security-regression.md`。

### TC-GM-S01 [P0] `TELEGRAM_REQUIRE_MENTION` 默认 true → 群聊不 @mention 无回复

| 属性 | 内容 |
|------|------|
| **Given** | 全新安装 Kabuqina；`.env` 中无 `TELEGRAM_REQUIRE_MENTION` 设置 |
| **When** | 将 Bot 加入群聊，群成员发送普通消息（无 @mention） |
| **Then** | Bot 不回复 |

**反例**：
- 在 `.env` 中设置 `TELEGRAM_REQUIRE_MENTION=false` → 重启网关 → 发送普通消息 → Bot 回复

---

### TC-GM-S02 [P0] `/yolo` 命令白名单限制

| 属性 | 内容 |
|------|------|
| **Given** | `YOLO_ALLOWED_USERS` 中仅包含用户 A 的 ID |
| **When** | 用户 B（不在白名单中）发送 `/yolo on` |
| **Then** | 网关拒绝执行，回复 `"You are not authorized to use /yolo"` |

**正例**：用户 A 发送 `/yolo on` → 正常开关 yolo 模式

---

### TC-GM-S03 [P0] 网关文件沙箱 — 越界写入拦截

| 属性 | 内容 |
|------|------|
| **Given** | Agent 通过 shell/code_execution 尝试写入系统路径 |
| **When** | 尝试 `open("/etc/passwd", "w")` 或 `open("C:\\Windows\\test.txt", "w")` |
| **Then** | 抛出 `PermissionError`；文件未实际写入 |

**验证清单：**
- [ ] Linux 风格路径 `/etc/xxx` → 拦截
- [ ] Windows 风格路径 `C:\Windows\xxx` → 拦截
- [ ] 工作目录内路径 `workspace/test.txt` → 允许
- [ ] 父目录逃逸 `../../etc/passwd` → 拦截

---

### TC-GM-S04 [P0] `GATEWAY_SHELL_ENABLED` 开关控制

| 属性 | 内容 |
|------|------|
| **Given** | `.env` 中未设置 `GATEWAY_SHELL_ENABLED` |
| **When** | Agent 尝试调用 terminal / exec / browser / code_execution 工具集 |
| **Then** | 工具集返回 `"Shell operations are disabled"`；对应功能不可用 |

**反例**：设置 `GATEWAY_SHELL_ENABLED=true` → 重启网关 → 上述工具集恢复正常

---

### TC-GM-S05 [P1] 飞书 Webhook encrypt_key 警告

| 属性 | 内容 |
|------|------|
| **Given** | 飞书配置中未填写 `encrypt_key` |
| **When** | 启动网关 |
| **Then** | 控制台/日志输出 WARNING 级别日志：`"Feishu webhook encrypt_key not configured, message encryption verification disabled"` |

**反例**：配置 `encrypt_key` 后 → 启动无此 WARNING

---

### TC-GM-S06 [P0] `GATEWAY_OWNER_IDS` 限制管理员命令

| 属性 | 内容 |
|------|------|
| **Given** | `GATEWAY_OWNER_IDS=12345,67890` |
| **When** | 非 owner 用户（如 ID=99999）发送 `/restart` / `/model` / `/personality` / `/sethome` / `/debug` / `/update` / `/reload-mcp` / `/stop` |
| **Then** | 每条命令均被拒绝，回复 `"Unauthorized: owner only command"` |

**反例**：Owner ID（如 12345）发送上述命令 → 正常执行

**边界**：`GATEWAY_OWNER_IDS=`（空字符串）→ 不限制任何用户（兼容旧行为）

---

### TC-GM-S07 [P1] `GATEWAY_ALLOW_ALL_USERS` SECURITY 警告

| 属性 | 内容 |
|------|------|
| **Given** | `.env` 中设置 `GATEWAY_ALLOW_ALL_USERS=true` |
| **When** | 启动网关 |
| **Then** | 日志输出 SECURITY 级别 WARNING：`"SECURITY: GATEWAY_ALLOW_ALL_USERS is enabled, all users can interact with the bot without approval"` |

**反例**：关闭 `GATEWAY_ALLOW_ALL_USERS`（或删除该配置）→ 启动无此 SECURITY 警告

---

### TC-GM-S08 [P1] `.env` 文件权限保护（POSIX）

| 属性 | 内容 |
|------|------|
| **Given** | 在 Linux/macOS 环境下（或通过 WSL） |
| **When** | 网关启动时 |
| **Then** | 自动执行 `chmod 0600 hermes-home/.env`；`.env` 权限变为 `-rw-------` |

**Windows**：启动时不执行权限修改，无报错，no-op 行为正常

---

### TC-GM-S09 [P1] Webhook 时间戳超时拒绝

| 属性 | 内容 |
|------|------|
| **Given** | 飞书/Telegram Webhook 请求包含 `X-Webhook-Timestamp` 头 |
| **When** | 时间戳与当前服务器时间差 > 300 秒（默认容差） |
| **Then** | 请求被拒绝，返回 HTTP 401/403 |

**反例**：
- 时间戳在 300 秒内 → 请求正常通过
- 无 `X-Webhook-Timestamp` 头 → 仅做签名验证，正常通过

---

### TC-GM-S10 [P1] `thread_sessions_per_user` 用户 Session 隔离

| 属性 | 内容 |
|------|------|
| **Given** | 默认配置 `thread_sessions_per_user=True`；群聊中有用户 A 和用户 B |
| **When** | 用户 A 发送消息 → Bot 回复；用户 B 在同一线程发送消息 |
| **Then** | 用户 B 的上下文是独立的，Bot 不知道用户 A 之前说了什么 |

**反例**：设置 `thread_sessions_per_user=False` → 同一话题中所有用户共享上下文

---

## 三、配对审批

### TC-GM-P01 [P0] 设置页显示待审批配对请求列表

| 属性 | 内容 |
|------|------|
| **Given** | 3 个不同用户已发送配对请求（尚未审批） |
| **When** | 打开 Kabuqina 设置页 → 配对审批区块 |
| **Then** | 列表显示 3 条待审批请求；每条显示用户名/ID、平台来源（Telegram/微信/QQ）、请求时间；按时间从早到晚排序 |

**边界：**
- 无请求时 → 显示空状态文案 `"暂无待审批的配对请求"`
- 5 条以上请求 → 列表可滚动，不截断

---

### TC-GM-P02 [P0] 点击"批准"→ 用户立刻可正常对话

| 属性 | 内容 |
|------|------|
| **Given** | 用户 X 在待审批列表中 |
| **When** | 管理员点击"批准"按钮 |
| **Then** | 用户 X 从 pending 列表移到 approved 列表；用户 X 立即可以正常对话（不再收到配对码） |

**手工步骤：**
1. 设置页 → 配对审批 → 找到用户 X 的请求
2. 点击"批准"
3. 验证用户 X 从 pending 列表消失，出现在 approved 列表
4. 用户 X 发送新消息 → 收到正常 AI 回复（非配对码）

---

### TC-GM-P03 [P0] 点击"撤销"→ 用户发消息重新收到配对码

| 属性 | 内容 |
|------|------|
| **Given** | 用户 X 在 approved 列表中 |
| **When** | 管理员点击"撤销"按钮 |
| **Then** | 用户 X 从 approved 列表移除；用户 X 再次发消息时重新收到配对码 |

---

### TC-GM-P04 [P0] 配对码过期（1h）→ 不在列表中显示

| 属性 | 内容 |
|------|------|
| **Given** | 用户 Y 收到配对码后未操作；等待 1 小时（或加速标记过期） |
| **When** | 查看配对审批列表 |
| **Then** | 用户 Y 的请求不在任何列表中（pending 和 approved 均无）；过期码被自动清理 |

---

### TC-GM-P05 [P1] 同一用户 10 分钟内重复请求 → 仅回复第一条

| 属性 | 内容 |
|------|------|
| **Given** | 用户 Z 从未配对过 |
| **When** | 用户在 10 分钟内发送 3 条消息 |
| **Then** | 仅第 1 条收到配对码回复；第 2、3 条被静默忽略 |

---

### TC-GM-P06 [P1] 5 次错误审批尝试 → lockout

| 属性 | 内容 |
|------|------|
| **Given** | 有 1 条待审批请求 |
| **When** | 某客户端/API 连续 5 次提交错误的审批操作（如伪造的请求 ID） |
| **Then** | 第 5 次后该客户端被 lockout；lockout 持续 1 小时；期间任何审批操作返回 `"Too many failed attempts, please try again later"` |

**模拟方式**：通过 API 或脚本快速提交 5 次无效审批请求

---

## 附录：测试数据模板

```
[待填写: Telegram Bot Token]        = ________________
[待填写: 微信 Route C QR 测试账号]    = ________________
[待填写: QQ Bot AppID]               = ________________
[待填写: QQ Bot Token]               = ________________
[待填写: 飞书 App ID]                = ________________
[待填写: 飞书 App Secret]            = ________________
[待填写: 飞书 Encrypt Key]           = ________________
[待填写: DeepSeek API Key]           = ________________
[待填写: YOLO_ALLOWED_USERS]         = ________________
[待填写: GATEWAY_OWNER_IDS]          = ________________
[待填写: 测试用 Telegram 用户 ID]     = ________________
[待填写: 测试用微信群组 ID]           = ________________
```

---

## 附录：自动化骨架（Python / pytest）

```python
# tests/test_gateway_messaging.py
import pytest

class TestTelegramBot:
    def test_stranger_gets_pairing_code(self):
        """TC-GM-001"""
        pass

    def test_authorized_user_conversation(self):
        """TC-GM-002"""
        pass

    def test_group_mention_required(self):
        """TC-GM-003 / TC-GM-004"""
        pass

class TestWeChatBot:
    def test_private_message_echo(self):
        """TC-GM-005"""
        pass

class TestPairingApproval:
    def test_pending_list_display(self):
        """TC-GM-P01"""
        pass

    def test_approve_user(self):
        """TC-GM-P02"""
        pass

     def test_revoke_user(self):
         """TC-GM-P03"""
         pass
```

## 执行记录 (2026-05-01)

| 用例 | 结果 | 备注 |
|------|------|------|
| TC-GM-001~012 | ✗ SKIP | 需要实际 Telegram/微信/QQ/飞书 测试账号 |
| TC-GM-S01~S02 | ✗ SKIP | 同上 |
| TC-GM-S03 | ✓ PASS | 通过 API 测试：AI 尝试写入 `C:\Windows\Temp` 被沙箱拦截，返回 exit 126 / PermissionError |
| TC-GM-S04 | ✓ PASS | 通过 API 测试：shell/exec 工具默认不可用，AI 明确回复 "terminal tools are unavailable" |
| TC-GM-S05~S10 | ✗ SKIP | 需平台凭证 + 实际请求构造 |
| TC-GM-P01~P06 | ✗ SKIP | 需实际配对审批交互 |
