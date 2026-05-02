"""HermesDesk Python entrypoint.

Spawned by the Tauri shell. Responsibilities:

  1. Configure logging under ``HERMESDESK_DATA_DIR`` (Tauri: e.g. ``%LOCALAPPDATA%\\com.hermesdesk.app``).
  2. Validate the Tauri <-> Python contract version.
  3. Build a typed ``DesktopConfig`` from env vars.
  4. Install runtime overlays (must happen before importing Hermes).
  5. Pick a free localhost port, write it to a handshake file the
     Tauri shell is polling.
  6. Launch Hermes' built-in web server bound to 127.0.0.1:PORT.
  7. Forward SIGTERM cleanly so closing the window closes the agent.

Tauri sets these env vars before spawn:

    HERMESDESK_BUNDLE_DIR        install dir (read-only)
    HERMESDESK_DATA_DIR          per-user state (writable)
    HERMESDESK_WORKSPACE         workspace folder
    HERMESDESK_PORT_FILE         path where we write the chosen port
    HERMESDESK_PROVIDER          e.g. "openrouter" or "custom"
    HERMESDESK_LLM_HOST          LLM hostname for the network allowlist
    HERMESDESK_API_BASE_URL      optional OpenAI-compatible base URL (custom vendor)
    HERMESDESK_MODEL             optional default model id (Hermes config seed)
    HERMESDESK_INFERENCE_PROVIDER  optional Hermes routing hint (e.g. "custom")
    HERMESDESK_SECRET_URL        one-shot loopback URL to fetch the API key
    HERMESDESK_APPROVAL_URL      loopback URL the approval bridge POSTs to
    HERMESDESK_BRIDGE_SECRET     shared with Tauri X-HermesDesk-Auth (shell /api)
    HERMESDESK_POWER_USER        "1" enables shell/code/browser/mcp tools
    HERMESDESK_CONTRACT_VERSION  must match desktop_contract.CONTRACT_VERSION
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
from pathlib import Path


def _setup_logging() -> None:
    data_dir = Path(os.environ.get("HERMESDESK_DATA_DIR", "."))
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "hermesdesk.log",
        maxBytes=2_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s %(message)s"
    ))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler(sys.stderr)])


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_handshake(port: int) -> None:
    path = os.environ.get("HERMESDESK_PORT_FILE")
    if not path:
        return
    Path(path).write_text(str(port), encoding="utf-8")


def _redirect_hermes_home() -> Path:
    """Force Hermes' config/cache root inside the per-user data dir.

    Hermes defaults to ``~/.hermes`` for ``HERMES_HOME`` (see
    ``hermes_constants.get_hermes_home``). On HermesDesk we don't want
    Hermes to write to the user's profile root; we want everything in
    ``%LOCALAPPDATA%\\HermesDesk\\hermes-home`` so:

      * uninstall is clean (one folder to delete),
      * the workspace jail can keep ``~/`` opaque,
      * profile separation per Windows user is automatic.

    Set the env var BEFORE overlays import anything that touches
    ``hermes_constants`` or ``hermes_cli.config``.
    """
    data_dir = Path(os.environ.get("HERMESDESK_DATA_DIR", "."))
    home = data_dir / "hermes-home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(home)
    return home


def _wire_sys_path() -> None:
    """Make `overlays/`, `hermes/`, and `site-packages/` importable.

    The bundled layout under ``HERMESDESK_BUNDLE_DIR`` is::

        runtime/
            desktop_entrypoint.py     <- this file
            overlays/                 <- our monkey patches
            hermes/                   <- upstream Hermes Agent (cloned subtree)
                hermes_cli/
                agent/
                tools/
                ...
            site-packages/            <- pip-installed deps (httpx, fastapi, ...)
            python/                   <- embedded CPython

    Python auto-adds the script's directory (``runtime/``) to ``sys.path[0]``
    when launched as ``python.exe runtime\\desktop_entrypoint.py``, which
    makes ``overlays`` importable. ``hermes/`` and ``site-packages/`` need
    to be added manually — the build does ship a ``.pth`` shim, but the
    relative paths in it are fragile across dev vs bundled layouts. Doing
    it here makes the launcher self-contained.
    """
    here = Path(__file__).resolve().parent
    for sub in ("hermes", "site-packages"):
        p = here / sub
        if p.is_dir():
            sys.path.insert(0, str(p))
    # Package ``helpers`` lives at ``runtime/helpers/``; parent must be on path.
    if (here / "helpers").is_dir():
        sys.path.insert(0, str(here))


def _verify_bundle_deps(log: logging.Logger) -> None:
    """Fail fast if ``build_bundle.ps1`` did not populate ``site-packages`` (or deps are broken).

    Common causes:
      * Never ran ``python\\build_bundle.ps1`` → empty ``site-packages``.
      * Inherited ``PYTHONPATH`` from the parent shell shadowing real PyYAML
        (Tauri now strips it; devs should avoid exporting a bogus ``yaml``).
      * Wrong PyPI package named ``yaml`` installed instead of ``PyYAML``.
    """
    here = Path(__file__).resolve().parent
    sp = here / "site-packages"
    if not sp.is_dir() or not (sp / "yaml").exists():
        log.error(
            "Bundle site-packages missing PyYAML layout under %s. "
            "From the repo root run: .\\python\\build_bundle.ps1",
            sp,
        )
        raise SystemExit(4)
    try:
        import yaml as _yaml  # type: ignore[no-redef]
    except ImportError as e:
        log.error("Cannot import yaml: %s. Re-run .\\python\\build_bundle.ps1", e)
        raise SystemExit(4) from e
    if not hasattr(_yaml, "safe_load"):
        log.error(
            "Broken `yaml` module at %s (expected PyYAML with safe_load). "
            "Remove conflicting PyPI package `yaml` / clear PYTHONPATH, then rebuild bundle.",
            getattr(_yaml, "__file__", "?"),
        )
        raise SystemExit(4)
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        log.error(
            "fastapi/uvicorn missing from bundle: %s. Re-run .\\python\\build_bundle.ps1",
            e,
        )
        raise SystemExit(4)


def main() -> int:
    _setup_logging()
    log = logging.getLogger("hermesdesk.entry")
    log.info("starting HermesDesk Python (pid=%d)", os.getpid())

    _wire_sys_path()
    _verify_bundle_deps(log)
    hermes_home = _redirect_hermes_home()
    log.info("HERMES_HOME -> %s", hermes_home)

    # 0. Contract version check.  Must match the Tauri shell's expectation.
    from desktop_contract import CONTRACT_VERSION as _EXPECTED_CONTRACT

    _got = int(os.environ.get("HERMESDESK_CONTRACT_VERSION", "0"))
    if _got != _EXPECTED_CONTRACT:
        log.error(
            "Contract version mismatch: Tauri shell sent v%d, Python expects v%d. "
            "Rebuild the Python bundle (python/build_bundle.ps1) so the bundled "
            "hermes_cli matches the Tauri shell's contract.",
            _got, _EXPECTED_CONTRACT,
        )
        return 5

    # 0b. Build typed bootstrap config (Phase 2 — no behavior change yet).
    # Phase 3 policy objects will consume this instead of raw env vars.
    from desktop_config import from_env

    cfg = from_env()
    log.info(
        "DesktopConfig: mode=%s provider=%s llm_host=%s workspace=%s",
        cfg.runtime_mode.value, cfg.provider, cfg.llm_host, cfg.workspace,
    )

    # 1. Overlays first.
    try:
        from overlays import apply_all
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from overlays import apply_all  # type: ignore[no-redef]
    apply_all()

    # 1b. Eager-load real ``gateway.session_context`` so ``tools/approval`` + terminal
    #     use ContextVar state (not a stale stub left in sys.modules).
    try:
        import importlib

        importlib.import_module("gateway.session_context")
        log.info("gateway.session_context import ok")
    except Exception as e:
        log.warning("gateway.session_context import failed: %s", e)

    # 2. Import web_server before the port handshake. Import creates session state
    #    (e.g. writes `hermes_web_session_token.txt` to HERMESDESK_DATA_DIR) that
    #    the Tauri shell reads once `port.txt` is visible — if we wrote port first,
    #    the shell could race and miss that file.
    try:
        from hermes_cli import web_server  # type: ignore
    except Exception:
        log.exception("failed to import hermes_cli.web_server; aborting")
        return 3

    # Main agent must know about HermesDesk power-user mode (terminal/browser/code gated off by default).
    try:
        try:
            from overlays.desk_system_prompt import install as _desk_system_prompt_install
        except ImportError:
            # Dev layout: `overlays/` lives under `python/`, not `python/src/`.
            _root = str(Path(__file__).resolve().parent.parent)
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from overlays.desk_system_prompt import install as _desk_system_prompt_install
        _desk_system_prompt_install()
    except Exception as e:
        log.warning("desk_system_prompt install: %s", e)

    # Mirror SPA session token for the Tauri shell (reads same path as ``paths::ensure_data_dir``).
    # web_server also writes this on import; we repeat here so an older bundled hermes without
    # that block still works.
    _dd = (os.environ.get("HERMESDESK_DATA_DIR") or "").strip()
    if _dd:
        try:
            tok = getattr(web_server, "_SESSION_TOKEN", None)
            if tok:
                p = Path(_dd) / "hermes_web_session_token.txt"
                p.write_text(str(tok), encoding="utf-8")
                log.info("wrote %s (len=%d)", p, len(str(tok)))
        except OSError as e:
            log.warning("hermes_web_session_token.txt: %s", e)

    # 3. Pick port and tell Tauri.
    port = _free_port()
    _write_handshake(port)
    log.info("bound port %d, handshake written", port)

    # Upstream API (hermes >= 0.10): hermes_cli.web_server.start_server(host, port, ...)
    runner = (
        getattr(web_server, "start_server", None)
        or getattr(web_server, "run", None)
        or getattr(web_server, "main", None)
    )
    if runner is None:
        log.error(
            "no start_server()/run()/main() entry in hermes_cli.web_server; "
            "upstream API may have changed"
        )
        return 4

    try:
        # Try a few common signatures so we tolerate small upstream churn.
        # Prefer no auto-open browser: HermesDesk shell is the main UI; OS browser is confusing noise.
        for attempt in (
            lambda: runner(host="127.0.0.1", port=port, open_browser=False),
            lambda: runner("127.0.0.1", port, False),
            lambda: runner(port=port),
        ):
            try:
                return int(attempt() or 0)
            except TypeError:
                continue
        # Last resort: argv-style.
        old_argv = sys.argv[:]
        sys.argv = ["hermes-web", "--host", "127.0.0.1", "--port", str(port)]
        try:
            return int(runner() or 0)
        finally:
            sys.argv = old_argv
    except KeyboardInterrupt:
        log.info("interrupt received; shutting down")
        return 0


if __name__ == "__main__":
    sys.exit(main())
