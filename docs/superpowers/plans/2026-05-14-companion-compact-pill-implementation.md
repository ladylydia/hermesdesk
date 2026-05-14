# Kabuqina Companion Compact Pill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the companion minimize button shrink the companion into a compact pill, with a clear expand path and unchanged hide/open-main behavior.

**Architecture:** Add a Tauri command for companion mode sizing and register it with the existing companion commands. Update `CompanionWindow` to own `expanded`/`compact` UI state, call native window resize, and render a compact pill that can expand back.

**Tech Stack:** Tauri 2 Rust commands, React 19, TypeScript, Tailwind CSS v4, lucide-react icons, existing desktop delivery notification state.

---

## File Structure

- Modify: `tauri/src/companion.rs`
  - Adds `cmd_set_companion_mode` and centralizes expanded/compact sizes.
- Modify: `tauri/src/lib.rs`
  - Registers `companion::cmd_set_companion_mode`.
- Modify: `tauri/capabilities/default.json`
  - Adds window size permission if needed by Tauri capability enforcement.
- Modify: `web/src/companion/CompanionWindow.tsx`
  - Adds mode state, minimize/expand handlers, compact pill rendering.
- Modify: `web/src/locales/strings.ts`
  - Adds companion mode labels.
- Test: `web/src/lib/desktopDelivery.test.mjs` or new `web/src/companion/companionUx.test.mjs`
  - Source-level test for compact mode behavior.

## Scope Notes

- Do not build a floating chat input.
- Do not change desktop delivery event payloads.
- Do not change `cmd_hide_companion` or `cmd_focus_main_window` behavior except to coexist with compact mode.
- Keep compact mode visible and draggable.

---

### Task 1: Add Companion UX Source Test

**Files:**
- Create: `web/src/companion/companionUx.test.mjs`
- Modify: `web/package.json`

- [ ] **Step 1: Add test script**

In `web/package.json`, add:

```json
"test:companion-ux": "node src/companion/companionUx.test.mjs"
```

- [ ] **Step 2: Write failing source test**

Create `web/src/companion/companionUx.test.mjs`:

```js
/* global URL */
import assert from "node:assert/strict";
import fs from "node:fs";

const companionSource = fs.readFileSync(new URL("./CompanionWindow.tsx", import.meta.url), "utf8");

assert.match(
  companionSource,
  /type CompanionMode = "expanded" \| "compact"/,
  "CompanionWindow should model expanded and compact modes.",
);

assert.match(
  companionSource,
  /cmd_set_companion_mode/,
  "CompanionWindow should call the Tauri companion mode resize command.",
);

assert.match(
  companionSource,
  /setMode\("compact"\)/,
  "The minimize action should enter compact mode.",
);

assert.match(
  companionSource,
  /setMode\("expanded"\)/,
  "The compact pill should be able to expand back.",
);

assert.doesNotMatch(
  companionSource,
  /onClick=\{\(\) => setNotice\(null\)\}/,
  "The minimize button must not merely clear the current notice.",
);
```

- [ ] **Step 3: Run test to verify it fails**

```powershell
cd web; npm run test:companion-ux; cd ..
```

Expected: FAIL because the current component does not have compact mode and still clears notice from the minimize button.

- [ ] **Step 4: Commit test**

Do not commit yet. The failing test should be committed with the implementation in Task 3 after it passes.

---

### Task 2: Add Native Companion Resize Command

**Files:**
- Modify: `tauri/src/companion.rs`
- Modify: `tauri/src/lib.rs`
- Modify: `tauri/capabilities/default.json`

- [ ] **Step 1: Add sizing constants and mode command**

In `tauri/src/companion.rs`, add imports and constants:

```rust
use tauri::{LogicalSize, Manager, Size, WebviewWindowBuilder};

const COMPANION_EXPANDED_WIDTH: f64 = 320.0;
const COMPANION_EXPANDED_HEIGHT: f64 = 160.0;
const COMPANION_COMPACT_WIDTH: f64 = 120.0;
const COMPANION_COMPACT_HEIGHT: f64 = 48.0;
```

Update the builder sizes:

```rust
.inner_size(COMPANION_EXPANDED_WIDTH, COMPANION_EXPANDED_HEIGHT)
.min_inner_size(COMPANION_COMPACT_WIDTH, COMPANION_COMPACT_HEIGHT)
```

Add:

```rust
#[tauri::command]
pub async fn cmd_set_companion_mode(
    app: tauri::AppHandle,
    mode: String,
) -> Result<(), String> {
    let Some(w) = app.get_webview_window(COMPANION_LABEL) else {
        return Ok(());
    };

    let (width, height) = match mode.as_str() {
        "compact" => (COMPANION_COMPACT_WIDTH, COMPANION_COMPACT_HEIGHT),
        "expanded" => (COMPANION_EXPANDED_WIDTH, COMPANION_EXPANDED_HEIGHT),
        _ => return Err(format!("invalid companion mode: {mode}")),
    };

    w.set_size(Size::Logical(LogicalSize { width, height }))
        .map_err(|e| e.to_string())?;
    Ok(())
}
```

- [ ] **Step 2: Register command**

In `tauri/src/lib.rs` inside `tauri::generate_handler![...]`, add:

```rust
companion::cmd_set_companion_mode,
```

next to the other companion commands.

- [ ] **Step 3: Add capability permission if needed**

In `tauri/capabilities/default.json`, add:

```json
"core:window:allow-set-size"
```

near the other `core:window:*` permissions. If Tauri rejects this identifier, run the build, read the exact capability error, and use the permission name Tauri suggests.

- [ ] **Step 4: Verify Rust type-check for command registration**

Run:

```powershell
cd tauri; cargo check; cd ..
```

