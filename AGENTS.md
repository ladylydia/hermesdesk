# Kabuqina — Development Guide

> **Windows-only** Tauri 2 desktop app wrapping [Hermes Agent](https://github.com/NousResearch/hermes-agent).
> The upstream code is frozen in `hermes_core/` — no automatic sync, no submodule, no patches.
> For internals of the frozen agent core, see `hermes_core/AGENTS.md`.

**Roadmap:** This repo has migrated from a patched submodule model to an owned monorepo with policy-layer architecture. See `docs/depatching-plan.md` for the full migration record.

## Architecture

```
Tauri 2 shell (Rust)
 ├─ Web shell (React/Vite, `web/`)        ← onboarding, /chat, settings
 ├─ Python child: desktop_entrypoint.py   ← Hermes web_server on loopback
 └─ Python child: gateway.run (optional)  ← messaging adapters
```

- The **web shell** (`web/src/`) is NOT the Hermes React UI. It handles onboarding/settings/chat, then redirects to Hermes' React dashboard at `http://127.0.0.1:<random-port>` (built from `hermes_core/web/`).
- **Two separate Python processes** — the web child runs `desktop_entrypoint.py`; the gateway child runs `python -m gateway.run`. They don't share memory. `strip_shims.py` prevents the web child from accidentally becoming the gateway entrypoint.
- All comms between Tauri ↔ Python use **loopback-only HTTP/WS on random ports** per launch.
- LLM API keys live in **Windows Credential Manager** (DPAPI via `keyring`), never on disk.

## Build pipeline (order matters)

**Prerequisites:** Rust 1.80+, Node 20+, PowerShell 7+

```powershell
# 1. Python bundle (downloads standalone CPython 3.11, installs deps)
.\python\build_bundle.ps1

# 2. Web shell
cd web; npm ci; npm run build; cd ..

# 3. Dev (combines all three layers)
.\scripts\dev.ps1

# Or manual Tauri dev:
cd tauri; cargo tauri dev
```

- `npm run build` in `web/` uses `tsc --noEmit` (not `tsc -b`) to avoid `tsconfig.tsbuildinfo` locking on Windows.
- `build_bundle.ps1` also builds Hermes' own React SPA (`hermes_core/web/` → `hermes_core/hermes_cli/web_dist/`) via Git Bash (`sync-assets` uses POSIX `rm`/`cp`). On machines without Git Bash, it falls back to `npm run build` directly.

## Policy layer (`python/src/`)

Core logic extracted from monkey-patch overlays into injected policy objects.
Each policy has a corresponding overlay wrapper (tagged `# DEPRECATED`):

| Policy | Overlay Wrapper | Responsibility |
|--------|----------------|----------------|
| `path_policy.py` | `workspace_jail.py`, `path_guard.py` | Confine file I/O to workspace + extra dirs |
| `secret_store.py` | (inlined in `overlays/__init__.py`) | Fetch API key from Tauri bridge (DPAPI) |
| `network_policy.py` | `network_allowlist.py` | Block egress to non-allowlisted hosts |
| `approval_backend.py` | `approval_bridge.py` | Route shell commands through Tauri approval dialog |
| `tool_policy.py` | `default_toolset.py` | Restrict tools to safe keep-list (or power-user list) |
| `gateway_policy.py` | `strip_shims.py` | Platform feature flags + gateway adapter defaults |

## Overlays (`python/overlays/`)

The Python entrypoint calls `overlays.apply_all()` **before importing any Hermes modules**. Seven overlays install in strict order:

| Order | Overlay | Effect |
|-------|---------|--------|
| 1 | `strip_shims` | Stub-out gateway imports in the web child |
| 2 | `desktop_llm_config` | Desktop-specific LLM routing |
| 3 | `workspace_jail` | Confine file I/O to workspace + temp + data dir |
| 4 | `network_allowlist` | Block egress to non-allowlisted hosts |
| 5 | `default_toolset` | Restrict tools to safe keep-list (or power-user list) |
| 6 | `builtin_helpers` | L1 QuickActions dispatch |
| 7 | `approval_bridge` | Route shell commands through Tauri approval dialog |

Failure is fatal by default. Set `HERMESDESK_OVERLAY_LENIENT=1` to make failures non-fatal (dev/smoke only).

Overlays `windows_safety` and `secret_loader` were removed in Phase 4 (no‑op and trivial wrapper respectively). The policy files under `python/src/` are the target replacement; overlays will be deleted per-policy once their wiring is stable.

## Power user mode

Controlled by `HERMESDESK_POWER_USER=1` (Rust sets it before spawning the Python child). Toggling it in Settings **restarts the Python child** — the entire toolset config is rewritten via `default_toolset.py`.

Without power user: `web, file, vision, image_gen, tts, skills, todo` toolsets.
With power user: adds `browser, terminal, code_execution, moa`.

## Upstream intake policy

- `hermes_core/` is a **frozen snapshot** of the upstream Hermes Agent. No automatic sync.
- All previously-patched behaviors are owned code, committed directly.
- **Upstream cherry-picks** (security advisories, CVE fixes, provider API breaking changes):
  - Manually `git cherry-pick <commit>` against `hermes_core/`
  - Commit message: `chore: cherry-pick <hash> <subject>`
  - Log in `DECISIONS.md`
- No batch merges. No submodule updates. No patch files.

## Key commands

```powershell
# Dev loop (build bundle if missing, web deps, Tauri dev)
.\scripts\dev.ps1
.\scripts\dev.ps1 -Rebuild     # force rebuild bundle

# Build everything for release
.\python\build_bundle.ps1 -Verify
cd web; npm ci; npm run build; cd ..
cd tauri; cargo tauri build

# Python tests (needs hermes_core/ directory — already in tree)
cd python; python -m unittest discover -s tests -p "test_*.py" -v; cd ..

# Lint web/
cd web; npm run lint

# Regenerate Tauri icons (source PNG: web/public/kabuqina_na_blue_256.png)
cd tauri; cargo tauri icon ..\web\public\kabuqina_na_blue_256.png
```

## Windows-specific gotchas

1. **Proxy strangling loopback:** System-wide proxies (Clash, V2Ray, corporate MITM) route `127.0.0.1` to the proxy, breaking Tauri↔Python comms. The Rust supervisor strips all proxy env vars and forces `NO_PROXY=127.0.0.1,localhost,::1`. `secret_store.py` uses an explicit empty `ProxyHandler({})`. See `docs/troubleshooting.md` §1.

2. **MSVC env for wheels on release builds** (`pydantic-core` etc.). Use **Developer PowerShell for VS** or **cmd.exe** with VC vars set when building release. See `docs/embedded-python-bundled.md`.

3. **PowerShell 7+ required** for build scripts. Windows PowerShell 5.1 won't work.

4. **Secrets never touch disk** — the plaintext API key is fetched once from a loopback HMAC URL at Python startup and set into `os.environ`.

5. **Gateway and web child are separate processes.** Don't assume they share state. `strip_shims.py` in the web child replaces `gateway.run` with a no-op stub.

## Where things live (runtime)

| Path | Purpose |
|------|---------|
| `python/dist/runtime/` | Bundled Python + hermes_core + overlays + site-packages |
| `%LOCALAPPDATA%\com.kabuqina.app\` | Per-user app data (logs, HERMES_HOME, workspace state) |
| `%LOCALAPPDATA%\com.kabuqina.app\hermes-home\` | Hermes config root (redirected from `~/.hermes`) |
| `%USERPROFILE%\Documents\KabuqinaWork\` | Default workspace (configurable) |
| `tauri/target/release/bundle/msi/` | MSI installer output |

## References

- **Frozen agent core:** `hermes_core/AGENTS.md`
- **De-patching migration plan:** `docs/depatching-plan.md`
- **Architecture:** `docs/architecture.md`
- **Safety model:** `docs/safety.md`
- **Troubleshooting:** `docs/troubleshooting.md`
- **Product decisions:** `DECISIONS.md`
- **Build details:** `docs/embedded-python-bundled.md`
