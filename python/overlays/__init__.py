"""HermesDesk runtime overlays.

These modules monkey-patch / wrap upstream Hermes so the desktop build
gets:

    - Workspace folder jail            (workspace_jail.py, m4)
    - Tauri-routed shell approval      (approval_bridge.py, m4)
    - Network egress allowlist         (network_allowlist.py, m4)
    - Secret loaded from Tauri vault   (secret_loader.py, m5)
    - Default toolset = keep-list      (default_toolset.py, m1)
    - L1 builtin helpers tool          (builtin_helpers.py, m7)
    - Stripped-package import shims    (strip_shims.py, m1)
    - Windows process-group safety     (windows_safety.py, m1)

Order matters: `apply_all()` enforces it. Call exactly once, before
importing anything from `hermes_cli`, `agent`, `tools`, or `gateway`.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable

log = logging.getLogger("hermesdesk.overlays")

_APPLIED = False


def apply_all() -> None:
    """Install every overlay. Idempotent."""
    global _APPLIED
    if _APPLIED:
        return

    if sys.version_info < (3, 11):
        raise RuntimeError("HermesDesk requires Python 3.11+")

    # Order matters. Earlier overlays make later imports safe.
    _run("strip_shims",         lambda: __import__(__name__ + ".strip_shims",       fromlist=["install"]).install())
    _run("windows_safety",      lambda: __import__(__name__ + ".windows_safety",    fromlist=["install"]).install())
    _run("secret_loader",       lambda: __import__(__name__ + ".secret_loader",     fromlist=["install"]).install())
    _run("desktop_llm_config",  lambda: __import__(__name__ + ".desktop_llm_config", fromlist=["install"]).install())
    _run("workspace_jail",      lambda: __import__(__name__ + ".workspace_jail",    fromlist=["install"]).install())
    _run("network_allowlist",   lambda: __import__(__name__ + ".network_allowlist", fromlist=["install"]).install())
    _run("default_toolset",     lambda: __import__(__name__ + ".default_toolset",   fromlist=["install"]).install())
    _run("builtin_helpers",     lambda: __import__(__name__ + ".builtin_helpers",   fromlist=["install"]).install())
    _run("approval_bridge",     lambda: __import__(__name__ + ".approval_bridge",   fromlist=["install"]).install())

    _APPLIED = True
    log.info("HermesDesk overlays applied")


def _run(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
        log.debug("overlay %s installed", name)
    except Exception:
        log.exception("overlay %s FAILED to install", name)
        # Fail loudly: a missing overlay is a security regression.
        if os.environ.get("HERMESDESK_OVERLAY_LENIENT") != "1":
            raise
