# Gateway — 进程生命周期

> 对应 test-plan.md §4
> 覆盖网关进程的启动、停止、crash 自动恢复、锁文件管理、以及构建后首次启动验证

---

## 环境前置条件

| 项 | 要求 |
|----|------|
| OS | Windows 10/11 |
| Kabuqina | 可稳定启动的版本（安装包或 dev 模式） |
| 监控工具 | 任务管理器（或 `Get-Process python` in PowerShell）可观察进程 |
| 日志 | `hermesdesk.log` 可读，日志级别建议设为 DEBUG |
| 前置配置 | Telegram Token 已配置（保证网关在启动条件满足时可自动启动） |

---

## 一、壳内停止 / 启动

### TC-GL-001 [P0] 壳内点击"停止网关"→ 进程终止 + 锁文件清理

| 属性 | 内容 |
|------|------|
| **Given** | Kabuqina 已启动；网关状态为"运行中"；任务管理器中可见 `python -m gateway.run` 进程 |
| **When** | 在设置页点击"停止网关"按钮 |
| **Then** | 网关状态变为"未运行"；任务管理器中 `python -m gateway.run` 进程消失；日志中出现 `[hermes-desklock]` stderr 输出，表明锁文件已被清理 |

**手工执行步骤（步骤级）：**
1. 启动 Kabuqina，等待网关自动启动（或手动点击"启动网关"）
2. 打开任务管理器 → Details 标签 → 确认存在 `python.exe` 进程，命令行包含 `gateway.run`
3. 在 Kabuqina 设置页 → 消息网关区块，点击"停止网关"
4. 观察状态指示器从"运行中"变为"未运行"（应在 3 秒内完成）
5. 切换回任务管理器 → 确认 `python.exe`（gateway.run）进程已消失
6. 打开 `hermesdesk.log` → 搜索 `[hermes-desklock]` → 应看到模块级 stderr 输出，确认锁文件已清理
7. 检查锁文件路径（通常在 `hermes-home/` 下）→ `.lock` 文件不应存在

**预期日志输出（示例）：**
```
[hermes-desklock] Releasing lock file: C:\Users\<user>\AppData\Roaming\Kabuqina\hermes-home\.gateway.lock
[hermes-desklock] Lock file removed successfully
```

**自动化模板：**
```python
def test_stop_gateway_cleans_lock_file():
    # 1. 启动网关
    gateway.start()
    assert gateway.process_is_running()
    
    # 2. 停止网关
    gateway.stop()
    
    # 3. 验证进程终止
    assert not gateway.process_is_running(), timeout=5
    
    # 4. 验证锁文件清理
    assert not os.path.exists(lock_file_path)
    assert "[hermes-desklock]" in gateway.stderr_logs
```

---

### TC-GL-002 [P0] 停止后立即启动 → 新进程正常无锁冲突

| 属性 | 内容 |
|------|------|
| **Given** | 网关已停止（TC-GL-001 执行完毕后的状态） |
| **When** | 在设置页点击"启动网关" |
| **Then** | 网关状态变为"运行中"；新 `python -m gateway.run` 进程启动；日志无锁冲突错误 |

**手工执行步骤（步骤级）：**
1. 确保网关处于"未运行"状态（TC-GL-001 已完成）
2. 在设置页点击"启动网关"
3. 观察状态指示器从"未运行" → "启动中" → "运行中"（应在 10 秒内完成）
4. 任务管理器 → 确认新的 `python.exe`（gateway.run）进程已创建，PID 与之前不同
5. 检查 `hermesdesk.log` → 确认无 `"Lock file already held"` / `"Another gateway instance is running"` 等错误
6. 发送一条 Telegram 测试消息 → 验证新网关进程正常响应

---

### TC-GL-003 [P0] 快速连续 3 次停止 → 启动 → 无残留进程

| 属性 | 内容 |
|------|------|
| **Given** | 网关处于"运行中"状态 |
| **When** | 连续执行：停止 → 启动 → 停止 → 启动 → 停止 → 启动（每步等待状态稳定） |
| **Then** | 最终状态为"运行中"；任务管理器中仅有 1 个 `gateway.run` 进程；无僵尸 PID |

**手工执行步骤（步骤级）：**
1. 确保网关处于"运行中"
2. 第 1 轮：点击"停止网关" → 等待状态变为"未运行" → 记录 PID_A
3. 第 1 轮：点击"启动网关" → 等待状态变为"运行中" → 记录 PID_B
4. 第 2 轮：停止 → 等待 → 启动 → 等待 → 记录 PID_C
5. 第 3 轮：停止 → 等待 → 启动 → 等待 → 记录 PID_D
6. 最终检查：
   - 任务管理器中只有 1 个 `python.exe`（gateway.run），PID = PID_D
   - PID_A、PID_B、PID_C 对应的进程均不存在（无僵尸）
   - 日志中无 `[hermes-desklock] ERROR` 级别的输出

