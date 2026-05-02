"""ApprovalBackend — POST shell-command approval requests to Tauri bridge.

Extracted from ``overlays/approval_bridge.py``.
Target replacement: injected policy instead of monkey-patching
``tools/approval.prompt_dangerous_approval``.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger("hermesdesk.approval")


class ApprovalBackend:
    """Route dangerous-command approvals to a Tauri native dialog."""

    def ask(self, command: str, description: str = "") -> str:
        """Return 'once' if allowed, 'deny' otherwise."""
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
