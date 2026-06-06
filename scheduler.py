"""
Zeitsteuerung der Berichte via APScheduler.

Es wird pro online definiertem Bericht (settings.list_reports) ein eigener
Cron-Job angelegt. Aendert sich die Konfiguration im Web-Interface, ruft die
Oberflaeche reschedule() auf. Ohne Definitionen passiert nichts -- es wird
absichtlich nicht automatisch "alles" versendet.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import activities
import config
import mailer
import settings
import users
from report import (build_attachment, build_grouped, collect_intervals,
                    previous_week_range, render_grouped_html,
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
    data, fname, mime = build_attachment(start, end, cfg["projects"],
                                         cfg.get("format", "excel"), cfg["name"])
    return mailer.send_report(subject_grouped(rep), render_grouped_text(rep),
                              render_grouped_html(rep), cfg["recipients"],
                              data, fname, base_url=config.PUBLIC_BASE_URL,
                              label=cfg["name"], actor="Automatik",
                              message=cfg.get("message", ""),
                              cc=cfg.get("cc", []), mime=mime)


def _fmt_dur(h: float) -> str:
    m = round(max(h, 0.0) * 60)
    return f"{m // 60}:{m % 60:02d} h"


def run_reminders() -> dict:
    """Erinnerung an Mitarbeiter, deren Buchung aelter als X Stunden ist und
    noch keine Taetigkeitsbeschreibung hat (einmalig je Buchung)."""
    now = datetime.now(config.TIMEZONE)
    after = timedelta(hours=config.REMINDER_AFTER_HOURS)
    maxage = timedelta(days=config.REMINDER_MAX_AGE_DAYS)
    sent = 0
    for iv in collect_intervals():
        if iv.description.strip():
            continue
        age = now - iv.end.astimezone(config.TIMEZONE)
        if age < after or age > maxage:
            continue
        if activities.reminded(iv.id):
            continue
        u = users.by_timemoto(iv.employee)
        if not u or not u.get("email"):
            continue
        d = iv.start.astimezone(config.TIMEZONE).strftime("%d.%m.%Y")
        dur = _fmt_dur(iv.duration_hours)
        name = u.get("name") or u["username"]
        link = f"{config.PUBLIC_BASE_URL}/meine-zeiten"
        subj = "Erinnerung: Tätigkeitsbeschreibung fehlt"
        text = (f"Hallo {name},\n\nfür deine Buchung am {d} "
                f"({iv.project or '-'}, {dur}) fehlt noch die "
                f"Tätigkeitsbeschreibung. Bitte trage sie nach:\n{link}\n")
        html = (f"<p>Hallo {name},</p><p>für deine Buchung am <b>{d}</b> "
                f"({iv.project or '-'}, {dur}) fehlt noch die "
                "<b>Tätigkeitsbeschreibung</b>. Bitte trage sie kurz nach "
                "(1–2 Sätze).</p>"
                f'<p><a href="{link}" style="display:inline-block;'
                f'background:{config.BRAND_COLOR};color:#123018;font-weight:bold;'
                'text-decoration:none;padding:11px 22px;border-radius:999px">'
                "Meine Zeiten öffnen</a></p>")
        res = mailer.send(subj, text, html, [u["email"]], label="Erinnerung",
                          actor="Automatik")
        if res.get("mailed"):
            activities.mark_reminded(iv.id)
            sent += 1
    if sent:
        print(f"[reminder] {sent} Erinnerung(en) versendet.", flush=True)
    return {"sent": sent}


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
        # Stuendliche Pruefung auf fehlende Taetigkeitsbeschreibungen.
        _scheduler.add_job(run_reminders, "interval", hours=1,
                           id="reminders", replace_existing=True,
                           misfire_grace_time=3600)
    reschedule()
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
