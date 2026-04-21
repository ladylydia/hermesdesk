# Auto-update

HermesDesk uses Tauri's [updater plugin](https://v2.tauri.app/plugin/updater/),
pointed at GitHub Releases. Updates are signed with a separate Ed25519
keypair (the "updater key") so a compromised CDN cannot push a malicious
binary even if the cert is fine.

## One-time setup (project owner)

```powershell
# Generates ~/.tauri/HermesDesk.key + HermesDesk.key.pub
cargo install tauri-cli --version "^2" --locked
cargo tauri signer generate -w ~/.tauri/HermesDesk.key
```

- Put the **public key** into `tauri.conf.json#plugins.updater.pubkey`.
- Put the **private key** + its password into GitHub Actions secrets
  (`TAURI_UPDATER_PRIVATE_KEY`, `TAURI_UPDATER_PRIVATE_KEY_PASSWORD`).
  Never commit the private key.

## Release flow

1. Tag a commit: `git tag v0.1.1 && git push --tags`
2. The `release` workflow (`.github/workflows/release.yml`) builds the
   signed MSI and runs `scripts/make_updater_manifest.ps1` to produce
   `latest.json`.
3. The action attaches `*.msi`, `*.msi.sig`, and `latest.json` to the
   GitHub release.
4. Existing installs check
   `https://github.com/your-org/hermesdesk/releases/latest/download/latest.json`
   on launch and from the tray menu, then prompt the user with a small
   "Update HermesDesk?" dialog.

## User experience

- No surprise restarts. The updater downloads in the background and waits
  for the user to click "Restart and update".
- Failure modes (no network, bad signature, partial download) all fall
  back silently to "stay on current version" — the user is never blocked
  from chatting because of an update glitch.

## Rolling back

If a release is bad, delete the GitHub Release (or unpublish it). Existing
installs that already updated keep running. New installs and not-yet-updated
installs go to the previous release.

For an "emergency replace", publish a new tag with a higher version number
that ships the previous good code.
