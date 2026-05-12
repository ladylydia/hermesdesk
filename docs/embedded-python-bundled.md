# Embedded Python bundle (Windows)

Kabuqina ships a **standalone CPython** plus pruned **`site-packages`**, the **`hermes/`** subtree, **`overlays/`**, and launcher scripts under **`python/dist/runtime/`**. Tauri copies this tree into the build output (`tauri/target/.../runtime`) for dev and release.

## How to build

From repo root:

```powershell
.\python\build_bundle.ps1
```

Options (`-Clean`, `-Verify`, `-SkipWebBuild`) are documented in the script header — see [`python/build_bundle.ps1`](../python/build_bundle.ps1).

After **`git pull`** or **`hermes/` submodule updates**, especially changes under **`hermes/gateway/`**, **re-run** `build_bundle.ps1` before expecting messaging gateway fixes to appear ([`troubleshooting.md`](troubleshooting.md) §12).

## MSVC / wheels

Release and some dev builds compile or pull wheels (e.g. **`pydantic-core`**) that expect a **Visual C++** toolchain. Prefer **Developer PowerShell for VS** or **cmd.exe** with MSVC environment when the bundler fails on native extensions; see repo **`README.md`** build section.

## Related

- [`architecture.md`](architecture.md) — `desktop_entrypoint.py` vs `python -m gateway.run`
- [`Kabuqina-capability-matrix.md`](Kabuqina-capability-matrix.md)
