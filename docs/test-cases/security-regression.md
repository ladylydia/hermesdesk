# 安全防护 — 10 条修复专项回归测试

> 对应 test-plan.md §2（独立回归套件）
> 每条安全修复至少 1 个正例（修复生效）+ 1 个反例（关闭/绕过时不生效）
> 本套件应在每次发版前完整执行一遍

---

## 环境前置条件

| 项 | 要求 |
|----|------|
| Kabuqina | 待测版本（安装包或 dev） |
| 权限 | 可修改 `hermes-home/.env`；可重启网关 |
| 账号 | `[待填写: Owner Telegram ID]`、`[待填写: 非 Owner Telegram ID]` |
| 日志 | `hermesdesk.log` 可读取，日志级别 INFO 以上 |

---

## 回归清单总览

| # | ID | 测试项 | 优先级 |
|---|-----|--------|--------|
| 1 | TC-SR-01 | `TELEGRAM_REQUIRE_MENTION` 默认 true | P0 |
| 2 | TC-SR-02 | `/yolo` 命令白名单 | P0 |
| 3 | TC-SR-03 | 文件沙箱越界写入拦截 | P0 |
| 4 | TC-SR-04 | `GATEWAY_SHELL_ENABLED` 开关 | P0 |
| 5 | TC-SR-05 | 飞书 Webhook encrypt_key 警告 | P1 |
| 6 | TC-SR-06 | `GATEWAY_OWNER_IDS` 管理员命令限制 | P0 |
| 7 | TC-SR-07 | `GATEWAY_ALLOW_ALL_USERS` SECURITY 警告 | P1 |
| 8 | TC-SR-08 | `.env` 文件权限保护 | P1 |
| 9 | TC-SR-09 | Webhook 时间戳超时拒绝 | P1 |
| 10 | TC-SR-10 | `thread_sessions_per_user` Session 隔离 | P1 |

---

## TC-SR-01 [P0] `TELEGRAM_REQUIRE_MENTION` 默认 true

**背景**：防止 Bot 在群聊中响应所有消息，仅限 @mention 触发。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例** | 1. 全新安装，不修改 `.env`<br>2. 将 Bot 加入群聊<br>3. 发送普通消息（无 @mention） | Bot **不回复**；日志 DEBUG 级别记录 `mention required, ignoring` |
| **反例** | 1. 在 `.env` 添加 `TELEGRAM_REQUIRE_MENTION=false`<br>2. 重启网关<br>3. 发送普通消息 | Bot **正常回复** |
| **还原** | 删除 `.env` 中该配置或设为 `true`，重启 | 恢复默认行为 |

**关键点**：全新安装时 `.env` 中不应自动写入该配置项（靠代码默认值 `true` 生效）。

---

## TC-SR-02 [P0] `/yolo` 命令白名单

**背景**：`/yolo` 命令（启用高风险模式）仅限白名单用户使用。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例** | 1. `.env` 设置 `YOLO_ALLOWED_USERS=12345,67890`<br>2. ID=99999（非白名单）发送 `/yolo on` | 回复 `"You are not authorized to use /yolo"`；yolo 模式未激活 |
| **反例** | ID=12345（白名单）发送 `/yolo on` → 再发 `/yolo off` | `/yolo on` 成功激活；`/yolo off` 成功关闭 |
| **边界** | `YOLO_ALLOWED_USERS=`（空） | 所有用户都不能使用 `/yolo`（非"所有用户都可以"） |

---

## TC-SR-03 [P0] 文件沙箱越界写入拦截

**背景**：Agent 文件操作被限制在 workspace 目录内，防止写入系统路径。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例-Linux** | Agent 执行 `open("/etc/passwd", "w").write("test")` | 抛出 `PermissionError: Path '/etc/passwd' is outside workspace` |
| **正例-Windows** | Agent 执行 `open("C:\\Windows\\test.txt", "w").write("test")` | 抛出 `PermissionError: Path 'C:\Windows\test.txt' is outside workspace` |
| **正例-父目录逃逸** | Agent 执行 `open("../../etc/passwd", "w")` | 抛出 `PermissionError`（路径解析后超出 workspace） |
| **反例-工作目录内** | Agent 执行 `open("workspace/output.txt", "w").write("ok")` | 成功写入，无异常 |
| **回归验证** | 以上所有场景执行后，系统路径未被实际修改 | `/etc/passwd` 内容不变；`C:\Windows\test.txt` 不存在 |

