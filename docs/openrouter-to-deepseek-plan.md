# OpenRouter → DeepSeek Default Provider Migration Plan

> Companion to `docs/smoke-test-hard-isolation.md`. This document tracks the
> replacement of OpenRouter as the upstream default LLM provider with DeepSeek.

## Background

Upstream Hermes (`hermes_core/`) hardcodes OpenRouter in ~18 files across
four categories. The data is from a comprehensive grep conducted 2026-05-05.
There are two independent tracks:

| Track | Scope | Goal |
|-------|-------|------|
| **Layer 1** (DONE) | Block OpenRouter in gateway children | Bot never tries upstream defaults |
| **Layer 2** (in progress) | Replace OpenRouter default → DeepSeek | CLI/TUI/setup, Kabuqina shell, and **empty-settings** fallbacks default to DeepSeek; runtime auxiliary chain follows separately |

**Layer 2 status (2026-05-12):** **Narrative / examples / desktop fallback** rows are done or updated. **Auxiliary chain, credential seed order, trajectory compressor defaults, and `run_agent` docstring** remain deferred until an explicit vision/aux policy (see Runtime section below).

## Layer 1 — Gateway Child OpenRouter Block (DONE 2026-05-05)

| File | Change | Status |
|------|--------|--------|
| `agent/model_metadata.py:531` | `fetch_model_metadata()`: `if HERMESDESK_GATEWAY_PLATFORM: return {}` | Done |
| `agent/auxiliary_client.py:1545` | `_get_provider_chain()`: `if HERMESDESK_GATEWAY_PLATFORM: return []` | Done |

These two gates prevent gateway children from:
1. Fetching model metadata from `openrouter.ai/api/v1/models` (10 s timeout)
2. Falling back to OpenRouter/Nous/API-key providers in the auxiliary chain

Gateway children use only the user's configured provider from `config.yaml`.

## Layer 2 — Replace OpenRouter → DeepSeek as Default

### Constants and UI

| # | File | Line | Current | Target | Status |
|---|------|------|---------|--------|--------|
| 1 | `hermes_core/hermes_constants.py` | — | `OPENROUTER_BASE_URL` only | Add `DEEPSEEK_BASE_URL`, keep both | **Done** (`DEEPSEEK_BASE_URL`) |
| 2 | `hermes_core/hermes_cli/config.py` | ~647 | Comment mentions openrouter as fallback | Config-driven / points to `auxiliary.*` + chain | **Done** |
| 3 | `hermes_core/.env.example` | — | First section is OpenRouter setup | DeepSeek first; OpenRouter secondary | **Done** |
| 4 | `hermes_core/hermes_cli/web_server.py` | ~2693 | Example JSON `openrouter` | `deepseek` + `deepseek-v4-flash` | **Done** |
| 5 | `hermes_core/hermes_cli/setup.py` | ~937-943 | Vision setup defaults to OpenRouter first | DeepSeek-first copy; vision fallback documented | **Done** |
| 6 | `hermes_core/hermes_cli/setup.py` | ~191 | `OPENROUTER_API_KEY` hint | `DEEPSEEK_API_KEY` / neutral | **Done** |
| 7 | `hermes_core/run_agent.py` | ~13697-13699 | Docstring defaults openrouter | DeepSeek-oriented defaults | **Deferred** |
| — | `web/src/locales/strings.ts`, `optionData.ts`, `lib/providers.ts` | — | OpenRouter-first copy | DeepSeek-first / optional OpenRouter | **Done** (Kabuqina web) |
| — | `tauri/src/secrets.rs` | — | Empty-settings default `openrouter` | Default `deepseek` + `api.deepseek.com` | **Done** (Tauri) |
| — | `hermes_core/hermes_cli/auth.py` | — | `resolve_provider` docstring | Neutral OpenAI-compatible wording | **Done** |
| — | `docs/onboarding.md`, `docs/qa-checklist.md`, test docs | — | OpenRouter as primary story | DeepSeek-first | **Done** |

### Runtime — Auxiliary Client

| # | File | Line | Current | Target | Status |
|---|------|------|---------|--------|--------|
| 8 | `agent/auxiliary_client.py` | 288 | `_OPENROUTER_MODEL = "google/gemini-3-flash-preview"` | Add `_DEEPSEEK_MODEL` / chain slots | **Deferred** (vision policy) |
| 9 | `agent/auxiliary_client.py` | 1147 | `_try_openrouter()` | Add `_try_deepseek()` where safe | **Deferred** |
| 10 | `agent/auxiliary_client.py` | 1559 | Provider chain order | `deepseek, …` without stealing vision | **Deferred** |
| 11 | `agent/auxiliary_client.py` | 1859 | Warning env vars | Prefer DeepSeek wording where unified | **Deferred** |

### Runtime — Compression

| # | File | Line | Current | Target | Status |
|---|------|------|---------|--------|--------|
| 12 | `trajectory_compressor.py` | 101-103 | `OPENROUTER_BASE_URL`, `OPENROUTER_API_KEY` | DeepSeek defaults (or config) | **Deferred** |
| 13 | `trajectory_compressor.py` | 438 | Provider inference → openrouter | Include deepseek | **Deferred** |

### Runtime — Credential Pool

| # | File | Line | Current | Target | Status |
|---|------|------|---------|--------|--------|
| 14 | `agent/credential_pool.py` | 1393-1413 | OpenRouter first in `_seed_from_env()` | DeepSeek branch + ordering | **Deferred** |

### Runtime — Pricing / Usage

| # | File | Line | Current | Target | Status |
|---|------|------|---------|--------|--------|
| 15 | `agent/usage_pricing.py` | 416-417 | OpenRouter billing route | DeepSeek: no `/models` pricing API — docs pricing | **Deferred** (when product prioritizes) |

### NOT in Scope

The following files keep their OpenRouter references (they are provider-specific tools,
not default settings):

- `tools/openrouter_client.py` — OpenRouter client (used when user selects OpenRouter)
- `tools/mixture_of_agents_tool.py` — MoA tool (OpenRouter-specific feature)
- `tools/rl_training_tool.py` — RL training (dev-only)
- `environments/**/default.yaml` — 5 benchmark configs (upstream testing)
- `skills/red-teaming/` — Skill templates (user-installed)

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| DeepSeek has no vision model | `_try_deepseek()` must NOT handle vision tasks; vision fallback stays on OpenRouter or Anthropic |
| DeepSeek `/models` endpoint returns different shape | Keep `fetch_model_metadata()` using OpenRouter for metadata; the gateway child gate already prevents it from running on bots |
| DeepSeek API key format vs OpenRouter | Both use `Authorization: Bearer <key>`, interchangeable for the HTTP layer |

---

*Last updated: 2026-05-12*
