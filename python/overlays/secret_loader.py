"""Load the LLM API key from the Tauri shell, never from disk.

# DEPRECATED: secret_store.remove_when=Phase4
# Target replacement: ``python/src/secret_store.py``

The Tauri shell holds the user's API key in Windows Credential Manager
(via the keyring plugin). At Python launch, Tauri spawns us with a
single one-shot HMAC-keyed handshake URL exposed only on loopback. We
fetch the secret over that URL exactly once at process start, set it
into the appropriate environment variables Hermes already reads, and
then forget the URL.

This avoids ever touching disk with the plaintext secret.

The secret-fetching logic is delegated to
``python/src/secret_store.py`` (Phase 3B).  This overlay is now a
thin wrapper.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("hermesdesk.secret")

try:
    from secret_store import SecretStore  # type: ignore[import-untyped]
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from secret_store import SecretStore  # type: ignore[import-untyped]


def install() -> None:
    store = SecretStore()
    store.fetch()
