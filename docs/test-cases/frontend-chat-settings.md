# 前端 — 壳内聊天 + 引导/设置 + 平台配置

> 对应 test-plan.md §5 / §6 / §7
> 覆盖 `/chat` 页面交互、Onboarding 引导流程、Settings 设置页、以及各消息平台的配置 UX

---

## 环境前置条件

| 项 | 要求 |
|----|------|
| OS | Windows 10/11 + WebView2 运行时 |
| Kabuqina | 可启动（dev 或安装包均可） |
| API Key | `[待填写: DeepSeek API Key]` 或选择跳过配置 |
| 屏幕 | 建议 1920x1080 以上，方便查看完整 UI |

---

## 一、壳内聊天（`/chat`）

### TC-FE-001 [P0] 壳内聊天 — 输入消息 → 发送 → 收到 AI 回复

| 属性 | 内容 |
|------|------|
| **Given** | Kabuqina 已启动，API Key 已配置；当前在 `/chat` 页面 |
| **When** | 在输入框输入 `"你好，请介绍一下自己"` → 点击发送按钮（或按 Enter） |
| **Then** | 输入框清空；用户消息出现在对话列表中；AI 在 5-10 秒内开始流式回复；最终回复内容完整显示 |

**手工执行步骤（步骤级）：**
1. 启动 Kabuqina，完成 onboarding（若首次启动）
2. 确认已导航到 `/chat` 页面（左侧应有消息输入框）
3. 在底部输入框点击聚焦
4. 输入测试消息：`"你好，请用一句话介绍自己"`
5. 按 `Enter` 键（或点击右侧发送按钮 ▶）
6. 观察：
   - 输入框内容清空 ✓
   - 用户消息气泡出现在对话区域右侧 ✓
   - AI 回复气泡出现在左侧，内容逐字流式输出 ✓
   - 回复内容合理（非空、非错误信息） ✓

**边界 — 空消息：**
- 输入框为空时按 Enter → 消息不应发送；输入框保持空状态，无报错

**边界 — API Key 未配置：**
- 清除 API Key 后刷新 `/chat` → 页面显示引导提示 `"请先配置 API Key"`，提供跳转到设置的链接

---

