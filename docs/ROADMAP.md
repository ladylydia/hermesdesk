# HermesDesk roadmap

**Last updated:** 2026-04-30

This file tracks **intentional, product-level** work. Bugfix triage lives in issues and changelogs (for example `CHANGES_*.md` in the repo root).

---

## 1. Shell chat + messaging gateway (**shipped baseline**)

**Status:** baseline delivered (ongoing polish)

HermesDesk today includes:

- **Dedicated shell chat** at **`/chat`** (`web/src/chat/*`), backed by Tauri **`invoke`** commands that proxy to the embedded Hermes loopback (`tauri/src/chat.rs`). Sessions list / messages / stop mirror Hermes desk APIs.
- **Messaging gateway** as a **second supervised Python process** (`python -m gateway.run`, `tauri/src/gateway_supervisor.rs`), auto-start optional on cold launch when `hermes-home/.env` contains messaging credentials, manual controls in Settings.
- **Onboarding / Settings UX** for **Weixin**, **QQ Bot**, **Feishu/Lark**, and **Telegram** (token), plus pairing helpers where Hermes requires them (`pairing.rs`, shell blocks).

The **`strip_shims`** overlay still stubs **`gateway.run.main`** inside the **Hermes web child** so the dashboard never accidentally hosts the gateway entrypoint; the **real** gateway module loads only in the **separate** gateway OS process. See `docs/architecture.md` §Process model.

**Remaining themes on this track** (examples — not ordered backlog):

- UX polish for `/chat` (streaming surfaces, attachments edge cases, error copy).
- Keep gateway flows aligned when **`hermes/`** submodule moves (re-run `python/build_bundle.ps1`; watch upstream adapter breaks).
- Optional deeper Hermes-web parity only where product asks for it — **without** folding unrelated onboarding fixes into chat regressions.

**References**

- `docs/architecture.md` — processes, `/chat` proxy, gateway boundaries.
- `README.md` — user-facing gateway summary.

---

## 2. Other ongoing themes (not a full backlog)

- **Onboarding & provider validation** — Tauri IPC vs post-`location.replace` behavior; keep validation on a path that can reach Rust or a trusted local proxy (`CHANGES_2026-04-21.md`).
- **“Configured” detection** — align keyring, `settings.json`, and UI so users are not sent past onboarding with stale state.
- **Build / Windows** — file locks during `cargo` + bundled Python (e.g. `os error 32`); antivirus exclusions; `build_bundle.ps1` hardening (see `CHANGES_2026-04-21.md` notes).

---

## 简体中文摘要

**壳内 `/chat` 与消息网关** 已在当前桌面产品中落地：`invoke` → Rust → Hermes loopback；网关为独立 **`gateway.run`** 子进程；微信 / QQ / 飞书·Lark / Telegram 的配置入口在引导与设置中。**strip_shims** 仅阻止「Hermes Web 主进程」误跑网关入口，与第二条网关进程并存——详见 **`docs/architecture.md`**。

路线图剩余部分多为体验打磨、与上游子模块同步及通用桌面工程质量项；不要把 onboarding / Keyring 等问题与 chat / gateway 缺陷混成同一类「顺带修」。

上方英文小节为正式范围说明；本文件与 `docs/architecture.md` 随实现更新。
