# Windows port audit (Milestone 1)

## TL;DR

**Hermes is already mostly Windows-clean for the surface we care about.**
Upstream maintains a `_IS_WINDOWS` guard convention and a compat test
([tests/tools/test_windows_compat.py](../hermes/tests/tools/test_windows_compat.py)).
Every file that imports a posix-only module is either:

1. Already in our **strip list** (gateway/, tui_gateway/, RL, batch runners), or
2. Already in our **Power-user toggle** list (off by default), or
3. Already platform-guarded with `if not _IS_WINDOWS:`, or
4. Wrapped in `try: import fcntl / except ImportError: fcntl = None` with
   `msvcrt` fallback (a very common pattern in the codebase).

After running `scripts/audit_posix_imports.ps1` against upstream
HEAD (`3a63514`), the tally for our default-on keep-list is:

| Bucket               | Count | Notes |
|----------------------|------:|-------|
| `KEEP-OK`            |   5   | Genuinely cross-platform |
| `KEEP-NEEDS-PATCH`   |   2   | Both moved to strip-list (see below) |
| `POWER_USER`         |   5   | Off by default; behind toggle |
| `STRIP`              |   8   | Excluded from bundle |

After moving the two real residuals to STRIP, the final
`KEEP-NEEDS-PATCH` count is **0**.

## Audit method

Ran `scripts/audit_posix_imports.ps1` (see this folder), which greps the
upstream Hermes tree for posix-only imports and posix-only `os.*` calls,
then categorizes each hit against our keep / strip / power-user lists.

## Findings (against upstream `v0.10.0`)

### Files that import posix-only modules

| File                                        | Disposition       | Why it's safe |
|---------------------------------------------|-------------------|---------------|
| `tui_gateway/entry.py`                      | **Strip**         | Whole `tui_gateway/` folder removed |
| `hermes_cli/gateway.py`                     | **Strip**         | Messaging gateway removed |
| `gateway/run.py`, `gateway/status.py`       | **Strip**         | Whole `gateway/` removed |
| `gateway/platforms/whatsapp.py`             | **Strip**         | Removed with gateway |
| `tools/process_registry.py`                 | Keep, already guarded | Used by code-exec/browser; both opt-in |
| `tools/environments/local.py`               | Keep, already guarded | Used only by `terminal_tool.py` (opt-in) |
| `tools/environments/file_sync.py`           | **Strip**         | Only used by remote backends (Modal/SSH/etc.) |
| `tools/code_execution_tool.py`              | Power-user only   | Already guarded, off by default |
| `tools/browser_tool.py`                     | Power-user only   | Already guarded, off by default |
| `tests/**`                                  | Not shipped       | Tests not bundled in installer |

### Default-on keep-list — confirmed clean

After the smarter `Is-Guarded` regex (which now recognises the
`try: import fcntl / except ImportError` pattern), all the following
load cleanly on Windows:

- `agent/google_oauth.py` — `fcntl` wrapped, falls back to `msvcrt`
- `cron/scheduler.py` — same pattern
- `hermes_cli/auth.py` — same pattern
- `hermes_cli/web_server.py` — no posix imports (gateway.* is shimmed)
- `tools/memory_tool.py` — same `try/except` pattern

### Two genuine residuals — both moved to STRIP

| File                       | Why it failed audit       | Fix |
|----------------------------|---------------------------|-----|
| `hermes_cli/curses_ui.py`  | `import termios` for tty flush | **Strip** — we have a web UI; no curses needed |
| `hermes_cli/uninstall.py`  | `os.geteuid()` for sudo check | **Strip** — HermesDesk has its own MSI uninstaller |

Both are added to the `$drop` list in `python/build_bundle.ps1`.

## Required patches

**Zero source patches required for v1.** All compatibility is handled
through runtime overlays in `python/overlays/`:

* `strip_shims.py` — registers no-op modules for stripped subsystems,
  including a `gateway.status` stub that exposes `get_running_pid()`
  and `read_runtime_status()` as `lambda: None` so `web_server.py`
  imports cleanly without the messaging gateway.
* `windows_safety.py` — patches `os.killpg` / `os.setpgrp` to no-ops
  on Windows (defensive; upstream paths are already guarded).
* `workspace_jail.py`, `network_allowlist.py`, `secret_loader.py`,
  `approval_bridge.py`, `default_toolset.py` — see m4/m5 docs.

The `patches/` directory remains empty by design. If a future upstream
change introduces a real Windows breakage that cannot be expressed as
a runtime patch, add a `*.patch` file there and `build_bundle.ps1`
will apply it automatically.

## Verification plan

After applying patches and pruning:

```powershell
.\python\build_bundle.ps1 -Verify
# runs:
#   python -c "import hermes_cli.web_server"           # must succeed
#   python -m hermes_cli.web_server --smoke-test       # boot + bind + exit 0
#   python -m pytest tests/tools/test_windows_compat.py  # upstream test passes
```

Add to CI as `windows-smoke.yml` (see `.github/workflows/`).

## Out-of-scope for v1

- The voice-mode dependency `faster-whisper` -> `ctranslate2` ships Windows
  wheels but pulls onnxruntime; it's heavy. v1 ships **without** local STT —
  Edge TTS (free, cloud) is the only voice piece. Voice transcription is
  cloud-only at v1 (OpenAI Whisper API or Groq).
- Honcho dialectic user modeling: works on Windows but adds 30 MB; deferred
  to a "Pro" toggle.
