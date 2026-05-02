"""Teach the main agent about HermesDesk power-user mode and permission UX.

`default_toolset.py` removes `terminal` / `browser` / `code_execution` / `moa` from
the CLI tool list when the user is not a power user. The model must still
*realize* those capabilities are absent, and when the user asks for a shell, local
browser automation, sandbox code execution, or similar, it should explain that
enabling “Power user mode” in the HermesDesk shell settings is required — not
hallucinate the tools.
"""

from __future__ import annotations

import logging
import os
from typing import Set

log = logging.getLogger("hermesdesk.desk_prompt")

_INSTALLED = False


def _is_desk() -> bool:
    return bool(os.environ.get("HERMESDESK_BUNDLE_DIR"))


def _has_power_user_style_tools(names: Set[str]) -> bool:
    """True if the session can call tools that are only enabled in power mode."""
    if "terminal" in names or "execute_code" in names or "mixture_of_agents" in names:
        return True
    return any(n.startswith("browser_") for n in names)


def _block_power_off() -> str:
    return (
        "## HermesDesk (desktop app)\n\n"
        "You are running inside the **HermesDesk** app (a Windows shell that hosts this UI). "
        "For this session, **power user / advanced mode is off**: you do not have the "
        "`terminal` tool, `browser_*` tools, `execute_code`, or `mixture_of_agents` in your tool list.\n\n"
        "If the user asks for shell/terminal commands, local browser control, ad‑hoc code "
        "execution, or other actions that require those tools, you **must not** pretend the "
        "tools are available. Say clearly you cannot in the current mode, and direct them: "
        "open the **HermesDesk** window (this app) → **Settings** (设置) → turn on **Power user mode** "
        "(高级用户模式), accept the dialog, and wait a few seconds for the helper to restart, "
        "then try again. Repeat this when the same class of request comes up. "
        "If part of the work is still possible with the tools you do have (e.g. files, web, todo), do that and state the limit."
    )


def _block_power_on() -> str:
    return (
        "## HermesDesk (desktop app)\n\n"
        "You are running **locally** on the user's Windows machine inside the "
        "HermesDesk desktop application. The `terminal` tool executes commands "
        "natively on Windows (cmd.exe), not in WSL or a remote server. "
        "When you see kernel names like \"WSL2\" or \"microsoft-standard\", "
        "those come from the machine's WSL subsystem which is separate from "
        "your execution environment.\n\n"
        "**Power user mode is on** for this session: terminal, browser, code, and/or mixture-of-agents tools "
        "may appear in your tool list. The user or system can still require confirmation for risky steps — "
        "only claim such actions were taken when you have a real successful tool result."
    )


def install() -> None:
    """Wrap `AIAgent._build_system_prompt` once. Call only after `run_agent` is importable."""
    global _INSTALLED
    if _INSTALLED:
        return
    if not _is_desk():
        return
    try:
        from run_agent import AIAgent
    except Exception as e:  # pragma: no cover
        log.warning("desk_system_prompt: import run_agent failed: %s", e)
        return

    if getattr(AIAgent, "_hermesdesk_desk_system_prompt", False):
        return

    _orig = AIAgent._build_system_prompt

    def _wrapped(self, system_message: str = None) -> str:
        base = _orig(self, system_message)
        if not _is_desk():
            return base
        try:
            names = self.valid_tool_names
        except Exception:  # pragma: no cover
            names = set()
        if _has_power_user_style_tools(names if isinstance(names, (set, frozenset)) else set(names or ())):
            extra = _block_power_on()
        else:
            extra = _block_power_off()
        if not (base and str(base).strip()):
            return extra
        return f"{str(base).rstrip()}\n\n{extra}"

    AIAgent._build_system_prompt = _wrapped
    AIAgent._hermesdesk_desk_system_prompt = True
    _INSTALLED = True
    log.info("desk_system_prompt: installed AIAgent._build_system_prompt wrap")