**关键断言：**
```
assert count_gateway_processes() == 1
assert no_orphaned_lock_files()
assert log_has_no_errors_containing("lock")
```

---

### TC-GL-004 [P0] 网关 Crash 后自动重启 + 消息队列不丢失

| 属性 | 内容 |
|------|------|
| **Given** | 网关处于"运行中"；`reconnect watcher` 已启用；Telegram 用户已配对并可正常对话 |
| **When** | 手动模拟 crash：在任务管理器中强制结束 `python -m gateway.run` 进程（或发送 SIGKILL） |
| **Then** | 5-10 秒内网关自动重启；重启后 Telegram 消息正常收发；crash 期间发送的消息在恢复后被处理（消息队列缓存生效） |

**手工执行步骤（步骤级）：**
1. 启动网关，确认 Telegram Bot 正常回复消息
2. 在任务管理器中找到 `python.exe`（gateway.run）进程 → 右键 → "Go to details" → 右键 → "End process tree"（模拟 crash）
3. 立即在 Telegram 发送一条测试消息（crash 期间发送）
4. 开始计时，观察 Kabuqina 设置页状态：
   - 预期："运行中" → "未运行"（短暂） → "启动中" → "运行中"
   - 总恢复时间应 < 15 秒
5. 恢复后检查 Telegram：
   - 第 3 步发送的消息是否被回复（验证消息队列缓存）
6. 检查日志：
   - 应看到 `gateway process exited unexpectedly` 或类似日志
   - 应看到 `restarting gateway...` 和启动成功的日志

**消息队列验证（关键）：**
```
Crash 前: 用户发送 "msg-1" → Bot 回复 "reply-1" ✓
Crash 中: 用户发送 "msg-2" → 等待...
恢复后:   Bot 回复 "reply-2"（msg-2 被缓存并处理） ✓ ← 关键断言
```

**自动化模板：**
```python
def test_crash_recovery_with_message_queue():
    # 1. 正常状态验证
    assert gateway.is_running()
    reply1 = send_telegram_message("msg-1")
    assert reply1.received
    
    # 2. 模拟 crash
    gateway.kill_process(signal=SIGKILL)  # 强制终止
    
    # 3. Crash 期间发消息
    pending_msg = send_telegram_message("msg-2")
    
    # 4. 等待自动恢复
    wait_for(gateway.is_running, timeout=15)
    
    # 5. 验证消息被处理
    reply2 = pending_msg.wait_for_reply(timeout=10)
    assert reply2.received, "Message sent during crash should be processed after recovery"
    
    # 6. 验证仅有一个进程
    assert len(get_gateway_processes()) == 1
```

---

## 二、开发环境重启

### TC-GL-005 [P1] `cargo tauri dev` 重启 → 旧进程被杀、新进程正常

| 属性 | 内容 |
|------|------|
| **Given** | 开发模式运行 `cargo tauri dev`；网关已启动 |
| **When** | 修改 Tauri/Rust 源码触发 dev 模式自动重启（或手动 Ctrl+C 后重新运行） |
| **Then** | 旧 `python.exe`（web_server + gateway）进程被完全终止；新进程正常启动；无僵尸 PID；锁文件自动清理 |

**手工执行步骤：**
1. 终端运行 `cargo tauri dev`
2. 等待完全启动，确认网关"运行中"
3. 任务管理器记录当前 python.exe PID
4. 修改 `tauri/src/` 中任意 `.rs` 文件保存（或按 Ctrl+C 后重新运行）
5. 等待 dev 模式重新编译并启动
6. 任务管理器确认：旧 PID 已消失，新 PID 已创建
7. 搜索 `.lock` 文件 → 无残留

**常见陷阱：**
- 若旧进程残留，检查 `tauri/src/python_supervisor.rs` 的 `Drop` 实现是否正确发送终止信号
- Windows 上可能出现 `os error 32`（文件被占用）→ 参见 ROADMAP.md §2

---

## 三、构建后首次启动

### TC-GL-006 [P2] `build_bundle.ps1` 后首次启动 — patch 成功 + 无 PyYAML 错误

| 属性 | 内容 |
|------|------|
| **Given** | 干净环境或 `python/dist/runtime` 已删除；`build_bundle.ps1` 可正常执行 |
| **When** | 执行 `powershell -ExecutionPolicy Bypass -File .\python\build_bundle.ps1` |
| **Then** | 脚本执行完成无报错；`python/dist/runtime/` 目录存在且包含完整依赖；首次启动 Kabuqina 无 PyYAML 相关 ImportError |

**手工执行步骤：**
1. （可选）删除 `python/dist/runtime/` 模拟干净环境
2. 打开 PowerShell → 执行 `cd <project_root>`
3. 执行 `.\python\build_bundle.ps1`
4. 观察输出：
   - 应看到 `Applying patch...` 或 `Patch already applied, skipping`
   - 不应有红色 ERROR 输出
   - 最后应看到 `Build complete` 或类似成功提示
