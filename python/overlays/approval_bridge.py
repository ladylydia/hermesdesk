"""Route Hermes' shell-command / messaging / cron-approval to Tauri-native modals.

# DEPRECATED: approval_backend.remove_when=Phase4
# Target replacement: ``python/src/approval_backend.py``

Hermes' approval system lives in ``tools/approval.py``. The CLI flow
prints a yes/no prompt to stdout and reads ``input()`` (see
``prompt_dangerous_approval`` in upstream). In a desktop app there is
no terminal, so we replace that function with one that POSTs the
request to the Tauri shell over loopback and blocks until the user
clicks Allow / Deny in a native Tauri WebView dialog.

Since the HermesDesk scheduled-tasks feature, this overlay ALSO wraps
``send_message_tool`` and ``cronjob`` so that:

  - Remote sends (telegram, feishu, …) show a Tauri approval dialog (standard user).
  - Cron job creation shows a Tauri approval dialog (standard user).
  - Desktop-local sends and cron-triggered delivery skip the dialog.

Default policy: deny. No "always allow" persistence in v1 — the user
must re-confirm every dangerous command. This is intentionally more
strict than upstream because most HermesDesk users are non-technical.

The approval-handshake logic + messaging policy are delegated to
``python/src/approval_backend.py`` + ``python/src/messaging_policy.py``.
This overlay only installs the monkey-patches.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("hermesdesk.approval")

try:
    from approval_backend import ApprovalBackend
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from approval_backend import ApprovalBackend

_backend = ApprovalBackend()

_APPROVAL_BRIDGE = "approval_bridge"


def _ask_tauri(command: str, description: str) -> str:
    return _backend.ask(command, description)


# ------------------------------------------------------------------
# Shell approval (existing)
# ------------------------------------------------------------------

def install() -> None:
    _install_shell_approval()
    _install_messaging_wraps()


def _install_shell_approval() -> None:
    try:
        from tools import approval  # type: ignore
    except ImportError:
        log.debug("tools.approval not present (no power-user tools); skip")
        return

    target_name = "prompt_dangerous_approval"
    if not hasattr(approval, target_name):
        log.warning(
            "tools.approval.%s missing; upstream API may have changed. "
            "HermesDesk will fall back to upstream prompt (which will hang "
            "in a desktop context — please file a bug).",
            target_name,
        )
        return

    def desktop_prompt(
        command: str,
        description: str,
        timeout_seconds: int | None = None,  # noqa: ARG001
        allow_permanent: bool = True,        # noqa: ARG001
        approval_callback: Any = None,       # noqa: ARG001
    ) -> str:
        return _ask_tauri(command, description)

    setattr(approval, target_name, desktop_prompt)
    log.info("approval bridge installed -> Tauri modal")


# ------------------------------------------------------------------
# Messaging + cron approval wraps
# ------------------------------------------------------------------

def _install_messaging_wraps() -> None:
    """Wrap send_message_tool and cronjob with Tauri approval dialogs.

    Called twice: once during overlay application (likely before
    ``hermes/`` is on sys.path — fails quietly), and again after
    ``_wire_sys_path()`` in ``desktop_entrypoint.py`` where imports
    succeed.
    """
    try:
        from messaging_policy import get_policy, expand_cron_default_deliver
    except ImportError:
        log.debug("messaging_policy not importable; skip messaging wraps")
        return

    policy = get_policy()

    # -- wrap send_message_tool -------------------------------------------------
    try:
        import tools.send_message_tool as _smt  # type: ignore

        _orig_send = _smt.send_message_tool

        def _wrapped_send_message_tool(args: dict, **kw: object) -> Any:
            target = str(args.get("target", "") or "")
            if policy.needs_messaging_approval(target):
                platform = _extract_platform(target)
                content = str(args.get("message", "") or args.get("content", "") or "")
                attaches = args.get("attachments") or args.get("media_files") or []
                result = _backend.ask_messaging(
                    target=target,
                    content_preview=str(content)[:500],
                    attachments=list(attaches) if isinstance(attaches, (list, tuple)) else [],
                )
                if result != "once":
                    return {"error": "User denied the messaging request."}
                policy.record_messaging_allow(target)

            return _orig_send(args, **kw)

        _smt.send_message_tool = _wrapped_send_message_tool

        # Also patch the registry entry so it picks up the wrapped handler.
        try:
            from tools.registry import registry
            entry = registry.get("send_message")
            if entry is not None:
                entry.handler = _wrapped_send_message_tool
                log.info("registry[send_message] handler wrapped")
        except Exception:
            log.debug("registry update for send_message skipped", exc_info=True)

        log.info("send_message_tool wrapped with approval bridge")

    except ImportError:
        log.debug("tools.send_message_tool not importable; skip messaging wrap")

    # -- wrap cronjob handler ---------------------------------------------------
    try:
        import tools.cronjob_tools as _cjt  # type: ignore

        _orig_cronjob = _cjt.cronjob

        def _wrapped_cronjob(
            action: str = "",
            job_id: str | None = None,
            prompt: str | None = None,
            schedule: str | None = None,
            name: str | None = None,
            repeat: int | None = None,
            deliver: str | None = None,
            include_disabled: bool = False,
            skill: str | None = None,
            skills: list[str] | None = None,
            model: str | None = None,
            provider: str | None = None,
            base_url: str | None = None,
            reason: str | None = None,
            script: str | None = None,
            context_from: str | list[str] | None = None,
            enabled_toolsets: list[str] | None = None,
            workdir: str | None = None,
            task_id: str | None = None,
        ) -> str:
            # Q2 smart default: for create/update with no explicit remote
            # target, fan-out to desktop + every configured home channel.
            # The expansion happens BEFORE approval so the dialog shows the
            # final target list.
            normalized_action = (action or "").strip().lower()
            if normalized_action in ("create", "update"):
                deliver = expand_cron_default_deliver(deliver)

            if policy.needs_cron_approval(action):
                result = _backend.ask_cron(
                    action=action or "",
                    schedule=schedule or "",
                    description=(prompt or name or ""),
                    delivery_target=deliver or "",
                )
                if result != "once":
                    return '{"error": "User denied the scheduled task."}'

            return _orig_cronjob(
                action=action,
                job_id=job_id,
                prompt=prompt,
                schedule=schedule,
                name=name,
                repeat=repeat,
                deliver=deliver,
                include_disabled=include_disabled,
                skill=skill,
                skills=skills,
                model=model,
                provider=provider,
                base_url=base_url,
                reason=reason,
                script=script,
                context_from=context_from,
                enabled_toolsets=enabled_toolsets,
                workdir=workdir,
                task_id=task_id,
            )

        _cjt.cronjob = _wrapped_cronjob

        # Also patch the registry entry.
        try:
            from tools.registry import registry
            entry = registry.get("cronjob")
            if entry is not None:
                # The cronjob registry handler is a lambda wrapping cronjob().
                # Re-create it with the wrapped function.
                def _wrapped_handler(args, **kw):
                    from tools.cronjob_tools import _resolve_model_override
                    try:
                        _resolve = _resolve_model_override
                    except Exception:
                        _resolve = lambda x: (None, None)
                    mo = _resolve(args.get("model"))
                    return _wrapped_cronjob(
                        action=args.get("action", ""),
                        job_id=args.get("job_id"),
                        prompt=args.get("prompt"),
                        schedule=args.get("schedule"),
                        name=args.get("name"),
                        repeat=args.get("repeat"),
                        deliver=args.get("deliver"),
                        include_disabled=args.get("include_disabled", True),
                        skill=args.get("skill"),
                        skills=args.get("skills"),
                        model=mo[1] if len(mo) > 1 else args.get("model"),
                        provider=mo[0] if len(mo) > 0 else args.get("provider"),
                        base_url=args.get("base_url"),
                        reason=args.get("reason"),
                        script=args.get("script"),
                        context_from=args.get("context_from"),
                        enabled_toolsets=args.get("enabled_toolsets"),
                        workdir=args.get("workdir"),
                        task_id=kw.get("task_id"),
                    )
                entry.handler = _wrapped_handler
                log.info("registry[cronjob] handler wrapped")
        except Exception:
            log.debug("registry update for cronjob skipped", exc_info=True)

        log.info("cronjob wrapped with approval bridge")

    except ImportError:
        log.debug("tools.cronjob_tools not importable; skip cronjob wrap")


def _extract_platform(target: str) -> str:
    t = (target or "").strip()
    if ":" in t:
        return t.split(":", 1)[0].lower()
    return t.lower()
