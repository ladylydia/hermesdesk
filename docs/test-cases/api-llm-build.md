# API / LLM — 模型调用 + 构建 & 部署

> 对应 test-plan.md §8 / §9
> 覆盖模型调用（含工具调用 / reasoning）、API Key 异常处理、模型切换、自定义 Provider，以及构建脚本和 CI 检查
> 
> **上次执行**：2026-05-01 | 执行人：AI + X13 | 版本：v2026.4.23-1126-g9a1454060

---

## 环境前置条件

| 项 | 要求 |
|----|------|
| Kabuqina | 可启动版本（dev 或安装包） |
| API Keys | `[待填写: DeepSeek API Key]`（有效）、`[待填写: 过期 DeepSeek API Key]`（用于异常测试） |
| 网络 | 主路径：`api.deepseek.com`；可选多提供商测试时需对应端点（如 `openrouter.ai`） |
| 构建环境 | PowerShell 5.1+ / 7.x；Python 3.11+；Rust toolchain（`cargo`） |
| 代码仓库 | 完整的 Kabuqina repo（含 `hermes/` submodule） |

---

## 一、模型调用

### TC-AB-001 [P0] DeepSeek v4 Flash — reasoning=high → 正常回复无 400

| 属性 | 内容 |
|------|------|
| **Given** | API Key 已配置；模型选择 DeepSeek v4 Flash；`reasoning=high` 参数生效 |
| **When** | 发送对话消息 `"请用中文解释什么是机器学习"` |
| **Then** | 收到正常回复；HTTP 状态 200；响应中 `reasoning_content` 字段存在且非空；无 400/500 错误 |

**手工执行步骤（步骤级）：**
1. 启动 Kabuqina，完成 API Key 配置（DeepSeek）
2. 在设置页确认当前模型为 `"DeepSeek v4 Flash"`
3. 进入 `/chat`
4. 发送消息：`"请用中文简要解释什么是机器学习"`
5. 观察回复：
   - 内容合理、通顺 ✓
   - 无错误弹窗或 `"请求失败"` 提示 ✓
6. 查看日志（DEBUG 级别）：
   - 搜索 `"reasoning_content"` → 字段存在且有内容
   - 搜索 HTTP status → 应为 200

**关键断言：**
```
response.status == 200
response.json().choices[0].reasoning_content is not None
response.json().choices[0].reasoning_content != ""
```

---

### TC-AB-002 [P0] 多轮对话中 tool-calls-only 回合 — 无 `reasoning_content missing` 错误

| 属性 | 内容 |
|------|------|
| **Given** | 当前模型 DeepSeek v4 Flash（支持 tool_calls）；对话已进行至少 2 轮 |
| **When** | 发送一条触发工具调用的消息，如 `"请帮我查看当前目录有什么文件"`（触发 `shell`/`exec` 工具） |
| **Then** | 工具调用正常执行；tool_calls 回合中若模型不返回 reasoning_content，网关不抛 `reasoning_content missing` 异常 |

**手工执行步骤（步骤级）：**
1. 确保 `GATEWAY_SHELL_ENABLED=true` 已配置
2. 在 `/chat` 发送：`"请用 ls 命令查看当前目录的文件"`
3. 观察 AI 回复流程：
   - 第 1 步：AI 生成 tool_call 请求（用户不可见或以内联方式展示）
   - 第 2 步：工具执行结果返回
   - 第 3 步：AI 基于工具结果生成最终回复
4. **关键验证**：整个流程无报错；日志中无 `"reasoning_content missing"` 或 `"KeyError: reasoning_content"`
5. 最终回复应包含当前目录的文件列表信息

**失败迹象**：
```
# 以下日志输出表示 BUG
ERROR: reasoning_content missing in message with role='assistant' tool_calls=[...]
KeyError: 'reasoning_content'
```

---

### TC-AB-003 [P1] API Key 过期 → 友好错误提示，网关不 crash

