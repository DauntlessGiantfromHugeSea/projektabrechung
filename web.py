"""
Passwortgeschuetztes Web-Interface inkl. Benutzerverwaltung.

Seiten:
- /login              Anmeldung (gegen die User-DB)
- /logout             Abmelden
- /                   Dashboard: Wochenbericht, Filter, "Bericht jetzt senden"
- /account            eigenes Passwort aendern
- /users              Benutzerverwaltung (nur Admin): anlegen, einladen, loeschen
- /invite/<token>     Eingeladener Nutzer setzt sein Passwort (ohne Mail noetig)

Templates sind inline (Jinja2), damit das Docker-Image schlank bleibt.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template

import config
import mailer
import users
from events import load_records, normalize, pair_intervals
from report import (build_report, previous_week_range, render_html,
                    this_week_range)

router = APIRouter()

_BASE = """
<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} – Projektabrechnung</title>
<style>
  :root { --fg:#1f2933; --muted:#647382; --line:#e1e7ef; --bg:#f5f7fa;
          --brand:#92c57a; --accent:#92c57a; --accent-d:#7eb863;
          --accent-text:#14361f; --link:#5f9e45; --danger:#dc2626; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
         color:var(--fg); background:var(--bg); }
  header { background:#fff; border-bottom:3px solid var(--brand);
           padding:.6rem 1.2rem; display:flex; align-items:center;
           justify-content:space-between; flex-wrap:wrap; gap:.5rem; }
  header .brand { display:flex; align-items:center; gap:.6rem;
           font-weight:700; }
  header .brand img { height:30px; display:block; }
  nav a { color:var(--muted); text-decoration:none; margin-left:1rem;
          font-size:.9rem; }
  nav a:hover, nav a.active { color:var(--link); }
  main { max-width:920px; margin:1.5rem auto; padding:0 1.2rem; }
  .card { background:#fff; border:1px solid var(--line); border-radius:10px;
          padding:1.2rem 1.3rem; margin-bottom:1.2rem; }
  h1 { font-size:1.3rem; margin:.2rem 0 1rem; }
  h2 { font-size:1.05rem; margin:0 0 .8rem; }
  label { display:block; font-size:.85rem; color:var(--muted); margin:.6rem 0 .2rem; }
  input, select { width:100%; padding:.55rem .6rem; border:1px solid var(--line);
          border-radius:7px; font:inherit; background:#fff; }
  button { background:var(--accent); color:var(--accent-text); border:0;
           border-radius:7px; padding:.55rem 1rem; font:inherit;
           font-weight:700; cursor:pointer; }
  button:hover { background:var(--accent-d); }
  a { color:var(--link); }
  button.danger { background:#fff; color:var(--danger);
           border:1px solid var(--danger); padding:.35rem .7rem; font-size:.85rem; }
  table { border-collapse:collapse; width:100%; margin-top:.4rem; }
  th,td { padding:.5rem .6rem; border-bottom:1px solid var(--line); text-align:left; }
  td.num,th.num { text-align:right; }
  .row { display:flex; gap:1rem; flex-wrap:wrap; align-items:end; }
  .row > div { flex:1; min-width:140px; }
  .pill { display:inline-block; padding:.15rem .55rem; border-radius:999px;
          font-size:.8rem; font-weight:600; }
  .ok { background:#dcfce7; color:#166534; }
  .no { background:#fee2e2; color:#991b1b; }
  .role { background:#e0e7ff; color:#3730a3; }
  .inv { background:#fef9c3; color:#854d0e; }
  .muted { color:var(--muted); font-size:.9rem; }
  .flash { background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af;
           padding:.7rem .9rem; border-radius:8px; margin-bottom:1rem;
           word-break:break-all; }
  .err { background:#fef2f2; border-color:#fecaca; color:#991b1b; }
  .tags span { display:inline-block; background:#eef2f7; border-radius:6px;
           padding:.15rem .5rem; margin:.15rem .2rem 0 0; font-size:.85rem; }
  code { background:#eef2f7; padding:.1rem .35rem; border-radius:5px; }
</style></head><body>
{% if user %}
<header>
  <span class="brand">
    <img src="{{ logo_url }}" alt="FBE">
    <span>Projektabrechnung</span>
  </span>
  <nav>
    <a href="/" class="{{ 'active' if page=='dash' }}">Bericht</a>
    {% if role=='admin' %}<a href="/users" class="{{ 'active' if page=='users' }}">Benutzer</a>{% endif %}
    <a href="/account" class="{{ 'active' if page=='account' }}">Konto</a>
    <span class="muted">· {{ user }}</span>
    <a href="/logout">Abmelden</a>
  </nav>
</header>
{% endif %}
<main>
{% if flash %}<div class="flash {{ flash_class }}">{{ flash }}</div>{% endif %}
{% block body %}{% endblock %}
</main>
</body></html>
"""

_LOGIN = """
{% extends base %}
{% block body %}
<div class="card" style="max-width:380px;margin:6vh auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:48px;margin:.3rem 0 1rem;">
  <h1 style="text-align:left;">Anmelden</h1>
  {% if not login_possible %}
    <div class="flash err">Noch kein Benutzer vorhanden. Bitte
      <code>ADMIN_PASSWORD</code> in der .env setzen und neu starten.</div>
  {% endif %}
  <form method="post" action="/login">
    <label>Benutzer</label>
    <input name="username" autofocus autocomplete="username">
    <label>Passwort</label>
    <input name="password" type="password" autocomplete="current-password">
    <div style="margin-top:1rem;"><button type="submit">Einloggen</button></div>
  </form>
</div>
{% endblock %}
"""

_DASH = """
{% extends base %}
{% block body %}
<div class="card">
  <h2>Zeitraum &amp; Projekt</h2>
  <form method="get" action="/">
    <div class="row">
      <div><label>Woche</label>
        <select name="week" onchange="this.form.submit()">
          <option value="last" {{ 'selected' if week=='last' }}>Vorige Woche</option>
          <option value="this" {{ 'selected' if week=='this' }}>Diese Woche</option>
          <option value="custom" {{ 'selected' if week=='custom' }}>Eigener Zeitraum</option>
        </select></div>
      <div><label>Projektfilter (leer = alle)</label>
        <input name="project" value="{{ project }}" placeholder="z. B. 26344"></div>
      {% if week=='custom' %}
      <div><label>Von</label><input name="start" value="{{ start_in }}" placeholder="2026-06-01"></div>
      <div><label>Bis</label><input name="end" value="{{ end_in }}" placeholder="2026-06-08"></div>
      {% endif %}
      <div style="flex:0 0 auto;"><label>&nbsp;</label><button type="submit">Anzeigen</button></div>
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
      konfiguriert – wird nur als Datei gespeichert.</span>{% endif %}
  </form>
</div>
<div class="card">
  <h2>Datenlage aus den Webhooks</h2>
  <p>Projektcode erkannt:
    {% if has_project %}<span class="pill ok">ja</span>{% else %}<span class="pill no">nein</span>{% endif %}
    &nbsp; Ein-/Ausstempeln erkannt:
    {% if has_direction %}<span class="pill ok">ja</span>{% else %}<span class="pill no">nein</span>{% endif %}</p>
  <p class="muted">{{ events_total }} Events gespeichert · {{ intervals_paired }} Arbeitsintervalle.</p>
  {% if projects_seen %}<p>Im Zeitraum erkannte Projekte:</p>
    <div class="tags">{% for p in projects_seen %}<span>{{ p }}</span>{% endfor %}</div>
  {% else %}<p class="muted">Im gewählten Zeitraum kein Projektfeld gefunden.</p>{% endif %}
</div>
{% endblock %}
"""

_ACCOUNT = """
{% extends base %}
{% block body %}
<div class="card" style="max-width:480px;">
  <h1>Konto: {{ user }}</h1>
  <form method="post" action="/account">
    <label>Aktuelles Passwort</label>
    <input name="current" type="password" autocomplete="current-password">
    <label>Neues Passwort</label>
    <input name="new1" type="password" autocomplete="new-password">
    <label>Neues Passwort wiederholen</label>
    <input name="new2" type="password" autocomplete="new-password">
    <div style="margin-top:1rem;"><button type="submit">Passwort ändern</button></div>
  </form>
</div>
{% endblock %}
"""

_USERS = """
{% extends base %}
{% block body %}
<div class="card">
  <h1>Benutzer</h1>
  <table>
    <thead><tr><th>Benutzer</th><th>Rolle</th><th>Status</th><th></th></tr></thead>
    <tbody>
    {% for u in userlist %}
      <tr>
        <td>{{ u.username }}</td>
        <td><span class="pill role">{{ u.role }}</span></td>
        <td>{% if u.status=='active' %}<span class="pill ok">aktiv</span>
            {% else %}<span class="pill inv">eingeladen</span>{% endif %}</td>
        <td>
          {% if u.status=='invited' and u.invite_token %}
            <span class="muted">Link:</span>
            <code>{{ base_url }}invite/{{ u.invite_token }}</code>
          {% endif %}
          {% if u.username != user %}
          <form method="post" action="/users/delete" style="display:inline;">
            <input type="hidden" name="username" value="{{ u.username }}">
            <button class="danger" onclick="return confirm('Benutzer {{ u.username }} löschen?')">löschen</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
<div class="card" style="max-width:520px;">
  <h2>Neuen Benutzer einladen</h2>
  <p class="muted">Es wird ein Einladungslink erzeugt. Den Link gibst du der
    Person – sie setzt darüber ihr eigenes Passwort. (Kein Mailversand nötig.)</p>
  <form method="post" action="/users/create">
    <div class="row">
      <div><label>Benutzername</label><input name="username" placeholder="z. B. m.mustermann"></div>
      <div style="flex:0 0 160px;"><label>Rolle</label>
        <select name="role"><option value="user">user</option><option value="admin">admin</option></select></div>
    </div>
    <div style="margin-top:1rem;"><button type="submit">Einladung erstellen</button></div>
  </form>
</div>
{% endblock %}
"""

_INVITE = """
{% extends base %}
{% block body %}
<div class="card" style="max-width:420px;margin:6vh auto 0;">
  <h1>Willkommen, {{ invite_user }}</h1>
  <p class="muted">Lege jetzt dein Passwort fest, um dein Konto zu aktivieren.</p>
  <form method="post" action="/invite/{{ token }}">
    <label>Passwort</label>
    <input name="new1" type="password" autocomplete="new-password" autofocus>
    <label>Passwort wiederholen</label>
    <input name="new2" type="password" autocomplete="new-password">
    <div style="margin-top:1rem;"><button type="submit">Konto aktivieren</button></div>
  </form>
</div>
{% endblock %}
"""

LOGO_URL = "https://fb-eng.de/wp-content/uploads/2024/10/FBE_green.png"

_base_tpl = Template(_BASE)
_login_tpl = Template(_LOGIN)
_dash_tpl = Template(_DASH)
_account_tpl = Template(_ACCOUNT)
_users_tpl = Template(_USERS)
_invite_tpl = Template(_INVITE)
for _tpl in (_base_tpl, _login_tpl, _dash_tpl, _account_tpl, _users_tpl,
             _invite_tpl):
    _tpl.environment.globals["base"] = _base_tpl       # type: ignore
    _tpl.environment.globals["logo_url"] = LOGO_URL    # type: ignore


def _session_user(request: Request):
    return request.session.get("user")


def _session_role(request: Request) -> str:
    return request.session.get("role", "user")


def _pop_flash(request: Request):
    return (request.session.pop("flash", None),
            request.session.pop("flash_class", ""))


def _common(request: Request, page: str, title: str):
    flash, flash_class = _pop_flash(request)
    return dict(user=_session_user(request), role=_session_role(request),
                page=page, title=title, flash=flash, flash_class=flash_class)


# --- Login / Logout --------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if _session_user(request):
        return RedirectResponse("/", status_code=303)
    flash, flash_class = _pop_flash(request)
    return HTMLResponse(_login_tpl.render(
        title="Login", user=None, flash=flash, flash_class=flash_class,
        login_possible=bool(users.list_users()) or config.login_possible()))


@router.post("/login")
async def login_submit(request: Request,
                       username: str = Form(""), password: str = Form("")):
    user = users.verify_login(username.strip(), password)
    if not user:
        request.session["flash"] = "Benutzer oder Passwort falsch."
        request.session["flash_class"] = "err"
        return RedirectResponse("/login", status_code=303)
    request.session["user"] = user["username"]
    request.session["role"] = user.get("role", "user")
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- Dashboard -------------------------------------------------------------

def _inspect_stats():
    records = load_records()
    valid = [p for p in (normalize(r) for r in records) if p]
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
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)

    proj = project if project is not None else config.PROJECT_CODE
    start_in, end_in = start or "", end or ""
    if week == "this":
        s, e = this_week_range()
    elif week == "custom" and start and end:
        s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
    else:
        week, (s, e) = "last", previous_week_range()

    rep = build_report(s, e, project=proj)
    stats = _inspect_stats()
    return HTMLResponse(_dash_tpl.render(
        **_common(request, "dash", "Dashboard"),
        week=week, project=proj, start_in=start_in, end_in=end_in,
        report_title=(proj or "alle Projekte"),
        period=f"{rep.start:%d.%m.%Y} – {rep.end:%d.%m.%Y}",
        report_html=render_html(rep),
        start_iso=rep.start.date().isoformat(), end_iso=rep.end.date().isoformat(),
        mail_configured=config.mail_configured(),
        has_project=stats["has_project"], has_direction=stats["has_direction"],
        events_total=stats["events_total"],
        intervals_paired=stats["intervals_paired"],
        projects_seen=rep.projects_seen))


@router.post("/send")
async def send_now(request: Request, project: str = Form(""),
                   start: str = Form(""), end: str = Form("")):
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    try:
        s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
        result = mailer.deliver(build_report(s, e, project=project or None))
        if result.get("mailed"):
            request.session["flash"] = f"Bericht an {', '.join(result['recipients'])} versendet."
        else:
            request.session["flash"] = ("Als Datei gespeichert (kein Mailversand "
                                        f"konfiguriert): {result.get('saved_path')}")
    except Exception as exc:
        request.session["flash"] = f"Fehler beim Senden: {exc}"
        request.session["flash_class"] = "err"
    return RedirectResponse(
        f"/?week=custom&project={project}&start={start}&end={end}", status_code=303)


# --- Eigenes Konto ---------------------------------------------------------

@router.get("/account", response_class=HTMLResponse)
async def account_form(request: Request):
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(_account_tpl.render(**_common(request, "account", "Konto")))


@router.post("/account")
async def account_submit(request: Request, current: str = Form(""),
                         new1: str = Form(""), new2: str = Form("")):
    username = _session_user(request)
    if not username:
        return RedirectResponse("/login", status_code=303)
    if not users.verify_login(username, current):
        request.session["flash"] = "Aktuelles Passwort ist falsch."
        request.session["flash_class"] = "err"
    elif len(new1) < 8:
        request.session["flash"] = "Neues Passwort muss mind. 8 Zeichen haben."
        request.session["flash_class"] = "err"
    elif new1 != new2:
        request.session["flash"] = "Die neuen Passwörter stimmen nicht überein."
        request.session["flash_class"] = "err"
    else:
        users.set_password(username, new1)
        request.session["flash"] = "Passwort geändert."
    return RedirectResponse("/account", status_code=303)


# --- Benutzerverwaltung (Admin) -------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    if not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    if _session_role(request) != "admin":
        return HTMLResponse("Kein Zugriff (nur Admin).", status_code=403)
    return HTMLResponse(_users_tpl.render(
        **_common(request, "users", "Benutzer"),
        userlist=users.list_users(), base_url=str(request.base_url)))


@router.post("/users/create")
async def users_create(request: Request, username: str = Form(""),
                       role: str = Form("user")):
    if _session_role(request) != "admin" or not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    token = users.create_invite(username, role)
    if token is None:
        request.session["flash"] = "Benutzername leer oder bereits vergeben."
        request.session["flash_class"] = "err"
    else:
        link = f"{request.base_url}invite/{token}"
        request.session["flash"] = f"Einladung erstellt. Link: {link}"
    return RedirectResponse("/users", status_code=303)


@router.post("/users/delete")
async def users_delete(request: Request, username: str = Form("")):
    if _session_role(request) != "admin" or not _session_user(request):
        return RedirectResponse("/login", status_code=303)
    if username == _session_user(request):
        request.session["flash"] = "Sich selbst kann man nicht löschen."
        request.session["flash_class"] = "err"
    elif users.delete_user(username):
        request.session["flash"] = f"Benutzer {username} gelöscht."
    else:
        request.session["flash"] = "Löschen nicht möglich (letzter Admin?)."
        request.session["flash_class"] = "err"
    return RedirectResponse("/users", status_code=303)


# --- Einladung annehmen ----------------------------------------------------

@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_form(request: Request, token: str):
    u = users.find_by_invite(token)
    if not u:
        return HTMLResponse(_base_tpl.render(
            title="Einladung", user=None,
            flash="Einladungslink ungültig oder bereits verwendet.",
            flash_class="err"), status_code=404)
    return HTMLResponse(_invite_tpl.render(
        title="Einladung", user=None, flash=None, flash_class="",
        invite_user=escape(u["username"]), token=token))


@router.post("/invite/{token}")
async def invite_submit(request: Request, token: str,
                        new1: str = Form(""), new2: str = Form("")):
    u = users.find_by_invite(token)
    if not u:
        return HTMLResponse("Einladungslink ungültig.", status_code=404)
    if len(new1) < 8 or new1 != new2:
        request.session["flash"] = ("Passwort muss mind. 8 Zeichen haben und "
                                    "beide Felder müssen übereinstimmen.")
        request.session["flash_class"] = "err"
        return RedirectResponse(f"/invite/{token}", status_code=303)
    users.set_password(u["username"], new1)
    request.session["user"] = u["username"]
    request.session["role"] = u.get("role", "user")
    request.session["flash"] = "Konto aktiviert. Willkommen!"
    return RedirectResponse("/", status_code=303)
