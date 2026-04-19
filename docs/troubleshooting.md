# HermesDesk troubleshooting & gotchas

A field log of every non-obvious failure mode we hit while bringing
HermesDesk up on Windows, with the root cause and where the fix lives.
Written for the next person (future us, a contributor, or a user filing
a bug report) so we don't burn the same hours twice.

Each entry follows the same shape:

> **Symptom** — what you see in logs / on screen
> **Root cause** — the actual mechanism
> **Fix** — what we did, and which file holds the permanent guard
> **Lesson** — the general principle, so we recognise the family next time

---

## 1. VPN / system-proxy strangling loopback HTTP

**Symptom**

* Python child logs `TimeoutError: timed out` on the very first
  `urllib.request.urlopen("http://127.0.0.1:<port>/secret/...")`.
* Rust side logs `bridge serve loop started on ...` but **no**
  `bridge accepted conn from ...` ever arrives.
* `bootstrap failed: python did not write port within 30s` follows.
* Reproduces 100% on machines with a system-wide proxy active
  (Clash / V2Ray / SS / SSR / Surge / corporate MITM proxy).
* Reproduces even when `HTTP_PROXY` env var is empty —
  Windows `urllib.request.getproxies()` reads the registry directly.

**Root cause**

Two compounding things:

1. **Windows registry-based system proxy.** Set under
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings\ProxyServer`,
   typically pointing at `127.0.0.1:<some_port>`. Python's
   `urllib.request` on Windows reads this key (via
   `getproxies_registry()`) regardless of env vars.
2. **`<local>` in `ProxyOverride` does not reliably match `127.0.0.1`.**
   It matches hostnames *without* a dot — `localhost`, `mymachine` — but
   numeric loopback usually slips through and goes to the proxy. The
   proxy then has no idea what to do with a loopback URL and just hangs
   the connection.

The Tauri bridge listens on `127.0.0.1:<random>`, so the GET silently
gets routed to Clash's `127.0.0.1:8668`, which holds the socket open
forever. Python read times out; bridge never accepts.

**Fix** — three layers, all required:

* `python/overlays/secret_loader.py` — explicit empty proxy table for
  the loopback fetch:

  ```python
  opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
  with opener.open(url, timeout=5) as resp:
      ...
  ```
* `tauri/src/python_supervisor.rs` — strip every proxy env var on the
  spawned Python child and force `NO_PROXY=127.0.0.1,localhost,::1`:

  ```rust
  .env_remove("HTTP_PROXY").env_remove("http_proxy")
  .env_remove("HTTPS_PROXY").env_remove("https_proxy")
  .env_remove("ALL_PROXY").env_remove("all_proxy")
  .env_remove("NO_PROXY").env_remove("no_proxy")
  .env("NO_PROXY", "127.0.0.1,localhost,::1")
  ```
* (Future, when we wire `httpx` for LLM calls inside Hermes:) construct
  the `httpx.Client` with `proxies=None` for any loopback URL, even
  though we don't currently make loopback `httpx` calls.

**Lesson**

> On Windows, **never trust env vars to express "no proxy"**. The OS
> registry wins for any client that uses
> `urllib.request.getproxies()` /  `WinHttpGetIEProxyConfigForCurrentUser`
> /  `system_proxy_resolver`. For loopback IPC, always pass an explicit
> empty proxy at the client level. Treat this as a hard requirement
> for any embedded HTTP-based IPC on Windows.

If we ever expose an option for the user's LLM traffic to *use* their
proxy (corporate networks, geo-restricted providers), it should be a
**separate, opt-in setting** — `HERMESDESK_HTTPS_PROXY` — that
`secret_loader` and the bridge both ignore.

---

## 2. Single-threaded Tokio runtime starved by sync I/O

**Symptom**

* Bridge `serve()` task is alive (we see "serve loop started").
* Python connects to the bridge port (TCP-level).
* But no `accept().await` ever returns, even though the OS clearly
  has the SYN.
* Removing `hyper` and rewriting bridge as raw `tokio::net::TcpListener`
  did **not** help — confirming the bug was outside the HTTP layer.

**Root cause**

`python_supervisor.rs::wait_for_port` was using
`std::fs::read_to_string` in a loop:

```rust
loop {
    if let Ok(s) = std::fs::read_to_string(&self.port_file) {  // <-- SYNC
        ...
    }
    tokio::time::sleep(Duration::from_millis(100)).await;
}
```

Tauri runs on a **single-threaded** Tokio runtime (`current_thread`
flavour) by default. A blocking syscall on the runtime thread parks
the entire executor — including the `serve()` task that owns the
`TcpListener`. So the kernel completed the TCP handshake, but the
userspace `accept()` future was never polled.

**Fix** — `tauri/src/python_supervisor.rs`:

```rust
if let Ok(s) = tokio::fs::read_to_string(&self.port_file).await {
    ...
}
```

**Lesson**

> Inside `tauri::async_runtime::spawn` and Tauri command handlers,
> **every I/O must be async**. `std::fs`, `std::process`,
> `reqwest::blocking`, `serde_json::from_reader(File)` — all forbidden
> on the runtime thread. Use `tokio::fs`, `tokio::process`, `reqwest`
> async, or move the work to a `tokio::task::spawn_blocking`.

Audit checklist for every new Rust file:

```
$ rg "std::fs::|std::process::Command::|::blocking" tauri/src/
```

Should return zero hits in code paths reachable from `#[tauri::command]`,
`spawn`, or `RunEvent` handlers.