**模拟方式**：在 `/chat` 中要求 AI 执行上述文件操作，观察返回结果。

---

## TC-SR-04 [P0] `GATEWAY_SHELL_ENABLED` 开关

**背景**：shell/exec/browser/code_execution 等高危工具集默认关闭，需显式启用。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例-默认关闭** | 1. `.env` 中无 `GATEWAY_SHELL_ENABLED`<br>2. 发送消息 `"请帮我执行 ls 命令"` | AI 回复 `"Shell operations are disabled in this environment"`；工具集未加载 |
| **反例-显式启用** | 1. `.env` 添加 `GATEWAY_SHELL_ENABLED=true`<br>2. 重启网关<br>3. 发送相同消息 | AI 正常调用 shell 工具并返回目录列表 |
| **回归** | 删除配置，重启 | 恢复禁用状态 |

**验证清单：**
- [ ] `terminal` 工具集不可用（默认关闭时）
- [ ] `exec` 工具集不可用
- [ ] `browser` 工具集不可用
- [ ] `code_execution` 工具集不可用

---

## TC-SR-05 [P1] 飞书 Webhook encrypt_key 警告

**背景**：未配置 encrypt_key 时飞书 Webhook 消息加密验证被禁用，需提醒用户。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例** | 1. 飞书配置中 `encrypt_key` 留空<br>2. 启动网关 | 日志/控制台输出：`WARNING: Feishu webhook encrypt_key not configured, message encryption verification disabled` |
| **反例** | 填写 `encrypt_key` 后启动 | 无上述 WARNING |
| **日志级别** | — | 确认是 `WARNING` 级别（非 DEBUG/INFO） |

---

## TC-SR-06 [P0] `GATEWAY_OWNER_IDS` 管理员命令限制

**背景**：敏感命令仅限 Owner 执行，防止普通用户操作网关。

**受保护命令清单：**
```
/restart, /model, /personality, /sethome, /debug, /update, /reload-mcp, /stop
```

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例** | 1. `.env` 设置 `GATEWAY_OWNER_IDS=12345`<br>2. ID=99999 发送 `/restart` | 回复 `"Unauthorized: owner only command"`；命令未执行 |
| **正例-全部命令** | 用非 Owner 逐一测试 `/model`, `/personality`, `/sethome`, `/debug`, `/update`, `/reload-mcp`, `/stop` | 每条均被拒绝 |
| **反例-Owner** | ID=12345 发送 `/restart` | 网关正常重启 |
| **边界-空字符串** | `GATEWAY_OWNER_IDS=`（空） | 所有用户均可执行（兼容旧行为）；日志打印兼容模式提示 |

---

## TC-SR-07 [P1] `GATEWAY_ALLOW_ALL_USERS` SECURITY 警告

**背景**：允许所有用户免审批使用 Bot 时，需显式 SECURITY 级别警告。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例** | 1. `.env` 添加 `GATEWAY_ALLOW_ALL_USERS=true`<br>2. 启动网关 | 日志输出：`SECURITY: GATEWAY_ALLOW_ALL_USERS is enabled, all users can interact with the bot without approval` |
| **日志级别** | — | 确认是 `SECURITY` 级别（高于 WARNING） |
| **反例** | 删除配置或设为 `false`，重启 | 无上述 SECURITY 日志 |
| **功能验证** | `GATEWAY_ALLOW_ALL_USERS=true` 时 | 陌生人发消息直接收到 AI 回复（不经配对审批） |

---

## TC-SR-08 [P1] `.env` 文件权限保护（POSIX）

**背景**：网关启动时自动设置 `.env` 文件权限为仅所有者可读写，防止敏感凭证泄露。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例-POSIX** | 1. Linux/macOS（或 WSL）<br>2. `chmod 644 hermes-home/.env`（先改为宽松权限）<br>3. 启动网关<br>4. `ls -l hermes-home/.env` | 权限变为 `-rw-------`（0600） |
| **Windows** | 1. 在 Windows 上启动网关 | 不执行权限修改；无报错；no-op 行为 |
| **回归** | 多次启动 | 权限保持 0600，不被意外改回 644 |

