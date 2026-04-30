"""
Verify pip --target output under ``python/dist/runtime/``.

Usage (from build_bundle.ps1)::

    python.exe tools\\verify_bundle_site_packages.py <absolute-path-to-runtime-dir>

Exits 0 if PyYAML (with ``safe_load``), fastapi, and uvicorn import from ``site-packages``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_bundle_site_packages.py <runtime-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    sp = root / "site-packages"
    if not sp.is_dir():
        print(f"missing site-packages: {sp}", file=sys.stderr)
        return 1
    sys.path.insert(0, str(sp))
    hermes = root / "hermes"
    if hermes.is_dir():
        sys.path.insert(0, str(hermes))
    import yaml

    if not hasattr(yaml, "safe_load"):
        sys.stderr.write("broken yaml module (not PyYAML): %r\n" % (yaml,))
        return 1
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401

    print("pip payload ok: PyYAML, fastapi, uvicorn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
