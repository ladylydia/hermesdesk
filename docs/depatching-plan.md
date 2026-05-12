# De-patching migration plan

Product direction change: **product independent, upstream code frozen, security/provider layer selective cherry-pick**.

## Current state

Product behavior is scattered across three mechanisms:

| Mechanism | Location | Problem |
|-----------|----------|---------|
| Dirty submodule | `hermes/` (gateway files + `hermes_cli/` + everything) | "Shipped behavior" is invisible in the owning repo |
| Patches | `patches/Kabuqina-changes.patch` | Applied *at build time* — not tested until bundle rebuild |
| Overlays | `python/overlays/*.py` (9 monkey-patches) | Applied at import time; easy to break with upstream import order changes |

## Target state

```
Kabuqina monorepo/
├── hermes_core/          ← frozen upstream snapshot, owned code
│   ├── gateway/            ← gateway patches baked in as normal commits
│   └── hermes_cli/         ← desk-specific web/API changes baked in as normal commits
├── python/
│   ├── src/policies/       ← 6 policy interfaces (Phase 3)
│   │   ├── path_policy.py
│   │   ├── network_policy.py
│   │   ├── secret_store.py
│   │   ├── tool_policy.py
│   │   ├── approval_backend.py
│   │   └── gateway_policy.py
│   ├── src/desktop_config.py     ← typed bootstrap config (Phase 2)
│   ├── src/desktop_contract.py   ← versioned Tauri↔Python contract (Phase 2)
│   └── overlays/           ← compat shims, removed per-phase (Phase 4)
├── docs/
└── scripts/                ← sync_upstream.ps1 deleted
```

## Key decisions

| Question | Decision |
|----------|----------|
| Directory name | `hermes_core/` |
| Migration style | Stepwise (not all-at-once) |
| Gateway platforms | All 6 stay in onboarding. WeChat + Feishu gated by feature flag at the `GatewayPolicy` level |
| Cherry-pick | Manual only (no automated sync) |
| Overlay migration order | Path → Secret/Approval → Network → Toolset → Gateway |

---

## Phase 0 — Inventory freeze

Completed **2026-05-03**. Canonical inventory of every shipped Kabuqina behavior before the de-patching migration.

### 0.1 Submodule baseline

| Field | Value |
|-------|-------|
| Submodule path | `hermes/` |
| Submodule URL | `D:/project/hermes-agent` (local clone) |
| Parent-recorded commit | `90b304b7c1a1d52a89f80d3fb296e2b299cd42e8` |
| Upstream tag | `v2026.4.23-1131-g90b304b7c` |
| Branch | `main` (ahead of `origin/main` by 5 commits) |

### 0.2 Dirty-file inventory

**Three-way comparison: patch file vs dirty submodule vs runtime bundle**

```
                    patch file          dirty submodule        runtime bundle
                    (9 files)           (118 files gw+cli)     (matches dirty)
                          \                 /                       |
                           \               /                        |
                            \             /                         |
                             \           /                          |
                              \         /                           |
                               \       /                            |
                                \     /                             |
                                 \   /                              |
                              9 matching files ────────────────── identical
                              (security patches)
```

| Inventory | Files | Scope |
|-----------|-------|-------|
| Patch file | 9 files (1 now absorbed by upstream — `pty_bridge.py`) | Security hardening |
| Dirty submodule (gateway + hermes_cli) | 118 → 8 files (after Phase 0.6 reset) | Down from full upstream drift to canonical Kabuqina-only diff |
| Dirty submodule (total) | 2765 → 8 files (after Phase 0.6 reset) | Only Kabuqina-owned changes remain |
| Runtime bundle vs dirty source | 0 files differ | Both contain the same code |

**Finding after Phase 0.6 cleanup:** The dirty submodule was reset to the pinned commit and the 9 patch files re-applied. `hermes_cli/pty_bridge.py` produced a zero-diff against HEAD (newer upstream already contains the change). The canonical state is **8 files**.

### 0.3 Patch-file detail

File: `patches/Kabuqina-changes.patch` (3227 lines). 8 of 9 files produce a diff against HEAD.