### TC-FE-002 [P0] 发送含附件的消息

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/chat` 页面，输入框可用 |
| **When** | 点击附件按钮（回形针图标）→ 选择 1 个文件 → 发送 |
| **Then** | 附件显示在消息气泡中；AI 回复中包含对附件内容的引用 |

**手工执行步骤（步骤级）：**
1. 在 `/chat` 页面，点击输入框左侧的回形针/附件图标
2. 在弹出的文件选择器中，选择一个文本文件（如 `.txt` 含 `"Hello World"`）
3. 确认文件名出现在输入框上方（附件预览区）
4. 输入附带消息 `"请总结这个文件的内容"`
5. 点击发送
6. 验证：附件名称显示在用户消息气泡中；AI 回复中提及文件内容

**边界验证：**
- 附件 > 12MB → 选择后提示 `"文件过大，请上传小于 12MB 的文件"`，不上传
- 选择 7 个文件 → 仅前 6 个显示在附件预览区，第 7 个被自动截断/提示
- 非文本附件（如 `.jpg`）→ AI 回复中说明 `"我无法直接查看图片内容"` 或进行图像理解（取决于模型能力）

---

### TC-FE-003 [P1] 停止生成按钮

| 属性 | 内容 |
|------|------|
| **Given** | AI 正在流式生成回复（回复尚未完成） |
| **When** | 点击"停止生成"按钮（通常为 ⬛ 方块图标） |
| **Then** | 流式输出立即停止；已生成的内容保留在对话中；停止按钮变回发送按钮；可继续发送新消息 |

**手工执行步骤：**
1. 发送一个需要较长时间回复的消息，如 `"请详细解释量子计算的原理，至少500字"`
2. 在 AI 回复流式输出的过程中，点击"停止生成"按钮
3. 验证：文字输出立即停止，已显示的内容保留
4. 立即发送新消息 `"你好"` → 验证对话可以继续

**底层验证**：`agent.interrupt()` 被正确调用；Rust 侧终止了 HTTP 流式请求

---

### TC-FE-004 [P1] 多轮对话上下文保持

| 属性 | 内容 |
|------|------|
| **Given** | 已有对话历史 |
| **When** | 进行多轮对话 |
| **Then** | 第 N 轮对话中 AI 仍能记住第 1 轮的内容 |

**手工执行步骤：**
1. 第 1 轮：发送 `"我叫张三，请记住这个名字"`
2. 等待 AI 回复确认
3. 第 2 轮：发送 `"1+1等于几"`（干扰问题）
4. 等待 AI 回复
5. 第 3 轮：发送 `"我刚才告诉你我叫什么？"`
6. **验证**：AI 回答 `"你叫张三"` 或类似内容，证明上下文保持

**失败迹象**：AI 回答 `"我不知道你的名字"` → 上下文丢失，提交 bug

---

### TC-FE-005 [P1] 侧边栏会话列表管理

| 属性 | 内容 |
|------|------|
| **Given** | 已有多个对话会话 |
| **When** | 新建 / 删除 / 切换会话 |
| **Then** | 各操作均正确生效 |

**手工执行步骤：**
1. **新建会话**：
   - 点击侧边栏 "+" 按钮（或"新对话"）
   - 验证：新会话出现在列表顶部，标题自动生成为 `"新对话"` 或基于首条消息内容
   - 对话区域清空，可开始新对话

2. **切换会话**：
   - 发送一条消息：`"这是会话A的内容"`
   - 点击侧边栏另一个会话 → 对话区域切换
   - 再点击原会话 → 验证 `"这是会话A的内容"` 仍在

3. **删除会话**：
   -  hover 会话项 → 点击出现的 "..." 或垃圾桶图标
   - 确认删除 → 会话从列表消失
   - 若删除的是当前会话 → 自动切换到最近的一个会话

4. **会话标题自动生成**：
   - 新建会话，发送 `"如何学习 Rust 编程语言"`
   - 验证：侧边栏会话标题自动变为 `"如何学习 Rust..."` 或类似摘要

---

## 二、引导 + 设置

### TC-FE-006 [P0] 引导流程 — 选择 DeepSeek → 输入 API Key → 完成引导

| 属性 | 内容 |
|------|------|
| **Given** | 首次安装 Kabuqina，未配置过任何内容 |
| **When** | 按引导流程完成设置 |
| **Then** | 引导完成，进入 `/chat` 页面，可正常对话 |

**手工执行步骤（步骤级）：**
1. 首次启动 Kabuqina → 看到 Splash 页面 → 自动跳转到 Onboarding 引导页
2. **欢迎页**：看到 Kabuqina 介绍文案 → 点击"开始"
3. **选择提供商**：
   - 默认显示 DeepSeek（选中状态）
   - 点击"下一步"
4. **输入 API Key**：
   - 输入 `[待填写: DeepSeek API Key]`
   - 点击"验证"按钮
   - 验证过程应 < 5 秒
   - 看到绿色 ✓ `"验证成功"`
5. **完成**：
   - 点击"完成设置"
   - 页面自动跳转到 `/chat`
6. 发送测试消息 → 验证可正常对话

**边界 — 跳过 API 配置：**
- 在 API Key 页面点击 `"稍后配置"` 或 `"跳过"`
- 引导完成，进入 `/chat`
- 发送消息时弹出提示 `"请先配置 API Key"`，提供跳转链接

---

### TC-FE-007 [P1] 引导流程 — 展开"更多提供商"→ 选可选提供商 / 自定义

| 属性 | 内容 |
|------|------|
| **Given** | 在引导的选择提供商页面 |
| **When** | 点击"更多提供商"展开 → 选择 **OpenRouter**（多模型聚合，可选） |
| **Then** | OpenRouter 被选中；继续到 API Key 输入页；可正常验证和完成引导 |

**自定义提供商路径：**
1. 展开"更多提供商"
2. 选择 `"自定义"`
3. 页面显示三个输入框：Base URL / Model Name / API Key
4. Base URL 预填 `https://api.openai.com/v1`（或类似默认值）
5. 填入自定义值 → 点击验证 → 完成引导

---

### TC-FE-008 [P1] 设置页 — 字体大小切换

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面 |
| **When** | 切换字体大小选项（小 / 中 / 大） |
| **Then** | `/chat` 页面文本即时变化；重启 Kabuqina 后保持 |

**手工执行步骤：**
1. 导航到 `/settings`
2. 找到"字体大小"选项（可能在"外观"或"通用"标签下）
3. 从"中"切换到"大"
4. 切换回 `/chat` → 观察消息气泡中的文字是否变大
5. 关闭 Kabuqina，重新启动
6. 回到 `/chat` → 字体仍为"大"
7. 切回 `/settings` → 字体大小显示为"大"

---

### TC-FE-009 [P1] 设置页 — 语言切换（中 / 英）

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面，当前语言为中文 |
| **When** | 切换语言为 English |
| **Then** | 所有页面标签即时变为英文；重启后保持；无未翻译的硬编码中文 |

**手工执行步骤：**
1. `/settings` → 找到"语言"下拉框
2. 从"简体中文"切换为"English"
3. 验证：
   - 设置页所有标签变为英文 ✓
   - 切换回 `/chat` → 输入框 placeholder、按钮 tooltip 变为英文 ✓
   - 侧边栏标签变为英文 ✓
