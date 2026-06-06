"""
TimeMoto Projektabrechnung
--------------------------
Aufbauend auf dem urspruenglichen Webhook-Logger. Der Dienst:

1. Nimmt weiterhin JEDEN TimeMoto-Webhook entgegen, loggt ihn (stdout) und
   schreibt ihn als JSON-Line nach LOG_FILE (Datenbasis fuer den Bericht).
2. Erzeugt aus den gesammelten Events einen WOECHENTLICHEN Projekt-Zeitbericht
   (pro Mitarbeiter summierte Stunden) und stellt ihn zu -- per Mail, sofern
   SMTP konfiguriert ist, sonst als Datei in REPORT_DIR.
3. Triggert den Bericht automatisch via APScheduler (Default: Mo 07:00) und
   bietet manuelle Endpoints zum Vorab-Ansehen, Sofort-Versenden und zum
   Inspizieren der erkannten Felder.

Endpoints:
  GET  /health             -> Health-Check
  POST <WEBHOOK_PATH>       -> Webhook-Empfang (auch GET/PUT, fuer Tests)
  GET  /report/preview      -> Bericht als Text/JSON ansehen (kein Versand)
  POST /report/run          -> Bericht jetzt erzeugen UND zustellen
  GET  /report/projects     -> im Zeitraum erkannte Projekte auflisten
  GET  /report/inspect      -> zeigt, welche Felder aus den Events erkannt werden
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware

import config
import mailer
import scheduler
import settings
import users
import web
from events import load_records, normalize, pair_intervals
from report import build_report, previous_week_range, render_text


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (config.LOG_FILE.parent, config.REPORT_DIR, config.DOWNLOAD_DIR,
              config.TICKET_FILES_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    settings.apply_timezone()  # gespeicherte Zeitzone aktiv setzen
    users.bootstrap_admin()    # ersten Admin aus ADMIN_USER/PASSWORD anlegen
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="TimeMoto Projektabrechnung", lifespan=lifespan)

# Session-Cookie fuer das Web-Login.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    session_cookie="projektabrechnung_session",
    https_only=config.SESSION_HTTPS_ONLY,
    same_site="lax",
)

# Web-Interface (Login + Dashboard) einbinden.
app.include_router(web.router)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health")
async def health():
    """Health-Check + kurzer Status zu Scheduler/Mailkonfiguration."""
    return {
        "status": "ok",
        "time": _now(),
        "scheduler_enabled": config.SCHEDULER_ENABLED,
        "mail_configured": config.mail_configured(),
        "brevo_api": bool(config.BREVO_API_KEY),
        "smtp_host_set": bool(config.SMTP_HOST),
        "smtp_host": config.SMTP_HOST or "(leer)",
        "smtp_from": config.SMTP_FROM or "(leer)",
        "default_recipients": config.REPORT_RECIPIENTS,
        "project_filter": config.PROJECT_CODE or "(alle)",
    }


@app.api_route(config.WEBHOOK_PATH, methods=["POST", "GET", "PUT"])
async def receive(request: Request):
    """Webhook-Empfang -- identisch zur Erkundungsphase: alles mitschreiben."""
    raw = await request.body()
    headers = dict(request.headers)

    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:
        parsed = None

    # Secret-Pruefung: Wir wissen noch nicht, in welchem Header TimeMoto das
    # Secret schickt -> mehrere uebliche Stellen pruefen. Alle Header werden
    # ohnehin geloggt, sodass wir die echte Stelle im ersten Event sehen.
    secret_ok = None
    if config.SHARED_SECRET:
        auth = headers.get("authorization", "")
        candidate = (
            headers.get("x-webhook-secret")
            or headers.get("x-api-key")
            or headers.get("x-timemoto-secret")
            or headers.get("secret")
            or (auth.removeprefix("Bearer ").removeprefix("bearer ").strip() or None)
            or request.query_params.get("secret")
            or ""
        )
        secret_ok = candidate == config.SHARED_SECRET

    record = {
        "received_at": _now(),
        "method": request.method,
        "path": request.url.path,
        "query": dict(request.query_params),
        "headers": headers,
        "secret_ok": secret_ok,
        "body_raw": raw.decode("utf-8", errors="replace"),
        "body_json": parsed,
    }

    print("=" * 70, flush=True)
    print(f"[{record['received_at']}] {record['method']} {record['path']}", flush=True)
    if parsed is not None:
        print(json.dumps(parsed, indent=2, ensure_ascii=False), flush=True)
    else:
        print("RAW:", record["body_raw"], flush=True)

    try:
        config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[warn] konnte Event nicht schreiben: {exc}", flush=True)

    return JSONResponse({"status": "received"}, status_code=200)


# --- Berichts-Endpoints ----------------------------------------------------

def _resolve_range(start: str | None, end: str | None):
    """Zeitraum bestimmen: explizite ISO-Daten oder die vorige Woche."""
    if start and end:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        if s.tzinfo is None:
            s = s.replace(tzinfo=config.TIMEZONE)
        if e.tzinfo is None:
            e = e.replace(tzinfo=config.TIMEZONE)
        return s, e
    return previous_week_range()


@app.get("/report/preview")
async def report_preview(
    project: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    fmt: str = Query(default="text"),
):
    """Bericht erzeugen und ansehen -- OHNE Versand. Praktisch zum Testen."""
    s, e = _resolve_range(start, end)
    rep = build_report(s, e, project=project)
    if fmt == "text":
        return PlainTextResponse(render_text(rep))
    return {
        "project": rep.project or "(alle)",
        "period": {"start": rep.start.isoformat(), "end": rep.end.isoformat()},
        "total_hours": round(rep.total_hours, 2),
        "rows": [
            {"employee": r.employee, "hours": round(r.hours, 2),
             "sessions": r.sessions}
            for r in rep.rows
        ],
        "projects_seen": rep.projects_seen,
        "intervals_in_window": rep.total_intervals,
    }


@app.post("/report/run")
async def report_run(
    project: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Bericht jetzt erzeugen UND zustellen (Mail, sonst Datei)."""
    s, e = _resolve_range(start, end)
    rep = build_report(s, e, project=project)
    result = mailer.deliver(rep)
    return {"status": "done", "delivery": result,
            "total_hours": round(rep.total_hours, 2),
            "rows": len(rep.rows)}


