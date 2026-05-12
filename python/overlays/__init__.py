"""HermesDesk runtime overlays.

These modules monkey-patch / wrap upstream Hermes so the desktop build
gets:

    - Stripped-package import shims    (strip_shims.py)
    - Secret loaded from Tauri vault   (secret_store.py policy, no overlay)
    - Desktop LLM config seed           (desktop_llm_config.py)
    - Workspace folder jail            (workspace_jail.py)
    - Network egress allowlist         (network_allowlist.py)
    - Default toolset = keep-list      (default_toolset.py)
    - L1 builtin helpers tool          (builtin_helpers.py)
    - Tauri-routed shell approval      (approval_bridge.py)

Order matters: `apply_all()` enforces it. Call exactly once, before
importing anything from `hermes_cli`, `agent`, `tools`, or `gateway`.

Phase 3 extracted the core logic into ``python/src/*_policy.py`` files.
The overlays that remain do essential monkey-patch wiring that Phase 4 has
not yet replaced.  Removed overlays:
  - windows_safety  (was a documented no-op)
  - secret_loader   (3-line wrapper, replaced by direct SecretStore call)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable

log = logging.getLogger("hermesdesk.overlays")

_APPLIED = False


def _install_secret_store() -> None:
    """Phase 4: call SecretStore directly instead of the secret_loader wrapper."""
    try:
        from secret_store import SecretStore  # type: ignore[import-untyped]
    except ImportError:
        # Dev layout: python/src/ not yet on sys.path
        from pathlib import Path as _Path  # noqa: F811
        _src = str(_Path(__file__).resolve().parent.parent / "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)
        from secret_store import SecretStore  # type: ignore[import-untyped]
    store = SecretStore()
    store.fetch()


def apply_all() -> None:
    """Install every overlay. Idempotent."""
    global _APPLIED
    if _APPLIED:
        return

    if sys.version_info < (3, 11):
        raise RuntimeError("HermesDesk requires Python 3.11+")

    # Order matters. Earlier overlays make later imports safe.
    _run("strip_shims",         lambda: __import__(__name__ + ".strip_shims",       fromlist=["install"]).install())
    _run("secret_store",        _install_secret_store)
    _run("desktop_llm_config",  lambda: __import__(__name__ + ".desktop_llm_config", fromlist=["install"]).install())
    _run("workspace_jail",      lambda: __import__(__name__ + ".workspace_jail",    fromlist=["install"]).install())
    _run("network_allowlist",   lambda: __import__(__name__ + ".network_allowlist", fromlist=["install"]).install())
    _run("default_toolset",     lambda: __import__(__name__ + ".default_toolset",   fromlist=["install"]).install())
    _run("builtin_helpers",     lambda: __import__(__name__ + ".builtin_helpers",   fromlist=["install"]).install())
    _run("approval_bridge",     lambda: __import__(__name__ + ".approval_bridge",   fromlist=["install"]).install())
    # cron.scheduler is part of the bundled hermes tree and only becomes
    # importable after _wire_sys_path() in desktop_entrypoint. The first
    # call here is best-effort (likely no-op); desktop_entrypoint runs
    # install() a second time after sys.path is wired.
    _run("cron_desktop_delivery", lambda: __import__(__name__ + ".cron_desktop_delivery", fromlist=["install"]).install())
    _run("cron_retain_completed", lambda: __import__(__name__ + ".cron_retain_completed", fromlist=["install"]).install())

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
