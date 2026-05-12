"""ToolPolicy — resolve active toolset list from runtime mode.

Extracted from ``overlays/default_toolset.py``.
Target replacement: policy-driven toolset resolution.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("hermesdesk.toolset")

KEEP_LIST = [
    "web", "file", "vision", "image_gen", "tts", "skills", "todo", "browser",
    "cronjob",    # scheduled tasks (create-once-approve, then auto-run)
    "messaging",  # cross-channel message delivery (cron delivery + proactive send)
]
POWER_USER_EXTRA = ["terminal", "code_execution", "moa"]
GATEWAY_KEEP_LIST = [
    "web", "file", "vision", "image_gen", "tts", "skills", "todo", "browser",
    "cronjob",
    "messaging",
]


class ToolPolicy:
    """Map a runtime mode to the list of active toolsets."""

    @staticmethod
    def resolve(power_user: bool) -> list[str]:
        if power_user:
            return KEEP_LIST + POWER_USER_EXTRA
        return list(KEEP_LIST)

    @staticmethod
    def is_power_user() -> bool:
        return os.environ.get("HERMESDESK_POWER_USER") == "1"

    @staticmethod
    def gateway_keep_list() -> list[str]:
        return list(GATEWAY_KEEP_LIST)
