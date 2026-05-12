# CHANGES: 2026-04-24 — Chat 前端组件拆分、UI 调优与模型展示

## 概述
本次修改对 `web/src/chat/` 下的壳内聊天页面进行了组件拆分、UI 精致度调优，并尝试增加助手消息底部的模型名称展示。组件拆分与 UI 调优已完成并通过构建验证；**模型名称展示功能测试未通过**，原因待排查。

---

## 1. 组件拆分（已完成 ✅）

### 目标
将 `ChatPage.tsx`（原 ~444 行单体组件）拆分为职责独立的子组件，降低后续迭代的心智负担。

### 新建文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `web/src/chat/ChatSidebar.tsx` | ~75 | 侧边栏：会话列表、新建会话、删除、激活态高亮 |
| `web/src/chat/ChatMessageList.tsx` | ~85 | 消息滚动容器、空状态、打字指示器、自动滚动、错误提示 |
| `web/src/chat/ChatMessage.tsx` | ~35 | 单条消息气泡：用户/助手样式区分、Markdown 渲染 |
| `web/src/chat/ChatInput.tsx` | ~60 | 输入区：受控 textarea、Enter/Shift+Enter 快捷键、发送按钮 |

### 修改文件

- **`web/src/chat/ChatPage.tsx`**：从 ~444 行精简至 ~260 行。保留状态管理（sessions、messages、input、sending 等）和业务逻辑（loadSessions、loadThread、onSend、onNewChat、onDelete 等），JSX 部分替换为子组件组合。
- **`web/src/chat/chat-api.ts`**：新增导出 `UiMsg` 类型（原定义在 `ChatPage.tsx` 内）。

### 设计决策
- Header（返回链接 + 标题 + LanguageToggle）逻辑较轻，v1 暂不独立组件，直接内联在 `ChatPage.tsx` 中。
- 所有状态仍保留在 `ChatPage`，通过 props 向下传递；未引入 Context 或全局状态库，保持轻量。

---

## 2. UI 调优（已完成 ✅）

### 消息气泡
- 助手消息增加 `shadow-sm`，边框改为 `border-zinc-200/60`，整体更柔和。
- 用户消息保持 `bg-zinc-900 text-white`，圆角统一为 `rounded-2xl`。
- 最大宽度保持 `min(100%, 42rem)`。

### 代码块（ChatMarkdown.tsx）
- 从简单的灰色条升级为带标题栏的卡片：
  - 外层容器：`rounded-xl` + `border border-zinc-700/50` + `shadow-sm`
  - 顶部标题栏：显示语言标识（如 `python`、`bash`），`11px` 等宽字体
  - 内容区：`bg-zinc-900` + `p-4` + `overflow-x-auto`
- 需要导入 `React` 以支持 `React.Children` / `React.isValidElement` 读取 code 子元素。

### 侧边栏（ChatSidebar.tsx）
- 激活态增加左侧 `3px` 指示条（`border-l-[3px] border-zinc-900 dark:border-zinc-100`）。
- 会话标题增加 `title` 属性，hover 时浏览器原生 tooltip 展示完整标题。
- 删除按钮 hover 色增加暗色模式兼容（`dark:hover:text-red-400`）。

### 输入区（ChatInput.tsx）
- 增加白色背景 + 顶部细阴影 `shadow-[0_-1px_4px_rgba(0,0,0,0.04)]`，与消息区形成层级分离。
- 底部增加提示文案 `Enter 发送，Shift+Enter 换行`（对应新增 i18n 键 `chat.hint`）。

### 空状态（ChatMessageList.tsx）
- 从纯文本提示改为居中卡片布局：
  - 大标题：`开启新对话`（i18n: `chat.emptyTitle`）
  - 副标题：`你可以问我任何问题，我会尽力帮助你。`（i18n: `chat.emptySubtitle`）
  - 3 个快捷提示 pill 按钮（i18n: `chat.prompt1/2/3`），点击后自动填入输入框。

### 打字指示器（ChatMessageList.tsx）
- 从静态 `…` 文本替换为 3 个依次跳动的圆点动画（CSS `animate-bounce` + 不同 `animationDelay`）。

---

## 3. i18n 补充（已完成 ✅）

`web/src/locales/strings.ts` 新增以下键（含中英文）：

- `chat.hint` — 输入框底部提示
- `chat.emptyTitle` — 空状态大标题
- `chat.emptySubtitle` — 空状态副标题
- `chat.prompt1` — 快捷提示 1（帮我写一段代码 / Write some code for me）
- `chat.prompt2` — 快捷提示 2（解释一下这个概念 / Explain this concept）
- `chat.prompt3` — 快捷提示 3（总结一下文档内容 / Summarize the document）

