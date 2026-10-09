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

import hmac
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
              config.TICKET_FILES_DIR, config.DOC_FILES_DIR,
              config.VCARD_FILES_DIR):
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


app = FastAPI(title="FBE Intranet", lifespan=lifespan)

# Schutz gegen untergeschobene Formular-Anfragen (CSRF) von anderen Seiten –
# auch von Nachbar-Subdomains unter rss-fb.com, die SameSite=Lax nicht
# abhält – und gegen Einbetten in fremde Frames (Sicherheits-Audit 2026-10).
_SICHERE_METHODEN = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def _sicherheits_middleware(request: Request, call_next):
    if (request.method not in _SICHERE_METHODEN
            and request.url.path != config.WEBHOOK_PATH):
        site = request.headers.get("sec-fetch-site")
        origin = (request.headers.get("origin") or "").rstrip("/")
        eigene = config.PUBLIC_BASE_URL.rstrip("/")
        if site is not None:
            if site not in ("same-origin", "none"):
                return PlainTextResponse(
                    "Anfrage von einer fremden Seite abgelehnt.", status_code=403)
        elif origin and origin != eigene:
            return PlainTextResponse(
                "Anfrage von einer fremden Seite abgelehnt.", status_code=403)
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    return response


# Obergrenze fuer Request-Bodys. Starlette parst Formulare/Uploads, bevor der
# Handler die Anmeldung prueft - ohne Grenze koennte also jeder beliebig
# grosse Dateien auf die Platte spoolen (Sicherheits-Audit 2026-10).
MAX_BODY_BYTES = int(os.getenv("MAX_UPLOAD_MB", "60")) * 1024 * 1024


class _BodyLimit:
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    zu_gross = int(v) > self.limit
                except ValueError:
                    zu_gross = True
                if zu_gross:
                    return await PlainTextResponse(
                        "Anfrage zu groß.", status_code=413)(scope, receive, send)
        gelesen = 0

        async def begrenzt():
            nonlocal gelesen
            msg = await receive()
            if msg["type"] == "http.request":
                gelesen += len(msg.get("body", b""))
                if gelesen > self.limit:
                    raise _ZuGross()
            return msg

        try:
            await self.app(scope, begrenzt, send)
        except _ZuGross:
            await PlainTextResponse("Anfrage zu groß.", status_code=413)(scope, receive, send)


class _ZuGross(Exception):
    pass


# Session-Cookie fuer das Web-Login.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    session_cookie="projektabrechnung_session",
    https_only=config.SESSION_HTTPS_ONLY,
    same_site="lax",
    max_age=12 * 3600,   # Sitzung läuft nach 12 h ab (vorher 14 Tage)
)

# Als aeusserste Schicht, damit das Limit vor jedem Parsen greift.
app.add_middleware(_BodyLimit, limit=MAX_BODY_BYTES)

# Web-Interface (Login + Dashboard) einbinden.
app.include_router(web.router)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health")
async def health():
    """Health-Check. Bewusst ohne Konfigurationsdetails (Empfänger, SMTP),
    weil der Endpunkt öffentlich erreichbar ist (Sicherheits-Audit 2026-10)."""
    return {"status": "ok"}


_WEBHOOK_MAX_BYTES = 64 * 1024
# Nur unkritische Header speichern – nie das Secret oder Authorization.
_WEBHOOK_HEADER_ALLOW = {"content-type", "user-agent", "x-forwarded-for",
                         "x-real-ip", "x-request-id"}


@app.api_route(config.WEBHOOK_PATH, methods=["POST", "GET", "PUT"])
async def receive(request: Request):
    """Webhook-Empfang -- identisch zur Erkundungsphase: alles mitschreiben."""
    # Größenlimit (Sicherheits-Audit 2026-10): TimeMoto-Events sind klein.
    try:
        if int(request.headers.get("content-length") or 0) > _WEBHOOK_MAX_BYTES:
            return JSONResponse({"status": "too large"}, status_code=413)
    except ValueError:
        return JSONResponse({"status": "bad request"}, status_code=400)
    raw = await request.body()
    if len(raw) > _WEBHOOK_MAX_BYTES:
        return JSONResponse({"status": "too large"}, status_code=413)
    headers = dict(request.headers)

    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:
        parsed = None

    # Secret-Pruefung (Sicherheits-Audit 2026-10): Ohne gueltiges Secret wird
    # NICHTS in die Abrechnungsdaten geschrieben. Ist kein SHARED_SECRET
    # konfiguriert, nimmt der Webhook gar nichts an (503) – sonst koennte
    # jeder anonym Buchungen anlegen oder loeschen.
    if not config.SHARED_SECRET:
        print("[warn] Webhook abgelehnt: SHARED_SECRET ist nicht gesetzt "
              "(deploy/.env).", flush=True)
        return JSONResponse({"status": "webhook disabled"}, status_code=503)
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
    secret_ok = hmac.compare_digest(candidate.encode("utf-8"),
                                    config.SHARED_SECRET.encode("utf-8"))
    if not secret_ok:
        print(f"[warn] Webhook ohne gueltiges Secret abgelehnt "
              f"({request.method} {request.url.path})", flush=True)
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    record = {
        "received_at": _now(),
        "method": request.method,
        "path": request.url.path,
        "query": {k: v for k, v in request.query_params.items() if k != "secret"},
        "headers": {k: v for k, v in headers.items() if k in _WEBHOOK_HEADER_ALLOW},
        "secret_ok": secret_ok,
        "body_raw": raw.decode("utf-8", errors="replace") if parsed is None else "",
        "body_json": parsed,
    }

    print(f"[{record['received_at']}] {record['method']} {record['path']} "
          f"({len(raw)} Bytes)", flush=True)

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