---

## 3. `windows_safety.py` overlay was actively harmful

**Symptom**

* Smoke test crashes immediately on `import random` with
  `AttributeError: module 'os' has no attribute 'register_at_fork'`.
* Stack lands inside `Lib/random.py:_inst.seed()`.

**Root cause**

We had an overlay that "defensively" set `os.fork = _noop` etc. on
Windows. **CPython's stdlib uses `hasattr(os, "fork")` as a feature
flag** — `random.py` reads it and, if true, calls
`os.register_at_fork(...)` which only exists on POSIX. Spoofing one
function tricked the stdlib into demanding a whole family of POSIX
APIs we couldn't fake.

**Fix** — `python/overlays/windows_safety.py` was gutted to a no-op
with a long docstring explaining *why* it's a no-op so nobody
"helpfully" re-introduces the bug. Audit (`scripts/audit_posix_imports.ps1`)
already proves no unguarded `os.fork`/`os.setpgrp`/etc. survives in
our keep-list.

**Lesson**

> **Do not monkey-patch attributes onto `os`, `sys`, or `builtins`
> as a "safety net".** The stdlib treats these as capability probes.
> If a specific upstream call site is broken on Windows, monkey-patch
> *that specific function on that specific module*, never the global.

---

## 4. Toolset overlay targeted the wrong upstream API

**Symptom**

* Smoke test logs `WARNING: no known toolset resolver function in
  toolset_distributions`.
* Default toolset is whatever upstream ships (includes terminal /
  code_execution), so the safety story is broken silently.

**Root cause**

We tried to monkey-patch `toolset_distributions.get_default_toolset()` —
a function that doesn't exist. `toolset_distributions` is for RL data
generation, not runtime selection. The actual source of truth is
`platform_toolsets.cli` in `~/.hermes/config.yaml`, maintained by the
interactive `hermes tools` CLI command.

**Fix** — `python/overlays/default_toolset.py` now *writes* the desired
toolset directly into Hermes' config file at startup, using
`hermes_cli.config.{load_config, save_config}`. It only overwrites if
the value differs from the desired set, so the user can still toggle
individual toolsets in the Settings UI without us stomping on every
launch.

**Lesson**

> Before patching a function, **grep upstream for actual call sites of
> that function**. If nothing calls it, you're patching dead code.
> Hermes' real surface for "what's enabled" is the YAML, not a Python
> entry point.

---

## 5. Approval bridge function-name drift

**Symptom**

* Smoke test logs `WARNING: approval module had no known prompt fn`.
* Any "dangerous" command would block on upstream's `input()` prompt
  — invisible inside a desktop app — and the agent appears to hang.

**Root cause**

We were patching three speculative names (`prompt_user`,
`request_approval`, `ask_user`). The actual upstream function is
`tools.approval.prompt_dangerous_approval(command, description,
timeout_seconds, allow_permanent, approval_callback)`.

