# HermesDesk

A friendly Windows desktop AI assistant for non-technical users. Powered by
the open-source [Hermes Agent](https://github.com/NousResearch/hermes-agent).

> Status: scaffolding / pre-alpha. Not yet usable. See
> [docs/architecture.md](docs/architecture.md) and the project plan for the
> roadmap.

## What this is

- A double-click `.msi` installer for Windows 10/11
- A native-feeling chat window (not a terminal, not a browser tab)
- A 2-minute onboarding wizard with no jargon
- Safe by default: the AI runs in a sandboxed workspace folder and asks
  permission before doing anything risky
- A pruned, non-technical subset of Hermes Agent's capabilities

## What this is NOT

- A power-user CLI. If you want the full Hermes feature surface (RL training,
  multi-platform messaging gateway, cron jobs, MCP servers, multiple terminal
  backends), use upstream [Hermes Agent](https://github.com/NousResearch/hermes-agent).
- A hosted service. You bring your own LLM provider key (the wizard helps).

## Architecture in one picture

```
+----------------------------------+
|  Tauri 2 shell (Rust + WebView2) |   <- one .exe, ~15 MB
|  - owns the window               |
|  - owns the system tray          |
|  - owns API key (DPAPI vault)    |
|  - approves shell commands       |
+--------------+-------------------+
               |
               | spawns + supervises
               v
+----------------------------------+
|  Embedded Python 3.11             |   <- bundled, ~80 MB
|  Hermes Agent (stripped)          |
|  serves localhost:RANDOM          |
+--------------+-------------------+
               |
               | HTTP + WebSocket
               v
+----------------------------------+
|  React UI (web/)                  |   <- chat + onboarding
|  loaded into WebView2             |
+----------------------------------+
```

See [docs/architecture.md](docs/architecture.md) for the full picture.

## Building from source

You need: Rust 1.80+, Node 20+, PowerShell 7+, Python 3.11.

```powershell
git clone --recursive https://github.com/your-org/hermesdesk.git
cd hermesdesk

# Build the Python bundle (downloads python-build-standalone)
.\python\build_bundle.ps1

# Build the web UI
cd web; npm ci; npm run build; cd ..

# Build and run the Tauri shell in dev mode
cd tauri; cargo tauri dev
```

To produce the signed installer, see [docs/code-signing.md](docs/code-signing.md).

If something doesn't work — especially first-launch hangs, blank window,
or `bridge accepted` never appearing in logs — read
[docs/troubleshooting.md](docs/troubleshooting.md) **first**. It covers
every non-obvious failure mode we hit while bringing this up on Windows
(VPN/proxy interception of loopback, Tauri single-thread runtime
starvation, upstream API drift, etc.) with the exact symptom → cause →
fix mapping.

## Layout

```
hermesdesk/
  tauri/        Rust + Tauri 2 shell (the .exe)
  python/       Build scripts for the embedded Python bundle
  web/          Onboarding wizard + UI overlays (Hermes web/ is reused)
  patches/      Small patches we apply on top of upstream Hermes
  installer/    WiX / Tauri bundler config
  docs/         Architecture, safety, onboarding, QA docs
  scripts/      Audit + dev helper scripts
  hermes/       git submodule -> NousResearch/hermes-agent
```

## License

MIT. See [LICENSE](LICENSE).

This project bundles and patches Hermes Agent (also MIT). All credit for the
underlying agent loop, skills system, and tools belongs to
[Nous Research](https://nousresearch.com).
