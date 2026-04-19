# Patches and overlays

We modify upstream Hermes via two complementary mechanisms:

## 1. Runtime overlays (preferred)

Lives in [`python/overlays/`](../python/overlays/). These are normal Python
modules imported by `desktop_entrypoint.py` **before** any `hermes_cli` /
`agent` / `tools` import. They monkey-patch / wrap / replace the bits we
care about (path jail, approval flow, secret loading, etc.).

Pros:

- Survives upstream rebases (only break if upstream renames a symbol)
- No `git apply` fragility
- Easy to unit-test in isolation
- Easy to disable per-module for debugging

This handles ~90% of what we need.

## 2. True source patches (only when overlays can't help)

Stored as `.patch` files in this folder, applied by `python/build_bundle.ps1`
after `git submodule update`. Use only for things you literally cannot do at
runtime, e.g. removing a problematic top-level import that crashes before
the overlay can load.

Currently shipped patches: **none** (overlays cover all v1 needs).

If you add one, name it `NNNN-short-description.patch` and document the
exact upstream commit it was generated against in the patch header. Use
`git -C hermes format-patch` to generate.

## Refresh procedure

```powershell
# bump submodule
git -C hermes fetch && git -C hermes checkout v0.11.0
# re-run audit; fix overlays if symbols moved
.\scripts\audit_posix_imports.ps1
.\scripts\verify_overlays.ps1
# commit submodule bump
git add hermes && git commit -m "Bump hermes to v0.11.0"
```
