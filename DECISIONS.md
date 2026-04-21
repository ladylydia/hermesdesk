# Locked product decisions

This file freezes the choices that shape the rest of the codebase. Anything
not on this list is open for change. Anything on this list requires a PR with
explicit reasoning to alter.

## Identity

| Field          | Value                                                    |
|----------------|----------------------------------------------------------|
| Working name   | **HermesDesk**                                           |
| Bundle id      | `com.hermesdesk.app`                                     |
| Install target | Per-user, `%LOCALAPPDATA%\HermesDesk` (no admin needed)  |
| License        | MIT                                                      |
| Upstream       | git submodule -> `NousResearch/hermes-agent` pinned to a tag (currently `v0.10.0`) |
| Tagline        | "A friendly AI helper for your PC. No setup, no terminal." |

The "HermesDesk" name is provisional. Trademark check is pending — see
`docs/branding-todo.md` (not yet written).

## Distribution & signing

| Field          | Value                                                    |
|----------------|----------------------------------------------------------|
| Format         | Windows `.msi` produced by Tauri bundler                 |
| Architectures  | x86_64 only at v1. ARM64 deferred.                       |
| Min OS         | Windows 10 22H2 (1809+ for WebView2 evergreen)           |
| Signing cert   | OV cert (~$80/yr, e.g. SSL.com or Sectigo) for v1; reassess EV cert (~$300/yr, removes SmartScreen reputation wait) before public launch |
| Update channel | Tauri updater -> GitHub Releases (signed manifest)       |

**Code-signing budget locked:** $100/yr for OV cert + $0 for GitHub Releases
hosting. Total infra cost target = $100/yr until we hit 10k users.

## LLM access (zero-threshold path)

Decided in plan-mode Q&A: **BYO key with a guided wizard.** The wizard:

1. Defaults to **OpenRouter** as the recommended provider — biggest model
   selection, $5 minimum top-up, single key works across all models.
2. Offers a **Free starter** path: OpenRouter free-tier models
   (`*:free` model IDs, e.g. `google/gemini-2.0-flash-exp:free`,
   `meta-llama/llama-3.3-70b-instruct:free`). Rate-limited but $0.
3. Allows **manual provider entry** (Anthropic, OpenAI, Nous Portal, etc.)
   under "I have my own".

Hosted backend is **explicitly deferred** — re-open this decision if BYO
friction proves to block adoption (see plan risks).

## Initial Hermes tool keep-list

These tools are enabled by default for non-pros. Everything else is hidden
behind the "Power user" toggle, off by default.

| Tool module                              | Why we keep it                            |
|------------------------------------------|-------------------------------------------|
| `tools/file_operations.py`               | Read/write files in workspace             |
| `tools/file_tools.py`                    | Search/glob/list inside workspace         |
| `tools/web_tools.py` (search subset)     | Web search via Exa/Brave/etc.             |
| `tools/image_generation_tool.py`         | Image generation (fal/etc.)               |
| `tools/tts_tool.py` (Edge TTS only)      | Free text-to-speech, no API key           |
| `tools/transcription_tools.py`           | Voice memo transcription                  |
| `tools/memory_tool.py`                   | Persistent memory                         |
| `tools/skills_tool.py`                   | Skills system (core differentiator) — see [docs/skills-design-decision.md](docs/skills-design-decision.md) for tiering model |
| `run_builtin_helper` (HermesDesk overlay) | L1 only: whitelist dispatch to bundled `python/helpers/*` — see [docs/skills-security.md](docs/skills-security.md); **not** generic `code_execution` |
| `tools/todo_tool.py`                     | Lightweight todo list                     |
| `tools/vision_tools.py`                  | Image understanding                       |
| `tools/clarify_tool.py`                  | Ask clarifying questions                  |

**HermesDesk Skills — recipe market strip (v1):** Off by default. The shell **Settings** app stores `hermesdesk.show_recipe_market` and mirrors it to `hermesdesk_show_recipe_market.txt` under `%LOCALAPPDATA%\HermesDesk\` so the embedded web `/api/status` and **Skills** page can show a **UI-only** placeholder banner without restarting Python. No remote catalog in v1.

**Hidden behind "Power user" toggle (off by default):**

- `tools/terminal_tool.py` (shell)
- `tools/code_execution_tool.py`
- `tools/browser_tool.py`, `tools/browser_camofox.py`
- `tools/mcp_tool.py`, MCP OAuth
- `tools/cronjob_tools.py`
- `tools/delegate_tool.py` (subagent spawning)
- `tools/mixture_of_agents_tool.py`
- `tools/rl_training_tool.py`
- `tools/send_message_tool.py` (multi-platform)
- `tools/feishu_*`, `tools/homeassistant_tool.py`

**Not shipped at all (out of scope for desktop):**

- `rl_cli.py`, `tinker-atropos/`
- `batch_runner.py`, `mini_swe_runner.py`
- `trajectory_compressor.py`
- `gateway/` (entire directory)
- `acp_adapter/`, `acp_registry/`
- `mcp_serve.py` (we host MCP clients only, not a server)
- All cloud terminal backends (Modal, Daytona, Singularity, SSH)

## Personality presets shipped at v1

The "Pick a vibe" onboarding step picks one of:

- **Helpful** (default) — neutral, clear, gets things done
- **Friendly** — warmer, more conversational
- **Concise** — short answers, no fluff

These map to existing Hermes personality files. Custom personalities are an
"Advanced" feature.

## Safety defaults

See [docs/safety.md](docs/safety.md). Highlights:

- Workspace folder: `%USERPROFILE%\Documents\HermesWork` (created on first
  launch). Single jail; the user can change it in Settings, but it always
  stays a single folder.
- Shell approval: **deny by default**, prompt every time, no "always allow".
- Network egress allowlist: LLM provider host + a small fixed allowlist
  (`*.agentskills.io` for the skills hub, `speech.platform.bing.com` for
  Edge TTS).
- Telemetry: **off by default**, opt-in only, anonymized.

## Skills exposure model

Replaces the original "Skills hidden behind Power-user toggle" plan.
Skills are tiered by *action* (use / install / author), not by user.
Default users get a curated set of built-in "Quick Actions" surfaced
on the chat screen; advanced mode unlocks an officially signed Skill
market; power-user mode unlocks unsigned third-party install and a
YAML editor. Full reasoning, security model, and implementation plan
in [docs/skills-design-decision.md](docs/skills-design-decision.md).

## Out of scope for v1

- Linux / macOS builds
- ARM64 Windows
- Multi-user / per-machine install
- Hosted backend
- Mobile (Telegram bridge etc.)
- Third-party (unsigned) Skill marketplace — v1.0 ships only built-in
  Recipes; signed market is v1.1, unsigned third-party is v1.2
- Voice-first / always-listening mode (push-to-talk only)
