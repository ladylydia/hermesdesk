"""SecretStore — fetch the LLM API key from the Tauri loopback bridge.

Extracted from ``overlays/secret_loader.py``.
Target replacement: injected policy instead of env-var monkey-patching.
"""

from __future__ import annotations

import logging
import os
import urllib.request

log = logging.getLogger("hermesdesk.secret")

_PROVIDER_ENV: dict[str, str] = {
    "deepseek":   "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "custom":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "nous":       "NOUS_PORTAL_API_KEY",
    "groq":       "GROQ_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "fireworks":  "FIREWORKS_API_KEY",
    "together":   "TOGETHER_API_KEY",
    "google":     "GOOGLE_API_KEY",
    "xai":        "XAI_API_KEY",
}


class SecretStore:
    """One-shot fetch of the LLM API key from the Tauri loopback bridge."""

    def fetch(self) -> str | None:
        url = os.environ.pop("HERMESDESK_SECRET_URL", None)
        provider = os.environ.get("HERMESDESK_PROVIDER", "").lower()
        log.info("secret_loader: url=%r provider=%r", url, provider)
        if not url or not provider:
            log.info("no secret handshake URL; assuming dev mode (env-provided keys)")
            return None

        env_name = _PROVIDER_ENV.get(provider)
        if not env_name:
            log.warning("unknown provider %r; secret left unfetched", provider)
            return None

        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=5) as resp:  # nosec - loopback
                secret = resp.read().decode("utf-8").strip()
        except Exception:
            log.exception("failed to fetch secret from Tauri")
            raise SystemExit(2)

        if not secret:
            log.info("no secret yet (provider=%s); awaiting onboarding wizard", provider)
            return None

        os.environ[env_name] = secret
        log.info("secret loaded into %s (provider=%s)", env_name, provider)

        api_base = os.environ.get("HERMESDESK_API_BASE_URL", "").strip()
        if api_base:
            os.environ["OPENAI_BASE_URL"] = api_base.rstrip("/")

        inf = os.environ.get("HERMESDESK_INFERENCE_PROVIDER", "").strip()
        if inf:
            os.environ["HERMES_INFERENCE_PROVIDER"] = inf

        return secret
