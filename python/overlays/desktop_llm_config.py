"""Pin default model / provider for HermesDesk from Tauri-provided env.

Hermes reads ``config.yaml`` ``model`` (string or dict). The shell passes:

    HERMESDESK_MODEL               optional default model id
    HERMESDESK_INFERENCE_PROVIDER  optional, e.g. ``custom`` for OpenAI-compatible URLs
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("hermesdesk.model")


def install() -> None:
    model = os.environ.get("HERMESDESK_MODEL", "").strip()
    inf = os.environ.get("HERMESDESK_INFERENCE_PROVIDER", "").strip()
    if not model and not inf:
        return

    try:
        from hermes_cli.config import load_config, save_config  # type: ignore
    except Exception as e:
        log.warning("hermes_cli.config not importable; skipping model seed (%s)", e)
        return

    try:
        cfg = load_config() or {}
    except Exception as e:
        log.warning("could not load config for model seed (%s)", e)
        cfg = {}

    if inf == "custom":
        cfg["model"] = {
            "default": model or "gpt-4o-mini",
            "provider": "custom",
        }
    elif model:
        prev = cfg.get("model")
        if isinstance(prev, dict):
            prev = {**prev, "default": model}
            cfg["model"] = prev
        else:
            cfg["model"] = model

    try:
        save_config(cfg)
        log.info("HermesDesk model seed applied (inference=%r model=%r)", inf, model)
    except Exception:
        log.exception("failed to save Hermes model seed")
