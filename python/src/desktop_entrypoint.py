"""HermesDesk Python entrypoint.

Spawned by the Tauri shell. Responsibilities:

  1. Configure logging to %LOCALAPPDATA%\\HermesDesk\\logs.
  2. Install runtime overlays (must happen before importing Hermes).
  3. Pick a free localhost port, write it to a handshake file the
     Tauri shell is polling.
  4. Launch Hermes' built-in web server bound to 127.0.0.1:PORT.
  5. Forward SIGTERM cleanly so closing the window closes the agent.

Tauri sets these env vars before spawn:

    HERMESDESK_BUNDLE_DIR    install dir (read-only)
    HERMESDESK_DATA_DIR      per-user state (writable)
    HERMESDESK_WORKSPACE     workspace folder
    HERMESDESK_PORT_FILE     path where we write the chosen port
    HERMESDESK_PROVIDER      e.g. "openrouter" or "custom"
    HERMESDESK_LLM_HOST      LLM hostname for the network allowlist
    HERMESDESK_API_BASE_URL  optional OpenAI-compatible base URL (custom vendor)
    HERMESDESK_MODEL         optional default model id (Hermes config seed)
    HERMESDESK_INFERENCE_PROVIDER  optional Hermes routing hint (e.g. "custom")
    HERMESDESK_SECRET_URL    one-shot loopback URL to fetch the API key
    HERMESDESK_APPROVAL_URL  loopback URL the approval bridge POSTs to
    HERMESDESK_POWER_USER    "1" enables shell/code/browser/mcp tools
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


def main() -> int:
    _setup_logging()
    log = logging.getLogger("hermesdesk.entry")
    log.info("starting HermesDesk Python (pid=%d)", os.getpid())

    _wire_sys_path()
    hermes_home = _redirect_hermes_home()
    log.info("HERMES_HOME -> %s", hermes_home)

    # 1. Overlays first.
    try:
        from overlays import apply_all
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from overlays import apply_all  # type: ignore[no-redef]
    apply_all()

    # 2. Pick port and tell Tauri.
    port = _free_port()
    _write_handshake(port)
    log.info("bound port %d, handshake written", port)

    # 3. Boot Hermes' web server.
    #
    # Upstream entrypoint as of v0.10.0 lives in hermes_cli.web_server:run().
    # We call it programmatically with the port we picked.
    try:
        from hermes_cli import web_server  # type: ignore
    except Exception:
        log.exception("failed to import hermes_cli.web_server; aborting")
        return 3

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
        for attempt in (
            lambda: runner(host="127.0.0.1", port=port),
            lambda: runner("127.0.0.1", port),
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
