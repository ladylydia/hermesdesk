"""Route Hermes' shell-command approval to a Tauri-native modal.

Hermes' approval system lives in ``tools/approval.py``. The CLI flow
prints a yes/no prompt to stdout and reads ``input()`` (see
``prompt_dangerous_approval`` in upstream). In a desktop app there is
no terminal, so we replace that function with one that POSTs the
request to the Tauri shell over loopback and blocks until the user
clicks Allow / Deny in a native Tauri WebView dialog.

Default policy: deny. No "always allow" persistence in v1 — the user
must re-confirm every dangerous command. This is intentionally more
strict than upstream because most HermesDesk users are non-technical.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

log = logging.getLogger("hermesdesk.approval")


def _ask_tauri(command: str, description: str) -> str:
    """Return one of: 'once', 'session', 'always', 'deny'.

    HermesDesk maps Tauri's two-choice dialog (Allow / Deny) onto
    `'once'` and `'deny'`. We never auto-promote to session/always; the
    user must explicitly re-confirm every dangerous command.
    """
    url = os.environ.get("HERMESDESK_APPROVAL_URL")
    if not url:
        log.warning("no HERMESDESK_APPROVAL_URL; denying command %r", command)
        return "deny"

    payload = json.dumps({
        "command": command,
        "description": description,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:  # nosec - loopback
            body = json.loads(resp.read())
            return "once" if bool(body.get("allowed")) else "deny"
    except urllib.error.URLError:
        log.exception("approval bridge unreachable; denying")
        return "deny"
    except Exception:
        log.exception("approval bridge error; denying")
        return "deny"


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