**Fix** — `python/overlays/approval_bridge.py` now patches that exact
symbol with a signature-matching replacement that POSTs to the Tauri
loopback bridge and returns one of `'once' | 'deny'` (we deliberately
never auto-promote to `'session'` / `'always'` — non-technical users
should re-confirm every dangerous command).

**Lesson**

> When monkey-patching upstream, the overlay should:
> 1. **Verify the symbol exists** at install time and log a loud
>    warning (or fail in strict mode) if it doesn't.
> 2. **Match the upstream signature exactly**, including kw-only
>    args, even if you ignore them — otherwise upstream callers will
>    `TypeError`.
> 3. **Pin the upstream commit** (`hermes` submodule SHA) so a silent
>    rename doesn't bypass the patch undetected.

---

## 6. `HERMES_HOME` collided with workspace jail

**Symptom**

* Smoke test logs `Failed to load permanent allowlist: HermesDesk
  workspace jail blocked write to C:\Users\X13\.hermes`.
* Hermes silently falls back to defaults; user-configured allowlist
  doesn't persist.

**Root cause**

Hermes defaults `HERMES_HOME` to `~/.hermes`. Our workspace jail
correctly blocks writes outside `%USERPROFILE%\Documents\HermesWork`,
which excludes `~/.hermes`.

**Fix** — two-part:

* `python/src/desktop_entrypoint.py` — set
  `os.environ["HERMES_HOME"] = "%LOCALAPPDATA%\\HermesDesk\\hermes-home"`
  *before* importing anything from `hermes_cli` (the import reads it
  via `hermes_constants.get_hermes_home()`).
* `python/overlays/workspace_jail.py` — add `HERMES_HOME` to the
  writable extras list so the jail recognises it as legitimate.

**Lesson**

> Per-user app state belongs under `%LOCALAPPDATA%\<AppName>`, not
> under `~`. This makes uninstall a single `rmdir`, isolates per-user
> data on shared machines, and lets the workspace jail keep `~`
> opaque. Set the env var **before** any module that reads it imports.

---

## 7. Hermes SPA was not built / not bundled

**Symptom**

* Tauri window opens, but `GET http://127.0.0.1:<port>/` returns
  `{"error":"Frontend not built. Run: cd web && npm run build"}`.
* `/api/status` returns 200 (so the API is up) — only the SPA mount
  is empty.

**Root cause**

`hermes_cli/web_server.py:mount_spa()` checks `WEB_DIST.exists()` at
**module import time** (where `WEB_DIST = hermes_cli/web_dist/`). If
the directory is missing, it registers a 404-returning catch-all
*instead of* the real SPA. Re-creating the directory at runtime is
useless — the FastAPI route table is frozen.

We had no step in `python/build_bundle.ps1` that invoked
`hermes/web`'s vite build, so the bundled `hermes_cli/web_dist/`
was always empty.

**Fix** — `python/build_bundle.ps1` step **4b** now:

1. If `hermes/hermes_cli/web_dist/index.html` is missing,
2. Runs `npm install` in `hermes/web/` (only if `node_modules` absent),
3. Runs `npm run build` (vite outputs to `../hermes_cli/web_dist`),
4. Hard-fails the bundle if `index.html` still doesn't exist.

The built SPA is then copied into `runtime/hermes/hermes_cli/web_dist/`
along with the rest of upstream Hermes.

**Lesson**

> When wrapping an upstream project that has its own frontend build,
> treat that build as a **first-class step in your bundler**, not a
> developer prerequisite. Otherwise CI on a fresh checkout will ship
> a blank UI and you won't notice until the smoke test reaches HTTP
> probing — which most smoke tests don't.

---

## 8. `.pth` relative paths brittle across dev/prod layouts

**Symptom**

* `ModuleNotFoundError: No module named 'hermes_cli'` even though
  `runtime\hermes\hermes_cli\__init__.py` clearly exists on disk.

**Root cause**

