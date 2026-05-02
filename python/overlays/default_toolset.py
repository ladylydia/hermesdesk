"""Seed Hermes' tool config to the HermesDesk keep-list.

# DEPRECATED: tool_policy.remove_when=Phase4
# Target replacement: ``python/src/tool_policy.py``

Hermes selects the active toolsets by reading
``~/.hermes/config.yaml`` (under HERMES_HOME) at the
``platform_toolsets["cli"]`` key. The CLI's `hermes tools` configurator
maintains it interactively. There is no programmatic "default" function
to monkey-patch; the source of truth is the file.

For HermesDesk we *write* a deterministic config on first launch (and on
every launch when the Power-user toggle changes), so the user never has
to use `hermes tools` from a terminal they don't have.

The toolset-resolution logic is delegated to
``python/src/tool_policy.py`` (Phase 3D).  This overlay only
writes the config file.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("hermesdesk.toolset")

try:
    from tool_policy import ToolPolicy  # type: ignore[import-untyped]
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from tool_policy import ToolPolicy  # type: ignore[import-untyped]


def _resolved_set() -> list[str]:
    return ToolPolicy.resolve(ToolPolicy.is_power_user())


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
