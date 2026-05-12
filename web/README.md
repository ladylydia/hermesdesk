# Kabuqina — web

Vite + React app embedded in the Tauri shell. Routes (`main.tsx`):

- **`/`** — Splash (routes to onboarding or **`/chat`**)
- **`/onboarding/*`** — Wizard (minimal LLM path + optional messaging sections)
- **`/chat`** — Shell chat (Tauri `invoke` → Hermes loopback — see `src/chat/`)
- **`/settings`** — Power user, proxy, messaging gateway, Telegram / Feishu / QQ / Weixin blocks, pairing

Opening the **full Hermes dashboard** uses `window.location.replace` (or equivalent navigation) to `http://127.0.0.1:<port>/` — that UI is built from **`hermes/web`** and shipped inside the Python bundle; styling may be trimmed via overlays in `desktop_entrypoint.py`.

Desk docs: [`docs/architecture.md`](../docs/architecture.md), [`docs/README.md`](../docs/README.md).

## Dev

```bash
npm install
npm run dev
```

Open `http://localhost:5173`. For real IPC (`invoke`), run **`cargo tauri dev`** from **`../tauri/`**.

## Build

```bash
npm run build
```

Output **`dist/`** — consumed by Tauri `frontendDist` in `tauri.conf.json`.
