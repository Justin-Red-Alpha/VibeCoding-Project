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


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
