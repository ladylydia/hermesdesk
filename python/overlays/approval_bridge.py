"""Route Hermes' shell-command approval to a Tauri-native modal.

Hermes already has an approval system in `tools/approval.py` that gates
shell commands behind a yes/no prompt printed to the terminal. In a
desktop app there is no terminal — we need a real Windows dialog.

We replace the approval prompt function with one that POSTs the request
to the Tauri shell over loopback and blocks until the user clicks
Allow / Deny in a native Tauri WebView dialog.

Default policy: deny. No "always allow" persistence.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

log = logging.getLogger("hermesdesk.approval")


def _ask_tauri(command: str, cwd: str, reason: str) -> bool:
    url = os.environ.get("HERMESDESK_APPROVAL_URL")
    if not url:
        # No bridge configured -> default-deny.
        log.warning("no HERMESDESK_APPROVAL_URL; denying command %r", command)
        return False

    payload = json.dumps({
        "command": command,
        "cwd": cwd,
        "reason": reason,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:  # nosec - loopback
            body = json.loads(resp.read())
            return bool(body.get("allowed"))
    except urllib.error.URLError:
        log.exception("approval bridge unreachable; denying")
        return False
    except Exception:
        log.exception("approval bridge error; denying")
        return False


def install() -> None:
    # tools/approval.py is only loaded if a power-user shell tool is enabled.
    # We patch lazily so the import doesn't fail when the module isn't shipped.
    try:
        from tools import approval  # type: ignore
    except ImportError:
        log.debug("tools.approval not present (no power-user tools); skip")
        return

    # Replace whatever interactive prompt function approval.py exposes.
    # Upstream API surface as of v0.10.0 includes `prompt_user_for_command(...)`.
    target_names = (
        "prompt_user_for_command",
        "ask_user",
        "interactive_approval",
    )

    def desktop_prompt(command: str, cwd: str = ".", reason: str = "", **_: Any) -> bool:
        return _ask_tauri(command, cwd, reason)

    patched = False
    for name in target_names:
        if hasattr(approval, name):
            setattr(approval, name, desktop_prompt)
            patched = True
    if not patched:
        log.warning("approval module had no known prompt fn; commands will use upstream default")
    else:
        log.info("approval bridge installed -> Tauri modal")