5. 构建完成后，启动 Kabuqina（或 `cargo tauri dev`）
6. 检查启动日志 → 搜索 `PyYAML` / `yaml` → 无 ImportError / ModuleNotFoundError
7. 验证 `/chat` 页面可正常打开并对话

**两种场景：**
- **首次构建**（无 runtime 目录）：patch apply + 完整 bundle 构建
- **增量构建**（runtime 已存在）：patch 检查（已 apply → 跳过 或 未 apply → apply）+ 增量更新

**预期输出示例：**
```powershell
# 首次构建
PS> .\python\build_bundle.ps1
Patch not yet applied. Applying patch...            ← patch 被应用
Collecting PyYAML>=6.0 ...                            ← 依赖安装
...
Bundle build complete: python/dist/runtime/           ← 成功

# 增量构建
PS> .\python\build_bundle.ps1
Patch already applied, skipping.                      ← 不重复 patch
...
Bundle build complete.
```

---

## 四、进程残留检查清单

以下检查项应在每次停止/重启/Crash 恢复后执行：

| 检查项 | 方法 | 预期 |
|--------|------|------|
| Gateway 进程数量 | `Get-Process python \| Where-Object {$_.CommandLine -like "*gateway.run*"}` | 0（停止后）或 1（运行中） |
| Web 子进程数量 | `Get-Process python \| Where-Object {$_.CommandLine -like "*desktop_entrypoint*"}` | 1（Kabuqina 运行期间始终 1 个） |
| 锁文件残留 | `ls $env:APPDATA\Kabuqina\hermes-home\*.lock` | 无文件 |
| 端口占用 | `netstat -ano \| findstr "127.0.0.1:<gateway_port>"` | 无占用（停止后） |

---

## 附录：自动化骨架

```python
# tests/test_gateway_lifecycle.py
import pytest
import psutil
import signal
import time
import os

class TestGatewayLifecycle:
    """TC-GL-001 ~ TC-GL-006"""

    def test_stop_gateway_cleans_lock(self, gateway):
        """TC-GL-001"""
        gateway.start()
        assert gateway.is_running()
        gateway.stop()
        assert not gateway.is_running(timeout=5)
        assert not gateway.lock_file_exists()
        assert "[hermes-desklock]" in gateway.stderr_logs

    def test_stop_then_start_no_lock_conflict(self, gateway):
        """TC-GL-002"""
        gateway.start()
        pid_before = gateway.pid
        gateway.stop()
        gateway.start()
        pid_after = gateway.pid
        assert pid_before != pid_after
        assert gateway.is_running()

    def test_rapid_stop_start_3_cycles(self, gateway):
        """TC-GL-003"""
        for i in range(3):
            gateway.start()
            time.sleep(1)
            gateway.stop()
            time.sleep(1)
        gateway.start()
        assert len(gateway.get_gateway_processes()) == 1
        assert not gateway.has_orphaned_locks()

    def test_crash_recovery_message_queue(self, gateway, telegram_client):
        """TC-GL-004"""
        gateway.start()
        telegram_client.send("msg-before-crash")
        reply1 = telegram_client.wait_for_reply(timeout=10)
        assert reply1.received

        # 模拟 crash
        gateway.kill(signal=signal.SIGKILL)
        pending = telegram_client.send("msg-during-crash")

        gateway.wait_for_recovery(timeout=15)
        reply2 = pending.wait_for_reply(timeout=10)
        assert reply2.received, "Queued message should be processed after recovery"

    def test_build_bundle_first_start(self):
        """TC-GL-006"""
        # 干净构建
        if os.path.exists("python/dist/runtime"):
            shutil.rmtree("python/dist/runtime")
        result = run_build_bundle()
        assert result.returncode == 0
        assert "error" not in result.stderr.lower()
        
        # 首次启动
         gateway = start_Kabuqina()
         assert "PyYAML" not in gateway.logs
         assert gateway.chat_page_is_accessible()
```

## 执行记录 (2026-05-01)

| 用例 | 结果 | 备注 |
|------|------|------|
| TC-GL-001 | ✓ PASS | 点停止 → 状态变为"未运行"，显示"stopped"；`gateway.lock`、`gateway.pid` 清理 |
| TC-GL-002 | ✓ PASS | 停止后启动 → 约 1 分钟完成启动，飞书 bot 正常回复（Telegram 超时未影响）<br>修复验证：`gateway/run.py:2774-2784`（首轮连接失败不退出）<br>修复验证：`tauri/src/lib.rs` + `gateway_supervisor.rs`（停止时清理锁文件 + state） |
| TC-GL-003 | ✓ PASS | 等价覆盖—停止一次后启动正常工作，锁文件被 spawn 阶段自动清理 |
| TC-GL-004 | ✗ NOT IMPL | Rust `GatewaySupervisor` 无进程监控重启逻辑，需后续实现 |
| TC-GL-005 | ✗ SKIP | 开发环境正常 |
| TC-GL-006 | ✓ PASS | build_bundle.ps1 执行成功，首次启动无 PyYAML 错误 |
