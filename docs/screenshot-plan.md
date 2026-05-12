
## 一、范围定义（写死边界）

In scope（桌面端）：

- 全局快捷键触发截图
- 区域 / 全屏 / 窗口截图
- 透明 overlay 选区
- 简单标注编辑器（P2）
- 截图 → 喂给 Agent 视觉链路 → 在 `/chat` 里看到 Agent 的分析

Out of scope（明确不做）：

- Gateway 渠道侧的截图按钮 / 上传 UI（由渠道自己决定，比如微信本来就有截图）
- Gateway 把桌面截图主动推给某个群
- 跨进程共享截图缓存

结论： 截图功能只活在 Tauri Rust 主进程 + web shell（React）+ Hermes web child 这条链路上，完全不碰 gateway child。`strip_shims.py` 的隔离不需要动。

## 二、架构落位

[全局快捷键: Ctrl+Alt+A]

↓ (Rust: tauri-plugin-global-shortcut)

[Overlay Window 创建] ← 新增独立 Tauri 窗口 "capture-overlay"

↓ (前端: React + 透明全屏)

[用户拖选区域]

↓ invoke('capture_region', {x,y,w,h})

[Rust: xcap 抓屏 + 裁剪]

↓

[落盘到 %USERPROFILE%\Documents\KabuqinaWork\captures\<uuid>.png]

↓ 返回 path 给前端

[前端: 预览 + (P2) Konva 标注]

↓ 用户点 "发送给 Agent"

[现有 /chat 走通的接口: 把 file path 作为 attachment]

↓

[Hermes web_server → vision_analyze_tool]

↓

[Agent 回复显示在 /chat]

关键设计点：

| 组件          | 归属                                    | 备注                                           |
| ----------- | ------------------------------------- | -------------------------------------------- |
| 快捷键注册       | Rust                                  | `tauri-plugin-global-shortcut`，新依赖           |
| 屏幕抓取        | Rust                                  | `xcap` crate，新依赖                             |
| Overlay 窗口  | Tauri 多窗口                             | `tauri.conf.json` 加一个 window，运行时按需 show/hide |
| 区域选择 UI     | web/ React                            | 单独路由 `/capture-overlay`，纯前端拖框                |
| 截图落盘路径      | `%USERPROFILE%\Documents\KabuqinaWork\captures\` | 已在 workspace 内，`path_policy.py` 无需额外开白       |
| 喂给 Agent    | 复用 `/chat` 现有上传链路                     | 不新发明协议，把 path 当作普通文件附件                       |
| OCR（可选 P1d） | Rust 调 WinRT `Windows.Media.Ocr`      | Win10+ 自带，零体积                                |
| 编辑器（P2）     | web/ + Konva.js                       | 只做矩形/箭头/文本/马赛克                               |

## 三、新增文件清单（仅规划）

tauri/

src/

capture.rs ← xcap 封装 + Tauri commands

overlay.rs ← overlay 窗口生命周期

Cargo.toml ← + xcap, + tauri-plugin-global-shortcut

capabilities/desktop.json ← 授权 capture_* 命令

web/

src/

capture/

OverlayWindow.tsx ← 区域选择

CapturePreview.tsx ← 预览 + 发送

(P2) Editor.tsx ← Konva 标注

routes.tsx ← + /capture-overlay

python/

src/path_policy.py ← 无需改动（captures/ 已在 workspace 内）

src/tool_policy.py ← keep-list 不用动（vision tool 已在）

docs/

agent-screenshot-design.md ← 现有文档

capture-implementation-plan.md ← 本方案落地版（建议你让我写一份）

## 四、对现有架构的最小侵入清单

按"动得越少越好"排：

1. `Cargo.toml` — 加两个依赖：`xcap`、`tauri-plugin-global-shortcut`
2. `tauri.conf.json` — 加一个 window 定义（默认隐藏的 overlay）
3. `capabilities/` — 给前端授权新增的 commands
4. `path_policy.py` — 无需改动（`%USERPROFILE%\Documents\KabuqinaWork\captures\` 已在 workspace 白名单内）
5. DPI 配置 — `tauri/build.rs` 或 manifest 里声明 `PerMonitorV2`（当前应该没显式设）
6. `/chat` 上传链路 — 零侵入（复用现有 file attachment 协议）

整个 Phase 1 不需要碰：`gateway_supervisor.rs`、`strip_shims.py`、`secret_store.py`、任何 platform adapter。

## 五、决策点

Q1. 截图触发入口

- 全局快捷键 + 托盘菜单 + 聊天框里一个相机图标按钮

Q2. 截图后默认行为

- B) 落到 `/chat` 输入框作为附件，等用户自己加文字描述再发

Q3. OCR 时机

- Phase 1 就加 WinRT OCR，把 OCR 文本和图片一起发给 Agent（提高文本类截图的准确率，比如代码、报错信息）


