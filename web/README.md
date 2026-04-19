# HermesDesk — web

This package is a small Vite + React app loaded by the Tauri shell **before**
the Hermes web UI takes over. It owns:

- The splash screen
- The 5-step onboarding wizard
- The Settings overlay (Power-user toggle, sign out, status)

After onboarding succeeds, the Tauri shell calls `window.location.replace`
on the WebView to point it at the Hermes Python web server (a separate React
app shipped inside the Python bundle). That Hermes UI lives at
`hermes/web/` upstream — we do **not** fork it; we trim it via the
`hermesdesk_ui_overlay.css` injected by `desktop_entrypoint.py` (TODO; see
below).

## Dev

```bash
npm install
npm run dev
```

Open `http://localhost:5173`. To exercise IPC (`cmd_save_secret`, etc.),
launch via `cargo tauri dev` from `../tauri/` instead.

## Build

```bash
npm run build
```

Produces `dist/`, which Tauri picks up via `frontendDist` in
`tauri.conf.json`.

## TODO

- Inject a CSS overlay into the upstream Hermes UI that hides the gateway,
  MCP config, skills hub admin, and multi-platform mirror tabs unless
  Power-user is on. See `docs/architecture.md` -> "UI trim".
- Replace splash logo with a real icon once branding lands.
