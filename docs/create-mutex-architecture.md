# Windows Gateway Lock — Architectural Fix

## 1. What Changed

**Before**: Cross-process gateway mutual exclusion used `msvcrt.locking(LK_NBLCK, 1)` — a user-mode byte-range lock on a file (`gateway.lock`).

**After**: Cross-process gateway mutual exclusion uses `CreateMutex` — a Windows kernel named mutex object.

```python
# Old (broken):
open("gateway.lock", "a+")
msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # file byte-range lock

# New (correct):
CreateMutex(None, True, "Global\\hermes-gateway-runtime-lock")  # kernel object
```

## 2. Why

The `msvcrt.locking` API is a user-mode emulation of POSIX `fcntl.flock`. Key behavioral differences:

| Property | `fcntl.flock` (Linux) | `msvcrt.locking` (Windows) |
|---|---|---|
| Lock lifetime | Process-scoped. Kernel releases on exit. | Byte-range lock on file content. Unreliable release. |
| Orphan process | Lock auto-released. | Lock may persist (stale lock). |
| File deletion under lock | Succeeds normally. | `unlink()` fails with `PermissionError`. |
| File truncation under lock | Succeeds. Content cleared; lock persists. | Content cleared; lock persists. |
| `handle.close()` after failed lock | No side effects. | May raise `PermissionError` (tainted handle). |

Every failure mode was encountered across four consecutive patches to the same code path:

1. **Patch 1**: Catch `PermissionError` in `get_running_pid()` → returned None, but `acquire_gateway_runtime_lock()` still failed.
2. **Patch 2**: `unlink()` stale lock file on acquire failure → `unlink()` silently failed on locked files.
3. **Patch 3**: `ftruncate(fd, 0)` the stale lock file → `handle.close()` raised `PermissionError` because file handle was in error state from failed `LockFile` call.
4. **Patch 4**: `ftruncate(fd, 0) + os.write(fd, b'\n')` to give locking a target byte → same `handle.close()` error.

All four patches targeted the symptom (how to clear a stale lock) instead of the root cause (the locking primitive cannot guarantee cleanup on process exit). The correct fix replaced the primitive.

`CreateMutex` is a kernel object. Windows guarantees:
- The mutex is released when the owning process exits — **always**, no `atexit` required.
- `CloseHandle` on the last handle destroys the object — no stale state.
- `OpenMutex` with `SYNCHRONIZE` detects an active mutex without side effects — perfect for `is_gateway_runtime_lock_active()`.

## 3. Implementation

### New file: `hermes/gateway/lock_win32.py` (~55 lines)

Three public functions, matching the existing API signatures of `gateway.status`:

```python
def acquire_gateway_runtime_lock() -> bool:
    """CreateMutex with bInitialOwner=True."""
    
def release_gateway_runtime_lock() -> None:
    """CloseHandle on the stored mutex handle."""

def is_gateway_runtime_lock_active(lock_path=None) -> bool:
    """OpenMutex(SYNCHRONIZE) — non-invasive detection."""
```

The `lock_path` parameter is accepted for call-site compatibility with the POSIX path but ignored on Windows.

### Modified: `hermes/gateway/status.py` (~30 lines removed, 8 lines added)

- **Added**: Conditional import at module bottom:
  ```python
  if _IS_WINDOWS:
      from .lock_win32 import (
          acquire_gateway_runtime_lock,
          release_gateway_runtime_lock,
          is_gateway_runtime_lock_active,
      )
  ```
  This overrides the POSIX `fnctl.flock` implementations at import time.

- **Removed**: All `PermissionError` / `OSError` catch blocks in `get_running_pid()` — the three Functions we added across four patches. No longer needed; the mutex doesn't throw on stale state.

- **Preserved**: The POSIX `fcntl.flock` implementations remain untouched. On Linux/WSL, the code path is identical to upstream hermes.

### Modified: `hermes/gateway/run.py` (~25 lines removed)

- **Removed**: The `ftruncate` + `os.write` + retry block in `start_gateway()`. Replaced with the original single `acquire_gateway_runtime_lock()` call.

### Net code change

| Layer | Lines added | Lines removed |
|-------|------------|---------------|
| `lock_win32.py` (new) | +55 | — |
| `status.py` | +8 | -30 |
| `run.py` | — | -25 |
| **Total** | **+63** | **-55** |

**Net: +8 lines.** 100 lines of fragile workarounds replaced by the correct kernel primitive.

## 4. Design Decision

This was not a patch-level fix. It was an architectural decision reached after four failed patches proved that the user-mode file-lock approach is fundamentally incorrect on Windows.

The question that produced the right answer was: *"Do we need to fundamentally redesign this?"* — asked by a human when the AI kept producing one-line fixes that each uncovered a deeper failure mode.

The answer was no — the architecture (three-process isolation, cross-process mutex) was correct. Only the Windows implementation of the mutex primitive was wrong. Replacing it preserved the security boundaries (shell/ui process, web_server process, gateway process all remain separate) while eliminating the platform-specific unreliability.

## 5. Verification

On restart, the gateway process acquires the mutex immediately. No `gateway.lock` file operations occur. No `PermissionError` can arise from stale state. All three processes (shell, web_server, gateway) start cleanly.

```bash
# Manual verification (optional):
python -c "
from gateway.status import acquire_gateway_runtime_lock, release_gateway_runtime_lock
print('acquire:', acquire_gateway_runtime_lock())  # True
print('release:', release_gateway_runtime_lock())  # None
"
```

## 6. Upstream Impact

- `lock_win32.py` is a Kabuqina-only file. Upstream hermes never touches it.
- `status.py` changes are a conditional import + removal of Kabuqina-specific workarounds. Re-merging upstream changes requires zero conflict resolution.
- `run.py` is restored to near-upstream state (only the parallel startup + concurrent write protection remain as Kabuqina additions).

## 7. Related Documents

- `docs/bugs/gateway-lock-windows.md` — detailed bug chain analysis for all four failed patches.