| 属性 | 内容 |
|------|------|
| **Given** | 使用一个已过期或已被撤销的 API Key |
| **When** | 发送任意消息 |
| **Then** | 前端显示友好错误提示（如 `"API Key 无效或已过期，请检查设置"`）；网关进程不退出；日志记录 401 Unauthorized |

**手工执行步骤：**
1. 在设置页将 DeepSeek API Key 替换为 `[待填写: 过期 DeepSeek API Key]`
2. 保存配置
3. 在 `/chat` 发送测试消息
4. 验证：
   - AI 消息气泡位置显示红色错误提示文案（非空白/非技术堆栈）
   - 文案示例：`"请求失败：API Key 无效或已过期 (HTTP 401)，请前往设置页检查"`
   - 提供跳转到设置的链接
5. 检查任务管理器 → `python -m gateway.run` 进程仍在运行（未 crash）
6. 检查日志 → 记录 `HTTP 401 Unauthorized`，但无 traceback/exception

**自动化模板：**
```python
def test_expired_api_key_friendly_error(gateway):
    gateway.configure_provider(api_key="sk-expired-invalid-key-12345")
    response = gateway.send_chat_message("Hello")
    
    assert response.http_status == 401
    assert "API Key 无效" in response.user_facing_error or "invalid" in response.user_facing_error.lower()
    assert gateway.process_is_running(), "Gateway should NOT crash on 401"
```

---

### TC-AB-004 [P1] 模型切换 `/model` 命令（**可选**：需单独配置 OpenRouter 等第二提供商）

| 属性 | 内容 |
|------|------|
| **Given** | 主对话为 **DeepSeek**；且已额外配置 **OpenRouter**（或其它网关支持 `openrouter/...` slug） |
| **When** | 在 Telegram 群聊中发送 `/model openrouter/gpt-4o`（Owner 用户） |
| **Then** | 网关回复确认切换；新会话使用 `openrouter/gpt-4o`；已有会话不受影响 |

**手工执行步骤：**
1. 确认发送者为 Owner（在 `GATEWAY_OWNER_IDS` 中）
2. 在 Telegram 发送 `/model openrouter/gpt-4o`
3. 验证 Bot 回复确认切换
4. 发送新消息 → 查看日志中请求的 model 字段是否为 `openrouter/gpt-4o`
5. **验证会话隔离**：之前已有的对话仍使用旧模型；新对话使用新模型

**边界 — 非 Owner 发送：**
- 非 Owner 发送 `/model xxx` → 回复 `"Unauthorized: owner only command"`

---

### TC-AB-005 [P2] 自定义 Provider 配置 — 正常路径

| 属性 | 内容 |
|------|------|
| **Given** | 在设置页选择"自定义提供商" |
| **When** | 填写 Base URL（如 `https://my-api.example.com/v1`）+ Model Name + API Key |
| **Then** | 配置保存成功；发送消息时请求发往自定义 Base URL |

**手工执行步骤：**
1. `/settings` → 模型提供商 → 选择"自定义"
2. Base URL: `https://my-api.example.com/v1`
3. Model Name: `custom-model-v1`
4. API Key: `[待填写: 自定义 Provider API Key]`
5. 点击"验证" → 绿色 ✓
6. 发送消息 → 检查日志中请求 URL 为自定义地址

---

### TC-AB-006 [P2] 自定义 Provider — URL 格式错误 + 连接超时

| 属性 | 内容 |
|------|------|
| **Given** | 在自定义提供商页面 |
| **When** | 输入错误的 URL 格式 / 不可达的服务器 |
| **Then** | 验证时显示相应错误提示 |

**异常场景：**
| 输入 | 预期错误 |
|------|---------|
| `not-a-url` | `"无效的 URL 格式"` |
| `ftp://invalid.com/v1` | `"仅支持 HTTP/HTTPS 协议"` |
| `https://192.0.2.1:9999/v1`（不可达 IP） | `"连接超时，请检查地址是否正确"`（超时时间约 10-15s） |

---

## 二、构建 & 部署

