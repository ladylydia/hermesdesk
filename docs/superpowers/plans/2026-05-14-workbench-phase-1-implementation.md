# Kabuqina Workbench Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P0 workbench shell: three-column chat layout, collapsible left rail, collapsible right workspace panel, and focus mode.

**Architecture:** Keep chat behavior in existing hooks and add layout-only state through a small `useWorkbenchLayout` hook. Add a presentational `WorkspacePanel` for active goal/materials/outputs/actions. Evolve `ChatSidebar` into a collapsible left rail without changing session loading or deletion behavior.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, React Router, existing Tauri invoke bridges, localStorage for shell UI preferences.

---

## File Structure

- Create: `web/src/chat/hooks/useWorkbenchLayout.ts`
  - Owns `leftOpen`, `rightOpen`, `focusMode`, derived visible states, localStorage persistence, and narrow-window detection.
- Create: `web/src/chat/WorkspacePanel.tsx`
  - Renders Current Goal, Materials, Outputs, and Quick Actions empty states.
- Modify: `web/src/chat/ChatPage.tsx`
  - Composes left rail, center work stream, and right panel using the layout hook.
- Modify: `web/src/chat/ChatSidebar.tsx`
  - Adds `collapsed`, `onToggleCollapsed`, and Capability navigation.
- Modify: `web/src/chat/ChatMessageList.tsx`
  - Allows the empty state to fit the workbench center and keeps useful starting actions.
- Modify: `web/src/locales/strings.ts`
  - Adds labels for Workbench, Workspace, Focus, collapse/expand, and empty panel sections.
- Test: `web/src/chat/chatUx.test.mjs`
  - Adds source-level checks for workbench layout, Capability rail action, workspace panel sections, and focus state persistence keys.

## Scope Notes

- Do not touch `hermes_core/`.
- Do not change chat send/session behavior.
- Do not implement draggable panel widths in Phase 1.
- Keep Settings in the top title bar; Capability moves into the left rail.

---

### Task 1: Add Workbench Layout State

**Files:**
- Create: `web/src/chat/hooks/useWorkbenchLayout.ts`
- Test: `web/src/chat/chatUx.test.mjs`

- [ ] **Step 1: Write the failing test**

Append these checks near the existing `chatUx.test.mjs` source assertions:

```js
const workbenchLayoutSource = fs.readFileSync(
  new URL("./hooks/useWorkbenchLayout.ts", import.meta.url),
  "utf8",
);

assert.match(
  workbenchLayoutSource,
  /WORKBENCH_LAYOUT_KEY\s*=\s*"kabuqina\.workbench\.layout"/,
  "Workbench layout should persist under a Kabuqina-specific localStorage key.",
);

assert.match(
  workbenchLayoutSource,
  /toggleFocusMode/,
  "Workbench layout hook should expose a focus mode toggle.",
);

assert.match(
  workbenchLayoutSource,
  /isNarrow/,
  "Workbench layout hook should track narrow-window behavior.",
);
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: FAIL because `web/src/chat/hooks/useWorkbenchLayout.ts` does not exist.

- [ ] **Step 3: Implement the hook**

Create `web/src/chat/hooks/useWorkbenchLayout.ts`:

```typescript
import { useCallback, useEffect, useMemo, useState } from "react";

export const WORKBENCH_LAYOUT_KEY = "kabuqina.workbench.layout";

type StoredWorkbenchLayout = {
  leftOpen?: boolean;
  rightOpen?: boolean;
  focusMode?: boolean;
};

export type WorkbenchLayout = {
  leftOpen: boolean;
  rightOpen: boolean;
  focusMode: boolean;
  isNarrow: boolean;
  showLeftRail: boolean;
  showRightPanel: boolean;
  toggleLeft: () => void;
  toggleRight: () => void;
  toggleFocusMode: () => void;
};

function readStoredLayout(): StoredWorkbenchLayout {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(WORKBENCH_LAYOUT_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function writeStoredLayout(layout: StoredWorkbenchLayout): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WORKBENCH_LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    /* localStorage can be unavailable in restricted webviews */
  }
}

