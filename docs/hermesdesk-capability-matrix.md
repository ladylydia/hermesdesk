# HermesDesk capability matrix

This document describes **what the Windows HermesDesk shell actually allows** for the embedded Hermes Python runtime: toolsets, workspace jail, network policy, approvals, and quick actions. Use it for PRD and security review.

**Source of truth:** `tauri/src/python_supervisor.rs`, `python/overlays/*.py`, and `hermes/hermes_cli/web_server.py` (`_desk_chat_build_agent`). If this file disagrees with `docs/safety.md` on a detail, **prefer the code** or update both.

---

## 1. Where settings come from

| Item | Storage / injection | Notes |
|------|---------------------|--------|
| **Power user** | `settings.json` key `hermesdesk.power_user` (`"1"` / `"true"` = on) → child env **`HERMESDESK_POWER_USER=1` or `0`** | `tauri/src/paths.rs`, `tauri/src/python_supervisor.rs` |
| **Capability catalog role** | Derived in Python by `CapabilityPolicy`: default when power user off, advanced when recipe market discovery is on, power when `HERMESDESK_POWER_USER=1` | Used by `/api/hermesdesk/capabilities` before the shell renders Skills / tools / plugins |
| **Workspace folder** | Key `hermesdesk.workspace`; if unset, default **`%USERPROFILE%\Documents\KabuqinaWork`** → **`HERMESDESK_WORKSPACE`** | `paths::ensure_workspace` |
| **LLM (non-secret)** | `settings.json` → `provider` (e.g. `api_base_url`, `host`, `model`) → **`HERMESDESK_*`** env and overlay sync into `config.yaml` | `tauri/src/secrets.rs`, `python/overlays/desktop_llm_config.py` |
| **API key** | Windows Credential Manager / keyring — **not** in `config.yaml` | `python/overlays/secret_loader.py` (and related) |

---

## 2. Toolsets (`platform_toolsets["cli"]`)

**Implementation:** [`python/overlays/default_toolset.py`](../python/overlays/default_toolset.py)

The overlay seeds `config.yaml` so `platform_toolsets["cli"]` matches the table below (it overwrites when the current value **differs** from the desired set, so users can still adjust individual toolsets via the Settings UI in some flows).

| Mode | Enabled toolset **names** (strings) | Intent (from overlay comments) |
|------|-------------------------------------|----------------------------------|
| **Default** (`HERMESDESK_POWER_USER` ≠ `1`) | `web`, `file`, `vision`, `image_gen`, `tts`, `skills`, `todo` | “Safe” default: **no** shell, no generic code execution in the default list |
| **Power user** (`HERMESDESK_POWER_USER=1`) | All of the above **+** `browser`, `terminal`, `code_execution`, `moa` | Adds browser automation, terminal, code execution, MoA, etc. |

**Desk chat / local AI agent** uses the same platform key **`cli`**: `AIAgent` is built with `enabled_toolsets` from `_get_platform_tools(config, "cli")` in [`hermes/hermes_cli/web_server.py`](../hermes/hermes_cli/web_server.py) (`_desk_chat_build_agent`).

---

## 3. Workspace jail (L2)

**Implementation:** [`python/overlays/workspace_jail.py`](../python/overlays/workspace_jail.py)

| Behavior | Description |
|----------|-------------|
| **If `HERMESDESK_WORKSPACE` is unset** | Logs a warning and runs in a **permissive** mode (jail not enforced) — intended to avoid breaking tests or odd environments. |
| **If set** | Wraps `builtins.open`, `os.*`, `shutil.*`, etc. Reads/writes must resolve under an **allowed root** after `realpath`. |
| **Primary workspace root** | `HERMESDESK_WORKSPACE` (default `Documents\KabuqinaWork` when Tauri sets it from `ensure_workspace`). |
| **Extra writable roots** | `HERMESDESK_DATA_DIR`, `HERMES_HOME` (config/sessions), `%TEMP%` (caches, temp uploads). |
| **Extra read-only roots** | Includes `HERMESDESK_BUNDLE_DIR` and Python stdlib paths so imports and bundle reads work. |
| **Multi-folder workspaces** | `docs/safety.md` states multi-folder is **power-user-only**; enforcement is product-specific — the jail is “one primary workspace + extra roots as configured”. |

---

## 4. Network egress allowlist (L3)

**Implementation:** [`python/overlays/network_allowlist.py`](../python/overlays/network_allowlist.py)

| Item | Description |
|------|-------------|
| **Default** | Patches `httpx` and `requests`; each outbound URL must match an allowlist (always includes e.g. `localhost` / `127.0.0.1`, skills hub hosts, Edge TTS, **plus** hosts derived from **`HERMESDESK_LLM_HOST`** and optional **`HERMESDESK_EXTRA_HOSTS`**). |
| **Disable allowlist** | Set **`HERMESDESK_NET_OPEN=1`** — all checks are skipped. |
| **Power user vs `NET_OPEN`** | The module **comment** says power user turns off the allowlist. **`python_supervisor.rs` does not set `HERMESDESK_NET_OPEN` from the power-user toggle.** Treat “open network” as **only** when `HERMESDESK_NET_OPEN=1` is set by hand or by future code. Align `docs/safety.md` with implementation when you change this. |