@app.get("/report/projects")
async def report_projects(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Alle im Zeitraum erkannten Projekte auflisten -- hilft, den richtigen
    Wert fuer PROJECT_CODE zu finden."""
    s, e = _resolve_range(start, end)
    rep = build_report(s, e, project="")  # ohne Filter
    return {"period": {"start": rep.start.isoformat(), "end": rep.end.isoformat()},
            "projects_seen": rep.projects_seen}


@app.get("/report/inspect")
async def report_inspect(limit: int = Query(default=10, ge=1, le=200)):
    """Zeigt fuer die letzten Events, welche Felder die Auto-Erkennung findet.

    Damit beantwortest du die offene Frage: 'Kommt der Projektcode im
    Webhook ueberhaupt mit?' -- ohne Raten.
    """
    records = load_records()
    tail = records[-limit:]
    punches = [normalize(r) for r in tail]
    detected = []
    for rec, p in zip(tail, punches):
        if p is None:
            detected.append({"received_at": rec.get("received_at"),
                             "normalized": None,
                             "note": "kein verwertbarer Zeitpunkt erkannt"})
            continue
        detected.append({
            "received_at": rec.get("received_at"),
            "time": p.time.isoformat(),
            "employee": p.employee,
            "project": p.project,
            "direction": p.direction,
        })
    intervals = pair_intervals([p for p in punches if p])
    return {
        "events_total": len(records),
        "events_shown": len(tail),
        "has_project_field": any(p and p.project for p in punches),
        "has_direction_field": any(p and p.direction for p in punches),
        "intervals_paired": len(intervals),
        "detected": detected,
    }
