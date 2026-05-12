# 工具进度事件 + 步骤列表 — 实现方案

## 现状问题

| 问题 | 描述 | 优先级 |
|------|------|--------|
| 后端一次性返回 | `desk_chat_proto` 跑完 agent 全循环才出结果 | 高 |
| 工具调用无回显 | 用户看不到 agent 在干什么，只能看到 "…" | 高 |
| 假流式治标不治本 | Part 1 逐字展开只是动画，不改变等待体验 | 中 |

## 已实现的部分

| 模块 | 文件 | 状态 |
|------|------|------|
| `_progress` 基本面 | `run_agent.py` — init + thinking/tool/status 更新 | ✅ |
| 预览端点 | `web_server.py` — `GET /api/desk/chat-preview/{sid}` | ✅ |
| Rust 代理 | `chat.rs` — `cmd_chat_preview` | ✅ |
| 前端轮询 | `useSendMessage.ts` — 600ms 间隔 poll | ✅ |
| 进度面板骨架 | `AgentProgress.tsx` — 单行状态展示 | ✅ |

## 增量改动

### 1. `hermes_core/run_agent.py` — 事件记录

**思路：** 在 agent 循环的关键节点追加事件到 `self._progress_events`，前端通过 `?since=N` 增量拉取。

**初始化**（line 10471 旁，已有 `_progress` 附近）：

```python
self._progress_events = []
```

**Thinking 事件**（line 10533，`api_call_count += 1` 后）：

```python
self._progress_events.append({
    "seq": len(self._progress_events),
    "ts": time.time(),
    "type": "thinking",
    "iteration": api_call_count,
})
```

**Tool start 事件**（line 9703，`tool_start_time = time.time()` 后）：

```python
self._progress_events.append({
    "seq": len(self._progress_events),
    "ts": time.time(),
    "type": "tool_start",
    "tool": function_name,
    "args": str(tool_call.function.arguments)[:200],
    "iteration": self._api_call_count,
})
```

**Tool done 事件**（line ~9896，`self._current_tool = None` 前，公共后处理区）：

```python
self._progress_events.append({
    "seq": len(self._progress_events),
    "ts": time.time(),
    "type": "tool_done",
    "tool": function_name,
    "preview": (
        function_result[:300] if len(function_result) > 300 else function_result
    ) if function_result else "",
    "duration_ms": round(tool_duration * 1000) if tool_duration else 0,
    "is_error": _is_error_result if "_is_error_result" in dir() else False,
})
```

**说明：**
- 所有 `elif` 分支（todo、session_search、quiet/visible mode）都经过 tool_start 和公共后处理，一行 events 捕获全部
- `seq` 从 0 开始自增，前端用 `since=lastSeq+1` 拉新事件
- 单线程执行，`list.append` + `len()` 在 GIL 下安全，无需锁

### 2. `hermes_core/hermes_cli/web_server.py` — 预览端点扩展

**当前：**

```python
@app.get("/api/desk/chat-preview/{session_id}")
async def desk_chat_preview(session_id: str):
```

**改为：**

```python
@app.get("/api/desk/chat-preview/{session_id}")
async def desk_chat_preview(session_id: str, since: int = 0):
    with _desk_active_lock:
        ag = _desk_active_agents.get(session_id)
    if ag is None:
        return JSONResponse({"running": False, "events": []})
    progress = getattr(ag, "_progress", {})
    events = getattr(ag, "_progress_events", [])
    new_events = events[since:]
    return JSONResponse({
        "running": progress.get("running", False),
        "status": progress.get("status", ""),
        "iteration": progress.get("iteration", 0),
        "max_iterations": progress.get("max_iterations", 0),
        "events": [
            {
                "seq": i,
                "ts": e["ts"],
                "type": e["type"],
                "tool": e.get("tool"),
                "args": e.get("args"),
                "preview": e.get("preview"),
                "duration_ms": e.get("duration_ms"),
                "is_error": e.get("is_error", False),
                "iteration": e.get("iteration"),
            }
            for i, e in enumerate(new_events)
        ],
    })
```

**说明：**
- `since` 是事件序号（从 0 开始），返回 `_progress_events[since:]`
- `running: False` 时前端停止轮询

### 3. `tauri/src/chat.rs` — 转发 `since` 参数

**当前：**

```rust
pub async fn cmd_chat_preview(app: AppHandle, session_id: String) -> Result<Value, String> {
    ...
    .get(format!("{base}/api/desk/chat-preview/{session_id}"))
```

**改为：**

```rust
pub async fn cmd_chat_preview(app: AppHandle, session_id: String, since: i32) -> Result<Value, String> {
    ...
    .get(format!("{base}/api/desk/chat-preview/{session_id}?since={since}"))
```

