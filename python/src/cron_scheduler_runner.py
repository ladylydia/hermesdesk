"""CronSchedulerRunner — run the upstream cron ticker inside the web child.

The gateway process normally hosts the 60-second ticker thread, but many
HermesDesk users never start the gateway.  This module runs the same
upstream ``cron.scheduler.tick()`` loop inside the web child so scheduled
jobs fire regardless of gateway status.

The upstream ticker already owns a file-based lock (``cron/.tick.lock``),
so running it in both the web child and the gateway is safe — only one
ticker thread ever holds the lock.

For desktop-target jobs (``deliver="desktop"``), a minimal adapter is
provided so the upstream scheduler's ``_deliver_result()`` can route
messages through the Tauri bridge.

Startup:

    from cron_scheduler_runner import CronSchedulerRunner
    runner = CronSchedulerRunner(interval=60)
    runner.start()

Shutdown:

    runner.stop()
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("hermesdesk.cron.runner")


class _DesktopDeliveryAdapter:
    """Minimal adapter that satisfies the ``send()`` contract expected by
    ``cron.scheduler._deliver_result()`` for live-adapters delivery."""

    async def send(self, chat_id: str, content: str, reply_to=None, metadata=None):
        from desktop_delivery import deliver

        ok = deliver(message=content, title="Cron Job")
        if ok:
            class _Ok:
                success = True
                message_id = "desktop"
                error = None
            return _Ok()
        else:
            class _Fail:
                success = False
                message_id = None
                error = "desktop delivery failed"
            return _Fail()


class CronSchedulerRunner:
    """Background thread that calls ``cron.scheduler.tick()`` every *interval* seconds."""

    def __init__(self, interval: float = 60.0) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            log.warning("cron ticker already running; skip duplicate start")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="cron-ticker-web",
        )
        self._thread.start()
        log.info("cron ticker started (interval=%ds)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5.0)
        log.info("cron ticker stopped")

    def _run(self) -> None:
        # Delay the first tick so the web server has time to start.
        self._stop.wait(self._interval)

        # Prune completed-history once per hour. ``RETAIN_COMPLETED_DAYS``
        # buys us plenty of slack, so we don't need a tight schedule.
        prune_every_n_ticks = max(1, int(3600 // self._interval))
        tick_count = 0

        # Once cron.scheduler is importable in this thread, re-install the
        # retain-completed overlay so it can patch ``cron.scheduler.mark_job_run``
        # too. Earlier install attempts (apply_all, desktop_entrypoint) ran
        # before scheduler was on sys.path, so they only patched cron.jobs.
        try:
            import cron.scheduler  # noqa: F401  -- force-load for the patch
            from overlays.cron_retain_completed import install as _crc_install
            _crc_install()
        except Exception:
            log.exception("cron ticker: retain-completed re-install failed")

        # Belt-and-suspenders for the ``from cron.jobs import mark_job_run``
        # binding inside cron.scheduler: re-run install() now that scheduler
        # is about to be imported below. Safe + idempotent.
        try:
            from overlays.cron_retain_completed import install as _retain_install
            _retain_install()
        except Exception:
            log.debug("cron retain-completed re-install in runner failed", exc_info=True)

        while not self._stop.is_set():
            try:
                from cron.scheduler import tick as cron_tick

                # First trip through the loop: cron.scheduler is now in
                # sys.modules, so re-bind its local mark_job_run.
                try:
                    from overlays.cron_retain_completed import install as _retain_install
                    _retain_install()
                except Exception:
                    pass

                adapters = {"desktop": _DesktopDeliveryAdapter()}
                cron_tick(verbose=False, adapters=adapters, loop=None)
            except Exception:
                log.exception("cron ticker: tick() failed")

            tick_count += 1
            if tick_count % prune_every_n_ticks == 0:
                try:
                    from overlays.cron_retain_completed import prune_old_completed
                    prune_old_completed()
                except Exception:
                    log.exception("cron ticker: prune_old_completed() failed")

            self._stop.wait(self._interval)
