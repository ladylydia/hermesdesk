# Hard Profile Isolation — Manual Smoke Tests

## Prerequisites

1. `cargo tauri dev` 启动成功，无编译/运行时错误
2. 至少配置了一个 gateway 平台的凭据（如 Telegram bot token）
3. 打开 DevTools Console（F12）便于观察报错
4. 关闭所有浏览器实例中打开的 Hermes 页面（避免端口冲突）

---

## M1: Fresh Migration

**操作：**
1. 关闭 Kabuqina
2. 删除 `%LOCALAPPDATA%\com.kabuqina.app\hermes-home\profiles\`（整个目录）
3. 启动 Kabuqina
4. 打开 Settings → 看 Status 区域

**验证：**
- [ ] 启动日志无 migration 相关报错
- [ ] `%LOCALAPPDATA%\com.kabuqina.app\hermes-home\profiles\` 已创建
- [ ] `profiles\.migrated` 文件存在
- [ ] `hermes-home\shared\USER_PREFS.md` 文件存在且内容为空
- [ ] 若已配凭据：`profiles\<platform>\` 存在，含 `memories/` + `sessions/` + `.env` + `config.yaml`

---

## M2: Single Platform — Profile Integrity

**操作：**
1. 在 Hermes Dashboard → Keys 中配置一个平台凭据（如 Telegram bot token）
2. Gateway 自动启动后，打开 Settings → 看 Gateway 状态

**验证：**
- [ ] `profiles\telegram\.env` 包含 `TELEGRAM_BOT_TOKEN=xxx`
- [ ] `profiles\telegram\config.yaml` 包含 `platforms: telegram: enable: true`
- [ ] `profiles\telegram\memories\` 和 `profiles\telegram\sessions\` 存在
- [ ] Settings 中 Gateway 状态显示 `telegram: running`

---

## M3: Multiple Platforms

**操作：**
1. 配置第二个平台凭据（如 Weixin/Feishu/DingTalk）
2. 确保两个平台都有完整凭据
3. 重启 Kabuqina

**验证：**
- [ ] `profiles\<platform1>\` 和 `profiles\<platform2>\` 都存在
- [ ] 各自的 `.env` 只含对应平台凭据（互不包含对方凭据）
- [ ] Settings → Gateway 状态显示两个平台 `running`
- [ ] 各自有独立的 `memories/` 和 `sessions/` 目录

---

## M4: Shared Preferences UI

**操作：**
1. 启动 Kabuqina
2. 导航到 Settings

**验证：**
- [ ] Settings 页面底部存在"共享偏好"（zh） / "Shared Preferences"（en） 分区
- [ ] 分区图标为 FileText（文件图标）
- [ ] 文本框内容为空（首次）
- [ ] 占位文本提示了格式示例
- [ ] "保存"按钮可见但不可点击变色（在内容不变时可用）

---

## M5: Save Shared Preferences

**操作：**
1. 在 Shared Preferences textarea 中输入：
   ```
   language: zh
   timezone: Asia/Shanghai
   preferred_name: 助手
   communication_style: formal
   ```
2. 点击"保存"

**验证：**
- [ ] 按钮显示"已保存" / "Saved"（约 2 秒后恢复）
- [ ] `%LOCALAPPDATA%\com.kabuqina.app\hermes-home\shared\USER_PREFS.md` 内容与输入一致
- [ ] `profiles\telegram\_host_prefs.md`（及其他已配平台）内容与 USER_PREFS.md 一致
- [ ] `profiles\telegram\` 根目录下存在 `_host_prefs.md`

---

## M6: Restart Gateway — Prefs Persist

**操作：**
1. Settings → Gateway → Stop
2. Settings → Gateway → Start

**验证：**
- [ ] Gateway 重启后，`_host_prefs.md` 在每个 profile 中仍然存在且内容不变
- [ ] Settings 中 Gateway 状态恢复 `running`

---

## M7: Edit Shared Preferences

**操作：**
1. 在 Shared Preferences 中将 `communication_style: formal` 改为 `communication_style: casual`
2. 点击保存
3. 重启 Kabuqina

**验证：**
- [ ] `USER_PREFS.md` 已更新
- [ ] 所有 profile 的 `_host_prefs.md` 已同步更新

---

## M8: Bot DM — Sees Host Prefs

**操作：**
1. 在 Telegram（或其他已配平台）中，以 DM 私聊方式向 bot 发送一条消息：
   ```
   What preferences do you have about me?
   ```
2. 或者打开一个 gateway 平台的 DM 会话

**验证：**
- [ ] Bot 的回复提及了 language/timezone 等信息（从 `_host_prefs.md` 读取）
- [ ] 确认方式：在 Hermes Dashboard 中查看该会话的 System Prompt，应包含 `HOST PREFERENCES` 块
- [ ] `HOST PREFERENCES` 块中包含用户设置的偏好内容

---

## M9: Bot Group — No Host Prefs

**操作：**
1. 将 bot 拉入一个群组/频道
2. 在群组中发送：
   ```
   What preferences do you have about me?
   ```

**验证：**
- [ ] Bot 回复中**不**包含 language/timezone 等信息
- [ ] 确认方式：查看该群组会话的 System Prompt，**不应**包含 `HOST PREFERENCES` 块
- [ ] Bot 无法从 `_host_prefs.md` 获取任何用户偏好

---

## M10: Bot DM — Memory Write Allowed

**操作：**
1. 在 bot DM 中发送：
   ```
   Remember that my name is Alice
   ```
2. 查看对应 profile 的 `memories/` 目录

**验证：**
- [ ] Bot 回复确认已记忆
- [ ] `profiles\<platform>\memories\USER.md` 包含姓名信息
- [ ] `profiles\<platform>\memories\MEMORY.md` 也可能包含
- [ ] 其他 profile 的 `memories/` 目录**不包含**这条记忆

---

## M11: Bot Group — Memory Write Blocked

**操作：**
1. 在 bot 群组中发送：
   ```
   Remember that my name is Bob
   ```
2. 注意 bot 回复

**验证：**
- [ ] Bot 回复错误信息，内容提及 "disabled in group" 或 "privacy"
- [ ] 所有 profile 的 `memories/` 目录**均不包含** Bob 的姓名信息
- [ ] Bot 的日志中有 memory write 被拒绝的记录

---

## M12: Remigration Idempotence

**操作：**
1. 删除 `profiles\` 目录
2. 修改 `profiles\.migrated` marker 文件（如修改时间）
3. 重启 Kabuqina

**验证：**
- [ ] `profiles\` 被重新创建
- [ ] `\.migrated` marker 存在
- [ ] 已有凭据的 profile 重新创建
- [ ] 已有数据**不会丢失**（因为旧数据在重启前已被删除，预期是空白起始）
- [ ] 日志中仅出现一次 migration 相关的 log 行

---

## 测试清单汇总

| 编号 | 名称 | 自动化 | 优先级 |
|------|------|--------|--------|
| M1 | Fresh Migration | 自动运行 | P0 |
| M2 | Single Platform Profile | 手动 | P0 |
| M3 | Multiple Platforms | 手动 | P0 |
| M4 | Shared Prefs UI | 手动 | P1 |
| M5 | Save Shared Prefs | 手动 | P0 |
| M6 | Restart Gateway | 手动 | P0 |
| M7 | Edit Shared Prefs | 手动 | P1 |
| M8 | Bot DM Sees Prefs | 手动 | P0 |
| M9 | Bot Group No Prefs | 手动 | P0 |
| M10 | Bot DM Memory Write | 手动 | P0 |
| M11 | Bot Group Memory Blocked | 手动 | P0 |
| M12 | Remigration Idempotence | 手动 | P1 |
