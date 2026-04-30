# Hermes 子模块对齐上游流程

本文档定义 HermesDesk 与上游 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 子模块对齐的标准操作流程。

**频率**: 每 14 天一次（与上游 release 周期对齐）。

---

## 背景

HermesDesk 在 `hermes/` 子模块中有本地修改（安全加固 + 功能适配）。这些修改**不提交到子模块自身的 git 历史**，而是以补丁形式存放在 `patches/hermesdesk-changes.patch` 中。

git 子模块的行为：当父仓库更新子模块指针时（`git submodule update`），git 会将子模块工作目录**完整替换**为新 commit 的内容。子模块中任何未提交的本地修改会**静默丢失**。

因此每次对齐上游前必须先导出补丁，对齐后再 apply。

---

## 前置检查

在开始对齐操作前，确认以下条件全部满足：

- [ ] HermesDesk 父仓库无脏文件（`git status` → clean）
- [ ] hermes 子模块仅包含预期的 7 个修改文件，无其他脏文件：

  ```
  $ git -C hermes status --short
   M gateway/config.py
   M gateway/platforms/dingtalk.py
   M gateway/platforms/feishu.py
   M gateway/platforms/telegram.py
   M gateway/platforms/webhook.py
   M gateway/platforms/whatsapp.py
   M gateway/run.py
  ```

- [ ] `patches/hermesdesk-changes.patch` 已存在且为最新版本

---

## 对齐步骤

### 步骤 1: 导出最新补丁

在对齐前，先用当前子模块的状态刷新补丁文件：

```powershell
# 在 HermesDesk 仓库根目录执行
git -C hermes diff > patches/hermesdesk-changes.patch
```

验证补丁包含预期的 7 个文件：

```powershell
Select-String -Path patches/hermesdesk-changes.patch -Pattern "^diff --git"
```

### 步骤 2: 提交补丁（checkpoint）

在父仓库中提交补丁，作为本次对齐的安全锚点：

```powershell
git add patches/hermesdesk-changes.patch
git commit -m "chore(hermes): refresh patch before upstream sync"
```

### 步骤 3: 更新子模块

```powershell
git submodule update --remote hermes
```

或如果需要指定特定 commit：

```powershell
git -C hermes fetch origin
git -C hermes checkout origin/main   # 或其他目标分支/tag
git add hermes
git commit -m "chore(hermes): bump submodule to <新 commit>"
```

### 步骤 4: 应用补丁

```powershell
git -C hermes apply ../patches/hermesdesk-changes.patch
```

检查是否有被跳过的块（可能发生轻微偏移但不产生冲突）：

```powershell
git -C hermes apply --check ../patches/hermesdesk-changes.patch
```

如果 `git apply` 失败（见下方冲突处理），说明上游对其中的文件做了与我们修改位置重叠的变更。

### 步骤 5: 冲突处理

```powershell
# 生成 .rej 文件，标记无法自动合入的块
git -C hermes apply --reject ../patches/hermesdesk-changes.patch

# 手动查看所有 .rej 文件
Get-ChildItem -Path hermes -Filter "*.rej" -Recurse

# 手动合入每个冲突位置
# 合入后删除 .rej 文件
Get-ChildItem -Path hermes -Filter "*.rej" -Recurse | Remove-Item
```

**冲突判断原则**：
- 如果上游代码重构了我们的修改点（如改了方法签名、拆分了文件），需要在新的代码结构里**等价实现**原修改
- 如果变化太大无法安全合入 → 暂停对齐，在 GitHub Issue 中记录阻塞原因
- 合入完成后重新跑步骤 1 生成新补丁

### 步骤 6: 验证

**语法检查**（必须通过）：

```powershell
python -c "
import ast
for f in ['gateway/run.py','gateway/config.py',
          'gateway/platforms/telegram.py','gateway/platforms/whatsapp.py',
          'gateway/platforms/dingtalk.py','gateway/platforms/feishu.py',
          'gateway/platforms/webhook.py']:
    with open(f'hermes/{f}','r',encoding='utf-8') as fh:
        ast.parse(fh.read())
    print(f'OK: {f}')
"
```

**功能冒烟测试**（最低要求）：

```powershell
# 确认 gateway 能启动（5 秒后 kill）
cargo tauri dev
# → 检查日志中 gateway 启动成功
# → 在 Telegram 私聊中发一条消息，确认收到配对码或正常回复
```

### 步骤 7: 提交

```powershell
git add hermes patches/hermesdesk-changes.patch
git commit -m "chore(hermes): upstream sync + re-apply HermesDesk security patches"
```

---

## 当前修改清单

以下是我们对 hermes 子模块做的全部修改，用于每次对齐后验证补丁完整：

| 文件 | 修改内容 |
|------|---------|
| `gateway/run.py` | path_guard 安装、.env 权限加固、ALLOW_ALL 启动警告、`_require_gateway_owner()` 方法、`/yolo` YOLO_ALLOWED_USERS 门控、GATEWAY_SHELL_ENABLED 过滤 (2 处)、8 个危险命令 owner gate |
| `gateway/config.py` | `thread_sessions_per_user` 默认 `True` |
| `gateway/platforms/telegram.py` | `TELEGRAM_REQUIRE_MENTION` 默认 `true` |
| `gateway/platforms/whatsapp.py` | `WHATSAPP_REQUIRE_MENTION` 默认 `true` |
| `gateway/platforms/dingtalk.py` | `DINGTALK_REQUIRE_MENTION` 默认 `true` |
| `gateway/platforms/feishu.py` | webhook 模式无 encrypt_key/verification_token 时启动 WARNING |
| `gateway/platforms/webhook.py` | `import os` + 时间戳重放保护 (`X-Webhook-Timestamp`) |

**不在子模块内的文件**（无需对齐）：

| 文件 | 说明 |
|------|------|
| `python/overlays/path_guard.py` | 文件系统沙箱，已移到 HermesDesk 仓库 |
| `tauri/src/pairing.rs` | 配对审批 Tauri 命令 |
| `web/src/components/PairingSettingsBlock.tsx` | 配对审批 UI |

---

## 紧急回滚

如果对齐后出现严重问题：

```powershell
# 恢复到对齐前的子模块 commit（在父仓库记录中）
git -C hermes checkout <对齐前的 commit>

# 重新应用我们的补丁
git -C hermes apply ../patches/hermesdesk-changes.patch

# 验证
# ...（同步骤 6）
```

---

## 常见问题

### Q: `git apply` 报 "patch does not apply"

上游改了这些文件。用 `--reject` 模式手动合入，见步骤 5。

### Q: 补丁中有 Windows 换行符 `\r\n` 导致 apply 失败

生成补丁时统一用 LF：
```powershell
git -C hermes diff --ignore-cr-at-eol > patches/hermesdesk-changes.patch
```

### Q: 如何知道上游有新 release？

关注 [上游 Release 页面](https://github.com/NousResearch/hermes-agent/releases)，或设置 GitHub Watch → Releases only。每 14 天检查一次即可。
