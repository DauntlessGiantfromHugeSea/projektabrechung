"""
Zeitsteuerung der Berichte via APScheduler.

Es wird pro online definiertem Bericht (settings.list_reports) ein eigener
Cron-Job angelegt. Aendert sich die Konfiguration im Web-Interface, ruft die
Oberflaeche reschedule() auf. Ohne Definitionen passiert nichts -- es wird
absichtlich nicht automatisch "alles" versendet.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import mailer
import settings
from report import (build_grouped, previous_week_range, render_grouped_html,
                    render_grouped_text, subject_grouped)

_scheduler: AsyncIOScheduler | None = None
_PREFIX = "report:"


def run_report_config(report_id: str) -> dict:
    """Einen definierten Bericht fuer die vorige Woche erzeugen und zustellen."""
    cfg = settings.get_report(report_id)
    if not cfg or not cfg.get("enabled"):
        return {"skipped": True, "reason": "missing_or_disabled"}
    start, end = previous_week_range()
    rep = build_grouped(start, end, cfg["projects"], name=cfg["name"])
    return mailer.send(subject_grouped(rep), render_grouped_text(rep),
                       render_grouped_html(rep), cfg["recipients"],
                       label=cfg["name"])


def reschedule() -> None:
    """Alle Bericht-Jobs neu aus der Konfiguration aufbauen."""
    if _scheduler is None:
        return
    for job in _scheduler.get_jobs():
        if job.id and job.id.startswith(_PREFIX):
            _scheduler.remove_job(job.id)
    active = 0
    for cfg in settings.list_reports():
        if not cfg.get("enabled"):
            continue
        trigger = CronTrigger(day_of_week=cfg["day_of_week"], hour=cfg["hour"],
                              minute=cfg["minute"], timezone=config.TIMEZONE)
        _scheduler.add_job(run_report_config, trigger,
                           id=f"{_PREFIX}{cfg['id']}", args=[cfg["id"]],
                           replace_existing=True, misfire_grace_time=3600)
        active += 1
    print(f"[scheduler] {active} aktive(r) Bericht(e) eingeplant.", flush=True)


def start() -> AsyncIOScheduler | None:
    global _scheduler
    if not config.SCHEDULER_ENABLED:
        print("[scheduler] deaktiviert (SCHEDULER_ENABLED=false).", flush=True)
        return None
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
        _scheduler.start()
    reschedule()
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
