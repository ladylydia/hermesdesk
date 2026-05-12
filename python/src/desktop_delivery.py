"""Desktop delivery — POST messages to the Tauri shell for local display.

This is HermesDesk's "desktop" virtual messaging platform.  When a user
(or a cron job) sends a message to ``target="desktop"``, it lands here:
the payload is POSTed to a loopback endpoint on the Tauri bridge, which
writes it into the /chat message stream and fires a Windows notification.

No network egress, no third-party service — local-only delivery.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger("hermesdesk.desktop.delivery")


def deliver(message: str, title: str = "", attachments: list[str] | None = None) -> bool:
    """Deliver a message to the desktop (Tauri /chat + Windows notification).

    Returns True on success.
    """
    url = os.environ.get("HERMESDESK_DESKTOP_DELIVERY_URL")
    if not url:
        log.warning("HERMESDESK_DESKTOP_DELIVERY_URL not set; cannot deliver")
        return False

    payload = json.dumps({
        "message": message,
        "title": title or "Kabuqina",
        "attachments": attachments or [],
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec - loopback
            body = json.loads(resp.read())
            ok = bool(body.get("ok"))
            if ok:
                log.info("desktop delivery: ok (title=%r, len=%d)", title, len(message))
            else:
                log.warning("desktop delivery: bridge returned ok=false")
            return ok
    except urllib.error.URLError:
        log.exception("desktop delivery: bridge unreachable")
        return False
    except Exception:
        log.exception("desktop delivery: unexpected error")
        return False
