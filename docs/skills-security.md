# Skills, recipes, and L1 helper security

This document is the public-facing trust story for anything we call a
**Skill**, **Recipe**, or **built-in helper** in HermesDesk. It expands the
“Security model” section of
[skills-design-decision.md](skills-design-decision.md) (ADR, accepted).

## Layers HermesDesk already had

These are unchanged; Skills and helpers must coexist with them:

1. **Workspace jail** (`python/overlays/workspace_jail.py`) — file I/O is
   confined to the user’s workspace (plus a small set of writable system
   paths documented in [safety.md](safety.md)).
2. **Network allowlist** — outbound HTTP is restricted unless the user is in
   power-user “open network” mode.
3. **Approval bridge** — risky *shell* commands are confirmed in the Tauri
   shell; this does **not** gate individual Skill steps today.

## The problem we are solving

A general **Skills marketplace** combined with a full **code_execution** tool
would be a bypass: a Skill could ask the model to paste secrets into prompts,
or stage files for exfiltration. Our target users are not expected to audit
Python.

So we **do not** expose arbitrary code execution for L1 “use” tier features.

## Quick Actions UI (HermesDesk)

When the dashboard is served from an embedded HermesDesk runtime, the web
shell injects `window.__HERMESDESK__` and shows a **Recipes / 快捷指令** strip
above the page content. Buttons call `POST /api/hermesdesk/builtin-helper`,
which dispatches to `run_builtin_helper` on the server (same whitelist as
above). The route returns **404** on plain Hermes installs so upstream
dashboards are unchanged. It is also **rate-limited** (burst cap per minute)
in addition to the session token, to blunt accidental tight loops in the UI
or a compromised tab hammering the endpoint.

## L1 — Whitelist helpers (`run_builtin_helper`)

**L1 “使用”** is implemented as a **single** Hermes tool,
`run_builtin_helper(name, args)`, registered from
`python/overlays/builtin_helpers.py`.

Properties:

| Property | Guarantee |
|----------|-----------|
| Callable surface | Only the string ids in an in-process frozenset (`folder_organize`, `excel_to_word`, `pdf_digest`, `image_batch`). Unknown names are rejected before dispatch. |
| HTTP abuse | `POST /api/hermesdesk/builtin-helper` requires the ephemeral dashboard token **and** a per-process sliding-window rate limit (returns HTTP 429 when exceeded). |
| Code provenance | Helper modules live under `python/helpers/` in this repo. They ship inside the installer/bundle next to the embedded runtime — **not** downloaded at runtime and **not** chosen by the LLM. |
| Review | Same bar as product code: PR + review; optional release signing is a separate v1.1 track for *market* Skills, not for these builtins. |
| vs `code_execution` | The generic `code_execution` tool remains **off** for default users (`default_toolset.py`). Helpers do not spawn the code-execution sandbox and do not `eval` model-supplied source. |

The LLM supplies **JSON args** only; helpers are normal Python functions with
bounded signatures. They still run **as the user** inside the workspace jail
— mistakes can move or resize real files, so UX copy must warn before
destructive actions.

### Current helpers (v1)

| Id | Purpose | Notes |
|----|---------|--------|
| `folder_organize` | Move loose files in one folder into `images/`, `documents/`, `data/`, `archives/`, or `other/` by extension | Skips dotfiles; refuses paths outside workspace; supports `dry_run` |
| `excel_to_word` | First sheet of `.xlsx` / `.xlsm` → simple `.docx` (rows as paragraphs) | Needs `openpyxl` + `python-docx` in the desktop bundle |
| `pdf_digest` | Text excerpt from PDFs in one workspace folder (non-recursive, capped) | Needs `pypdf` in the bundle |
| `image_batch` | `action: info` counts images; `thumbnail` writes `_thumbs/` JPEGs | Needs **Pillow** in the bundle; otherwise returns a clear skip |

## L2 / L3 (roadmap, not v1 behaviour)

- **L2** — Signed Skills from an official market; install-time permission
  sheet from declarative manifest (see ADR table).
- **L3** — Power-user only: unsigned Skills, editors, and dangerous tools
  (`terminal`, `code_execution`, `browser`) per existing HermesDesk policy.

## Reporting issues

If a built-in helper behaves incorrectly or unsafely, treat it as a **product
security bug**: file an issue with reproduction steps and the helper id. We
can ship a fixed helper in the next bundle without changing the Hermes
upstream submodule.
