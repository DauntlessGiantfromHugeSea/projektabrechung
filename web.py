"""
Passwortgeschuetztes Web-Interface.

- /login        Login-Formular (Session-Cookie)
- /logout       Abmelden
- /             Dashboard: Wochenbericht, Projektfilter, Wochenauswahl,
                erkannte Projekte, "kommt der Projektcode an?"-Status,
                Button "Bericht jetzt senden".

Bewusst ohne externe Template-Dateien: die wenigen Seiten sind als
Jinja2-Templates inline gehalten, damit das Docker-Image schlank bleibt
(COPY *.py genuegt weiterhin).
"""

from __future__ import annotations

import hmac
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template

import config
import mailer
from events import load_records, normalize, pair_intervals
from report import (build_report, previous_week_range, render_html,
                    this_week_range)

router = APIRouter()

_BASE = """
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} – Projektabrechnung</title>
<style>
  :root { --fg:#1f2933; --muted:#647382; --line:#e1e7ef; --bg:#f5f7fa;
          --accent:#2563eb; --accent-d:#1d4ed8; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
         color:var(--fg); background:var(--bg); }
  header { background:#fff; border-bottom:1px solid var(--line);
           padding:.8rem 1.2rem; display:flex; align-items:center;
           justify-content:space-between; }
  header .brand { font-weight:700; }
  header a { color:var(--muted); text-decoration:none; font-size:.9rem; }
  main { max-width:920px; margin:1.5rem auto; padding:0 1.2rem; }
  .card { background:#fff; border:1px solid var(--line); border-radius:10px;
          padding:1.2rem 1.3rem; margin-bottom:1.2rem; }
  h1 { font-size:1.3rem; margin:.2rem 0 1rem; }
  h2 { font-size:1.05rem; margin:0 0 .8rem; }
  label { display:block; font-size:.85rem; color:var(--muted);
          margin:.6rem 0 .2rem; }
  input, select { width:100%; padding:.55rem .6rem; border:1px solid var(--line);
          border-radius:7px; font:inherit; background:#fff; }
  button { background:var(--accent); color:#fff; border:0; border-radius:7px;
           padding:.6rem 1rem; font:inherit; font-weight:600; cursor:pointer; }
  button:hover { background:var(--accent-d); }
  button.secondary { background:#fff; color:var(--accent);
           border:1px solid var(--accent); }
  table { border-collapse:collapse; width:100%; margin-top:.4rem; }
  th,td { padding:.5rem .6rem; border-bottom:1px solid var(--line);
          text-align:left; }
  td.num,th.num { text-align:right; }
  .row { display:flex; gap:1rem; flex-wrap:wrap; align-items:end; }
  .row > div { flex:1; min-width:140px; }
  .pill { display:inline-block; padding:.15rem .55rem; border-radius:999px;
          font-size:.8rem; font-weight:600; }
  .ok { background:#dcfce7; color:#166534; }
  .no { background:#fee2e2; color:#991b1b; }
  .muted { color:var(--muted); font-size:.9rem; }
  .flash { background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af;
           padding:.7rem .9rem; border-radius:8px; margin-bottom:1rem; }
  .err { background:#fef2f2; border-color:#fecaca; color:#991b1b; }
  .tags span { display:inline-block; background:#eef2f7; border-radius:6px;
           padding:.15rem .5rem; margin:.15rem .2rem 0 0; font-size:.85rem; }
</style>
</head>
<body>
{% block body %}{% endblock %}
</body>
</html>
"""

_LOGIN = """
{% extends base %}
{% block body %}
<main style="max-width:380px;margin-top:8vh;">
  <div class="card">
    <h1>Anmelden</h1>
    {% if error %}<div class="flash err">{{ error }}</div>{% endif %}
    {% if not login_possible %}
      <div class="flash err">Kein Passwort gesetzt. Bitte <code>ADMIN_PASSWORD</code>
        in der docker-compose.yml setzen und neu starten.</div>
    {% endif %}
    <form method="post" action="/login">
      <label>Benutzer</label>
      <input name="username" autofocus autocomplete="username">
      <label>Passwort</label>
      <input name="password" type="password" autocomplete="current-password">
      <div style="margin-top:1rem;"><button type="submit">Einloggen</button></div>
    </form>
  </div>
  <p class="muted" style="text-align:center;">TimeMoto Projektabrechnung</p>
</main>
{% endblock %}
"""

