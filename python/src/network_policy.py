"""NetworkPolicy — egress host allowlist.

Extracted from ``overlays/network_allowlist.py``.
Target replacement: injected policy that checks outbound hosts.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

log = logging.getLogger("hermesdesk.net")

DEFAULT_ALLOW: set[str] = {
    "localhost",
    "127.0.0.1",
    "speech.platform.bing.com",
    "agentskills.io",
    "raw.githubusercontent.com",
    "github.com",
    "api.github.com",
}


class NetworkPolicy:
    """Check whether an outbound URL is on the allowlist."""

    def __init__(self, *, llm_host: str = "", extra_hosts: str = "") -> None:
        self._allow = set(DEFAULT_ALLOW)
        for v in (llm_host, extra_hosts):
            for h in v.split(","):
                h = h.strip().lower()
                if h:
                    self._allow.add(h)

    def check_url(self, url: str) -> None:
        host = urlparse(url).hostname
        if host is None:
            raise PermissionError(
                f"HermesDesk network allowlist could not parse host from URL: {url}"
            )
        allow = host.lower() in self._allow
        # Allow bare IPs in RFC1918 if they match loopback (handled above).
        if not allow and host.startswith("127."):
            allow = True
        if not allow and host == "::1":
            allow = True
        if not allow:
            raise PermissionError(
                f"HermesDesk network allowlist blocked outbound request to {host}. "
                f"To grant access, add the host in Settings or enable "
                f"HERMESDESK_NET_OPEN=1."
            )

    @property
    def allowed_hosts(self) -> set[str]:
        return set(self._allow)