| # | File | Δ (+/-) | Behavior |
|---|------|---------|----------|
| 1 | `gateway/config.py` | +1/-1 | `thread_sessions_per_user: False → True` (safe default) |
| 2 | `gateway/platforms/dingtalk.py` | +1/-1 | `DINGTALK_REQUIRE_MENTION: false → true` (safe default) |
| 3 | `gateway/platforms/feishu.py` | +17/-0 | Webhook security warning (logs when ENCRYPT_KEY/VERIFICATION_TOKEN missing) |
| 4 | `gateway/platforms/telegram.py` | +1/-1 | `telegram_require_mention` config for group @mention gating |
| 5 | `gateway/platforms/webhook.py` | +21/-0 | Webhook verification token config |
| 6 | `gateway/platforms/whatsapp.py` | +1/-1 | `whatsapp_require_mention` config |
| 7 | `gateway/run.py` | +20/-0 | First-connect survival (retry failed platforms with backoff) |
| 8 | `hermes_cli/pty_bridge.py` | — | **Absorbed by upstream** — zero diff; Kabuqina PTY needs met by upstream |
| 9 | `hermes_cli/web_server.py` | +437/-6 | Desk-specific auth + `/shell-chat` endpoint + session token bridge |

**Total:** 498 insertions, 11 deletions across 8 files.

### 0.4 Bundle-specific drift

The runtime bundle (`python/dist/runtime/`) was built from commit `9a1454060` (`v2026.4.23-1126-g9a1454060`), which is **5 commits behind** the parent-recorded submodule commit and **2765 commits behind** the dirty working tree. The source and runtime files are identical because `build_bundle.ps1` copies from the working tree (which includes the dirty version drift).

**No bundle-only drift exists** — the runtime is a snapshot of the same dirty working tree. This is expected because `build_bundle.ps1` copies files from disk, not from git.

### 0.5 Retained-behavior checklist

Every Kabuqina-specific behavior, where it currently lives, and what must happen to it:

| Behavior | Current mechanism | Phase 1-3 action |
|----------|------------------|-------------------|
| Gateway thread session isolation (safe default) | Patch: `gateway/config.py` | Bake into `hermes_core/` as committed change |
| DingTalk require @mention (safe default) | Patch: `gateway/platforms/dingtalk.py` | Bake into `hermes_core/`; also fold into `GatewayPolicy` |
| Feishu webhook security warning | Patch: `gateway/platforms/feishu.py` | Bake into `hermes_core/`; also fold into `GatewayPolicy` |
| Telegram require mention (new feature) | Patch: `gateway/platforms/telegram.py` | Bake into `hermes_core/`; also fold into `GatewayPolicy` |
| Webhook verification token | Patch: `gateway/platforms/webhook.py` | Bake into `hermes_core/` |
| WhatsApp require mention (new feature) | Patch: `gateway/platforms/whatsapp.py` | Bake into `hermes_core/` |
| Gateway first-connect survival | Patch: `gateway/run.py` | Bake into `hermes_core/` |
| Dashboard PTY bridge | Patch: `hermes_cli/pty_bridge.py` | **Already absorbed** — zero diff vs HEAD; upstream now provides this |
| Desk auth + shell-chat endpoint | Patch: `hermes_cli/web_server.py` | Bake into `hermes_core/` |
| Workspace file jail | Overlay: `workspace_jail.py` | Migrate to `PathPolicy` (Phase 3A) |
| Path guard (gateway context) | Overlay: `path_guard.py` | Migrate to `PathPolicy` (Phase 3A) |
| Secret handshake from Tauri | Overlay: `secret_loader.py` | Migrate to `SecretStore` (Phase 3B) |
| Shell approval dialog | Overlay: `approval_bridge.py` | Migrate to `ApprovalBackend` (Phase 3B) |
| Desk system-prompt injection | Overlay: `desk_system_prompt.py` | Migrate to `DesktopConfig` (Phase 3B) |
| Network egress allowlist | Overlay: `network_allowlist.py` | Migrate to `NetworkPolicy` (Phase 3C) |
| Desktop LLM config | Overlay: `desktop_llm_config.py` | Migrate to `DesktopConfig` (Phase 3C) |
| Default toolset (keep-list) | Overlay: `default_toolset.py` | Migrate to `ToolPolicy` (Phase 3D) |
| L1 QuickActions | Overlay: `builtin_helpers.py` | Migrate to `ToolPolicy` (Phase 3D) |
| Gateway import stubs | Overlay: `strip_shims.py` | Replace with `GatewayPolicy` (Phase 3E) |
| Windows process-group safety | Overlay: `windows_safety.py` | Inline into entrypoint (Phase 3E) |
| Power-user toggle → restart child | Rust: `cmd_set_power_user` | Keep; narrow Tauri↔Python contract (Phase 2) |
| API key: DPAPI vault → loopback | Rust+Overlay: `secrets.rs` + `secret_loader.py` | Consolidate into `SecretStore` (Phase 3B) |