export function useWorkbenchLayout(): WorkbenchLayout {
  const stored = useMemo(readStoredLayout, []);
  const [leftOpen, setLeftOpen] = useState(stored.leftOpen ?? true);
  const [rightOpen, setRightOpen] = useState(stored.rightOpen ?? true);
  const [focusMode, setFocusMode] = useState(stored.focusMode ?? false);
  const [isNarrow, setIsNarrow] = useState(false);

  useEffect(() => {
    const update = () => setIsNarrow(window.innerWidth < 768);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    writeStoredLayout({ leftOpen, rightOpen, focusMode });
  }, [leftOpen, rightOpen, focusMode]);

  const toggleLeft = useCallback(() => {
    setFocusMode(false);
    setLeftOpen((value) => !value);
  }, []);

  const toggleRight = useCallback(() => {
    setFocusMode(false);
    setRightOpen((value) => !value);
  }, []);

  const toggleFocusMode = useCallback(() => {
    setFocusMode((value) => !value);
  }, []);

  return {
    leftOpen,
    rightOpen,
    focusMode,
    isNarrow,
    showLeftRail: !focusMode && (leftOpen || isNarrow),
    showRightPanel: !focusMode && rightOpen && !isNarrow,
    toggleLeft,
    toggleRight,
    toggleFocusMode,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: PASS.

- [ ] **Step 5: Commit**

Commit only this task's files:

```powershell
git add web/src/chat/hooks/useWorkbenchLayout.ts web/src/chat/chatUx.test.mjs
git commit -m "feat(web): add workbench layout state"
```

---

### Task 2: Add Workspace Panel

**Files:**
- Create: `web/src/chat/WorkspacePanel.tsx`
- Modify: `web/src/locales/strings.ts`
- Test: `web/src/chat/chatUx.test.mjs`

- [ ] **Step 1: Write the failing test**

Append:

```js
const workspacePanelSource = fs.readFileSync(
  new URL("./WorkspacePanel.tsx", import.meta.url),
  "utf8",
);

assert.match(
  workspacePanelSource,
  /workspace\.currentGoal/,
  "Workspace panel should render a Current Goal section.",
);

assert.match(
  workspacePanelSource,
  /workspace\.materials/,
  "Workspace panel should render a Materials section.",
);

assert.match(
  workspacePanelSource,
  /workspace\.outputs/,
  "Workspace panel should render an Outputs section.",
);

assert.match(
  workspacePanelSource,
  /workspace\.quickActions/,
  "Workspace panel should render a Quick Actions section.",
);
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: FAIL because `WorkspacePanel.tsx` does not exist.

- [ ] **Step 3: Add locale strings**

In both `zh` and `en` `chat` objects in `web/src/locales/strings.ts`, add these keys:

```typescript
workspaceTitle: "工作区",
workspaceCollapse: "收起工作区",
workspaceExpand: "展开工作区",
workspaceCurrentGoal: "当前目标",
workspaceGoalEmpty: "还没有固定目标。开始对话后，小娜会在这里整理当前工作。",
workspaceMaterials: "材料",
workspaceMaterialsEmpty: "添加文件、截图或路径后会显示在这里。",
workspaceOutputs: "产出",
workspaceOutputsEmpty: "提醒、草稿和导出结果会显示在这里。",
workspaceQuickActions: "快捷操作",
workspaceAddFile: "添加文件",
workspaceCapture: "截图",
workspaceOrganizeDesktop: "整理桌面",
```

For English:

```typescript
workspaceTitle: "Workspace",
workspaceCollapse: "Collapse workspace",
workspaceExpand: "Open workspace",
workspaceCurrentGoal: "Current goal",
workspaceGoalEmpty: "No pinned goal yet. Once work starts, Nana will summarize it here.",
workspaceMaterials: "Materials",
workspaceMaterialsEmpty: "Files, screenshots, and paths you add will appear here.",
workspaceOutputs: "Outputs",
workspaceOutputsEmpty: "Reminders, drafts, and exports will appear here.",
workspaceQuickActions: "Quick actions",
workspaceAddFile: "Add file",
workspaceCapture: "Capture screen",
workspaceOrganizeDesktop: "Organize desktop",
```

- [ ] **Step 4: Create `WorkspacePanel.tsx`**

```typescript
import { Camera, FilePlus2, FolderKanban, PanelRightClose } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

type WorkspacePanelProps = {
  className?: string;
  onCollapse: () => void;
  onOrganizeDesktop?: () => void;
};

function WorkspaceSection({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <section className="border-b border-zinc-200/80 pb-4 last:border-b-0 dark:border-zinc-800">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {title}
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
        {body}
      </p>
    </section>
  );
}

export function WorkspacePanel({
  className,
  onCollapse,
  onOrganizeDesktop,
}: WorkspacePanelProps) {
  const { t } = useI18n();

  return (
    <aside
      className={cn(
        "flex w-64 shrink-0 flex-col border-l border-zinc-200/90 bg-white/70 dark:border-zinc-700 dark:bg-zinc-950/40",
        className,
      )}
    >
      <div className="flex h-14 items-center justify-between border-b border-zinc-200/80 px-4 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {t("chat.workspaceTitle")}
        </h2>
        <button
          type="button"
          onClick={onCollapse}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          aria-label={t("chat.workspaceCollapse")}
          title={t("chat.workspaceCollapse")}
        >
          <PanelRightClose className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <WorkspaceSection title={t("chat.workspaceCurrentGoal")} body={t("chat.workspaceGoalEmpty")} />
        <WorkspaceSection title={t("chat.workspaceMaterials")} body={t("chat.workspaceMaterialsEmpty")} />
        <WorkspaceSection title={t("chat.workspaceOutputs")} body={t("chat.workspaceOutputsEmpty")} />

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            {t("chat.workspaceQuickActions")}
          </h3>
          <div className="mt-3 grid gap-2">
            <button type="button" className="hd-btn-ghost justify-start text-left">
              <FilePlus2 className="mr-2 inline h-4 w-4" aria-hidden />
              {t("chat.workspaceAddFile")}
            </button>
            <button type="button" className="hd-btn-ghost justify-start text-left">
              <Camera className="mr-2 inline h-4 w-4" aria-hidden />
              {t("chat.workspaceCapture")}
            </button>
            <button
              type="button"
              onClick={onOrganizeDesktop}
              className="hd-btn-ghost justify-start text-left"
            >
              <FolderKanban className="mr-2 inline h-4 w-4" aria-hidden />
              {t("chat.workspaceOrganizeDesktop")}
            </button>
          </div>
        </section>
      </div>
    </aside>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/src/chat/WorkspacePanel.tsx web/src/locales/strings.ts web/src/chat/chatUx.test.mjs
git commit -m "feat(web): add chat workspace panel"
```

---

### Task 3: Evolve Sidebar Into Collapsible Left Rail

**Files:**
- Modify: `web/src/chat/ChatSidebar.tsx`
- Modify: `web/src/chat/chatUx.test.mjs`

- [ ] **Step 1: Write the failing test**

Append:

```js
assert.match(
  sidebarSource,
  /collapsed\?: boolean/,
  "ChatSidebar should accept a collapsed prop.",
);

assert.match(
  sidebarSource,
  /onToggleCollapsed/,
  "ChatSidebar should expose a left-rail collapse action.",
);

assert.match(
  sidebarSource,
  /nav\("\/capabilities"\)/,
  "Capability should be a first-class left rail destination.",
);
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: FAIL because the sidebar has no collapsed prop and no Capability action.

- [ ] **Step 3: Update props and imports**

In `ChatSidebar.tsx`, import icons:

```typescript
import {
  AlarmClock,
  Boxes,
  Download,
  FileText,
  Image as ImageIcon,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
} from "lucide-react";
```

Update props:

```typescript
export interface ChatSidebarProps {
  sessions: SessionRow[];
  activeSessionId: string | null;
  loading?: boolean;
  collapsed?: boolean;
  onToggleCollapsed: () => void;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string, e: React.MouseEvent) => void;
}
```

- [ ] **Step 4: Implement collapsed layout**

At the top of `ChatSidebar`, destructure `collapsed = false`. Change `<aside>` class:

```typescript
<aside
  className={cn(
    "flex shrink-0 flex-col border-r border-zinc-200/90 bg-zinc-100/30 transition-[width] duration-200 ease-out dark:border-zinc-700 dark:bg-zinc-900/30",
    collapsed ? "w-14" : "w-56",
  )}
>
```

Add a collapse toggle in the top area:

```tsx
<div className="flex items-center gap-2 border-b border-zinc-200/80 p-3 dark:border-zinc-700/80">
  <button
    type="button"
    onClick={onToggleCollapsed}
    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-200/70 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
    aria-label={collapsed ? t("chat.leftRailExpand") : t("chat.leftRailCollapse")}
    title={collapsed ? t("chat.leftRailExpand") : t("chat.leftRailCollapse")}
  >
    {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
  </button>
  {!collapsed && (
    <button
      type="button"
      onClick={() => onNewChat()}
      className="inline-flex min-w-0 flex-1 items-center justify-start gap-2 rounded-lg bg-sky-600 px-3 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-sky-700 active:scale-[0.99] dark:bg-sky-500 dark:hover:bg-sky-600"
    >
      <span className="truncate">{t("chat.newChat")}</span>
      <Plus className="h-4 w-4 shrink-0 stroke-[2.75]" aria-hidden />
    </button>
  )}
</div>
```

When `collapsed` is true, hide group labels and session text, but keep icons clickable with `title={label}`. Add `aria-label={label}` to the session buttons.

- [ ] **Step 5: Add Capability destination**

In the footer area, add:

```tsx
<button
  type="button"
  onClick={() => nav("/capabilities")}
  className={cn(
    "group inline-flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm font-medium",
    "text-zinc-600 transition hover:bg-zinc-200/70 hover:text-zinc-900",
    "dark:text-zinc-400 dark:hover:bg-zinc-800/70 dark:hover:text-zinc-100",
    collapsed && "justify-center px-0",
  )}
  title={t("capabilities.title")}
  aria-label={t("capabilities.title")}
>
  <Boxes className="h-4 w-4 shrink-0" aria-hidden />
  {!collapsed && <span>{t("capabilities.title")}</span>}
</button>
```

- [ ] **Step 6: Add locale strings**

Add `chat.leftRailCollapse` and `chat.leftRailExpand` in both locales:

```typescript
leftRailCollapse: "收起侧栏",
leftRailExpand: "展开侧栏",
```

English:

```typescript
leftRailCollapse: "Collapse sidebar",
leftRailExpand: "Open sidebar",
```

- [ ] **Step 7: Run test**

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add web/src/chat/ChatSidebar.tsx web/src/locales/strings.ts web/src/chat/chatUx.test.mjs
git commit -m "feat(web): make chat sidebar a collapsible rail"
```

---

### Task 4: Wire Three-Column Workbench In ChatPage

**Files:**
- Modify: `web/src/chat/ChatPage.tsx`
- Modify: `web/src/chat/chatUx.test.mjs`

- [ ] **Step 1: Write the failing test**

Append:

```js
assert.match(
  chatPageSource,
  /useWorkbenchLayout/,
  "ChatPage should use the workbench layout hook.",
);

assert.match(
  chatPageSource,
  /WorkspacePanel/,
  "ChatPage should render the workspace panel.",
);

assert.match(
  chatPageSource,
  /toggleFocusMode/,
  "ChatPage should expose focus mode controls.",
);
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: FAIL because `ChatPage` has not been wired.

- [ ] **Step 3: Import the new pieces**

Add:

```typescript
import { Maximize2, PanelRightOpen } from "lucide-react";
import { WorkspacePanel } from "./WorkspacePanel";
import { useWorkbenchLayout } from "./hooks/useWorkbenchLayout";
```

- [ ] **Step 4: Instantiate layout state**

Inside `ChatPage`:

```typescript
const workbench = useWorkbenchLayout();
```

- [ ] **Step 5: Update the layout**

Replace the current `div className="flex min-h-0 flex-1"` body with:

```tsx
<div className="flex min-h-0 flex-1">
  {workbench.showLeftRail && (
    <ChatSidebar
      sessions={sessions}
      activeSessionId={activeSessionId}
      loading={listLoading}
      collapsed={!workbench.leftOpen || workbench.isNarrow}
      onToggleCollapsed={workbench.toggleLeft}
      onNewChat={onNewChat}
      onSelectSession={onPickSession}
      onDeleteSession={handleDelete}
    />
  )}

  <main className="flex min-w-0 flex-1 flex-col">
    <div className="flex h-11 shrink-0 items-center justify-between border-b border-zinc-200/80 bg-zinc-50/90 px-3 dark:border-zinc-800 dark:bg-[#0F172A]">
      <div className="min-w-0">
        <p className="truncate text-xs font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
          {t("chat.activeWork")}
        </p>
      </div>
      <div className="flex items-center gap-1">
        {!workbench.showRightPanel && (
          <button
            type="button"
            onClick={workbench.toggleRight}
            className="hd-btn-ghost inline-flex h-8 w-8 items-center justify-center px-0"
            aria-label={t("chat.workspaceExpand")}
            title={t("chat.workspaceExpand")}
          >
            <PanelRightOpen className="h-4 w-4" />
          </button>
        )}
        <button
          type="button"
          onClick={workbench.toggleFocusMode}
          className="hd-btn-ghost inline-flex h-8 w-8 items-center justify-center px-0"
          aria-label={workbench.focusMode ? t("chat.focusExit") : t("chat.focusEnter")}
          title={workbench.focusMode ? t("chat.focusExit") : t("chat.focusEnter")}
        >
          <Maximize2 className="h-4 w-4" />
        </button>
      </div>
    </div>

    <ChatMessageList
      messages={messages}
      sending={sending}
      sendErr={sendErr}
      progress={progress}
      onPickSuggestion={setInput}
      onOrganizeDesktop={handleOrganizeDesktop}
    />
    <ChatInput
      value={input}
      onChange={setInput}
      onSend={onSend}
      sending={sending}
      pendingAttachmentNames={pendingAttachments.map((a) => a.name)}
      onRemoveAttachment={onRemoveAttachment}
      onFilesPicked={onAddFiles}
      onStop={onStopAgent}
      powerUser={powerUser}
      onTogglePowerUser={togglePowerUser}
    />
  </main>

  {workbench.showRightPanel && (
    <WorkspacePanel
      onCollapse={workbench.toggleRight}
      onOrganizeDesktop={handleOrganizeDesktop}
    />
  )}
</div>
```

- [ ] **Step 6: Add locale strings**

Add to `chat` in both locales:

```typescript
activeWork: "当前工作",
focusEnter: "专注聊天",
focusExit: "退出专注",
```

English:

```typescript
activeWork: "Active work",
focusEnter: "Focus chat",
focusExit: "Exit focus",
```

- [ ] **Step 7: Run test**

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add web/src/chat/ChatPage.tsx web/src/locales/strings.ts web/src/chat/chatUx.test.mjs
git commit -m "feat(web): wire chat workbench layout"
```

---

### Task 5: Verify Build And Visual States

**Files:**
- No planned source edits unless verification reveals a defect.

- [ ] **Step 1: Run chat UX tests**

```powershell
cd web; npm run test:chat-ux; cd ..
```

Expected: PASS.

- [ ] **Step 2: Run lint**

```powershell
cd web; npm run lint; cd ..
```

Expected: zero lint errors.

- [ ] **Step 3: Run web build**

```powershell
cd web; npm run build; cd ..
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 4: Start local dev app for visual verification**

```powershell
cd web; npm run dev -- --host 127.0.0.1; cd ..
```

Expected: Vite prints a local URL, typically `http://127.0.0.1:5173/`.

- [ ] **Step 5: Browser verification checklist**

Open `/chat` and verify:

- Default: left rail, center work stream, and right workspace are visible.
- Left collapse: left rail becomes compact and center expands.
- Right collapse: workspace disappears and center expands.
- Focus: both sides collapse and center dominates.
- Narrow window: right panel is hidden or drawer-ready and center remains usable.

- [ ] **Step 6: Commit verification fixes if needed**

If visual verification requires small fixes:

```powershell
git add web/src/chat web/src/locales/strings.ts
git commit -m "fix(web): polish workbench layout states"
```

If no fixes are needed, do not create an empty commit.

---

## Self-Review

- Spec coverage: covers Phase 1 layout, independent panel collapse, focus mode, Capability in left rail, right panel empty sections, existing routes, and verification.
- No planned `hermes_core/` changes.
- No placeholders remain.
- Later enhancements such as draggable widths and live Materials/Outputs extraction are intentionally excluded from Phase 1.
