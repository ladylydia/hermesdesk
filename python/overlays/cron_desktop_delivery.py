"""Route cron job output to the desktop instead of dropping it on the floor.

Upstream behavior:
    cron jobs with ``deliver="local"`` (the default) call ``_deliver_result``,
    which calls ``_resolve_delivery_targets`` and gets back ``[]``, then
    silently returns — agent output goes to the void.  Output is still saved
    to ``cron/output/{job_id}/{ts}.md`` for posterity, but the user never
    sees it.

For HermesDesk we want every cron firing to surface in the /chat window and
fire a Windows toast.  The cleanest hook is ``cron.scheduler._deliver_result``:
we wrap it so that for ``deliver in {"local", "desktop", ""}`` we POST to the
Tauri desktop_delivery bridge.  Any non-local target (telegram, feishu, …) is
forwarded to the original implementation unchanged.

This overlay is lazy: ``cron.scheduler`` is part of the bundled hermes tree,
which only becomes importable after ``desktop_entrypoint._wire_sys_path``.
``apply_all()`` installs us once early (best-effort, may fail) and the
entrypoint re-runs ``install()`` after sys.path is wired.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("hermesdesk.cron.delivery")

_INSTALLED = False


def _resolve_desktop_targets(deliver_value: str) -> tuple[bool, str]:
    """Decide whether this delivery should also fire a desktop notification.

    Returns ``(should_deliver_to_desktop, remaining_targets_string)``.

    Rules:
      - ``""`` / ``"local"`` / ``"desktop"`` -> desktop only
      - ``"desktop, telegram:#foo"``         -> desktop AND telegram (return ``"telegram:#foo"``)
      - ``"telegram:#foo"``                  -> no desktop, full string forwarded
    """
    raw = (deliver_value or "").strip().lower()
    if raw in ("", "local", "desktop"):
        return True, ""

    parts = [p.strip() for p in deliver_value.split(",") if p.strip()]
    desktop_seen = False
    others: list[str] = []
    for p in parts:
        head = p.split(":", 1)[0].strip().lower()
        if head in ("local", "desktop"):
            desktop_seen = True
        else:
            others.append(p)
    return desktop_seen, ", ".join(others)


def install() -> None:
    """Wrap ``cron.scheduler._deliver_result`` to also fire desktop notifications."""
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from cron import scheduler as _sched  # type: ignore[import-untyped]
    except ImportError:
        log.debug("cron.scheduler not importable yet; will retry from desktop_entrypoint")
        return

    if not hasattr(_sched, "_deliver_result"):
        log.warning(
            "cron.scheduler._deliver_result missing; upstream API may have "
            "changed. Desktop cron delivery disabled."
        )
        return

    # Resolve the desktop_delivery helper. python/src/ is on sys.path either
    # because build_bundle copies it next to desktop_entrypoint.py (release)
    # or because we add it here (dev).
    try:
        from desktop_delivery import deliver as _desktop_deliver  # type: ignore[import-untyped]
    except ImportError:
        _src = str(Path(__file__).resolve().parent.parent / "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)
        try:
            from desktop_delivery import deliver as _desktop_deliver  # type: ignore[import-untyped]
        except ImportError:
            log.warning("desktop_delivery module unavailable; skipping cron delivery overlay")
            return

    _orig_deliver_result = _sched._deliver_result

    def _patched_deliver_result(job: dict, content: str, adapters: Any = None, loop: Any = None):
        """Run desktop delivery first, then forward any remaining remote targets."""
        deliver_value = str(job.get("deliver", "local") or "local")
        desktop_wanted, remaining = _resolve_desktop_targets(deliver_value)

        desktop_error: str | None = None
        if desktop_wanted:
            try:
                title = job.get("name") or f"Cron Job ({job.get('id', '')})"
                ok = _desktop_deliver(message=str(content), title=str(title))
                if not ok:
                    desktop_error = "desktop bridge returned ok=false"
                    log.warning("Job '%s': desktop delivery failed", job.get("id", "?"))
                else:
                    log.info("Job '%s': delivered to desktop", job.get("id", "?"))
            except Exception as e:
                desktop_error = f"desktop delivery error: {e}"
                log.exception("Job '%s': desktop delivery raised", job.get("id", "?"))

        if not remaining:
            # Pure desktop delivery — return error if any, else success.
            return desktop_error

        # Mutate a *copy* of the job so the upstream codepath thinks the user
        # only configured the remote targets. (We must not mutate the caller's
        # job dict — the scheduler holds it for state updates.)
        forwarded_job = dict(job)
        forwarded_job["deliver"] = remaining
        try:
            remote_error = _orig_deliver_result(forwarded_job, content, adapters=adapters, loop=loop)
        except Exception as e:
            log.exception("Job '%s': upstream _deliver_result raised on remote targets", job.get("id", "?"))
            remote_error = f"remote delivery error: {e}"

        # Combine errors: prefer remote (more actionable) but include desktop
        # status if both failed.
        if remote_error and desktop_error:
            return f"{remote_error}; also: {desktop_error}"
        return remote_error or desktop_error

    _sched._deliver_result = _patched_deliver_result
    _INSTALLED = True
    log.info("cron desktop-delivery overlay installed")
