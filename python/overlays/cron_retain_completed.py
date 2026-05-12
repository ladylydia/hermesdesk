"""Keep one-shot cron jobs around after they fire instead of deleting them.

Upstream (`cron.jobs.mark_job_run`) deletes a job from ``jobs.json`` the moment
its ``repeat.times`` limit is reached.  That makes sense for headless servers
running thousands of jobs, but in HermesDesk the user just asked Kabuqina to
"remind me in 1 minute" and got the reminder — they expect to see "this fired"
somewhere, not just a silently-empty list.

This overlay rewrites that branch: instead of popping the job, we mark it as
``state="completed"``, ``enabled=False``, and stamp ``completed_at``.  The
``cron_scheduler_runner`` periodically prunes anything older than 7 days.

The ticker's "is this job due?" check already filters by ``enabled=True``, so
completed jobs are inert — they just sit in jobs.json for the UI to render.

IMPORTANT — the ``from X import Y`` trap
----------------------------------------
``cron.scheduler`` does ``from cron.jobs import mark_job_run`` at module
load, which binds the original function into ``cron.scheduler``'s namespace.
Patching ``cron.jobs.mark_job_run`` AFTER scheduler is loaded does NOT
update that binding — ``tick()`` would keep calling the original.

So this overlay patches BOTH module-level names. ``install()`` is idempotent
and re-callable: the first call (early, from ``apply_all``) patches
``cron.jobs`` and may fail to patch the scheduler (not yet importable). A
later call (from ``desktop_entrypoint`` after ``_wire_sys_path()``, and again
from ``cron_scheduler_runner._run()`` after its lazy import) patches the
scheduler too.
"""

from __future__ import annotations

import logging

log = logging.getLogger("hermesdesk.cron.retain")

# How long completed jobs stay in jobs.json before the runner prunes them.
RETAIN_COMPLETED_DAYS = 7

# Module-level state: keep the wrapper stable across multiple install()
# calls so ``cron.scheduler.mark_job_run = _PATCHED_FN`` always refers to
# the same callable, no matter when scheduler becomes importable.
_ORIG_MARK_JOB_RUN = None
_PATCHED_FN = None


def _build_patched(orig):
    def _patched_mark_job_run(
        job_id: str,
        success: bool,
        error: str | None = None,
        delivery_error: str | None = None,
    ) -> None:
        try:
            from hermes_time import now as _hermes_now  # type: ignore[import-untyped]
        except ImportError:
            from datetime import datetime, timezone

            def _hermes_now():
                return datetime.now(timezone.utc).astimezone()

        from cron import jobs as _jobs  # type: ignore[import-untyped]

        with _jobs._jobs_file_lock:
            jobs = _jobs.load_jobs()
            for i, job in enumerate(jobs):
                if job["id"] != job_id:
                    continue

                now_iso = _hermes_now().isoformat()
                job["last_run_at"] = now_iso
                job["last_status"] = "ok" if success else "error"
                job["last_error"] = error if not success else None
                job["last_delivery_error"] = delivery_error

                if job.get("repeat"):
                    job["repeat"]["completed"] = job["repeat"].get("completed", 0) + 1

                    times = job["repeat"].get("times")
                    completed = job["repeat"]["completed"]
                    if times is not None and times > 0 and completed >= times:
                        # NEW: retain instead of pop. UI shows a "Completed"
                        # section; runner prunes after RETAIN_COMPLETED_DAYS.
                        job["state"] = "completed"
                        job["enabled"] = False
                        job["completed_at"] = now_iso
                        job["next_run_at"] = None
                        _jobs.save_jobs(jobs)
                        log.info(
                            "Job '%s' (%s): repeat limit reached, retained as completed",
                            job.get("name", job_id),
                            job_id,
                        )
                        return

                # Recurring jobs: delegate to upstream so we don't fork the
                # next-run-computation logic (croniter, DST, etc.). Drop our
                # partial edits and let the original do its thing.
                break
            else:
                pass

        return orig(job_id, success, error=error, delivery_error=delivery_error)

    return _patched_mark_job_run


def install() -> None:
    """Install / refresh the patch. Idempotent and safe to re-call."""
    global _ORIG_MARK_JOB_RUN, _PATCHED_FN

    try:
        from cron import jobs as _jobs  # type: ignore[import-untyped]
    except ImportError:
        log.debug("cron.jobs not importable yet; will retry from desktop_entrypoint")
        return

    if not hasattr(_jobs, "mark_job_run"):
        log.warning("cron.jobs.mark_job_run missing; upstream API may have changed")
        return

    # First install: capture original and build the wrapper.
    if _PATCHED_FN is None:
        _ORIG_MARK_JOB_RUN = _jobs.mark_job_run
        _PATCHED_FN = _build_patched(_ORIG_MARK_JOB_RUN)

    # Re-bind cron.jobs.mark_job_run on every call (cheap, idempotent).
    if _jobs.mark_job_run is not _PATCHED_FN:
        _jobs.mark_job_run = _PATCHED_FN
        log.info("cron retain-completed: cron.jobs.mark_job_run patched")

    # Re-bind scheduler's local copy too. cron.scheduler does
    # ``from cron.jobs import mark_job_run`` at load time, which captures
    # whatever the function was at that moment — patching cron.jobs alone
    # does NOT propagate. This is the bug that caused completed one-shots
    # to keep getting popped despite the cron.jobs patch being in place.
    try:
        import cron.scheduler as _sched  # type: ignore[import-untyped]
        if hasattr(_sched, "mark_job_run") and _sched.mark_job_run is not _PATCHED_FN:
            _sched.mark_job_run = _PATCHED_FN
            log.info("cron retain-completed: cron.scheduler.mark_job_run also re-bound")
    except ImportError:
        log.debug("cron.scheduler not yet importable; will re-bind on next install()")


def prune_old_completed() -> int:
    """Delete completed jobs whose ``completed_at`` is older than RETAIN_COMPLETED_DAYS.

    Called periodically by ``CronSchedulerRunner._run``.  Returns the number
    of jobs removed.
    """
    try:
        from cron import jobs as _jobs  # type: ignore[import-untyped]
    except ImportError:
        return 0

    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_COMPLETED_DAYS)
    removed = 0
    with _jobs._jobs_file_lock:
        all_jobs = _jobs.load_jobs()
        kept = []
        for job in all_jobs:
            if job.get("state") == "completed" and job.get("completed_at"):
                try:
                    when = datetime.fromisoformat(job["completed_at"])
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    if when < cutoff:
                        removed += 1
                        continue
                except (ValueError, TypeError):
                    pass
            kept.append(job)
        if removed:
            _jobs.save_jobs(kept)
            log.info("pruned %d completed cron job(s) older than %dd", removed, RETAIN_COMPLETED_DAYS)
    return removed
