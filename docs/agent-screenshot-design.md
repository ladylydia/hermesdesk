# **Tauri Windows Agent 截图系统设计建议**

```
# Tauri Windows Agent 截图系统设计建议

## 一、核心判断

对于 Agent 产品而言：

真正重要的不是“截图工具”。

而是：

Screen
↓
Capture
↓
OCR
↓
UI Analysis
↓
Agent Memory
↓
Action
```

截图功能本质上应该被设计成：

# **Visual Context Pipeline（视觉上下文管线）**

而不是传统截图软件。

---

# **二、技术路线建议**

当前技术栈：

* Tauri
* Windows
* Rust
* WebView Frontend
  推荐结构：

```
Windows API (Rust)
↓
Tauri Command
↓
WebView UI
↓
Canvas Editor
↓
AI Analysis
```

原则：

* Rust 负责系统层
* 前端负责 UI 层
* AI 独立成分析层

---

# **三、截图复杂度评估**

| **功能**         | **难度** | **开发周期** |
| -------------- | ------ | -------- |
| 基础截图           | ★      | 1~3天     |
| 区域截图           | ★★     | 3~5天     |
| 基础编辑           | ★★     | 1周       |
| 类 Snipaste 编辑器 | ★★★★★  | 1~3个月    |
| AI视觉Agent系统    | ★★★★★★ | 长期演化     |

---

# **四、推荐开发阶段**

---

## **Phase 1（推荐立即实现）**

目标：

建立最小视觉输入闭环。

功能：

* 全局快捷键

* 区域截图

* OCR

* 发给 Agent 分析
  不要做：

* 复杂编辑器

* 图层系统

* 高级绘图

---

## **Phase 2**

增加：

* 箭头

* 矩形

* 文本

* 马赛克
  推荐：

* Konva.js
  避免：

* 自己实现 Canvas 编辑器

---

## **Phase 3**

增加：

* Accessibility
* UI Detection
* 自动点击
* Overlay Hover
* Desktop Memory

---

# **五、截图推荐技术方案**

## **推荐方案：xcap**

Rust crate：

```
xcap = "0.x"
```

示例：

```
let monitors = Monitor::all()?;
let image = monitors[0].capture_image()?;
```

优点：

* Windows 支持稳定

* 多显示器支持

* DPI 处理较好

* 性能足够

* 易于集成 Tauri
  适合：

* Agent 产品

* OCR

* Desktop Automation
  不建议一开始直接使用：

* DXGI

* DirectX Capture
  因为复杂度过高。

---

# **六、核心重点：Overlay System**

截图体验核心不是截图 API。

而是：

# **Overlay（覆盖层）**

推荐结构：

```
Global Hotkey
↓
Transparent Overlay
↓
User Selection
↓
Rust Capture
↓
Canvas Edit
↓
Agent Analysis
```

---

# **七、Tauri Overlay 配置建议**

窗口建议：

```
transparent: true
decorations: false
always_on_top: true
fullscreen: true
```

后期建议支持：

* 鼠标穿透
* Hover UI
* 动态高亮

---

# **八、最重要的坑：DPI 缩放**

Windows 下必须处理：

* 125%
* 150%
* 175%
  否则会出现：

```
鼠标坐标 != 截图坐标
```

程序启动建议：

```
SetProcessDpiAwarenessContext
```

否则后续：

* 框选错位
* 点击偏移
* Overlay 错位
  都会出现。

---

# **九、编辑器建议**

推荐：

# **Konva.js**

原因：

* 交互性能更稳定

* 更适合 Overlay

* 更适合截图标注
  推荐只实现：

* 矩形

* 箭头

* 文本

* 马赛克
  不要一开始实现：

* 图层系统

* 贝塞尔曲线

* 高级 transform

* snapping
  否则会逐渐演变成：

```
“半个 Figma”
```

---

# **十、真正重要的能力**

截图工具只是入口。

真正重要的是：

# **Agent 对屏幕的理解能力**

---

## **OCR**

推荐：

* PaddleOCR
* Windows OCR API

---

## **UI Grounding**

目标：

```
AI知道：
哪个按钮能点
哪个输入框能输入
```

这是：

# **GUI Agent 核心能力**

---

## **Accessibility Tree**

重要性高于 OCR。

因为：

OCR 只能“看见”。

Accessibility 能“理解”。

例如：

```
<Button role="submit">
```

Agent 可以直接操作。

---

# **十一、长期演化方向**

Agent Desktop 产品通常会经历：

---

## **第一阶段**

```
AI Chat
```

---

## **第二阶段**

```
AI + Screenshot
```

---

## **第三阶段**

```
AI + Desktop Understanding
```

---

## **第四阶段**

```
AI + Computer Control
```

---

## **第五阶段**

```
AI Runtime OS
```

---

# **十二、最终建议**

优先级：

```
AI理解链路
>
截图体验
>
编辑器复杂度
```

用户真正需要的不是：

```
“一个强大的截图工具”
```

而是：

```
“AI能够理解我的屏幕”
```

这是 Agent 产品的核心差异化。