### 0.6 Completed state

Phase 0.6 executed **2026-05-03**:

```powershell
git -C hermes checkout HEAD -- .                     # reset to pinned commit
git -C hermes apply --3way ../patches/Kabuqina-changes.patch  # apply patches
# 1 conflict in gateway/run.py resolved manually (keep-theirs)
git -C hermes add gateway/run.py                     # mark resolved
```

Final canonical state: **8 files dirty** (498+ / 11-). `pty_bridge.py` absorbed by upstream.

This is the canonical Kabuqina source diff that Phase 1 should import.

---

## Phase 1 — Import frozen snapshot (stepwise)

| Step | Action | Impact |
|------|--------|--------|
| 1.1 | Import the clean upstream base commit as `hermes_core/` | Imports frozen Hermes as owned directory with history |
| 1.2 | Apply the canonical Kabuqina diff (9 patched files) as normal commits on `hermes_core/` | Gateway security defaults and desk-specific `hermes_cli` changes become permanent owned code |
| 1.3 | Update `build_bundle.ps1`: source path `hermes/`→`hermes_core/`, remove `git apply` block, update BUNDLE_INFO | Stale bundle trap eliminated — code is what's in the tree |
| 1.4 | `git rm hermes/`, remove `.gitmodules` | Terminates submodule relationship |
| 1.5 | Delete `patches/`, `scripts/sync_upstream.ps1`, `SYNC_UPSTREAM.md` | No more patch-based workflow |
| 1.6 | Update CI `release.yml`: remove `submodules: recursive` | CI no longer fetches upstream |
| 1.7 | `.\python\build_bundle.ps1 -Verify` + `cargo tauri dev` | Full-stack smoke test |

## Phase 2 — Bootstrap/config contract (no behavior change)

| File | Purpose |
|------|---------|
| `python/src/desktop_config.py` | Dataclasses: `RuntimeMode(Enum)`, `PathPolicy`, `NetworkPolicy`, `SecretStore`, `ToolPolicy`, `ApprovalBackend`, `GatewayPolicy`. Reads from env vars. |
| `python/src/desktop_contract.py` | `CONTRACT_VERSION = 1`. JSON schemas for `/api/health`, `/api/config`, `/api/status`. |
| `python/src/desktop_entrypoint.py` | Build `DesktopConfig` from env vars, validate `HERMESDESK_CONTRACT_VERSION`, pass config to overlay init points. |
| `tauri/src/python_supervisor.rs` | Set `HERMESDESK_CONTRACT_VERSION=1` when spawning child. |

## Phase 3 — Overlay migration (by policy domain)

Batched by policy domain, applied in this order:

### Batch A: Path policies

| File | Action |
|------|--------|
| `python/src/policies/path_policy.py` | **New** — `PathPolicy` class: `enforce(path)` resolves with `realpath`, checks workspace/data/temp/bundle allowlist. |
| `python/overlays/workspace_jail.py` | Rewrite as thin wrapper calling `PathPolicy.enforce()`. Tag: `# DEPRECATED remove_when=Phase4`. |
| `python/overlays/path_guard.py` | Same treatment as `workspace_jail.py`. |

### Batch B: Secret + Approval

| File | Action |
|------|--------|
| `python/src/policies/secret_store.py` | **New** — `SecretStore.fetch()`: loopback handshake (`ProxyHandler({})`, HMAC URL, provider→env mapping). |
| `python/src/policies/approval_backend.py` | **New** — `ApprovalBackend.ask(cmd)` → POST to loopback approval URL. |
| `python/overlays/secret_loader.py` | Wraps `SecretStore.fetch()`. |
| `python/overlays/approval_bridge.py` | Wraps `ApprovalBackend.ask()`. |
| `python/overlays/desk_system_prompt.py` | Wraps system-prompt injection config. |

