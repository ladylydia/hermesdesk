"""Network egress allowlist (m4).

# DEPRECATED: network_policy.remove_when=Phase4
# Target replacement: ``python/src/network_policy.py``

By default we allow only:

  - 127.0.0.1 / localhost   (Hermes' own web_server)
  - The configured LLM provider host
  - A small fixed allowlist (skill hub, Edge TTS)

Implemented by patching httpx (used by Hermes core) and requests
(used by some tools). Every outbound request is checked against the
allowlist; non-matching requests raise a clear error.

Power-user mode disables the allowlist entirely (HERMESDESK_NET_OPEN=1).

The host-checking logic is delegated to
``python/src/network_policy.py`` (Phase 3C).  This overlay only
installs the httpx / requests monkey-patches.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("hermesdesk.net")

try:
    from network_policy import NetworkPolicy  # type: ignore[import-untyped]
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from network_policy import NetworkPolicy  # type: ignore[import-untyped]

_policy: NetworkPolicy | None = None


def _check_url(url: str) -> None:
    if os.environ.get("HERMESDESK_NET_OPEN") == "1":
        return
    if _policy is not None:
        try:
            _policy.check_url(url)
            return
        except PermissionError:
            pass
    # Fallback logic (should not be reachable after policy is loaded)
    host = (urlparse(url).hostname or "").lower()
    if not host or host.endswith(".localhost"):
        return
    if host in {"localhost", "127.0.0.1"} or host.startswith("127.") or host == "::1":
        return
    raise PermissionError(
        f"HermesDesk: outbound request to {host!r} blocked by network allowlist."
    )


def install() -> None:
    global _policy
    _policy = NetworkPolicy(
        llm_host=os.environ.get("HERMESDESK_LLM_HOST", ""),
        extra_hosts=os.environ.get("HERMESDESK_EXTRA_HOSTS", ""),
    )
    try:
        import httpx
    except ImportError:
        return

    _orig_send = httpx.Client.send
    _orig_asend = httpx.AsyncClient.send

    def safe_send(self, request, *args, **kwargs):
        _check_url(str(request.url))
        return _orig_send(self, request, *args, **kwargs)

    async def safe_asend(self, request, *args, **kwargs):
        _check_url(str(request.url))
        return await _orig_asend(self, request, *args, **kwargs)

    httpx.Client.send = safe_send  # type: ignore[assignment]
    httpx.AsyncClient.send = safe_asend  # type: ignore[assignment]

    try:
        import requests  # noqa
        from requests.adapters import HTTPAdapter

        _orig_req_send = HTTPAdapter.send

        def safe_req_send(self, request, *args, **kwargs):
            _check_url(request.url)
            return _orig_req_send(self, request, *args, **kwargs)

        HTTPAdapter.send = safe_req_send  # type: ignore[assignment]
    except ImportError:
        pass

    log.info("network allowlist installed; allowed=%s", sorted(_policy.allowed_hosts))