### TC-AB-007 [P1] `build_bundle.ps1` 干净构建

| 属性 | 内容 |
|------|------|
| **Given** | 代码仓库完整（含 `hermes/` submodule）；`python/dist/runtime` 不存在或为空 |
| **When** | 执行 `powershell -ExecutionPolicy Bypass -File .\python\build_bundle.ps1` |
| **Then** | 脚本退出码 0；`python/dist/runtime/` 包含完整 Python 运行时；无红色 ERROR 输出 |

**手工执行步骤（步骤级）：**
1. 打开 PowerShell（建议 7.x，5.1 兼容也可）
2. `cd <project_root>`
3. 清理旧构建（可选）：`if (Test-Path python/dist/runtime) { Remove-Item -Recurse -Force python/dist/runtime }`
4. 执行：`.\python\build_bundle.ps1`
5. 观察输出：
   - 依赖安装过程（pip install）
   - patch 应用（`Applying patch...` 或 `Patch already applied, skipping`）
   - 无红色 ERROR
   - 最终以 `"Build complete"` / `"Done"` 结束
6. 验证退出码：`$LASTEXITCODE` → 应为 `0`
7. 检查输出目录：`ls python/dist/runtime/` → 应包含 Python 解释器、site-packages 等
8. 启动 Kabuqina → `/chat` 正常对话 → 验证 bundle 可用

---

### TC-AB-008 [P1] `build_bundle.ps1` 增量构建 — patch 已 apply 时跳过

| 属性 | 内容 |
|------|------|
| **Given** | 已执行过一次 `build_bundle.ps1`，patch 已 apply，runtime 目录存在 |
| **When** | 再次执行 `build_bundle.ps1` |
| **Then** | patch 步骤检测到已 apply → 跳过，不报错；增量更新依赖；总耗时比首次构建短 |

**手工执行步骤：**
1. 确认 `python/dist/runtime/` 已存在
2. 再次执行 `.\python\build_bundle.ps1`
3. 观察输出：
   - 应看到 `Patch already applied, skipping.` 或类似提示
   - 不执行重复的 patch 操作
4. 验证退出码 0
5. 验证 Kabuqina 仍可正常启动

---

### TC-AB-009 [P2] `sync_upstream.ps1 -DryRun` 所有检查通过

| 属性 | 内容 |
|------|------|
| **Given** | 代码仓库处于干净状态；`hermes/` submodule 无意外修改 |
| **When** | 执行 `.\scripts\sync_upstream.ps1 -DryRun` |
| **Then** | 所有检查项通过；输出绿色/成功提示；退出码 0 |

**手工执行步骤：**
1. PowerShell → `cd <project_root>`
2. 执行 `.\scripts\sync_upstream.ps1 -DryRun`
3. 检查输出：
   - 应列出检查项清单（如 submodule 状态、脏文件检测等）
   - 每项显示 `[PASS]` / `✓` / 绿色
   - 无 `[FAIL]` / `✗` / 红色
4. `$LASTEXITCODE` → `0`

**边界 — 有脏文件时拒绝：**
1. 故意修改 `hermes/` 下的某个文件（不提交）
2. 再次执行 `-DryRun`
3. 验证：脏文件检测项显示 `[FAIL]`；脚本建议先清理或提交
4. `$LASTEXITCODE` → 非 0
5. 恢复原文件 → 重新运行 → 通过

---

### TC-AB-010 [P2] `cargo tauri dev` 冷启动（首次编译）

| 属性 | 内容 |
|------|------|
| **Given** | Rust 工具链已安装；`target/` 目录不存在或被清理 |
| **When** | 执行 `cargo tauri dev` |
| **Then** | Rust 编译通过无 error；Vite dev server 正常启动；窗口打开后 `/chat` 可访问 |

**手工执行步骤：**
1. 清理（可选）：`cargo clean`
2. 终端执行 `cargo tauri dev`
3. 观察编译过程：
   - Rust 编译：`Compiling Kabuqina v0.x.x`
   - 依赖下载/编译无报错
   - 最终以 `Running Kabuqina` 结束