### Batch C: Network policies

| File | Action |
|------|--------|
| `python/src/policies/network_policy.py` | **New** — `NetworkPolicy.allow(host)` wraps `httpx.Client.send`. |
| `python/overlays/network_allowlist.py` | Wraps `NetworkPolicy`. |
| `python/overlays/desktop_llm_config.py` | Content merged into `DesktopConfig`, overlay deleted. |

### Batch D: Tool policies

| File | Action |
|------|--------|
| `python/src/policies/tool_policy.py` | **New** — `ToolPolicy.resolve(modes)` maps `RuntimeMode` to toolset list. L1 QuickActions registry. |
| `python/overlays/default_toolset.py` | Wraps `ToolPolicy.resolve()`. |
| `python/overlays/builtin_helpers.py` | QuickActions dispatch wrapped in `ToolPolicy`. |

### Batch E: Gateway policies

| File | Action |
|------|--------|
| `python/src/policies/gateway_policy.py` | **New** — `GatewayPolicy`: `platforms: dict`, `weixin_enabled: bool`, `feishu_enabled: bool`, `PlatformConfig` per adapter (mention rules, webhook verify, owner default). |
| `python/overlays/strip_shims.py` | Replaced: web child never loads real gateway, gated by `GatewayPolicy`. |
| `python/overlays/windows_safety.py` | Inlined into `desktop_entrypoint.py`, overlay deleted. |

## Phase 4 — Remove shims, add CI gates

| Step | Action |
|------|--------|
| 4.1 | Delete each overlay per phase-3 batch once its policy replacement passes tests. |
| 4.2 | `python/tests/test_bootstrap_modes.py` — verify `chat-only`, `power-user`, `gateway-enabled` all start clean. |
| 4.3 | `python/tests/test_policy_contract.py` — policy injection fail-closed on missing config. |
| 4.4 | CI drift check: forbid `git apply` anywhere in build scripts. |

## Phase 5 — Documentation sync

| File | Change |
|------|--------|
| `AGENTS.md` | Replace "Submodule & patches" / "Overlays" sections with "Upstream intake policy" + policy layer architecture. |
| `DECISIONS.md` | Add de-patching decision entry: product independence, cherry-pick policy, feature flags. |
| `docs/architecture.md` | Update to `agent_core` + `desktop_policy` two-layer diagram. |
| `README.md` | Remove submodule init from build steps; update build commands. |

## Upstream cherry-pick policy

```
Trigger:       security advisory, CVE, provider API breaking change
Source:        upstream-intake mirror (separate branch, not daily development)
Process:       git cherry-pick <upstream-commit> → resolve → commit
Commit msg:    "chore: cherry-pick <hash> <subject>"
Log:           maintained in DECISIONS.md
Rule:          No automated sync. No batch merges. Every cherry-pick is deliberate.
```

Gateway cherry-picks additionally require updating `hermes_core/gateway/platforms/` entries plus the corresponding `GatewayPolicy` default if platform behavior changed.

## Gateway feature flags

All 6 platforms remain in the onboarding UI. Two are feature-gated at the `GatewayPolicy` level:

```
WEIXIN_ENABLED   = true   (product can disable if unstable)
FEISHU_ENABLED   = true   (product can disable if unstable)
```

When a platform is disabled:
- Its onboarding QR/token flow still works
- The gateway process skips connecting that adapter
- The Settings UI shows the platform as "disabled by system policy"

## Acceptance criteria

- [ ] Phase 0 inventory exists and identifies the winning behavior for patch-file, dirty-tree, and runtime drift
- [ ] No dirty submodule — `hermes_core/` is a regular directory
- [ ] No `patches/` directory — all patches are normal commits
- [ ] No `.gitmodules` entry and no gitlink entry named `hermes`
- [ ] No overlay depends on import-order side effects
- [ ] Each policy has a `fail-closed` test (missing config = startup abort)
- [ ] `build_bundle.ps1` contains no `git apply`, no `-C hermes`
- [ ] `DECISIONS.md` upstream cherry-pick log is non-empty (at minimum: initial freeze commit)
- [ ] CI check: build scripts, docs, and workflows contain no required submodule or patch-application path
