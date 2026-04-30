# HermesDesk documentation index

Quick map of **`docs/`** (repo root). Prefer **`architecture.md`** + **`README.md`** for “how it works today”; **`ROADMAP.md`** for intentional next themes.

| Doc | Purpose |
|-----|---------|
| [architecture.md](architecture.md) | Processes (web child / `gateway.run` / QR workers), `/chat` proxy, startup sequence, failure modes |
| [ROADMAP.md](ROADMAP.md) | Product-level themes; baseline shipped vs polish |
| [gateway-desk-weixin-strategy.md](gateway-desk-weixin-strategy.md) | Route A/B/C rationale; four-channel desk implementation index |
| [gateway-route-c-weixin-validation.md](gateway-route-c-weixin-validation.md) | Weixin iLink field semantics + bundle probe commands |
| [hermesdesk-capability-matrix.md](hermesdesk-capability-matrix.md) | Toolsets, jail, network allowlist, approval, L1 helpers, **messaging gateway** |
| [safety.md](safety.md) | Layered threat model (align with capability matrix §4 for `NET_OPEN`) |
| [troubleshooting.md](troubleshooting.md) | Field log — proxies, Tokio I/O, **`build_bundle` vs gateway**, WinError 87, `.env` duplicates |
| [onboarding.md](onboarding.md) | UX spec for wizard + extended messaging sections |
| [qa-checklist.md](qa-checklist.md) | Release QA — install, `/chat`, dashboard, gateway smoke |
| [windows-port-audit.md](windows-port-audit.md) | POSIX audit snapshot + **2026 gateway ship** context note |
| [skills-security.md](skills-security.md) | Trust model for Skills / Recipes |
| [skills-design-decision.md](skills-design-decision.md) | L1 / L2 / L3 ADR |
| [skills-l2-frontend.md](skills-l2-frontend.md) | L2 Recipe Book IA notes |
| [embedded-python-bundled.md](embedded-python-bundled.md) | `build_bundle.ps1`, runtime layout, MSVC note |
| [auto-update.md](auto-update.md) | Updater behaviour |
| [code-signing.md](code-signing.md) | Installer signing |

Supporting / incident docs (titles vary): `hermesdesk_gateway_bug_report.md`, etc.
