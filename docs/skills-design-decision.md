# Skills system: design decision

> Status: **Accepted**, supersedes the m7 plan ("Skill Hub hidden behind
> Power-user toggle"). Implementation tracked under m7-revised /
> `docs/onboarding.md`.
> Date: 2026-04-19
> Author: Claude (HermesDesk implementation), responding to a written
> proposal by Kimi K2.5.

---

## Context

m7 as originally written treated Skills as a power-user feature: the
default UI hid Skills entirely, and only the `HERMESDESK_POWER_USER=1`
profile exposed the Skill Hub. The reasoning was "non-technical users
shouldn't have to think about workflows."

A subsequent product review pushed back on this:

> "ChatGPT Desktop and Claude Desktop both have no programmable
> workflows. Zapier has them but is cloud-only. HermesDesk's
> differentiator is exactly the *combination* of local files + AI
> orchestration + zero deploy. Hiding Skills entirely throws that
> differentiator away."

That argument is correct. Putting our USP behind a hidden flag is a
product mistake. But the proposed remedy — "open the Skill market to
the user, including community-contributed skills" — has a security
flaw the original review did not address. This document records both
the redirected direction and the safety constraints that go with it.

## Decision

**Expose Skills by tier of action, not by tier of user.**

```
                    L1 use         L2 install        L3 author
                    ─────────────────────────────────────────────
default user        built-in       —                 —
advanced mode       built-in       signed market     —
power user          all            any source        full editor
                                   (warn loudly)     (+ recorder
                                                      v1.2+)
```

### What goes in each tier

**L1 — Use built-in Skills (always on, all users)**

A small curated set of Skills shipped inside the installer, surfaced
as "Quick Actions" buttons next to the chat input. Branding: **快捷指令
(zh) / Recipes (en)**. The user does not need to know the word "Skill".

v1.0 ships at least these two; more are stretch goals:

| Recipe              | What it does                              |
|---------------------|-------------------------------------------|
| Folder cleanup      | Sort files in a folder by type, dedupe    |
| Weekly report       | Read an Excel range, fill a Word template |
| (stretch) PDF digest| Summarise every PDF in a folder           |
| (stretch) Image batch| Resize / watermark / re-encode           |

These are **bundled as signed assets**, not downloaded. They run
through a new `run_builtin_helper(name, args)` tool (see
"Implementation: builtin helpers" below) which is whitelisted at
compile time and cannot be extended at runtime.

**L2 — Install signed Skills from the official market (advanced
mode)**

A "Recipe Book" page in the dashboard. Lists Skills published by
HermesDesk team or partners and signed with our Ed25519 signing key.
On install, the user sees a Chrome-extension-style permission sheet
derived from the Skill's declarative manifest:

```
Install: Weekly Report Pro v1.2 (by reports-team)
Signature: ✅ HermesDesk official

This recipe will:
  📁 Read files in HermesWork/reports/
  🌐 Reach api.openai.com
  💾 Write to HermesWork/output/
  ⏱️ Run on schedule (every Monday 9:00)

  [Cancel]   [Install]
```

The permission set is computed from `SKILL.md` metadata, not from
inspecting code. This is intentional: it keeps the consent UI honest
and machine-checkable.

**Advanced mode** is a single user-facing toggle in Settings labelled
"Show recipe market" (off by default). It does *not* enable any tool
that wasn't already on; it only enables the install/browse UI.

**L3 — Install any source + author your own (power user only)**

Behind the existing `HERMESDESK_POWER_USER=1` toggle. Adds:
- Install of unsigned third-party Skills, gated by a red-bordered
  "this recipe has not been reviewed by HermesDesk" warning sheet.
- A YAML editor for hand-authoring Skills.
- (v1.2+) The declarative recipe recorder — see Open Questions.

Power-user mode also unlocks the dangerous tools (`terminal`,
`code_execution`, `browser`) so authored Skills have something
non-trivial to compose.

## Consequences

### Security model

The original "open the market to anyone" proposal would have made the
Skills system into an effective bypass of every safety layer we built:

* `workspace_jail` keeps file I/O inside `HermesWork/` — but a
  malicious Skill is *legitimately* allowed to read everything in
  `HermesWork/`, including bank statements the user dropped there.
* `network_allowlist` restricts egress to known LLM hosts — but the
  payload of an LLM request is opaque to the allowlist; a malicious
  Skill can exfiltrate user data by stuffing it into a system prompt.
* `approval_bridge` only fires on shell commands, not on Skills
  composing existing tools.

Our chosen tiering closes this hole at the points that matter:

* L1 cannot exfiltrate because L1 Skills don't introduce new code,
  only call our own signed helpers with bounded args.
* L2 cannot run untrusted code because every L2 Skill is signed by us;
  attribution is recoverable if one ever turns out to be malicious.
* L3 is opt-in by an environment variable that no normal user will
  ever set. Reaching L3 is itself the consent.

### What this commits us to building

| When  | Item                                                       |
|-------|------------------------------------------------------------|
| v1.0  | QuickActions UI strip in the chat view                     |
| v1.0  | `run_builtin_helper` tool + 2 bundled helpers              |
| v1.0  | `docs/skills-security.md` describing the trust model       |
| v1.0  | Settings toggle "Show recipe market" (UI only, no market yet) |
| v1.1  | Ed25519 signing pipeline for Skill packages                |
| v1.1  | Recipe Book browse + install UI                            |
| v1.1  | Permission consent sheet derived from `SKILL.md` manifest  |
| v1.2  | Power-user unsigned-Skill install path                     |
| v1.2+ | Declarative recipe recorder                                |

### What this explicitly does **not** do

* No third-party Skill installation in v1.0. The "Show recipe market"
  toggle in Settings is wired but the market itself is empty until
  v1.1 ships signing.
* No code-recording recorder, ever. If we ship a recorder it records
  declarative actions (an iOS-Shortcuts-style step list), not Python.
  This rules out a whole class of "I recorded a macro that turned out
  to be a keylogger" scenarios.
* No automatic enabling of `terminal` / `code_execution` /
  `browser` for L1 or L2 Skills. If a Skill needs these, it must
  declare them in its manifest and the user sees them on install.
* No "always allow" for Skills. Each Skill's permissions are granted
  at install time, not on first use; revoke = uninstall.

## Implementation: builtin helpers

The `run_builtin_helper` tool replaces opening up `code_execution` for
the L1 demo Skills. It lives in `python/overlays/builtin_helpers.py`
(new) and is wired into Hermes' tool registry through the existing
overlay system.

```python
# python/overlays/builtin_helpers.py  (sketch)

_HELPERS: dict[str, Callable[[dict], dict]] = {
    "folder_organize":  folder_organize.run,
    "excel_to_word":    excel_to_word.run,
    "pdf_digest":       pdf_digest.run,
    "image_batch":      image_batch.run,
}

def install():
    @tool("run_builtin_helper")
    def run(name: str, args: dict) -> dict:
        if name not in _HELPERS:
            raise PermissionError(
                f"helper '{name}' is not in the HermesDesk whitelist"
            )
        # Helpers receive args, return a dict. They cannot exec arbitrary
        # code, cannot import outside their module, and cannot escape the
        # workspace jail.
        return _HELPERS[name](args)
```

Each helper module is a small, readable Python file under
`python/helpers/`. They are reviewed and signed as part of the
HermesDesk binary, not loaded from disk at runtime. The set is
deliberately small and domain-focused: "do one Office task well",
not "be a general-purpose runtime".

This gives us "Skills that do useful local-file work" without ever
shipping the bullet-loaded gun that is generic `code_execution`.

## Alternatives considered

**A. Keep m7 as-is (Skills hidden, power-user only).**
Rejected. Throws away the differentiator. Doesn't solve safety either,
because power users who do flip the toggle still get the unsafe
unsigned-market path.

**B. Open the market without signing, rely on user judgement.**
Rejected. Our target user is non-technical; "user judgement" is not a
defence. See "Security model" above.

**C. Allow `code_execution` for L1 with a sandboxed Python.**
Rejected for v1.0. A real Python sandbox (no `eval`, no `exec`, no
`__import__` outside an allowlist, no FFI) is research-grade work and
historically a source of CVEs. The builtin-helper path is a strictly
smaller surface that ships sooner.

**D. Use Hermes upstream's existing skill ecosystem unchanged.**
Rejected. Surveyed `hermes/skills/` — most existing Skills declare
`prerequisites: {commands: [some-cli]}` and assume `terminal` is
available. They are designed for power users on Linux/macOS who have
the prerequisite CLIs installed. They are not appropriate as
"out-of-the-box value" for our target user.

## Open questions (revisit before v1.1)

* **Who maintains the official Recipe set?** v1.0 has at most 2-3
  recipes; that's fine for one engineer. By v1.1 we need a process for
  accepting external contributions and reviewing them — pull request
  review against a `recipes/` folder in this repo, with CI running the
  signature step.
* **Signature mechanism: roll our own or adopt Sigstore?** Ed25519 is
  the easy path; Sigstore gives us free transparency log and identity
  binding (GitHub Actions OIDC) but couples us to their service.
  Decision: roll our own for v1.1, migrate to Sigstore in v1.2 if the
  community grows enough to need transparency.
* **English term for the user-visible "Skill" concept.** Chinese is
  decided (`快捷指令`, copying iOS). English candidates:
  - "Recipe" (this doc's working name) — warm, no overlap with
    keyboard shortcuts, has IFTTT/Zapier precedent
  - "Action" — Apple Shortcuts uses it but means a single step there,
    not a workflow
  - "Workflow" — accurate but corporate-y
  Decision deferred to onboarding copywriting pass.
* **Recorder design.** Must be declarative. Worth a separate ADR when
  we get to v1.2+; do not start implementing without one.

## Cross-references

* [`docs/safety.md`](safety.md) — workspace jail, network allowlist,
  approval bridge — the layers that this design coexists with.
* [`docs/onboarding.md`](onboarding.md) — needs an update to describe
  Quick Actions on the chat screen and the "Show recipe market"
  Settings toggle.
* [`docs/skills-security.md`](skills-security.md) — trust model for L1
  `run_builtin_helper`, L2/L3 roadmap pointers, and reporting.
* [`DECISIONS.md`](../DECISIONS.md) — top-level decision summary;
  amended to point here and to flip the Skills row from "hidden" to
  "tiered".
