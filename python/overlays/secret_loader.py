"""Load the LLM API key from the Tauri shell, never from disk.

The Tauri shell holds the user's API key in Windows Credential Manager
(via the keyring plugin). At Python launch, Tauri spawns us with a
single one-shot HMAC-keyed handshake URL exposed only on loopback. We
fetch the secret over that URL exactly once at process start, set it
into the appropriate environment variables Hermes already reads, and
then forget the URL.

This avoids ever touching disk with the plaintext secret.

Env wired by Tauri:

    HERMESDESK_SECRET_URL    http://127.0.0.1:PORT/secret/<token>
    HERMESDESK_PROVIDER      openrouter | openai | anthropic | nous | ...

The matching env var Hermes reads is derived by `_PROVIDER_ENV` below.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("hermesdesk.secret")


_PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "nous":       "NOUS_PORTAL_API_KEY",
    "groq":       "GROQ_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "fireworks":  "FIREWORKS_API_KEY",
    "together":   "TOGETHER_API_KEY",
    "google":     "GOOGLE_API_KEY",
    "xai":        "XAI_API_KEY",
}


def install() -> None:
    url = os.environ.pop("HERMESDESK_SECRET_URL", None)
    provider = os.environ.get("HERMESDESK_PROVIDER", "").lower()
    if not url or not provider:
        log.info("no secret handshake URL; assuming dev mode (env-provided keys)")
        return

    env_name = _PROVIDER_ENV.get(provider)
    if not env_name:
        log.warning("unknown provider %r; secret left unfetched", provider)
        return

    # IMPORTANT: this fetch happens BEFORE network_allowlist installs, so
    # we use stdlib urllib (no httpx wrapping yet). Loopback only.
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=5) as resp:  # nosec - loopback
            secret = resp.read().decode("utf-8").strip()
    except Exception:
        log.exception("failed to fetch secret from Tauri")
        raise SystemExit(2)

    if not secret:
        raise SystemExit("HermesDesk: empty secret returned by Tauri")

    os.environ[env_name] = secret
    log.info("secret loaded into %s (provider=%s)", env_name, provider)
