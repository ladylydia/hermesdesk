"""MessagingPolicy — decide whether a send_message or cronjob call needs approval.

Decisions match the product spec (``docs/定时任务开发方案.md``):

+-------------------------------+----------------+---------------+
| Scenario                      | Standard User  | Power User    |
+-------------------------------+----------------+---------------+
| send_message to ``desktop``   | auto-allow     | auto-allow    |
| send_message to remote target | ask (per-sesh) | auto-allow    |
| cronjob create/update         | ask (one-time) | auto-allow    |
| cronjob delete                | auto-allow     | auto-allow    |
| cronjob list/run              | auto-allow     | auto-allow    |
| cron-triggered send_message   | auto-allow     | auto-allow    |
+-------------------------------+----------------+---------------+

Per-session cache: a standard user who clicks "Allow for this target this session"
won't be re-prompted for the same platform+target combo until restart.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("hermesdesk.policy.messaging")


class MessagingPolicy:
    """Approval gate for send_message and cronjob calls."""

    def __init__(self) -> None:
        # (target, platform) → expiry timestamp (0 = session-lifetime)
        self._session_allow: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def is_power_user(self) -> bool:
        return os.environ.get("HERMESDESK_POWER_USER") == "1"

    def is_cron_context(self) -> bool:
        """True when the current agent invocation is a cron-triggered run.

        Set by the cron scheduler runner before firing a job so that
        delivery-phase send_message calls skip approval (they were already
        approved at cron-creation time).
        """
        return os.environ.get("HERMES_CRON_CONTEXT") == "1"

    # ------------------------------------------------------------------
    # send_message
    # ------------------------------------------------------------------

    def needs_messaging_approval(self, target: str) -> bool:
        """Return True if this send_message MUST show a Tauri dialog."""
        if self.is_power_user():
            return False
        if self.is_cron_context():
            return False
        platform = _extract_platform(target)
        if platform == "desktop":
            return False  # local delivery — never a risk
        key = (target, platform)
        with self._lock:
            expiry = self._session_allow.get(key)
            if expiry is not None and (expiry == 0 or time.monotonic() < expiry):
                return False
        return True

    def record_messaging_allow(self, target: str) -> None:
        """Mark a target as approved for this session."""
        platform = _extract_platform(target)
        with self._lock:
            self._session_allow[(target, platform)] = 0  # 0 = session lifetime

    # ------------------------------------------------------------------
    # cronjob
    # ------------------------------------------------------------------

    def needs_cron_approval(self, action: str) -> bool:
        """Return True if this cronjob call MUST show a Tauri dialog."""
        if self.is_power_user():
            return False
        normalized = (action or "").strip().lower()
        if normalized in ("list", "run", "delete", "remove", "pause", "resume"):
            return False  # read-only / manual trigger / cleanup
        if normalized in ("create", "update"):
            return True
        # Unknown actions: be safe — ask.
        return True


# ------------------------------------------------------------------
# module-level singleton
# ------------------------------------------------------------------

_policy: Optional[MessagingPolicy] = None
_lock = threading.Lock()


def get_policy() -> MessagingPolicy:
    global _policy
    if _policy is None:
        with _lock:
            if _policy is None:
                _policy = MessagingPolicy()
    return _policy


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def expand_cron_default_deliver(current_deliver: Optional[str]) -> str:
    """Expand a "default" cron deliver target into ``desktop + all home channels``.

    Product decision (Q2: smart default): if the agent doesn't explicitly
    target a remote platform, fan-out to desktop AND every messaging channel
    the user has configured a home channel for (Telegram, Discord, Slack, ...).
    The user can still narrow it: ``deliver="telegram"`` is respected as-is.

    Triggers expansion when ``current_deliver`` is one of:
      - ``None`` / empty string  (agent didn't specify)
      - ``"local"`` / ``"desktop"``  (legacy local-only marker)

    Otherwise returns ``current_deliver`` unchanged.
    """
    raw = (current_deliver or "").strip().lower()
    if raw not in ("", "local", "desktop"):
        return current_deliver  # type: ignore[return-value]

    parts: list[str] = ["desktop"]

    try:
        from gateway.config import load_gateway_config  # type: ignore[import-untyped]

        cfg = load_gateway_config()
        for platform_enum, pconfig in cfg.platforms.items():
            if not getattr(pconfig, "enabled", True):
                continue
            if not getattr(pconfig, "home_channel", None):
                continue
            name = getattr(platform_enum, "value", str(platform_enum)).lower()
            if name and name not in parts:
                parts.append(name)
    except Exception:
        # Gateway config not available — desktop-only is a safe default.
        log.debug("expand_cron_default_deliver: gateway.config unavailable", exc_info=True)

    expanded = ", ".join(parts)
    if len(parts) > 1:
        log.info("cron deliver: expanded default → %s", expanded)
    return expanded


def _extract_platform(target: str) -> str:
    """Extract the platform portion from a target string.

    ``telegram:#channel`` → ``telegram``
    ``desktop``           → ``desktop``
    ``feishu:oc_xxx``    → ``feishu``
    """
    t = (target or "").strip()
    if not t:
        return ""
    if ":" in t:
        return t.split(":", 1)[0].lower()
    return t.lower()