**注意**：Windows 上无需验证权限修改（Windows 权限模型不同），只需验证启动不报错。

---

## TC-SR-09 [P1] Webhook 时间戳超时拒绝

**背景**：防止重放攻击，时间戳与服务器时间差超过容差（默认 300s）的请求被拒绝。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例-超时** | 构造 Webhook 请求，`X-Webhook-Timestamp` = 当前时间 - 400 秒 | 请求被拒绝，HTTP 401/403 |
| **反例-正常** | `X-Webhook-Timestamp` = 当前时间 - 60 秒 | 请求正常通过（签名验证也通过后） |
| **反例-无头** | 请求中不含 `X-Webhook-Timestamp` | 仅做签名验证，正常通过 |
| **容差边界** | 时间戳差 = 299 秒 | 通过；= 301 秒 → 拒绝 |

**模拟方式**：使用 `curl` 或 Postman 手动构造请求，修改 `X-Webhook-Timestamp` 值为过去的时间戳。

```bash
# 超时请求示例（时间戳为10分钟前）
curl -X POST http://localhost:<port>/webhook/feishu \
  -H "X-Webhook-Timestamp: $(($(date +%s) - 400))" \
  -H "X-Webhook-Signature: <valid_sig>" \
  -d '{"event": "test"}'
# 预期：HTTP 401
```

---

## TC-SR-10 [P1] `thread_sessions_per_user` Session 隔离

**背景**：群聊中不同用户的话题上下文默认隔离，防止信息串台。

| 场景 | 步骤 | 预期 |
|------|------|------|
| **正例-默认隔离** | 1. 默认 `thread_sessions_per_user=True`<br>2. 群话题中用户 A 发送 `"我的密码是 123456"`<br>3. 同话题中用户 B 发送 `"我刚才说了什么？"` | Bot 回复用户 B 时不知道用户 A 的密码（上下文独立） |
| **反例-共享** | 1. 设置 `thread_sessions_per_user=False`<br>2. 重启网关<br>3. 重复上述步骤 | 用户 B 的回复中可能引用用户 A 的消息（共享上下文） |
| **还原** | 恢复 `thread_sessions_per_user=True`，重启 | 恢复隔离 |

**验证要点**：在共享模式下，用户 B 发送 `"刚才谁说了密码？"` → Bot 应能回答 `"用户 A 说..."`；在隔离模式下 → Bot 回答 `"我没有相关信息"`。

---

## 快速回归脚本（供手动执行）

以下命令序列可快速验证大部分安全修复（在 PowerShell 中执行）：

```powershell
# ====== TC-SR-01: TELEGRAM_REQUIRE_MENTION ======
# 默认状态（不写配置）→ 群聊无 mention 不回复 → PASS
# .env += TELEGRAM_REQUIRE_MENTION=false → 群聊无 mention 回复 → PASS

# ====== TC-SR-03: 文件沙箱（通过 /chat 测试）======
# 发送: "请尝试写入 /etc/passwd"
# 预期: AI 返回 PermissionError

# ====== TC-SR-04: GATEWAY_SHELL_ENABLED ======
# 默认 → 请求 shell 操作被拒绝 → PASS
# .env += GATEWAY_SHELL_ENABLED=true → 重启 → shell 操作可用 → PASS

# ====== TC-SR-06: OWNER_IDS ======
# .env += GATEWAY_OWNER_IDS=<your_id>
# 用另一个账号发送 /restart → 被拒绝 → PASS
# Owner 账号发送 /restart → 执行 → PASS

# ====== TC-SR-08: .env 权限 ======
# WSL: ls -l ~/.config/Kabuqina/hermes-home/.env → 权限 0600 → PASS
```

---

## 附录：自动化骨架

