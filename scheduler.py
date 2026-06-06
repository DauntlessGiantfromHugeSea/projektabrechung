"""
Woechentlicher Ausloeser via APScheduler.

Faehrt den Bericht fuer die *vorige* abgeschlossene Woche und stellt ihn zu.
Default: jeden Montag 07:00 (konfigurierbar in config / per Env-Vars).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import mailer
from report import build_report, previous_week_range

_scheduler: AsyncIOScheduler | None = None


def run_weekly_report() -> dict:
    """Bericht der vorigen Woche erzeugen und zustellen."""
    start, end = previous_week_range()
    rep = build_report(start, end)
    return mailer.deliver(rep)


def start() -> AsyncIOScheduler | None:
    """Scheduler starten (idempotent). Liefert die Instanz oder None."""
    global _scheduler
    if not config.SCHEDULER_ENABLED:
        print("[scheduler] deaktiviert (SCHEDULER_ENABLED=false).", flush=True)
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    trigger = CronTrigger(
        day_of_week=config.CRON_DAY_OF_WEEK,
        hour=config.CRON_HOUR,
        minute=config.CRON_MINUTE,
        timezone=config.TIMEZONE,
    )
    _scheduler.add_job(run_weekly_report, trigger, id="weekly_report",
                       replace_existing=True, misfire_grace_time=3600)
    _scheduler.start()
    nxt = _scheduler.get_job("weekly_report").next_run_time
    print(f"[scheduler] Wochenbericht aktiv. Naechster Lauf: {nxt}", flush=True)
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
