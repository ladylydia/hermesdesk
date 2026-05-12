# Kabuqina Gateway 启动问题排查报告

> **存档说明（2026-04）：** 本文记录一次集中排查过程；**当前权威排障**见 [`troubleshooting.md`](troubleshooting.md) §§12–14（启动命令、`PYTHONPATH`、`build_bundle` 与子模块同步）。实现以 `tauri/src/gateway_supervisor.rs` 为准。

> 排查时间：2026-04-27  
> 状态：核心根因已定位，待最终验证

---

## 1. 症状描述

- **Gateway 无法启动**，网页端显示"未运行"
- **日志文件完全为空**（`hermes-home/logs/gateway.log` 不存在或 0 字节）
- 所有消息平台（微信/QQ/Telegram/飞书等）均无法测试
- 早期版本：网页端报红字 `Gateway exited during startup (exit code: 1)`
- 最新版本（去掉 `--replace -q` 后）：红字消失，但点击"启动网关"后**终端无任何输出**，状态仍为"未运行"

---

## 2. 排查路径与发现

### 2.1 第一层：Rust 端日志系统未初始化

**发现**：`gateway_supervisor.rs` 使用 `log::info!` / `log::error!` 记录 Gateway 启动信息，但 `main.rs` 中**未初始化 logger 后端**（如 `env_logger`、`tauri-plugin-log`）。

**后果**：Python Gateway 的所有报错（`ModuleNotFoundError`、`TypeError`、`AttributeError`）被直接丢弃，终端和日志文件均不可见，形成"黑盒"。

**验证方法**：临时将 `log::info!` 改为 `println!` 可强制输出到终端。

---

### 2.2 第二层：Tauri 启动命令错误

**文件**：`tauri/src/gateway_supervisor.rs`

**原始代码**：
```rust
cmd.args([
    "-m",
    "hermes_cli.main",      // ❌ 错误入口
    "gateway",
    "run",
    "--replace",
    "-q",
])
```

**问题**：`hermes_cli.main` 的 `cmd_gateway()` 函数尝试 `from hermes_cli.gateway import gateway_command`，但 `gateway` 包的 `__init__.py` 中**没有定义 `gateway_command`**，且 `run.py` 的 `main()` **不接受参数**。

**修复方向**：应直接调用 `hermes_cli.gateway.run`：
```rust
cmd.args([
    "-m",
    "hermes_cli.gateway.run",  // ✅ 正确入口
])
```

---

### 2.3 第三层：`gateway` 目录打包位置错误

**发现**：`runtime/hermes/gateway/` 存在，但 `runtime/hermes/hermes_cli/gateway/` **不存在**。

**根因**：打包脚本/CI 将 `gateway` 复制到了 `hermes/gateway/`（与 `hermes_cli` 同级），但 Python import 路径要求它在 `hermes/hermes_cli/gateway/` 下。

**临时修复**：手动移动目录：
```powershell
Move-Item ".\hermes\gateway" ".\hermes\hermes_cli\gateway"
```

**永久修复**：修改打包脚本，确保 `gateway` 复制到 `hermes/hermes_cli/gateway/`。

---

### 2.4 第四层：`hermes/__init__.py` 缺失

**发现**：`runtime/hermes/` 目录下**没有 `__init__.py`**。

**后果**：Python 将 `hermes` 视为**隐式命名空间包**（PEP 420），导致子线程中的 `from cron.scheduler import tick` 解析异常：
```
ModuleNotFoundError: No module named 'cron.scheduler'; 'cron' is not a package
```

**临时修复**：创建空文件：
```powershell
New-Item -Path ".\hermes\__init__.py" -ItemType File -Force
```

**永久修复**：打包时确保创建 `hermes/__init__.py`。

---

### 2.5 第五层：`cron` 子线程导入不稳定

**文件**：`runtime/hermes/hermes_cli/gateway/run.py`，第 10265 行

**原始代码**：
```python
from cron.scheduler import tick as cron_tick
```

**问题**：主线程 `import cron` 能看到 `tick`，但子线程（`cron-ticker` 线程）执行同样 import 时，`cron` 模块被重新加载为**未完整初始化的版本**，`tick` 属性丢失。

**根因**：`run.py` 第 85 行 `sys.path.insert(0, ...)` 动态修改了路径，结合隐式命名空间包，导致子线程模块解析行为不一致。

**临时修复**：主线程预导入，子线程直接使用全局变量：
```python
# 文件顶部，import asyncio 之前
import cron as _cron_module
_cron_tick = getattr(_cron_module, "tick", None)

# _start_cron_ticker 函数内
cron_tick = _cron_tick  # 不再执行 import
```

**永久修复**：同上，修改源码 `hermes/hermes_cli/gateway/run.py`。

---

### 2.6 第六层：`run.py` 不接受 `--replace -q` 参数

**发现**：裸运行 `python -m hermes_cli.gateway.run` ✅ 正常启动。
但裸运行 `python -m hermes_cli.gateway.run --replace -q` ❌ 报错：
```
usage: run.py [-h] [--config CONFIG] [--verbose]
run.py: error: unrecognized arguments: --replace -q
```

