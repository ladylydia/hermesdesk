"""Force the default Hermes toolset to the HermesDesk keep-list.

Upstream `toolset_distributions.py` defines a number of presets
(`full`, `minimal`, `coding`, etc.). For HermesDesk we always want
the same curated set (see DECISIONS.md) unless the user has flipped
the Power-user toggle, in which case we add the dangerous ones back.

This overlay registers a new preset name `hermesdesk` and patches
the default-resolution function to return it.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("hermesdesk.toolset")


KEEP_LIST = (
    "file_operations",
    "file_tools",
    "web_tools",
    "image_generation_tool",
    "tts_tool",
    "transcription_tools",
    "memory_tool",
    "skills_tool",
    "todo_tool",
    "vision_tools",
    "clarify_tool",
)


POWER_USER_EXTRA = (
    "terminal_tool",
    "code_execution_tool",
    "browser_tool",
    "mcp_tool",
    "cronjob_tools",
    "delegate_tool",
)


def _resolved_set() -> tuple[str, ...]:
    if os.environ.get("HERMESDESK_POWER_USER") == "1":
        return KEEP_LIST + POWER_USER_EXTRA
    return KEEP_LIST


def install() -> None:
    try:
        import toolset_distributions  # type: ignore
    except ImportError:
        log.warning("toolset_distributions not importable; tools default unchanged")
        return

    enabled = _resolved_set()
    setattr(toolset_distributions, "HERMESDESK_DEFAULT", enabled)

    # Best-effort patches to known upstream entry points. These names are
    # checked at install time; if they don't exist we log and move on so
    # an upstream rename produces a warning instead of a crash.
    for fname in ("get_default_toolset", "default_toolset", "resolve_default"):
        if hasattr(toolset_distributions, fname):
            setattr(toolset_distributions, fname, lambda *a, **kw: list(enabled))
            log.info("patched toolset_distributions.%s -> %d tools", fname, len(enabled))
            return

    log.warning("no known toolset resolver function in toolset_distributions; "
                "verify after upstream bumps")