---

## 5. Dangerous command approval (L4)

**Implementation:** [`python/overlays/approval_bridge.py`](../python/overlays/approval_bridge.py)

| Item | Description |
|------|-------------|
| **Mechanism** | Replaces Hermes’ `prompt_dangerous_approval` with a POST to **`HERMESDESK_APPROVAL_URL`**; Tauri shows a native **Allow / Deny** flow. |
| **Policy** | On allow, maps to a **one-shot** approval (`once`); no persistent “always allow” in v1. If the bridge is missing or errors, **deny**. |

Which tools trigger approval is defined upstream in Hermes (`tools/approval.py` and related), not in this repo’s overlays alone.

---

## 6. Builtin “quick actions” (L1 helpers)

**Implementation:** [`python/overlays/builtin_helpers.py`](../python/overlays/builtin_helpers.py), HTTP entry [`POST /api/hermesdesk/builtin-helper`](../hermes/hermes_cli/web_server.py) (when running in HermesDesk runtime).

| Item | Description |
|------|-------------|
| **Whitelist** | Only: `folder_organize`, `excel_to_word`, `pdf_digest`, `image_batch` (via `run_builtin_helper`). |
| **Not** | Arbitrary user code, arbitrary imports, or runtime download — helpers are **signed/bundled** under `python/helpers/`. |

---

## 7. Chat UI vs agent capabilities

- A **ChatGPT-style single page** is **UI only**; what the model can do is still bounded by **`platform_toolsets["cli"]`**, workspace jail, network allowlist, and approval bridge.
- **Shell `/chat`** (`web/src/chat/`) talks to Hermes over loopback via Tauri **`invoke`** → [`tauri/src/chat.rs`](../tauri/src/chat.rs); capabilities match the same agent/toolset boundaries as the embedded dashboard desk chat.
- **Terminal `cwd` note:** `_desk_chat_build_agent` uses `HERMES_WORKSPACE` or `TERMINAL_CWD` for `register_task_env_overrides` when present; Tauri currently sets **`HERMESDESK_WORKSPACE`**. If terminal should default to the workspace folder, align env var names in a follow-up.

---

## 8. Desktop capability catalog

**Implementation:** Python policy [`python/src/capability_policy.py`](../python/src/capability_policy.py), Hermes API `GET /api/hermesdesk/capabilities`, Tauri IPC proxy, and shell page under `web/src/advanced/pages/CapabilitiesPage.tsx`.

| Area | Behavior |
|------|----------|
| **Skills** | Visible entries are filtered server-side. Details include content, linked files, source/trust/risk labels, and whether agent-assisted editing is available. |
| **Tools/toolsets** | Users can browse enabled and locked toolsets. Power-user-only tools are labelled locked outside `power`; the UI does not directly mutate tool implementation. |
| **Plugins** | Dashboard plugin manifests are browsed through the same policy. Default users do not see advanced/plugin entries unless policy metadata makes them visible. |
| **Writes** | Editing Skills or installing recommended Skills/tools/plugins starts a chat draft for the agent. The write boundary remains `skill_manage`, hub install, plugin tooling, and approval prompts. |

---

## 9. Messaging gateway (second Python process)

**Implementation:** [`tauri/src/gateway_supervisor.rs`](../tauri/src/gateway_supervisor.rs), Hermes upstream [`hermes/gateway/run.py`](../hermes/gateway/run.py).

| Item | Description |
|------|-------------|
| **Lifecycle** | Tauri supervises **`python.exe -m gateway.run`** when **`hermes-home/.env`** contains messaging credentials (manual Start/Stop + optional cold-start auto-start). Distinct from **`desktop_entrypoint.py`** (Hermes web). |
| **`strip_shims` boundary** | The **web child** stubs `gateway.run.main` so the dashboard never hosts the gateway entrypoint; the **gateway child** loads the real module. See [`strip_shims.py`](../python/overlays/strip_shims.py), [`architecture.md`](architecture.md). |
| **Desk UX** | Onboarding / Settings blocks + **`cmd_gateway_*`**; QR/token flows in [`web/src/advanced/Settings.tsx`](../web/src/advanced/Settings.tsx). Channels shipped in Desk: **Weixin**, **QQ Bot**, **Feishu/Lark**, **Telegram** (token). |
| **LLM for bots** | Gateway reuse **`secret_loader`** / Credential Manager injection — same provider key as shell chat. |

---

## Related docs

- [safety.md](./safety.md) — layered threat model and onboarding defaults.
- [gateway-desk-weixin-strategy.md](./gateway-desk-weixin-strategy.md) — route C product notes and channel index.
- [troubleshooting.md](./troubleshooting.md) §12–§16 — gateway startup, PYTHONPATH, WinError 87.
- [Overlays `__init__.py`](../python/overlays/__init__.py) — load order of patches (must run before Hermes imports).