4. 重启 Kabuqina → 验证语言仍为英文
5. 检查无硬编码中文（查看按钮、提示文案是否全部翻译）

---

### TC-FE-010 [P2] 设置页 — 深色模式

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面 |
| **When** | 切换深色模式（或选择"跟随系统"） |
| **Then** | 所有页面背景变为深色；文字颜色反转为浅色；对比度可读 |

**要点：**
- 深色模式下消息气泡边框/背景色应与主题协调
- 代码块、附件预览等子组件也应跟随主题
- "跟随系统"选项：修改 Windows 主题后 Kabuqina 自动切换（可能需要重启生效）

---

## 三、平台配置（Telegram / 微信 / QQ / 飞书）

### TC-FE-011 [P1] Telegram 配置块 — 保存 Token → 状态正确

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面，Telegram 区块可见 |
| **When** | 输入有效的 Bot Token → 点击保存 |
| **Then** | 显示 `"已配置 ✓"`；Token 被安全存储；重启后仍显示已配置 |

**手工执行步骤：**
1. `/settings` → 找到"Telegram"配置区块
2. 输入 `[待填写: Telegram Bot Token]`
3. 点击"保存"或"验证"
4. 验证：
   - 出现绿色 ✓ 和 `"配置成功"` 或 `"已配置"`
   - 区块显示 Bot 名称（如 `@TestBot`）
5. 重启 Kabuqina → 回到 `/settings` → Telegram 区块仍显示"已配置"

**边界 — Token 无效：**
- 输入错误的 Token（如 `"abc123"`）
- 点击验证 → 显示红色 ✗ `"验证失败：无效的 Bot Token"`
- 不应保存无效 Token

---

### TC-FE-012 [P1] 飞书 QR 扫码流程

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面，飞书区块可见 |
| **When** | 点击"扫码绑定"→ 展示 QR 码 → 使用飞书扫描 |
| **Then** | 扫码成功后显示"已绑定"；凭证写入 `.env` |

**手工执行步骤：**
1. `/settings` → 找到"飞书"配置区块
2. 确认 App ID 和 App Secret 已填写（或在此页面一并填写）
3. 点击"扫码绑定"按钮
4. 验证：弹出 QR 码图片（含飞书 logo）
5. 使用飞书手机 App 扫描二维码
6. 确认绑定
7. Kabuqina 中 QR 码弹窗关闭，飞书区块显示 `"已绑定 ✓"`

**异常 — 扫码超时：**
- 打开 QR 码后不扫描
- 等待 5 分钟 → QR 码区域显示 `"二维码已过期，点击刷新"`
- 点击刷新 → 新 QR 码生成

**异常 — 重复扫码换绑：**
- 已绑定状态下再次点击"扫码绑定"
- 扫描新账号 → 提示 `"该飞书应用已绑定账号 XXX，是否换绑？"`
- 确认后 → 旧账号解绑，新账号绑定

---

### TC-FE-013 [P1] 微信 Route C 扫码流程

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面，微信区块可见 |
| **When** | 点击"扫码绑定"→ 展示 QR 码 → 使用微信扫描 |
| **Then** | 扫码成功后显示"已绑定"；微信凭证写入 `.env` |

**手工执行步骤：** 同 TC-FE-012（飞书流程），平台替换为微信

**异常场景：** 同 TC-FE-012（超时、重复扫码、换绑）

---

### TC-FE-014 [P1] QQ QR 扫码流程

| 属性 | 内容 |
|------|------|
| **Given** | 在 `/settings` 页面，QQ 区块可见 |
| **When** | 点击"扫码绑定"→ 展示 QR 码 → 使用 QQ 手机版扫描 |
| **Then** | 扫码成功后显示"已绑定"；QQ 凭证写入 `.env` |

**手工执行步骤：** 同 TC-FE-012，平台替换为 QQ

**注意**：QQ 扫码可能需要手机 QQ 的特定版本支持；若 QR 码无法识别，记录 QQ 版本号作为测试环境信息

---

### TC-FE-015 [P2] 设置页 — 消息网关启动/停止 + 状态指示器

| 属性 | 内容 |
|------|------|
| **Given** | 至少一个平台（如 Telegram）已配置 |
| **When** | 点击"启动网关" / "停止网关" |
| **Then** | 状态指示器正确反映当前状态 |

**状态验证清单：**

| 操作 | 预期状态指示器 | 预期颜色 |
|------|---------------|---------|
| 点击"启动网关" | `"启动中..."` → `"运行中"` | 黄色 → 绿色 |
| 点击"停止网关" | `"未运行"` | 灰色 |
| 网关 crash | `"未运行"` → 自动 `"启动中..."` → `"运行中"` | 灰色 → 黄色 → 绿色 |
| 未配置任何平台 | `"请先配置消息平台"` | 灰色（不可用状态） |

