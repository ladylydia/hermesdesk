"""Seed Hermes' tool config to the HermesDesk keep-list.

Hermes selects the active toolsets by reading
``~/.hermes/config.yaml`` (under HERMES_HOME) at the
``platform_toolsets["cli"]`` key. The CLI's `hermes tools` configurator
maintains it interactively. There is no programmatic "default" function
to monkey-patch; the source of truth is the file.

For HermesDesk we *write* a deterministic config on first launch (and on
every launch when the Power-user toggle changes), so the user never has
to use `hermes tools` from a terminal they don't have.

The names below come from ``hermes_cli/tools_config.py:CONFIGURABLE_TOOLSETS``.

Default-on (safe, no shell, no code exec):
    web, file, vision, image_gen, tts, skills, todo

Power-user adds (only when HERMESDESK_POWER_USER=1):
    browser, terminal, code_execution, moa
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("hermesdesk.toolset")


KEEP_LIST = [
    "web",
    "file",
    "vision",
    "image_gen",
    "tts",
    "skills",
    "todo",
]

POWER_USER_EXTRA = [
    "browser",
    "terminal",
    "code_execution",
    "moa",
]


def _resolved_set() -> list[str]:
    if os.environ.get("HERMESDESK_POWER_USER") == "1":
        return KEEP_LIST + POWER_USER_EXTRA
    return list(KEEP_LIST)


def install() -> None:
    enabled = _resolved_set()

    try:
        from hermes_cli.config import load_config, save_config  # type: ignore
    except Exception as e:
        log.warning("hermes_cli.config not importable; skipping toolset seed (%s)", e)
        return

    try:
        cfg = load_config() or {}
    except Exception as e:
        log.warning("could not load existing config; starting fresh (%s)", e)
        cfg = {}

    pts = cfg.setdefault("platform_toolsets", {})
    current = pts.get("cli")

    # Only overwrite if missing or differs from desired set. This way the
    # user can still flip individual toolsets via the Settings UI later
    # without us stomping on it on every launch (the Settings UI must
    # also call this overlay's `install()` after writing).
    if current != enabled:
        pts["cli"] = enabled
        try:
            save_config(cfg)
            log.info("seeded platform_toolsets[cli] -> %s", enabled)
        except Exception as e:
            log.warning("could not save toolset config: %s", e)
    else:
        log.debug("toolset config already matches desired set")
