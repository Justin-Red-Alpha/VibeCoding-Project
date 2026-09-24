"""Background job that re-checks all tracked products every REFRESH_INTERVAL_HOURS,
so the app makes fresh decisions automatically without you clicking anything."""

import os
from apscheduler.schedulers.background import BackgroundScheduler

from .refresh import refresh_all

REFRESH_INTERVAL_HOURS = float(os.environ.get("REFRESH_INTERVAL_HOURS", "6"))

_scheduler = BackgroundScheduler()


def start_scheduler() -> None:
    if _scheduler.running:
        return
    _scheduler.add_job(
        refresh_all,
        "interval",
        hours=REFRESH_INTERVAL_HOURS,
        id="refresh_all_products",
    )
    _scheduler.start()


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
