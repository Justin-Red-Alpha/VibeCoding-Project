"""Background job that re-checks all tracked products every few hours (an admin
setting, default 6), so the app makes fresh decisions without anyone clicking."""

from apscheduler.schedulers.background import BackgroundScheduler

from . import site_settings
from .refresh import refresh_all

REFRESH_JOB_ID = "refresh_all_products"

_scheduler = BackgroundScheduler()


def start_scheduler() -> None:
    if _scheduler.running:
        return
    _scheduler.add_job(
        refresh_all,
        "interval",
        hours=site_settings.refresh_interval_hours(),
        id=REFRESH_JOB_ID,
    )
    _scheduler.start()


def set_refresh_interval(hours: float) -> None:
    """Apply a new interval to the live job, with no restart. Does nothing if the
    scheduler was never started (tests, or before startup)."""
    if _scheduler.get_job(REFRESH_JOB_ID) is not None:
        _scheduler.reschedule_job(REFRESH_JOB_ID, trigger="interval", hours=hours)


def run_once(job_id: str, func, *args) -> None:
    """Run `func(*args)` once, as soon as possible, in the background.

    One job per id: asking again while one is queued does nothing (APScheduler's
    replace_existing only dedupes once the scheduler is running), and
    max_instances=1 skips a new run while one with that id is still executing.
    """
    if _scheduler.get_job(job_id) is not None:
        return
    _scheduler.add_job(
        func, "date", args=list(args), id=job_id,
        replace_existing=True, max_instances=1, misfire_grace_time=None,
    )


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