Expected: PASS or a capability/config-only issue. If Rust fails on imports, fix imports in `companion.rs` only.

- [ ] **Step 5: Commit**

```powershell
git add tauri/src/companion.rs tauri/src/lib.rs tauri/capabilities/default.json
git commit -m "feat(tauri): add companion mode sizing command"
```

---

### Task 3: Implement Compact Pill UI

**Files:**
- Modify: `web/src/companion/CompanionWindow.tsx`
- Modify: `web/src/locales/strings.ts`
- Test: `web/src/companion/companionUx.test.mjs`

- [ ] **Step 1: Add locale labels**

Add under `companion` in both locales:

```typescript
minimize: "缩小悬浮窗",
expand: "展开悬浮窗",
idleShort: "待机中",
```

English:

```typescript
minimize: "Shrink companion",
expand: "Expand companion",
idleShort: "Here",
```

- [ ] **Step 2: Add mode state and resize helper**

In `CompanionWindow.tsx`, add:

```typescript
type CompanionMode = "expanded" | "compact";
```

Inside the component:

```typescript
const [mode, setMode] = useState<CompanionMode>("expanded");
```

Add:

```typescript
const setCompanionMode = async (next: CompanionMode) => {
  try {
    await invoke("cmd_set_companion_mode", { mode: next });
  } catch (error) {
    console.error("cmd_set_companion_mode failed:", error);
    try {
      const win = getCurrentWindow();
      await win.setSize(
        next === "compact"
          ? { type: "Logical", width: 120, height: 48 }
          : { type: "Logical", width: 320, height: 160 },
      );
    } catch (fallbackError) {
      console.error("companion setSize fallback failed:", fallbackError);
    }
  }
  setMode(next);
};
```

If the TypeScript API rejects the object shape for `setSize`, import `LogicalSize` from `@tauri-apps/api/dpi` and use:

```typescript
await win.setSize(new LogicalSize(120, 48));
```

- [ ] **Step 3: Replace minimize behavior**

Replace:

```tsx
onClick={() => setNotice(null)}
```

with:

```tsx
onClick={() => void setCompanionMode("compact")}
```

Use:

```tsx
aria-label={t("companion.minimize")}
title={t("companion.minimize")}
```

- [ ] **Step 4: Render compact pill**

Before the expanded return, add:

```tsx
if (mode === "compact") {
  return (
    <button
      type="button"
      className={cn(
        "flex h-screen w-screen cursor-move select-none items-center gap-2 overflow-hidden rounded-3xl border border-white/50 bg-white/95 px-2 text-left text-zinc-800 shadow-lg shadow-zinc-950/10 backdrop-blur",
        "dark:border-zinc-700/60 dark:bg-zinc-950/95 dark:text-zinc-100",
      )}
      onClick={() => void setCompanionMode("expanded")}
      onMouseDown={startDrag}
      aria-label={t("companion.expand")}
      title={t("companion.expand")}
      data-tauri-drag-region
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300">
        <img src="/kabuqina_na_blue_48.png" alt="" className="h-5 w-5" />
      </span>
      <span className="min-w-0 truncate text-xs font-semibold">
        {locale === "zh" ? t("companion.idleShort") : "Nana"}
      </span>
    </button>
  );
}
```

If click-to-expand conflicts with dragging, change `onMouseDown` to call `startDrag` only when the mouse movement exceeds a small threshold in a follow-up fix. Do not solve drag thresholding in this task unless manual verification shows it is necessary.

- [ ] **Step 5: Run companion UX test**

```powershell
cd web; npm run test:companion-ux; cd ..
```

Expected: PASS.

- [ ] **Step 6: Run web build**

```powershell
cd web; npm run build; cd ..
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add web/src/companion/CompanionWindow.tsx web/src/locales/strings.ts web/src/companion/companionUx.test.mjs web/package.json
git commit -m "feat(web): add companion compact pill mode"
```

---

### Task 4: Manual Companion Verification

**Files:**
- No planned source edits unless verification reveals a defect.

- [ ] **Step 1: Start app**

Run the normal dev flow:

```powershell
.\scripts\dev.ps1
```

Expected: Kabuqina launches.

- [ ] **Step 2: Show companion**

Use the title bar sparkle button or tray menu to show companion.

Expected: expanded companion appears, main window hides per current behavior.

- [ ] **Step 3: Verify minimize**

Click minimize.

Expected: companion visibly shrinks to compact pill, no long preview text remains.

- [ ] **Step 4: Verify expand**

Click compact pill body.

Expected: companion returns to expanded size and content.

- [ ] **Step 5: Verify close**

Click close in expanded mode.

Expected: companion hides and can be reopened from main title bar or tray.

- [ ] **Step 6: Verify open main**

Click open-main in expanded mode.

Expected: main Kabuqina window is shown/focused and companion hides.

- [ ] **Step 7: Run final checks**

```powershell
cd web; npm run test:companion-ux; npm run build; cd ..
cd tauri; cargo check; cd ..
```

Expected: all pass.

- [ ] **Step 8: Commit any verification fix**

If manual verification reveals a small issue:

```powershell
git add web/src/companion tauri/src/companion.rs tauri/src/lib.rs tauri/capabilities/default.json web/src/locales/strings.ts
git commit -m "fix: polish companion compact mode"
```

If no fixes are needed, do not create an empty commit.

---

## Self-Review

- Spec coverage: covers visible minimize behavior, compact pill mode, hide/open-main behavior, Tauri native sizing, frontend fallback, no-notice minimize, drag preservation, and verification.
- No B2B/workbench changes are included in this plan.
- No placeholders remain.
- The plan keeps native sizing because CSS-only shrinking would leave a large transparent hit area.
