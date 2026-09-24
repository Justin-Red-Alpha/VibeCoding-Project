"""Background job that re-checks all tracked products every few hours (an admin
setting, default 6), so the app makes fresh decisions without anyone clicking."""

from datetime import datetime, timezone

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
        max_instances=1,
    )
    _scheduler.start()


def set_refresh_interval(hours: float) -> None:
    """Apply a new interval to the live job, with no restart.

    Only when it actually changed: rescheduling restarts the countdown, so doing it
    on every settings save would keep pushing the next refresh further away.
    Does nothing if the scheduler was never started (tests, or before startup).
    """
    job = _scheduler.get_job(REFRESH_JOB_ID)
    if job is None:
        return
    current = getattr(job.trigger, "interval", None)
    if current is not None and current.total_seconds() == hours * 3600:
        return
    _scheduler.reschedule_job(REFRESH_JOB_ID, trigger="interval", hours=hours)


def refresh_all_now() -> None:
    """Run the scheduled refresh now rather than as a second, parallel job. It's the
    same job, so its max_instances=1 stops it overlapping a run already going."""
    job = _scheduler.get_job(REFRESH_JOB_ID)
    if job is not None:
        job.modify(next_run_time=datetime.now(timezone.utc))
    else:
        run_once("refresh-all-now", refresh_all)  # scheduler not started (tests)


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