---

## 4. 模型名称展示（已修复 ✅）

### 设计目标
在每条助手消息气泡底部展示当前调用的 AI 模型名称，格式为 `Hermes(model-name)`。

### 已实施的改动

**后端**（`hermes/hermes_cli/web_server.py`）
- 在 `desk_chat_proto` 的成功响应 JSON 中新增字段：
  ```python
  "model": getattr(agent, "model", "") or "",
  ```

**前端 API 层**（`web/src/chat/chat-api.ts`）
- `UiMsg` 增加 `model?: string`
- `parseChatSend` 返回值增加 `model: string`，从后端 JSON 解析 `model` 字段

**前端页面**（`web/src/chat/ChatPage.tsx`）
- `onSend` 中：pending 占位消息的 `model` 初始化为空字符串；收到响应后将 `parsed.model` 写入最终消息对象。

**前端消息组件**（`web/src/chat/ChatMessage.tsx`）
- 增加 `model?: string` prop
- 助手消息底部增加展示逻辑：
  ```tsx
  {!isUser && model && (
    <div className="mt-2 pt-1.5 border-t border-zinc-100 dark:border-zinc-800">
      <span className="text-[11px] text-zinc-400 dark:text-zinc-500 font-mono">
        Hermes({model})
      </span>
    </div>
  )}
  ```

**前端列表组件**（`web/src/chat/ChatMessageList.tsx`）
- `<ChatMessage />` 调用时透传 `model={m.model}`

### 测试结果
**~~未通过~~ → 已验证通过 ✅**。修复后助手消息气泡底部可正常显示 `Hermes(...)` 模型标签。

### 根因
`agent.model` 为空字符串，导致后端返回 `"model": ""`，前端 `model && ...` 条件不渲染。  
空字符串的直接原因是：**Python 子进程加载的是 `python/dist/runtime/` 下的 bundle 代码，而非源代码 `hermes/`**。修改了 `hermes/hermes_cli/web_server.py` 后未重新同步到 bundle，子进程仍在运行旧代码。同步后问题解决。

### 修复内容

**后端**（`hermes/hermes_cli/web_server.py`）
- 在 `desk_chat_proto` 返回前增加诊断日志：
  ```python
  _log.info("desk chat model: agent=%r result=%r effective=%r", _agent_model, _result_model, _effective_model)
  ```
- 改进 `model` 字段取值逻辑：优先取 `agent.model`，若为空则 fallback 到 `payload["result"]["model"]`，确保返回值尽可能非空。

**前端**（`web/src/chat/ChatMessage.tsx`）
- 移除 `model &&` 条件守卫，改为始终渲染模型标签；当 `model` 为空时展示 `Hermes(unknown)`，避免信息缺失时 UI 完全消失导致用户无法判断问题所在。

### 验证步骤
1. **同步后端代码到 bundle**：
   ```powershell
   Copy-Item D:\project\Kabuqina\hermes\hermes_cli\web_server.py `
     D:\project\Kabuqina\python\dist\runtime\hermes\hermes_cli\web_server.py -Force
   ```
   （或运行完整 `\.python\build_bundle.ps1`）
2. 完全退出并重启 Kabuqina（`Ctrl+C` 停掉 `cargo run`，再重新 `cargo run`）。
3. 发送一条消息，查看日志确认出现 `desk chat model` 行，且助手消息气泡底部显示 `Hermes(...)` 模型标签。
4. 若日志中 model 仍为空，检查 `~/.hermes/config.yaml`（或 Windows 对应路径 `C:\Users\<用户名>\.hermes\config.yaml`）中 `model.default` 或 `model.model` 是否已配置，配置后重启应用即可显示实际模型名。

> **实际验证结果（2026-04-25）**：通过 `Copy-Item` 直接覆盖 bundle 中的 `web_server.py`，重启应用后模型标签正常显示。

---

## 5. 构建验证

```bash
cd web && npm run build
# tsc -b && vite build
# ✓ built in 4.07s
```
TypeScript 编译通过，无类型错误。

---

## 相关文件清单

### 新建
- `web/src/chat/ChatSidebar.tsx`
- `web/src/chat/ChatMessageList.tsx`
- `web/src/chat/ChatMessage.tsx`
- `web/src/chat/ChatInput.tsx`
- `CHANGES_2026-04-24-chat-refactor.md`（本文件）

### 修改
- `web/src/chat/ChatPage.tsx`
- `web/src/chat/ChatMarkdown.tsx`
- `web/src/chat/chat-api.ts`
- `web/src/locales/strings.ts`
- `hermes/hermes_cli/web_server.py`
