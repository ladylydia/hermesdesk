# Gateway Lock 文件在 Windows 上的已知问题

> 记录日期：2026-05-01  
> 会话范围：Kabuqina 测试轮 — 网关生命周期 / 消息渠道相关 bug

---

## 1. 背景

Hermes gateway 使用 `msvcrt.locking(LK_NBLCK, 1)` 在 `gateway.lock` 文件上加跨进程字节范围锁。这个 API 是 POSIX `flock` 的近似物，但行为差异显著：

| | POSIX fcntl.flock | Windows msvcrt.locking |
|---|---|---|
| 进程死时 | 自动释放 | 经常残留 |
| 可被 unlink 删除 | 可以 | 不行 |
| 可被 ftruncate 清内容 | 可以 | 内容被清，锁还在 |
| 可被其他进程解锁 | 不行 | 不行 |

所有 bug 都源于：**旧的 gateway 进程退出时未释放锁，新的 gateway 启动时尝试加锁失败。**

---

## 2. 已修复的锁相关 bug

### 2.1 `get_running_pid()` — 读 stale 锁文件触发 PermissionError

**文件**：`gateway/status.py → get_running_pid()`  
**症状**：新 gateway 启动时调 `get_running_pid()` → 内部 `read_text()` stale `gateway.lock` → `PermissionError` → 未捕获 → 穿透到 `main()` → 进程崩溃  
**修复**：`PermissionError / OSError` 视为 stale lock，调用 `_cleanup_invalid_pid_path()` 删除文件，返回 `None`  
**状态**：✅ 已修复（hermes submodule: `8b65d361f`）

### 2.2 `acquire_gateway_runtime_lock()` — 加锁失败直接 return False

**文件**：`gateway/run.py → start_gateway()`  
**症状**：`get_running_pid()` 返回 None（过程是对的——没活进程），但接下来的 `acquire_gateway_runtime_lock()` 在 stale 锁文件上 `msvcrt.locking(LK_NBLCK, 1)` 失败 → 直接 `return False` → `sys.exit(1)`  
**修复**：失败时判断 `_current_pid is None` → 认定 stale → 清理文件后重试一次  
**状态**：✅ 已修复（hermes submodule: `279b823ba`）

### 2.3 `unlink()` 删不动 Windows 上带字节锁的文件

**文件**：同上 `gateway/run.py`  
**症状**：2.2 的清理用 `unlink(missing_ok=True)` → 在 Windows 上 `DeleteFileW` 拒绝删除被锁文件 → `except Exception: pass` 静默吞了 → 文件还在，锁还在，重试仍然失败  
**修复**：改为 `os.open + os.ftruncate + os.write(b'\n')` 代替 `unlink`。`ftruncate` 在文件描述符层面操作，可清空文件内容，写 1 字节确保后续 `msvcrt.locking` 有目标字节可锁  
**状态**：✅ 已修复（hermes submodule: `bfbcabe43`, `65700d219`）

### 2.4 Rust 侧 `std::fs::remove_file` 在加锁文件上静默失败

**文件**：`tauri/src/gateway_supervisor.rs → spawn()`  
**症状**：`let _ = std::fs::remove_file(hermes_home.join("gateway.lock"))` — Windows 上删不动 → 错误被 `let _=` 吞掉 → Python 进程起不来  
**影响**：仅在 Rust 侧的清理步骤中（spawn 前置清理、stop_gateway_service 后清理）。依赖 Python 侧 2.2/2.3 的修复兜底  
**状态**：⚠️ 未修复——`let _=` 仍然是静默吞错。已通过 Python 侧兜底缓解，但 Rust 侧的错误日志缺失

### 2.5 `cargo tauri dev` 退出时孤儿 process 持有锁

**文件**：`tauri/src/gateway_supervisor.rs → shutdown()`  
**症状**：`cargo tauri dev` 退出时，Rust 进程先死，但 `shutdown()` 里的 `child.start_kill()` 没等到 Python gateway 子进程真正退出。子进程变为孤儿，继续持有 `gateway.lock` 的字节锁 → 下次 `cargo tauri dev` 启动时锁冲突  
**临时规避**：启动前手动杀孤儿进程：
```powershell
taskkill /F /IM python.exe 2>$null
```
**状态**：⚠️ 未修复——Rust 侧 `shutdown()` 需要 `wait_timeout` 确认子进程已退出，而非仅等待 3 秒

---

## 3. 已完成的锁相关辅助修复

### 3.1 停止网关时清理锁文件 + 写入 "stopped" 状态

