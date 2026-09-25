"""Background job that re-checks all tracked products every few hours (an admin
setting, default 6), so the app makes fresh decisions without anyone clicking.

Two modes (env SCHEDULER_MODE):
- `in-process` (the default: local runs, Docker): the interval job above.
- `cron` (the hosted site): the host calls GET /cron/daily once a day, which runs
  daily_run(). Instances scale to zero between visits, so an in-process timer
  would never fire reliably there. The scheduler still starts, for run_once jobs.
"""

import os
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from . import database as db
from . import history, site_settings
from .refresh import refresh_all, refresh_stalest

REFRESH_JOB_ID = "refresh_all_products"

# The daily run's budget. Vercel Hobby cuts a request at 300 s; the worst single
# step after a deadline is a price check (~75 s: HTTP, then a render) or an
# archive index request (60 s timeout), so both finish in time.
DAILY_REFRESH_S = 150   # no new price check starts after this
DAILY_HISTORY_S = 230   # no new archive request starts after this

_scheduler = BackgroundScheduler()


def mode() -> str:
    """'cron' when the host schedules refreshes, else 'in-process'."""
    value = (os.environ.get("SCHEDULER_MODE") or "").strip().lower()
    return "cron" if value == "cron" else "in-process"


def start_scheduler() -> None:
    if _scheduler.running:
        return
    if mode() == "cron":
        _scheduler.start()  # no interval job: /cron/daily does that work
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


def daily_run(clock=time.monotonic) -> dict:
    """What the host's daily call does, within one request's time limit.

    1. Re-check prices, stalest listings first, until DAILY_REFRESH_S.
    2. Then, unless an admin paused them, finish archive lookups that were asked
       for but never completed (their listing still has no history_checked_at),
       until DAILY_HISTORY_S or the archive asks us to slow down.

    Anything not reached is left as it was, so the next run picks it up. Returns
    a report of what was done.
    """
    start = clock()
    report = refresh_stalest(deadline=start + DAILY_REFRESH_S, clock=clock)
    report["history_paused"] = site_settings.history_paused()
    report["history_products"] = 0
    if not report["history_paused"]:
        deadline = start + DAILY_HISTORY_S

        def stop() -> bool:
            return clock() >= deadline or history.cooling_down()

        for product_id in db.get_products_with_unchecked_sources():
            if stop() or site_settings.history_paused():
                break
            history.backfill_product(product_id, only_unchecked=True, stop=stop)
            report["history_products"] += 1
    report["history_products_left"] = len(db.get_products_with_unchecked_sources())
    return report


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
