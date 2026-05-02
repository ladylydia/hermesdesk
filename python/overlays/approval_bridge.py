"""Route Hermes' shell-command approval to a Tauri-native modal.

# DEPRECATED: approval_backend.remove_when=Phase4
# Target replacement: ``python/src/approval_backend.py``

Hermes' approval system lives in ``tools/approval.py``. The CLI flow
prints a yes/no prompt to stdout and reads ``input()`` (see
``prompt_dangerous_approval`` in upstream). In a desktop app there is
no terminal, so we replace that function with one that POSTs the
request to the Tauri shell over loopback and blocks until the user
clicks Allow / Deny in a native Tauri WebView dialog.

Default policy: deny. No "always allow" persistence in v1 — the user
must re-confirm every dangerous command. This is intentionally more
strict than upstream because most HermesDesk users are non-technical.

The approval-handshake logic is delegated to
``python/src/approval_backend.py`` (Phase 3B).  This overlay only
installs the monkey-patch on ``tools.approval``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

log = logging.getLogger("hermesdesk.approval")

try:
    from approval_backend import ApprovalBackend
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from approval_backend import ApprovalBackend

_backend = ApprovalBackend()


def _ask_tauri(command: str, description: str) -> str:
    return _backend.ask(command, description)


def install() -> None:
    try:
        from tools import approval  # type: ignore
    except ImportError:
        log.debug("tools.approval not present (no power-user tools); skip")
        return

    target_name = "prompt_dangerous_approval"
    if not hasattr(approval, target_name):
        log.warning(
            "tools.approval.%s missing; upstream API may have changed. "
            "HermesDesk will fall back to upstream prompt (which will hang "
            "in a desktop context — please file a bug).",
            target_name,
        )
        return

    def desktop_prompt(
        command: str,
        description: str,
        timeout_seconds: int | None = None,  # noqa: ARG001 - kept for signature compat
        allow_permanent: bool = True,        # noqa: ARG001
        approval_callback: Any = None,       # noqa: ARG001
    ) -> str:
        return _ask_tauri(command, description)

    setattr(approval, target_name, desktop_prompt)
    log.info("approval bridge installed -> Tauri modal")