---

## 附录：前端元素参考（供自动化用）

| 元素 | 预期选择器（供参考） | 所在页面 |
|------|---------------------|---------|
| 消息输入框 | `input[data-testid="chat-input"]` 或 `textarea[placeholder*="消息"]` | `/chat` |
| 发送按钮 | `button[data-testid="send-button"]` | `/chat` |
| 附件按钮 | `button[data-testid="attachment-button"]` 或回形针图标 | `/chat` |
| 停止生成按钮 | `button[data-testid="stop-button"]` 或 ⬛ 图标 | `/chat` |
| 侧边栏会话列表 | `[data-testid="session-list"]` | `/chat` |
| 新建会话按钮 | `button[data-testid="new-session"]` 或 `"+"` | `/chat` |
| 设置页 Telegram Token 输入 | `input[name="telegram-token"]` | `/settings` |
| 启动网关按钮 | `button[data-testid="start-gateway"]` | `/settings` |
| 停止网关按钮 | `button[data-testid="stop-gateway"]` | `/settings` |
| 网关状态指示器 | `[data-testid="gateway-status"]` | `/settings` |

> **说明**：以上选择器为建议命名。实际开发中请以工程师 AI 提供的 `data-testid` 为准。

---

## 附录：自动化骨架（Playwright）

```typescript
// tests/frontend/chat.spec.ts
import { test, expect } from '@playwright/test';

test.describe('/chat 页面', () => {
  test('发送消息并收到回复', async ({ page }) => {
    // TC-FE-001
    await page.goto('tauri://localhost/chat');
    await page.fill('[data-testid="chat-input"]', '你好，请介绍一下自己');
    await page.click('[data-testid="send-button"]');
    await expect(page.locator('[data-testid="user-message"]').last()).toContainText('你好');
    await expect(page.locator('[data-testid="ai-message"]').last()).toBeVisible({ timeout: 10000 });
  });

  test('空消息不应发送', async ({ page }) => {
    await page.goto('tauri://localhost/chat');
    await page.press('[data-testid="chat-input"]', 'Enter');
    await expect(page.locator('[data-testid="user-message"]')).toHaveCount(0);
  });

  test('附件大小超过 12MB 被拒绝', async ({ page }) => {
    // TC-FE-002 boundary
    await page.goto('tauri://localhost/chat');
    // 选择大文件...
    await expect(page.locator('[data-testid="file-error"]')).toContainText('12MB');
  });

  test('停止生成按钮生效', async ({ page }) => {
    // TC-FE-003
    await page.fill('[data-testid="chat-input"]', '请详细解释量子计算，至少500字');
    await page.click('[data-testid="send-button"]');
    await page.waitForTimeout(500); // 等待开始生成
    await page.click('[data-testid="stop-button"]');
    await expect(page.locator('[data-testid="stop-button"]')).not.toBeVisible();
  });

  test('多轮对话上下文保持', async ({ page }) => {
    // TC-FE-004
    await page.fill('[data-testid="chat-input"]', '我叫张三，请记住');
    await page.click('[data-testid="send-button"]');
    await page.waitForTimeout(3000);
    await page.fill('[data-testid="chat-input"]', '1+1等于几');
    await page.click('[data-testid="send-button"]');
    await page.waitForTimeout(3000);
    await page.fill('[data-testid="chat-input"]', '我刚才告诉你我叫什么？');
    await page.click('[data-testid="send-button"]');
    const lastReply = page.locator('[data-testid="ai-message"]').last();
    await expect(lastReply).toContainText('张三', { timeout: 10000 });
  });
});

test.describe('引导流程', () => {
  test('首次启动进入 onboarding', async ({ page }) => {
    // TC-FE-006
    await page.goto('tauri://localhost');
    await expect(page).toHaveURL(/onboarding/);
  });

  test('设置页语言切换', async ({ page }) => {
    // TC-FE-009
    await page.goto('tauri://localhost/settings');
    await page.selectOption('[data-testid="language-select"]', 'en');
    await expect(page.locator('text=Settings')).toBeVisible();
  });
});
```

## 执行记录 (2026-05-01)

| 用例 | 结果 | 备注 |
|------|------|------|
| TC-FE-001 | ✗ SKIP | 需在前端手动操作 |
| TC-FE-002 | ✗ SKIP | 需在前端手动操作 |
| TC-FE-003 | ✗ SKIP | 需在前端手动操作 |
| TC-FE-004 | ✓ PASS | 通过 API 验证：3 轮对话后 AI 仍记住 "张三" |
| TC-FE-005 | ✗ SKIP | 需在前端手动操作 |
| TC-FE-006 | ✗ SKIP | 需在前端手动操作 |
| TC-FE-007~015 | ✗ SKIP | 需在前端手动操作 |