4. 窗口自动打开
5. 等待前端资源加载（Vite）→ Splash → Onboarding（首次）或直接到 `/chat`
6. 验证页面可交互

**常见问题排查：**
- 若 Rust 编译报错 → 检查 `rustc --version` 和 `cargo --version`
- 若 Vite 热更新不工作 → 检查 `web/` 目录下 `npm install` 是否已执行
- Windows 上若报 `os error 32` → 关闭杀毒软件或添加排除项（参见 ROADMAP.md）

---

## 附录：测试数据

```
[待填写: DeepSeek API Key（有效）]       = ________________
[待填写: DeepSeek API Key（已过期）]      = ________________
[待填写: OpenRouter API Key（可选，用于 TC-AB-004）] = ________________
[待填写: 自定义 Provider Base URL]        = ________________
[待填写: 自定义 Provider Model Name]      = ________________
[待填写: 自定义 Provider API Key]         = ________________
```

---

## 附录：自动化骨架

```python
# tests/test_api_llm.py
import pytest

class TestModelCalling:
    """TC-AB-001 ~ TC-AB-006"""

    def test_deepseek_reasoning_high(self, gateway):
        """TC-AB-001"""
        gateway.configure_model("deepseek-v4-flash", reasoning="high")
        response = gateway.send_chat_message("解释什么是机器学习")
        assert response.status_code == 200
        assert response.json()["choices"][0].get("reasoning_content")

    def test_tool_calls_no_reasoning_error(self, gateway):
        """TC-AB-002"""
        gateway.configure_model("deepseek-v4-flash")
        # 发送触发 tool-call 的消息
        response = gateway.send_chat_message("查看当前目录文件")
        assert "reasoning_content missing" not in gateway.logs
        assert "KeyError" not in gateway.logs

    def test_expired_api_key_no_crash(self, gateway):
        """TC-AB-003"""
        gateway.configure_provider(api_key="sk-expired-key")
        response = gateway.send_chat_message("Hello")
        assert response.http_status == 401
        assert gateway.is_running()

class TestBuild:
    """TC-AB-007 ~ TC-AB-010"""

    def test_build_bundle_clean(self):
        """TC-AB-007"""
        # 清理并构建
        pass

    def test_build_bundle_incremental(self):
        """TC-AB-008"""
        # 二次构建，验证 patch skip
        pass

    def test_sync_upstream_dryrun(self):
        """TC-AB-009"""
        result = run("./scripts/sync_upstream.ps1 -DryRun")
         assert result.returncode == 0
         assert "FAIL" not in result.stdout

---

## 执行记录 (2026-05-01)

| 用例 | 结果 | 备注 |
|------|------|------|
| TC-AB-001 | ✓ PASS | DeepSeek v4 Flash 6.5s 正常回复，46 completion tokens，无 400 错误 |
| TC-AB-002 | ✓ PASS | tool-calls 流程无 `reasoning_content missing` 或 KeyError，AI 正常降级回复 |
| TC-AB-003 | ✓ PASS | 过期 Key → HTTP 401 被捕获，错误信息清晰："Authentication Fails, Your api key: ****3dv3 is invalid"，进程未崩溃 |
| TC-AB-004 | ✗ SKIP | 可选：未配置 OpenRouter（主路径为 DeepSeek 时可跳过） |
| TC-AB-005 | ✗ SKIP | 无可用的自定义 Provider |
| TC-AB-006 | ✗ SKIP | 同上 |
| TC-AB-007 | ✓ PASS | build_bundle.ps1 成功执行（阿里云镜像） |
| TC-AB-008 | ✗ SKIP | 增量构建未测试 |
| TC-AB-009 | ✗ SKIP | scripts/sync_upstream.ps1 不存在 |
| TC-AB-010 | ✓ PASS | cargo tauri dev 编译通过，窗口正常打开 |
```