```python
# tests/test_security_regression.py
import pytest

class TestSecurityRegression:
    """TC-SR-01 ~ TC-SR-10"""

    def test_telegram_require_mention_default(self, gateway, telegram_group):
        """TC-SR-01"""
        # 默认配置
        telegram_group.send("hello without mention")
        assert not telegram_group.bot_replied()

    def test_yolo_whitelist(self, gateway):
        """TC-SR-02"""
        gateway.set_env("YOLO_ALLOWED_USERS", "12345")
        response = simulate_user_command(user_id="99999", command="/yolo on")
        assert "not authorized" in response.text.lower()

    def test_path_guard_blocks_system_paths(self, gateway):
        """TC-SR-03"""
        for path in ["/etc/passwd", "C:\\Windows\\test.txt", "../../etc/passwd"]:
            result = gateway.agent_try_write(path, "test")
            assert result.error_type == "PermissionError"
            assert "outside workspace" in result.error_message

    def test_shell_disabled_by_default(self, gateway):
        """TC-SR-04"""
        assert gateway.env.get("GATEWAY_SHELL_ENABLED") is None
        response = gateway.send_chat_message("执行 ls 命令")
        assert "disabled" in response.text.lower()

    def test_owner_only_commands(self, gateway):
        """TC-SR-06"""
        gateway.set_env("GATEWAY_OWNER_IDS", "12345")
        for cmd in ["/restart", "/model", "/personality", "/sethome", "/debug", "/update", "/reload-mcp", "/stop"]:
            response = simulate_user_command(user_id="99999", command=cmd)
            assert "unauthorized" in response.text.lower(), f"Command {cmd} should be blocked"

    def test_allow_all_users_security_warning(self, gateway):
        """TC-SR-07"""
        gateway.set_env("GATEWAY_ALLOW_ALL_USERS", "true")
        gateway.restart()
        assert any("SECURITY: GATEWAY_ALLOW_ALL_USERS" in line for line in gateway.logs)

    def test_env_file_permissions(self, gateway):
        """TC-SR-08 — POSIX only"""
        import os, stat
        env_path = gateway.get_env_file_path()
        mode = stat.S_IMODE(os.stat(env_path).st_mode)
        assert mode == 0o600, f".env permissions should be 0600, got {oct(mode)}"

    def test_webhook_timestamp_timeout(self, gateway):
        """TC-SR-09"""
        import time
        old_ts = str(int(time.time()) - 400)
        response = gateway.send_webhook(
            headers={"X-Webhook-Timestamp": old_ts},
            body='{"event": "test"}'
        )
        assert response.status_code in (401, 403)

    def test_session_isolation_per_user(self, gateway):
        """TC-SR-10"""
        # 默认 thread_sessions_per_user=True
        gateway.set_env("THREAD_SESSIONS_PER_USER", "true")
        # 用户 A 发送敏感信息
        user_a_context = gateway.simulate_message(user_id="A", text="密码是 secret123")
        # 用户 B 查询
        user_b_context = gateway.simulate_message(user_id="B", text="用户A说了什么？")
        assert "secret123" not in user_b_context.reply.lower()
```

---

## 执行记录模板

每次发版前执行本套件，记录结果：

```
执行日期: ___________
执行人: _____________
版本号: _____________

TC-SR-01 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-02 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-03 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-04 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-05 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-06 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-07 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-08 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-09 [ ] PASS [ ] FAIL  备注: ___________
TC-SR-10 [ ] PASS [ ] FAIL  备注: ___________
```

## 实际执行记录 (2026-05-01)

| 用例 | 结果 | 备注 |
|------|------|------|
| TC-SR-01 | ✗ SKIP | 需要实际 Telegram Bot + 群聊 |
| TC-SR-02 | ✗ SKIP | 同上 |
| TC-SR-03 | ✓ PASS | 同 TC-GM-S03 — AI 尝试写系统路径被拦截 |
| TC-SR-04 | ✓ PASS | 同 TC-GM-S04 — shell 工具默认不可用 |
| TC-SR-05 | ✗ SKIP | 需要飞书配置 |
| TC-SR-06 | ✗ SKIP | 需要 Telegram Owner/非Owner 账号 |
| TC-SR-07 | ✗ SKIP | 需要实际测试 |
| TC-SR-08 | ✗ SKIP | Windows上无需验证 |
| TC-SR-09 | ✗ SKIP | 需构造 Webhook 请求 |
| TC-SR-10 | ✗ SKIP | 需要 Telegram 群聊多用户 |