**后果**：Tauri 传递 `--replace -q` 时，`run.py` 的 `argparse` 解析失败，`sys.exit(1)`，进程秒退。

**修复**：`gateway_supervisor.rs` 中**删除 `--replace` 和 `-q` 参数**。

---

## 3. 当前状态（截至 2026-04-27 22:00）

### 3.1 已完成的手动修复（runtime 目录）

| 修复项 | 状态 |
|--------|------|
| `gateway` 移动到 `hermes/hermes_cli/gateway/` | ✅ 完成 |
| 创建 `hermes/__init__.py` | ✅ 完成 |
| `run.py` 主线程预导入 `_cron_tick` | ✅ 完成 |
| `gateway_supervisor.rs` 删除 `--replace -q` | ✅ 完成 |
| 重新编译 `cargo build --release` | ✅ 完成 |

### 3.2 待验证现象

- 点击"启动网关"后，**Tauri 终端无任何 `[gateway_spawn]` 输出**
- 网页状态仍为"未运行"
- 红字报错已消失

### 3.3 两种可能的解释

**解释 A：spawn 执行了，但 Gateway 秒退（exit 0）**
- `run.py` 的 `main()` 在没有平台配置时主动退出
- 需要配置至少一个平台的 Token 才能持续运行
- 验证方法：在 `.env` 里添加 `GATEWAY_ALLOW_ALL_USERS=true` 和任意平台 Token

**解释 B：spawn 根本没执行**
- Rust 代码中可能存在前置检查（如 `dotenv_suggests_messaging_gateway`），发现无平台配置直接返回
- 或 `println!` / `log::info!` 被前端过滤，实际 spawn 已执行但看不到输出
- 验证方法：将 `gateway_supervisor.rs` 中的 `log::info!` 改为 `println!`，观察终端

---

## 4. 永久修复清单（回源码仓库）

### 4.1 Rust 侧

**文件**：`tauri/src/gateway_supervisor.rs`

```rust
// 修改启动命令
cmd.args([
    "-m",
    "hermes_cli.gateway.run",  // 直接调用 gateway.run
]);

// 删除以下参数（run.py 的 argparse 不认识）：
// "--replace",
// "-q",
```

**文件**：`tauri/src/main.rs`（或 `lib.rs`）
- 检查并初始化 logger 后端（如 `tauri-plugin-log` 或 `env_logger`），确保 `log::info!` 能输出到文件/终端

### 4.2 Python 侧

**文件**：`hermes/hermes_cli/gateway/run.py`
- 在 `import asyncio` 之前添加主线程预导入：
```python
import cron as _cron_module
_cron_tick = getattr(_cron_module, "tick", None)
```
- 修改 `_start_cron_ticker` 函数：
```python
cron_tick = _cron_tick  # 不再执行 from cron.scheduler import tick
```

**文件**：`hermes/hermes_cli/gateway/__init__.py`
- 如果保留 `main.py` 的 `cmd_gateway` 调用方式，添加适配器：
```python
def gateway_command(args=None):
    from .run import main
    main()
```

### 4.3 打包脚本/CI

- 确保 `gateway` 目录复制到 `hermes/hermes_cli/gateway/`（不是 `hermes/gateway/`）
- 确保创建空的 `hermes/__init__.py`
- 确保 `hermes/hermes_cli/gateway/__init__.py` 包含正确的导出

---

## 5. 下一步验证建议

### 5.1 验证 spawn 是否执行

将 `gateway_supervisor.rs` 中的 `log::info!` 替换为 `println!`：
```rust
println!("[gateway_spawn] about to spawn: {:?}", py_exe);
println!("[gateway_spawn] child spawned, pid={:?}", c.id());
```

重新编译，点击"启动网关"，观察终端是否有输出。

### 5.2 验证平台配置是否影响启动

在 `hermes-home/.env` 中添加：
```env
GATEWAY_ALLOW_ALL_USERS=true
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

重启应用，点击"启动网关"，观察状态是否变为"运行中"。

### 5.3 验证裸运行行为

```powershell
cd tauri/target/release/runtime
$env:PYTHONPATH = ".\hermes;.\site-packages"
$env:HERMES_HOME = "$env:APPDATA\Kabuqina\hermes-home"
.\python\python.exe -m hermes_cli.gateway.run
```

观察：是 hang 住（正常）还是秒退（需要配置平台）。

---

## 6. 关键文件路径速查

| 文件 | 路径 |
|------|------|
| Rust Gateway 启动器 | `tauri/src/gateway_supervisor.rs` |
| Tauri 主入口 | `tauri/src/main.rs` |
| Python Gateway 入口 | `runtime/hermes/hermes_cli/gateway/run.py` |
| Gateway 包 init | `runtime/hermes/hermes_cli/gateway/__init__.py` |
| Hermes 包 init | `runtime/hermes/__init__.py` |
| 用户配置 | `%APPDATA%/Kabuqina/hermes-home/.env` |
| 日志目录 | `%APPDATA%/Kabuqina/hermes-home/logs/` |
| 编译输出 | `tauri/target/release/Kabuqina.exe` |

---

*排查人：Kimi / kimimi*
*备注：所有手动修复在 `cargo build --release` 后可能被构建脚本覆盖，需同步修改源码。*