### 4. `chat-api.ts` — `cmdChatPreview` 加参数

**当前：**

```typescript
export function cmdChatPreview(sessionId: string) {
  return invoke("cmd_chat_preview", { sessionId });
}
```

**改为：**

```typescript
export function cmdChatPreview(sessionId: string, since = 0) {
  return invoke("cmd_chat_preview", { sessionId, since });
}
```

### 5. `useSendMessage.ts` — 累积式轮询，移除假流式

**改动清单：**

| 改动 | 内容 |
|------|------|
| 删 `streamRef` | 移除 Part 1 假流式的 `setInterval` 和 `advance` 逻辑 |
| 删 `progress` state | 不再用单独的 progress state |
| 加 `events` state | `useState<EventItem[]>([])` |
| 加 `lastSeq` ref | 记录上次拉取的最后一条 event seq |
| 修改 `pollProgress` | 携带 `since=lastSeq+1`，返回新事件追加到 `events` 尾部 |
| Turn 开始重置 | 发送消息时 `setEvents([])`, `lastSeqRef.current = 0` |
| 暴露 `events` | return 值加上 `events` |

**伪代码：**

```typescript
// 删掉: streamRef, typewriter 相关代码

const [events, setEvents] = useState<EventItem[]>([]);
const lastSeqRef = useRef(0);

// onSend 里清空：
lastSeqRef.current = 0;
setEvents([]);

// pollProgress 改为：
const pollProgress = async () => {
  try {
    const p = await cmdChatPreview(pollSid, lastSeqRef.current);
    if (p.events?.length) {
      setEvents(prev => [...prev, ...p.events]);
      lastSeqRef.current = p.events[p.events.length - 1].seq + 1;
    }
    if (!p.running) stopPolling();
  } catch { /* ignore */ }
};
```

**消息占位点保留：** `"pending-assistant"` placeholder 消息保留。进度面板存在时显示它，`running: False` 后隐藏。

### 6. `AgentProgress.tsx` — 步骤列表 + 底部状态行

```
┌───────────────────────────────────────────────────┐
│ 🔄 思考中…                               2/90    │
│ ✓  web_search(fix_type: "auto") ─── 2.3s ✅       │
│ 🔄 思考中…                               3/90    │
│ ✓  web_search(text: "天工筑影") ── 1.8s ✅       │
│ ────────────────────────────────────────── │
│ 🧠 thinking · 🔧 2 tools · 💬 wait       │
└───────────────────────────────────────────────────┘
```

**状态映射：**

| `type` | 图标 | 行样式 |
|--------|------|--------|
| `thinking` | `LoaderCircle` 旋转 | `text-sky-500` |
| `tool_start` | `Wrench` | `text-amber-500` |
| `tool_done` | `CheckCircle` | `text-emerald-500` |

**底部状态行：**
- 最新事件是 `thinking` → "🧠 思考中…"
- 最新事件是 `tool_start` → "🔧 执行中…"
- 最新事件是 `tool_done` → "💬 等待回复…"
- 右侧显示 `{iteration}/{max_iterations}`

**边缘情况：**
- 首次 poll 还没返回 → fallback 显示 `TypingIndicator`
- `events` 为空但 `sending` → 简单 spinner
- `running=false` → 隐藏面板

## 文件改动总表

| 文件 | 改动量 | 功能 |
|------|--------|------|
| `hermes_core/run_agent.py` | +~15 行 | 3 处加事件 + 初始化 |
| `hermes_core/hermes_cli/web_server.py` | ~20 行重写 | `since` 参数 + 事件返回格式 |
| `tauri/src/chat.rs` | ~5 行 | 加 `since: i32` 参数 |
| `web/src/chat/chat-api.ts` | ~3 行 | `cmdChatPreview` 加 `since` |
| `web/src/chat/hooks/useSendMessage.ts` | ~30 行 | 删假流式→改为累积事件轮询 |
| `web/src/chat/AgentProgress.tsx` | ~100 行重写 | 步骤列表 + 底部状态行 |
| `web/src/chat/ChatMessageList.tsx` | ~5 行 | 更新 props 传递 |
| `web/src/chat/ChatPage.tsx` | ~5 行 | 传递新 props |

## 执行顺序

```
1 → run_agent.py          (事件记录)
2 → web_server.py         (端点扩展)
3 → chat.rs               (since 参数)
4 → chat-api.ts           (TS 类型)
5 → useSendMessage.ts     (删假流式 + 累积轮询)
6 → AgentProgress.tsx     (步骤列表)
7 → ChatMessageList.tsx   (传递 props)
8 → ChatPage.tsx          (传递 props)
→ copy to runtime bundle
→ cargo tauri dev
```
