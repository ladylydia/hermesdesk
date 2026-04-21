"""Network egress allowlist (m4).

By default we allow only:

  - 127.0.0.1 / localhost   (Hermes' own web_server)
  - The configured LLM provider host
  - A small fixed allowlist (skill hub, Edge TTS)

Implemented by patching httpx (used by Hermes core) and requests
(used by some tools). Every outbound request is checked against the
allowlist; non-matching requests raise a clear error.

Power-user mode disables the allowlist entirely (HERMESDESK_NET_OPEN=1).
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

log = logging.getLogger("hermesdesk.net")


# Hosts we always allow regardless of provider config.
DEFAULT_ALLOW = {
    "localhost",
    "127.0.0.1",
    "speech.platform.bing.com",   # Edge TTS
    "agentskills.io",              # skills hub
    "raw.githubusercontent.com",   # skills hub backing store
    "github.com",                  # skills hub repo metadata
    "api.github.com",
}


def _allowed_hosts() -> set[str]:
    extra = set()
    for v in (
        os.environ.get("HERMESDESK_LLM_HOST", ""),
        os.environ.get("HERMESDESK_EXTRA_HOSTS", ""),
    ):
        for h in v.split(","):
            h = h.strip().lower()
            if h:
                extra.add(h)
    return DEFAULT_ALLOW | extra


def _check_url(url: str) -> None:
    if os.environ.get("HERMESDESK_NET_OPEN") == "1":
        return
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        raise PermissionError(f"HermesDesk: could not parse URL {url!r}")
    if not host:
        return  # local relative paths
    if host.endswith(".localhost"):
        return
    allowed = _allowed_hosts()
    # exact match or one-level subdomain match (api.openrouter.ai matches openrouter.ai)
    if host in allowed:
        return
    for a in allowed:
        if host.endswith("." + a):
            return
    raise PermissionError(
        f"HermesDesk: outbound request to {host!r} blocked by network "
        f"allowlist. Add it under Settings -> Power user -> Network."
    )


def install() -> None:
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

    log.info("network allowlist installed; allowed=%s", sorted(_allowed_hosts()))