**文件**：`tauri/src/lib.rs → stop_gateway_service()`  
**修复**：杀死子进程后，主动删除 `gateway.lock`、`gateway.pid`，写入 `gateway_state.json` 为 `"stopped"`  
**状态**：✅ 已修复（commit `a8a1bd4`）

### 3.2 `GatewaySupervisor::spawn()` 清理 stale `gateway_state.json`

**文件**：`tauri/src/gateway_supervisor.rs → spawn()`  
**修复**：启动前删除旧 `gateway_state.json`，避免前端显示死进程的 "running" 状态  
**状态**：✅ 已修复（commit `a8a1bd4`）

---

## 4. 并行启动修改中引入的相关 bug

### 4.1 微信撤销配置只删了 2 个 key，残留 8 个

**文件**：`tauri/src/weixin_qr.rs → cmd_weixin_env_remove`  
**症状**：初版只匹配 `WEIXIN_ACCOUNT_ID=` 和 `WEIXIN_TOKEN=`，但 `.env` 里还有 `WEIXIN_BASE_URL`、`WEIXIN_CDN_BASE_URL` 等 8 个键残留 → 微信 adapter 拿到残缺配置 → 触发未捕获异常 → 进程崩溃 → 留下 stale 锁文件  
**修复**：改为匹配所有 `WEIXIN_` 前缀  
**状态**：✅ 已修复（commit `a8a1bd4`）。同步修了 QQ（所有 `QQ_` 前缀）和飞书（所有 `FEISHU_` 前缀）

### 4.2 并行连接异常穿透

**文件**：`gateway/run.py → _start_platforms → _connect_one`  
**症状**：`except Exception` 没覆盖 `BaseException` 子类（如 `CancelledError`），异常可能穿透 `asyncio.gather(return_exceptions=True)`  
**修复**：`except Exception` → `except BaseException`  
**状态**：✅ 已修复（commit `a8a1bd4`）

### 4.3 并行写 `gateway_state.json` 无锁

**文件**：`gateway/status.py → write_runtime_status`  
**症状**：并行启动时多个 platform 同时调 `write_runtime_status`（读-改-写 JSON）→ 后写的覆盖先写的  
**修复**：加 `threading.Lock` 保护  
**状态**：✅ 已修复（commit `a8a1bd4`）

---

## 5. 其他相关改动

### 5.1 web_dist 过旧导致平台配置状态不显示

**文件**：`python/dist/runtime/hermes/hermes_cli/web_dist/`  
**症状**：前端源码有 `cmd_*_env_status` 调用，但打包的 JS bundle 里没有 → 已配 Telegram 不显示"已配置"  
**修复**：`cd hermes/web && npm run build`，同步到 dist/runtime  
**状态**：✅ 已修复（commit `a8a1bd4`）

---

## 6. 修改文件清单

| 文件 | 改动类型 |
|------|---------|
| `hermes/gateway/run.py` | 并行连接 + stale lock 恢复 (2.2, 2.3, 4.2) |
| `hermes/gateway/status.py` | PermissionError 处理 + 并发锁 (2.1, 4.3) |
| `hermes/hermes_cli/pty_bridge.py` | Windows 兼容 (fcntl/termios 条件导入) |
| `tauri/src/lib.rs` | stop 清理文件 + platforms 字段 + stderr 显示 (3.1) |
| `tauri/src/gateway_supervisor.rs` | spawn 清理 + stderr 最后 8KB 捕获 (3.2) |
| `tauri/src/telegram_env.rs` | 撤销配置命令 (4.1) |
| `tauri/src/weixin_qr.rs` | 撤销配置命令 (4.1) |
| `tauri/src/qq_env.rs` | 撤销配置命令 (4.1) |
| `tauri/src/feishu_env.rs` | 撤销配置命令 (4.1) |
| `web/src/onboarding/setupCatalog/optionData.ts` | Wizard 只显示 4 个渠道 |
| `web/src/components/TelegramSettingsBlock.tsx` | 撤销按钮 + 确认弹窗 |
| `web/src/components/WeixinQrRouteCBlock.tsx` | 撤销按钮 + 确认弹窗 |
| `web/src/components/FeishuQrRouteBlock.tsx` | 撤销按钮 + 确认弹窗 |
| `web/src/components/QqbotQrRouteBlock.tsx` | 撤销按钮 + 确认弹窗 |
| `web/src/advanced/Settings.tsx` | 平台进度 + 2s 轮询 |
| `web/src/locales/strings.ts` | i18n |
| `python/build_bundle.ps1` | 构建脚本（镜像配置） |
| `docs/test-plan.md` + 5 个 test-case 文件 | 测试文档 |