_DASH = """
{% extends base %}
{% block body %}
<header>
  <span class="brand">Projektabrechnung</span>
  <span><span class="muted">{{ user }}</span> &nbsp;·&nbsp;
    <a href="/logout">Abmelden</a></span>
</header>
<main>
  {% if flash %}<div class="flash {{ flash_class }}">{{ flash }}</div>{% endif %}

  <div class="card">
    <h2>Zeitraum &amp; Projekt</h2>
    <form method="get" action="/">
      <div class="row">
        <div>
          <label>Woche</label>
          <select name="week" onchange="this.form.submit()">
            <option value="last" {{ 'selected' if week=='last' }}>Vorige Woche</option>
            <option value="this" {{ 'selected' if week=='this' }}>Diese Woche</option>
            <option value="custom" {{ 'selected' if week=='custom' }}>Eigener Zeitraum</option>
          </select>
        </div>
        <div>
          <label>Projektfilter (leer = alle)</label>
          <input name="project" value="{{ project }}" placeholder="z. B. ACME">
        </div>
        {% if week=='custom' %}
        <div><label>Von</label><input name="start" value="{{ start_in }}" placeholder="2026-06-01"></div>
        <div><label>Bis</label><input name="end" value="{{ end_in }}" placeholder="2026-06-08"></div>
        {% endif %}
        <div style="flex:0 0 auto;"><label>&nbsp;</label>
          <button type="submit">Anzeigen</button></div>
      </div>
    </form>
  </div>

  <div class="card">
    <h2>Bericht: {{ report_title }}</h2>
    <p class="muted">{{ period }}</p>
    {{ report_html|safe }}
    <form method="post" action="/send" style="margin-top:1rem;">
      <input type="hidden" name="project" value="{{ project }}">
      <input type="hidden" name="start" value="{{ start_iso }}">
      <input type="hidden" name="end" value="{{ end_iso }}">
      <button type="submit">Bericht jetzt senden{{ '' if mail_configured else ' (als Datei)' }}</button>
      {% if not mail_configured %}<span class="muted"> &nbsp;SMTP nicht
        konfiguriert – Bericht wird nur als Datei gespeichert.</span>{% endif %}
    </form>
  </div>

  <div class="card">
    <h2>Datenlage aus den Webhooks</h2>
    <p>
      Projektcode erkannt:
      {% if has_project %}<span class="pill ok">ja</span>{% else %}<span class="pill no">nein</span>{% endif %}
      &nbsp; Ein-/Ausstempeln erkannt:
      {% if has_direction %}<span class="pill ok">ja</span>{% else %}<span class="pill no">nein</span>{% endif %}
    </p>
    <p class="muted">{{ events_total }} Events gespeichert ·
      {{ intervals_paired }} Arbeitsintervalle paarbar.</p>
    {% if projects_seen %}
      <p>Im Zeitraum erkannte Projekte:</p>
      <div class="tags">{% for p in projects_seen %}<span>{{ p }}</span>{% endfor %}</div>
    {% else %}
      <p class="muted">Im gewählten Zeitraum kein Projektfeld gefunden.</p>
    {% endif %}
  </div>
</main>
{% endblock %}
"""

_base_tpl = Template(_BASE)
_login_tpl = Template(_LOGIN)
_dash_tpl = Template(_DASH)
_login_tpl.environment.globals["base"] = _base_tpl  # type: ignore
_dash_tpl.environment.globals["base"] = _base_tpl   # type: ignore


def _is_authed(request: Request) -> bool:
    return bool(request.session.get("user"))


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if _is_authed(request):
        return RedirectResponse("/", status_code=303)
    html = _login_tpl.render(title="Login", error=None,
                             login_possible=config.login_possible())
    return HTMLResponse(html)


@router.post("/login")
async def login_submit(request: Request,
                       username: str = Form(""), password: str = Form("")):
    ok = (config.login_possible()
          and hmac.compare_digest(username, config.ADMIN_USER)
          and hmac.compare_digest(password, config.ADMIN_PASSWORD))
    if not ok:
        html = _login_tpl.render(title="Login",
                                 error="Benutzer oder Passwort falsch.",
                                 login_possible=config.login_possible())
        return HTMLResponse(html, status_code=401)
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _inspect_stats():
    records = load_records()
    punches = [normalize(r) for r in records]
    valid = [p for p in punches if p]
    return {
        "events_total": len(records),
        "has_project": any(p.project for p in valid),
        "has_direction": any(p.direction for p in valid),
        "intervals_paired": len(pair_intervals(valid)),
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, week: str = "last",
                    project: str | None = None,
                    start: str | None = None, end: str | None = None):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=303)

    proj = project if project is not None else config.PROJECT_CODE
    start_in, end_in = start or "", end or ""

    if week == "this":
        s, e = this_week_range()
    elif week == "custom" and start and end:
        s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
    else:
        week = "last"
        s, e = previous_week_range()

    rep = build_report(s, e, project=proj)
    stats = _inspect_stats()

    flash = request.session.pop("flash", None)
    flash_class = request.session.pop("flash_class", "")

    html = _dash_tpl.render(
        title="Dashboard", user=request.session.get("user"),
        week=week, project=proj, start_in=start_in, end_in=end_in,
        report_title=(proj or "alle Projekte"),
        period=f"{rep.start:%d.%m.%Y} – {(rep.end):%d.%m.%Y}",
        report_html=render_html(rep),
        start_iso=rep.start.date().isoformat(),
        end_iso=rep.end.date().isoformat(),
        mail_configured=config.mail_configured(),
        has_project=stats["has_project"], has_direction=stats["has_direction"],
        events_total=stats["events_total"],
        intervals_paired=stats["intervals_paired"],
        projects_seen=rep.projects_seen,
        flash=flash, flash_class=flash_class,
    )
    return HTMLResponse(html)


@router.post("/send")
async def send_now(request: Request, project: str = Form(""),
                   start: str = Form(""), end: str = Form("")):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=303)
    try:
        s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
        rep = build_report(s, e, project=project or None)
        result = mailer.deliver(rep)
        if result.get("mailed"):
            request.session["flash"] = (
                f"Bericht an {', '.join(result['recipients'])} versendet.")
            request.session["flash_class"] = ""
        else:
            request.session["flash"] = (
                "Bericht als Datei gespeichert (kein Mailversand konfiguriert): "
                f"{result.get('saved_path')}")
            request.session["flash_class"] = ""
    except Exception as exc:
        request.session["flash"] = f"Fehler beim Senden: {exc}"
        request.session["flash_class"] = "err"
    # zurueck aufs Dashboard mit gleichem Projekt/Zeitraum
    return RedirectResponse(
        f"/?week=custom&project={project}&start={start}&end={end}",
        status_code=303)