We shipped a `hermesdesk.pth` file containing `..\hermes` and
`..\site-packages`. `.pth` files resolve relative to the
`site-packages` directory they live in
(`runtime\python\Lib\site-packages\`), which means `..\hermes`
resolves to `runtime\python\Lib\hermes` — a directory that doesn't
exist. Correct value would be `..\..\..\hermes`, but that's fragile
across layout changes.

**Fix** — `python/src/desktop_entrypoint.py` now wires `sys.path`
explicitly from the *script's own location*, which is layout-stable
because Python always adds the script directory to `sys.path[0]`:

```python
def _wire_sys_path() -> None:
    here = Path(__file__).resolve().parent  # = runtime/
    for sub in ("hermes", "site-packages"):
        p = here / sub
        if p.is_dir():
            sys.path.insert(0, str(p))
```

The `.pth` file remains as belt-and-braces but is no longer relied on.

**Lesson**

> `.pth` files are a fine *fallback* but a brittle *contract*. For an
> embedded interpreter where you control the launcher, derive
> `sys.path` from `__file__` — it's the only thing guaranteed to be
> right regardless of CWD, layout, or which directory the user
> double-clicked from.

---

## 9. Upstream entry-point name churn (`run` → `main` → `start_server`)

**Symptom**

* `ERROR: no run()/main() entry in hermes_cli.web_server; check upstream`.

**Root cause**

We probed for `web_server.run` then `web_server.main`. The actual entry
in current upstream is `start_server(host, port, open_browser,
allow_public)`.

**Fix** — `desktop_entrypoint.py` now probes a list of likely names
(`start_server`, `run`, `main`) and tries multiple call signatures
(`(host=, port=)`, `(host, port)`, `(port=)`, `argv-style`) before
giving up.

**Lesson**

> When delegating to an upstream entry point you don't own, **probe
> defensively**: list of names × list of signatures, with a friendly
> error pointing at the upstream commit when all combinations fail.
> Pin the submodule SHA so the probe doesn't rot silently between
> upstream releases.

---

## 10. Stale dev-runtime overlays (changes don't take effect)

**Symptom**

* Edited `python/overlays/secret_loader.py`, restarted Tauri, behaviour
  unchanged. Eventually realise the running Python is loading a *copy*.

**Root cause**

The build copies overlays into two places:

* `python/dist/runtime/overlays/` — the bundled output
* `tauri/target/debug/runtime/overlays/` — what dev mode actually executes

A source edit doesn't propagate until you re-run `build_bundle.ps1`.

**Fix** — for now, a manual two-line copy after each overlay edit:

```powershell
Copy-Item -Force python\overlays\secret_loader.py python\dist\runtime\overlays\
Copy-Item -Force python\overlays\secret_loader.py tauri\target\debug\runtime\overlays\
```

**TODO** (tracked separately): a `scripts/sync-overlays.ps1` that's
idempotent, plus a Cargo build script that depends on
`python/overlays/**/*.py` and triggers the sync automatically. Until
then, this is a contributor-onboarding paragraph in `README.md`.

**Lesson**

> Any artefact the runtime loads from a *copy* of source is a
> debugging trap. Either symlink, or make the copy step automatic and
> visible (build-script noise > silent staleness).

---

## Appendix: diagnostic one-liners

Quick checks worth running before opening an issue.

```powershell
# 1. Is the user behind a system proxy that could capture loopback?
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
    Select-Object ProxyEnable, ProxyServer, ProxyOverride

# 2. Is anything else holding the Vite dev port?
Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue

# 3. Is the bridge actually accepting?
#    Look in the Tauri log for: "bridge accepted conn from 127.0.0.1:..."
Select-String -Path .tauri-dev.log -Pattern "bridge accepted|bridge req"

# 4. Did Hermes' SPA build land where mount_spa() expects?
Test-Path D:\project\hermesdesk\hermes\hermes_cli\web_dist\index.html

# 5. Probe Hermes directly (bypass Tauri to isolate UI vs API issues)
$port = (Select-String -Path .tauri-dev.log -Pattern "loading http://127.0.0.1:(\d+)").Matches.Groups[1].Value
Invoke-WebRequest "http://127.0.0.1:$port/api/status" -UseBasicParsing -Proxy $null
```

If `#1` shows `ProxyEnable=1` and `#3` shows the bridge serve loop
started but never accepted, **9 times out of 10 it's #1 from this doc**.
