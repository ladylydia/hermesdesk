# Icons

Replace the placeholders in this folder with real branded icons before
release. The Tauri bundler expects:

```
icons/
  32x32.png
  128x128.png
  128x128@2x.png       (256 x 256)
  icon.ico             (multi-resolution Windows ICO)
  tray.png             (32 x 32 PNG used by the tray icon)
```

To regenerate from a single high-res PNG:

```powershell
cargo install tauri-cli --version "^2" --locked
cargo tauri icon path\to\source-1024.png
```

That command writes all the variants above into this folder.

Until real branding lands, the build will fail because no icons are
present. This is intentional — we don't want unbranded binaries to leak.
