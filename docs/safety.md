# Safety model

HermesDesk's "safe by default" promise rests on five concentric layers, each
defended in a different language. A bug in any single layer should not be
sufficient to compromise the user's machine.

```
     +----------------------------------------------+
     |  L5  Onboarding defaults (UI nudges)         |  React
     |  L4  Per-tool gates (Power-user toggle)      |  Python overlay
     |  L3  Network egress allowlist                |  Python overlay
     |  L2  Workspace folder jail                   |  Python overlay
     |  L1  OS sandbox (cap allowlist, no admin)    |  Tauri capabilities + Windows ACLs
     +----------------------------------------------+
```

## L1 — OS / Tauri capabilities

- Per-user install under `%LOCALAPPDATA%\HermesDesk`. **No admin elevation
  is ever requested.** Anything Hermes can break, the user's normal
  privileges can already break.
- The Tauri WebView has a tight CSP (`tauri.conf.json#app.security.csp`)
  and an explicit capability allowlist
  ([tauri/capabilities/default.json](../tauri/capabilities/default.json)).
- The bundled Python binary is a stock CPython from `python-build-standalone`
  with no special privileges.
- Loopback-only HTTP between Tauri and Python; ports are random per-launch.

## L2 — Workspace folder jail

Implemented by [`python/overlays/workspace_jail.py`](../python/overlays/workspace_jail.py).
Wraps `builtins.open`, `os.{remove,rename,replace,mkdir,...}`, and
`shutil.{copy,copy2,move,rmtree}`. Every path is resolved with
`os.path.realpath` (so symlink escapes are caught) and rejected unless it
canonicalises under one of:

- `HERMESDESK_WORKSPACE` — the user's workspace folder (default
  `Documents/HermesWork`)
- `HERMESDESK_DATA_DIR` (writable; logs, sqlite caches)
- `%TEMP%` (writable; httpx caches, fal-client uploads)
- The bundle dir (read-only; bundled Python stdlib + site-packages)

The user can change the workspace folder, but it always remains a single
folder; multi-folder setups are an explicit Power-user-only feature.

## L3 — Network egress allowlist

Implemented by [`python/overlays/network_allowlist.py`](../python/overlays/network_allowlist.py).
Wraps `httpx.Client.send` (and async equivalent), plus `requests`'
`HTTPAdapter.send`. Every outbound URL is checked against an allowlist:

- `127.0.0.1` / `localhost` (Hermes' own loopback)
- The configured LLM provider host
- Skills hub: `agentskills.io`, `raw.githubusercontent.com`,
  `github.com`, `api.github.com`
- Edge TTS: `speech.platform.bing.com`

Any other host raises `PermissionError` with a message that points the
user at the Settings page where they can add an exception. Power-user mode
disables the allowlist (`HERMESDESK_NET_OPEN=1`).

## L4 — Per-tool gates

[`python/overlays/default_toolset.py`](../python/overlays/default_toolset.py)
forces the default Hermes toolset to the curated keep-list (see
`DECISIONS.md`). The dangerous tools — shell (`terminal_tool`),
`code_execution_tool`, browser automation, MCP servers, cron — are
**only registered** when `HERMESDESK_POWER_USER=1`.

When Power-user mode is on, those tools still go through the **shell
approval bridge**: every command is shown to the user in a native Windows
dialog before it runs. There is no "always allow" — every command is
re-confirmed.

## L5 — Onboarding defaults

The onboarding wizard never enables Power-user mode. It never presents the
user with security-relevant toggles. The Settings page has a single
"Power user" switch with a clear, plain-language warning and a link to
this document.

## Threat model — what we explicitly do NOT defend against

- A user who flips Power-user on, then approves a destructive command in
  the modal. We assume informed consent.
- A malicious skill the user installs from outside the official skill hub.
  Skills run as Python; they have the same privileges as Hermes itself.
  The skill hub has its own review process.
- A compromised LLM provider host. We don't pin certificates beyond the
  system trust store.
- Side-channel data exfiltration through the LLM (the LLM provider sees
  whatever Hermes sends them). Use a self-hosted endpoint if this matters.

## Reporting security issues

See [SECURITY.md](../SECURITY.md) (TBD).
