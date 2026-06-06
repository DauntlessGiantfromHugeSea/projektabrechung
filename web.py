"""
Web-Interface: Login, Dashboard (Bericht + Einzelbuchungen), Konto,
Benutzerverwaltung und online konfigurierbare Berichte (Projekte/Empfaenger/
Zeitplan). Design: helles Glassmorphism im FBE-Look (#92c57a).

Templates inline (Jinja2), damit das Image schlank bleibt.
"""

from __future__ import annotations

import io
from datetime import datetime
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Template

import audit
import config
import mailer
import manual
import scheduler
import settings
import users
from events import load_records, normalize, pair_intervals
from report import (build_grouped, build_report, collect_intervals,
                    collect_open, detail_sessions, filter_intervals,
                    previous_week_range, render_grouped_html,
                    render_grouped_text, render_html, subject_grouped,
                    this_week_range)

router = APIRouter()

LOGO_URL = "https://fb-eng.de/wp-content/uploads/2024/10/FBE_green.png"

_BASE = """
<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} – Projektabrechnung</title>
<style>
  :root{
    --fg:#16331f; --muted:#5b6b5f; --brand:#92c57a; --brand-d:#6fa84f;
    --accent-text:#123018; --link:#4d8838; --danger:#c0392b;
    --glass:rgba(255,255,255,.55); --glass-strong:rgba(255,255,255,.72);
    --stroke:rgba(255,255,255,.65); --shadow:0 10px 30px rgba(40,80,40,.18);
    --radius:22px;
  }
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;color:var(--fg);
    font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    background:
      radial-gradient(1200px 600px at 10% -10%, #d8eecb 0%, transparent 55%),
      radial-gradient(1000px 700px at 110% 10%, #bfe3cf 0%, transparent 50%),
      linear-gradient(135deg,#eef6e8 0%,#e3f0ea 45%,#dceef3 100%);
    background-attachment:fixed;}
  a{color:var(--link);text-decoration:none}
  a:hover{text-decoration:underline}
  .glass{background:var(--glass);backdrop-filter:blur(18px) saturate(160%);
    -webkit-backdrop-filter:blur(18px) saturate(160%);
    border:1px solid var(--stroke);border-radius:var(--radius);
    box-shadow:var(--shadow);}
  header{position:sticky;top:0;z-index:10;margin:0;padding:.7rem 1.4rem;
    display:flex;align-items:center;justify-content:space-between;
    flex-wrap:wrap;gap:.6rem;border-radius:0 0 var(--radius) var(--radius);
    background:var(--glass-strong);backdrop-filter:blur(18px) saturate(160%);
    -webkit-backdrop-filter:blur(18px) saturate(160%);
    border-bottom:1px solid var(--stroke);box-shadow:var(--shadow);}
  header .brand{display:flex;align-items:center;gap:.7rem;font-weight:800;
    letter-spacing:.2px}
  header .brand img{height:30px;display:block}
  nav a{color:var(--muted);margin-left:1.1rem;font-size:.92rem;font-weight:600}
  nav a:hover,nav a.active{color:var(--brand-d);text-decoration:none}
  main{max-width:960px;margin:1.6rem auto;padding:0 1.2rem}
  .card{padding:1.3rem 1.4rem;margin-bottom:1.3rem}
  h1{font-size:1.4rem;margin:.1rem 0 1rem}
  h2{font-size:1.1rem;margin:0 0 .9rem}
  h3{font-size:1rem;margin:1rem 0 .4rem}
  label{display:block;font-size:.83rem;color:var(--muted);margin:.7rem 0 .25rem;
    font-weight:600}
  input,select,textarea{width:100%;padding:.6rem .7rem;border-radius:14px;
    border:1px solid rgba(146,197,122,.45);background:rgba(255,255,255,.7);
    font:inherit;color:var(--fg);outline:none;transition:.15s}
  input:focus,select:focus,textarea:focus{border-color:var(--brand);
    box-shadow:0 0 0 3px rgba(146,197,122,.3);background:#fff}
  textarea{min-height:80px;resize:vertical}
  button,.btn{background:linear-gradient(135deg,var(--brand),var(--brand-d));
    color:var(--accent-text);border:0;border-radius:999px;padding:.6rem 1.15rem;
    font:inherit;font-weight:800;cursor:pointer;box-shadow:0 6px 16px rgba(111,168,79,.35);
    transition:.15s;display:inline-block}
  button:hover,.btn:hover{transform:translateY(-1px);text-decoration:none;
    box-shadow:0 10px 22px rgba(111,168,79,.45)}
  button.ghost,.btn.ghost{background:rgba(255,255,255,.6);color:var(--brand-d);
    border:1px solid rgba(111,168,79,.5);box-shadow:none;font-weight:700}
  button.danger{background:rgba(255,255,255,.6);color:var(--danger);
    border:1px solid rgba(192,57,43,.5);box-shadow:none;padding:.4rem .8rem;
    font-size:.85rem}
  table{border-collapse:collapse;width:100%;margin-top:.5rem;font-size:.95rem}
  th,td{padding:.55rem .6rem;border-bottom:1px solid rgba(90,107,95,.18);
    text-align:left}
  th{font-size:.8rem;color:var(--muted);text-transform:uppercase;
    letter-spacing:.4px}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .row{display:flex;gap:1rem;flex-wrap:wrap;align-items:end}
  .row>div{flex:1;min-width:150px}
  .pill{display:inline-block;padding:.18rem .6rem;border-radius:999px;
    font-size:.78rem;font-weight:700}
  .ok{background:rgba(146,197,122,.35);color:#2f6b1f}
  .no{background:rgba(192,57,43,.18);color:#922}
  .role{background:rgba(99,102,241,.18);color:#3730a3}
  .inv{background:rgba(234,179,8,.22);color:#854d0e}
  .muted{color:var(--muted);font-size:.9rem}
  .chip{display:inline-block;background:rgba(146,197,122,.25);
    border:1px solid rgba(111,168,79,.35);border-radius:999px;
    padding:.15rem .6rem;margin:.15rem .25rem 0 0;font-size:.84rem}
  .chip.click{cursor:pointer}
  .flash{padding:.75rem .95rem;border-radius:16px;margin-bottom:1rem;
    background:rgba(146,197,122,.25);border:1px solid rgba(111,168,79,.4);
    color:#2f6b1f;word-break:break-word}
  .flash.err{background:rgba(192,57,43,.14);border-color:rgba(192,57,43,.4);
    color:#922}
  code{background:rgba(255,255,255,.65);padding:.12rem .4rem;border-radius:7px;
    font-size:.86em}
  .toolbar{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
</style></head><body>
{% if user %}
<header>
  <span class="brand"><img src="{{ logo_url }}" alt="FBE"><span>Projektabrechnung</span></span>
  <nav>
    <a href="/" class="{{ 'active' if page=='dash' }}">Bericht</a>
    <a href="/log" class="{{ 'active' if page=='log' }}">Log</a>
    {% if role=='admin' %}<a href="/reports" class="{{ 'active' if page=='reports' }}">Berichte</a>
    <a href="/users" class="{{ 'active' if page=='users' }}">Benutzer</a>
    <a href="/audit" class="{{ 'active' if page=='audit' }}">Änderungen</a>{% endif %}
    <a href="/anleitung" class="{{ 'active' if page=='help' }}">Anleitung</a>
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
<div class="card glass" style="max-width:390px;margin:8vh auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:52px;margin:.4rem 0 1.1rem;">
  <h1 style="text-align:left;">Anmelden</h1>
  {% if not login_possible %}
    <div class="flash err">Noch kein Benutzer. <code>ADMIN_PASSWORD</code> in
      der .env setzen und neu starten.</div>{% endif %}
  <form method="post" action="/login" style="text-align:left;">
    <label>Benutzer</label>
    <input name="username" autofocus autocomplete="username">
    <label>Passwort</label>
    <input name="password" type="password" autocomplete="current-password">
    <div style="margin-top:1.1rem;"><button type="submit">Einloggen</button></div>
  </form>
</div>
{% endblock %}
"""

_DASH = """
{% extends base %}
{% block body %}
<div class="card glass">
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
        <input name="project" value="{{ project }}" placeholder="z. B. 26344" list="projlist">
        <datalist id="projlist">{% for p in all_projects %}<option value="{{ p }}">{% endfor %}</datalist></div>
      {% if week=='custom' %}
      <div><label>Von</label><input name="start" value="{{ start_in }}" placeholder="2026-06-01"></div>
      <div><label>Bis</label><input name="end" value="{{ end_in }}" placeholder="2026-06-08"></div>
      {% endif %}
      <div style="flex:0 0 auto;"><label>&nbsp;</label><button type="submit">Anzeigen</button></div>
    </div>
  </form>
</div>

<div class="card glass">
  <h2>Zusammenfassung: {{ report_title }}</h2>
  <p class="muted">{{ period }}</p>
  {{ report_html|safe }}
  <form method="post" action="/send" style="margin-top:1rem;" class="toolbar">
    <input type="hidden" name="project" value="{{ project }}">
    <input type="hidden" name="start" value="{{ start_iso }}">
    <input type="hidden" name="end" value="{{ end_iso }}">
    <button type="submit">Diese Ansicht jetzt senden{{ '' if mail_configured else ' (als Datei)' }}</button>
    {% if not mail_configured %}<span class="muted">SMTP nicht konfiguriert – nur Datei.</span>{% endif %}
  </form>
</div>

<div class="card glass">
  <h2>Einzelbuchungen (Kommt / Geht)</h2>
  {% if sessions %}
  <table>
    <thead><tr><th>Datum</th><th>Mitarbeiter</th><th>Projekt</th>
      <th>Kommt</th><th>Geht</th><th class="num">Dauer</th></tr></thead>
    <tbody>
    {% for s in sessions %}
      <tr><td>{{ s.date }}</td><td>{{ s.employee }}</td><td>{{ s.project }}</td>
        <td>{{ s.start }}</td><td>{{ s.end }}</td><td class="num">{{ s.dur }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="muted">Keine Einzelbuchungen im Zeitraum.</p>{% endif %}
</div>

<div class="card glass">
  <h2>Datenlage aus den Webhooks</h2>
  <p>Projektcode erkannt:
    {% if has_project %}<span class="pill ok">ja</span>{% else %}<span class="pill no">nein</span>{% endif %}
    &nbsp; Ein-/Ausstempeln erkannt:
    {% if has_direction %}<span class="pill ok">ja</span>{% else %}<span class="pill no">nein</span>{% endif %}</p>
  <p class="muted">{{ events_total }} Events · {{ intervals_paired }} Arbeitsintervalle.</p>
  {% if projects_seen %}<div>{% for p in projects_seen %}<span class="chip">{{ p }}</span>{% endfor %}</div>{% endif %}
</div>
{% endblock %}
"""

_LOG = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Log – Buchungen</h1>
    <div class="toolbar">
      {% if role=='admin' %}<a class="btn" href="/log/edit">+ Eintrag hinzufügen</a>{% endif %}
      <a class="btn ghost" href="/export.xlsx?employee={{ employee|urlencode }}&project={{ project|urlencode }}&start={{ start_in }}&end={{ end_in }}">Excel-Export</a>
    </div>
  </div>
  <form method="get" action="/log">
    <div class="row">
      <div><label>Mitarbeiter</label>
        <select name="employee"><option value="">– alle –</option>
          {% for e in all_employees %}<option value="{{ e }}" {{ 'selected' if employee==e }}>{{ e }}</option>{% endfor %}
        </select></div>
      <div><label>Projekt</label>
        <select name="project"><option value="">– alle –</option>
          {% for p in all_projects %}<option value="{{ p }}" {{ 'selected' if project==p }}>{{ p }}</option>{% endfor %}
        </select></div>
      <div style="flex:0 0 150px;"><label>Von</label><input type="date" name="start" value="{{ start_in }}"></div>
      <div style="flex:0 0 150px;"><label>Bis</label><input type="date" name="end" value="{{ end_in }}"></div>
      <div style="flex:0 0 auto;"><label>&nbsp;</label><button type="submit">Filtern</button></div>
    </div>
  </form>
</div>

{% if open_sessions %}
<div class="card glass">
  <h2>Läuft gerade (eingestempelt, noch nicht ausgestempelt)</h2>
  <table><thead><tr><th>Mitarbeiter</th><th>Projekt</th><th>Seit</th></tr></thead>
  <tbody>{% for o in open_sessions %}<tr><td>{{ o.employee }}</td><td>{{ o.project }}</td>
    <td>{{ o.start }}</td></tr>{% endfor %}</tbody></table>
</div>
{% endif %}

<div class="card glass">
  <p class="muted">{{ count }} Buchung(en) · Summe <b>{{ total }}</b></p>
  {% if sessions %}
  <table>
    <thead><tr><th>Datum</th><th>Mitarbeiter</th><th>Projekt</th>
      <th>Kommt</th><th>Geht</th><th class="num">Dauer</th><th>Quelle</th>
      {% if role=='admin' %}<th></th>{% endif %}</tr></thead>
    <tbody>
    {% for s in sessions %}
      <tr><td>{{ s.date }}</td><td>{{ s.employee }}</td><td>{{ s.project }}</td>
        <td>{{ s.start }}</td><td>{{ s.end }}</td><td class="num">{{ s.dur }}</td>
        <td>{% if s.source=='manual' %}<span class="pill role">manuell</span>{% else %}<span class="muted">TimeMoto</span>{% endif %}</td>
        {% if role=='admin' %}<td class="toolbar">
          <a class="btn ghost" href="/log/edit?iid={{ s.id|urlencode }}">{{ 'bearbeiten' if s.source=='manual' else 'korrigieren' }}</a>
          <form method="post" action="/log/delete" style="display:inline;">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="danger" onclick="return confirm('Eintrag {{ 'löschen' if s.source=='manual' else 'ausblenden' }}?')">{{ 'löschen' if s.source=='manual' else 'ausblenden' }}</button>
          </form></td>{% endif %}
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p>Keine Buchungen für diese Filter.</p>{% endif %}
</div>

{% if role=='admin' and hidden %}
<div class="card glass">
  <h2>Ausgeblendete TimeMoto-Buchungen</h2>
  <table><tbody>
  {% for h in hidden %}<tr><td><code>{{ h }}</code></td>
    <td style="text-align:right;"><form method="post" action="/log/restore" style="display:inline;">
      <input type="hidden" name="iid" value="{{ h }}">
      <button class="ghost" type="submit">wieder einblenden</button></form></td></tr>{% endfor %}
  </tbody></table>
</div>
{% endif %}
{% endblock %}
"""

_LOG_FORM = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:560px;">
  <h1>{{ heading }}</h1>
  {% if is_correction %}<p class="muted">Korrektur einer TimeMoto-Buchung: das
    Original wird ausgeblendet und durch diesen Eintrag ersetzt.</p>{% endif %}
  <form method="post" action="/log/save">
    <input type="hidden" name="iid" value="{{ iid }}">
    <div class="row">
      <div><label>Mitarbeiter</label>
        <input name="employee" value="{{ f.employee }}" list="emps">
        <datalist id="emps">{% for e in all_employees %}<option value="{{ e }}">{% endfor %}</datalist></div>
      <div><label>Projekt</label>
        <input name="project" value="{{ f.project }}" list="projs">
        <datalist id="projs">{% for p in all_projects %}<option value="{{ p }}">{% endfor %}</datalist></div>
    </div>
    <div class="row">
      <div style="flex:0 0 180px;"><label>Datum</label><input type="date" name="date" value="{{ f.date }}"></div>
      <div style="flex:0 0 130px;"><label>Kommt</label><input type="time" name="start_time" value="{{ f.start_time }}"></div>
      <div style="flex:0 0 130px;"><label>Geht</label><input type="time" name="end_time" value="{{ f.end_time }}"></div>
    </div>
    <label>Notiz (optional)</label>
    <input name="note" value="{{ f.note }}" placeholder="z. B. Nachtrag, Korrektur Pause">
    <div style="margin-top:1.2rem;" class="toolbar">
      <button type="submit">Speichern</button>
      <a class="btn ghost" href="/log">Abbrechen</a>
    </div>
  </form>
</div>
{% endblock %}
"""

_ANLEITUNG = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1>Anleitung</h1>
  <h2>Überblick</h2>
  <p>Diese Anwendung sammelt die Stempelungen aus TimeMoto (per Webhook in
    Echtzeit) und macht daraus Projekt-Zeitberichte – ansehbar im Web und
    automatisch per E-Mail.</p>

  <h2>Bericht (Startseite)</h2>
  <ul>
    <li>Wähle <b>Woche</b> (vorige/diese/eigener Zeitraum) und optional einen
      <b>Projektfilter</b>.</li>
    <li>Oben die <b>Zusammenfassung</b> je Mitarbeiter (Stunden mit Minuten),
      darunter die <b>Einzelbuchungen</b> mit Kommt/Geht.</li>
    <li><b>Diese Ansicht jetzt senden</b> verschickt den aktuellen Ausschnitt
      sofort an die Standard-Empfänger.</li>
  </ul>

  <h2>Log</h2>
  <ul>
    <li>Alle Buchungen, filterbar nach <b>Mitarbeiter</b>, <b>Projekt</b> und
      <b>Zeitraum</b>.</li>
    <li><b>Läuft gerade</b>: zeigt offene Stempelungen (eingestempelt, noch
      nicht ausgestempelt) – so siehst du eine frische Buchung sofort.</li>
    <li><b>Excel-Export</b> exportiert genau die gefilterte Liste.</li>
    <li>Als Admin: <b>+ Eintrag hinzufügen</b>, einzelne Einträge
      <b>bearbeiten</b>, manuelle <b>löschen</b> oder TimeMoto-Buchungen
      <b>korrigieren/ausblenden</b>. Alle Änderungen stehen unter
      <b>Änderungen</b> (Audit-Log).</li>
  </ul>

  <h2>Berichte (Automatik, Admin)</h2>
  <ul>
    <li>Lege fest: <b>welche Projekte</b>, <b>an wen</b> und <b>wann</b>
      (Wochentag + Uhrzeit) ein Bericht automatisch verschickt wird.</li>
    <li>Es wird nur versendet, was hier definiert ist – nie automatisch „alle“.</li>
    <li><b>jetzt senden</b> testet einen Bericht (Inhalt = vorige Woche).</li>
  </ul>

  <h2>Benutzer (Admin)</h2>
  <ul>
    <li>Neue Personen per <b>Einladungslink</b> hinzufügen (sie setzen ihr
      eigenes Passwort), Rollen <b>admin</b>/<b>user</b>, Löschen.</li>
    <li>Eigenes Passwort jederzeit unter <b>Konto</b> ändern.</li>
  </ul>
</div>
{% endblock %}
"""

_AUDIT = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1>Änderungen (Audit-Log)</h1>
  {% if entries %}
  <table>
    <thead><tr><th>Zeit</th><th>Benutzer</th><th>Aktion</th><th>Details</th></tr></thead>
    <tbody>{% for a in entries %}<tr>
      <td class="muted">{{ a.when }}</td><td>{{ a.user }}</td>
      <td><span class="pill role">{{ a.action }}</span></td><td>{{ a.detail }}</td>
    </tr>{% endfor %}</tbody>
  </table>
  {% else %}<p class="muted">Noch keine Änderungen protokolliert.</p>{% endif %}
</div>
{% endblock %}
"""

_ACCOUNT = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:480px;">
  <h1>Konto: {{ user }}</h1>
  <form method="post" action="/account">
    <label>Aktuelles Passwort</label>
    <input name="current" type="password" autocomplete="current-password">
    <label>Neues Passwort</label>
    <input name="new1" type="password" autocomplete="new-password">
    <label>Neues Passwort wiederholen</label>
    <input name="new2" type="password" autocomplete="new-password">
    <div style="margin-top:1.1rem;"><button type="submit">Passwort ändern</button></div>
  </form>
</div>
{% endblock %}
"""

_USERS = """
{% extends base %}
{% block body %}
<div class="card glass">
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
            <span class="muted">Link:</span> <code>{{ base_url }}invite/{{ u.invite_token }}</code>
          {% endif %}
          {% if u.username != user %}
          <form method="post" action="/users/delete" style="display:inline;">
            <input type="hidden" name="username" value="{{ u.username }}">
            <button class="danger" onclick="return confirm('Benutzer {{ u.username }} löschen?')">löschen</button>
          </form>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
<div class="card glass" style="max-width:560px;">
  <h2>Neuen Benutzer einladen</h2>
  <p class="muted">Es wird ein Einladungslink erzeugt – die Person setzt darüber
    ihr eigenes Passwort (kein Mailversand nötig).</p>
  <form method="post" action="/users/create">
    <div class="row">
      <div><label>Benutzername</label><input name="username" placeholder="z. B. m.mustermann"></div>
      <div style="flex:0 0 160px;"><label>Rolle</label>
        <select name="role"><option value="user">user</option><option value="admin">admin</option></select></div>
    </div>
    <div style="margin-top:1.1rem;"><button type="submit">Einladung erstellen</button></div>
  </form>
</div>
{% endblock %}
"""

_INVITE = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:420px;margin:8vh auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:48px;margin:.3rem 0 1rem;">
  <h1 style="text-align:left;">Willkommen, {{ invite_user }}</h1>
  <p class="muted" style="text-align:left;">Lege dein Passwort fest (mind. 8 Zeichen).</p>
  <form method="post" action="/invite/{{ token }}" style="text-align:left;">
    <label>Passwort</label>
    <input name="new1" type="password" autocomplete="new-password" autofocus>
    <label>Passwort wiederholen</label>
    <input name="new2" type="password" autocomplete="new-password">
    <div style="margin-top:1.1rem;"><button type="submit">Konto aktivieren</button></div>
  </form>
</div>
{% endblock %}
"""

_REPORTS = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Berichte</h1>
    <a class="btn" href="/reports/new">+ Neuer Bericht</a>
  </div>
  <p class="muted">Nur diese definierten Berichte werden automatisch versendet.
    Ohne Eintrag geht keine Mail raus.</p>
  {% if not reports %}<p>Noch keine Berichte angelegt.</p>{% else %}
  <table>
    <thead><tr><th>Name</th><th>Projekte</th><th>Empfänger</th><th>Plan</th>
      <th>Status</th><th></th></tr></thead>
    <tbody>
    {% for r in reports %}
      <tr>
        <td><b>{{ r.name }}</b></td>
        <td>{% for p in r.projects %}<span class="chip">{{ p }}</span>{% endfor %}</td>
        <td class="muted">{{ r.recipients|join(', ') }}</td>
        <td>{{ r.day_label }} {{ '%02d:%02d'|format(r.hour, r.minute) }}</td>
        <td>{% if r.enabled %}<span class="pill ok">aktiv</span>{% else %}<span class="pill no">aus</span>{% endif %}</td>
        <td class="toolbar">
          <a class="btn ghost" href="/reports/{{ r.id }}/edit">bearbeiten</a>
          <form method="post" action="/reports/{{ r.id }}/send" style="display:inline;">
            <button class="ghost" type="submit">jetzt senden</button></form>
          <form method="post" action="/reports/{{ r.id }}/delete" style="display:inline;">
            <button class="danger" onclick="return confirm('Bericht löschen?')">löschen</button></form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>{% endif %}
</div>
{% endblock %}
"""

_REPORT_FORM = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:640px;">
  <h1>{{ 'Bericht bearbeiten' if r.id else 'Neuer Bericht' }}</h1>
  <form method="post" action="{{ action }}">
    <label>Name</label>
    <input name="name" value="{{ r.name }}" placeholder="z. B. Arcadis – wöchentlich">

    <label>Projekte (eines pro Zeile oder mit Komma; Teilstring genügt)</label>
    <textarea name="projects" placeholder="26344&#10;5543">{{ projects_text }}</textarea>
    {% if all_projects %}<div style="margin-top:.3rem;">
      <span class="muted">Erkannt:</span>
      {% for p in all_projects %}<span class="chip click" onclick="addProj(this.innerText)">{{ p }}</span>{% endfor %}
    </div>{% endif %}

    <label>Empfänger (Mailadressen, Komma- oder zeilengetrennt)</label>
    <textarea name="recipients" placeholder="chef@rss-fb.com, buchhaltung@rss-fb.com">{{ recipients_text }}</textarea>

    <div class="row">
      <div><label>Wochentag</label>
        <select name="day_of_week">
          {% for d,lbl in days %}<option value="{{ d }}" {{ 'selected' if r.day_of_week==d }}>{{ lbl }}</option>{% endfor %}
        </select></div>
      <div style="flex:0 0 110px;"><label>Stunde</label>
        <input name="hour" type="number" min="0" max="23" value="{{ r.hour }}"></div>
      <div style="flex:0 0 110px;"><label>Minute</label>
        <input name="minute" type="number" min="0" max="59" value="{{ r.minute }}"></div>
      <div style="flex:0 0 auto;"><label>Aktiv</label>
        <input type="checkbox" name="enabled" value="1" {{ 'checked' if r.enabled }} style="width:auto;transform:scale(1.4);margin-top:.6rem;"></div>
    </div>

    <div style="margin-top:1.2rem;" class="toolbar">
      <button type="submit">Speichern</button>
      <a class="btn ghost" href="/reports">Abbrechen</a>
    </div>
  </form>
</div>
<script>
function addProj(t){var ta=document.getElementsByName('projects')[0];
  ta.value=(ta.value.trim()?ta.value.trim()+'\\n':'')+t;}
</script>
{% endblock %}
"""

LOGO_GLOBAL = LOGO_URL
_base_tpl = Template(_BASE)
_tpls = {n: Template(s) for n, s in {
    "login": _LOGIN, "dash": _DASH, "log": _LOG, "log_form": _LOG_FORM,
    "anleitung": _ANLEITUNG, "audit": _AUDIT, "account": _ACCOUNT,
    "users": _USERS, "invite": _INVITE, "reports": _REPORTS,
    "report_form": _REPORT_FORM,
}.items()}
for _tpl in [_base_tpl, *_tpls.values()]:
    _tpl.environment.globals["base"] = _base_tpl       # type: ignore
    _tpl.environment.globals["logo_url"] = LOGO_URL    # type: ignore


# --- Helfer ----------------------------------------------------------------

def _user(request: Request):
    return request.session.get("user")


def _role(request: Request) -> str:
    return request.session.get("role", "user")


def _common(request: Request, page: str, title: str):
    return dict(user=_user(request), role=_role(request), page=page,
                title=title, flash=request.session.pop("flash", None),
                flash_class=request.session.pop("flash_class", ""))


def _all_projects() -> list[str]:
    seen = set()
    for r in load_records():
        p = normalize(r)
        if p and p.project:
            seen.add(p.project)
    return sorted(seen)


def _all_employees() -> list[str]:
    seen = set()
    for r in load_records():
        p = normalize(r)
        if p and p.employee and p.employee != "unbekannt":
            seen.add(p.employee)
    return sorted(seen)


def _session_view(iv) -> dict:
    return {
        "date": iv.start.astimezone(config.TIMEZONE).strftime("%a %d.%m.%Y"),
        "employee": iv.employee, "project": iv.project or "–",
        "start": iv.start.astimezone(config.TIMEZONE).strftime("%H:%M"),
        "end": iv.end.astimezone(config.TIMEZONE).strftime("%H:%M"),
        "dur": _fmt_dur(iv.duration_hours),
        "id": iv.id, "source": iv.source,
    }


def _fmt_dur(hours: float) -> str:
    m = round(hours * 60)
    return f"{m // 60}:{m % 60:02d} h"


def _need_login(request: Request):
    return None if _user(request) else RedirectResponse("/login", status_code=303)


def _need_admin(request: Request):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if _role(request) != "admin":
        return HTMLResponse("Kein Zugriff (nur Admin).", status_code=403)
    return None


# --- Login / Logout --------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if _user(request):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_tpls["login"].render(
        title="Login", user=None,
        flash=request.session.pop("flash", None),
        flash_class=request.session.pop("flash_class", ""),
        login_possible=bool(users.list_users()) or config.login_possible()))


@router.post("/login")
async def login_submit(request: Request, username: str = Form(""),
                       password: str = Form("")):
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
    return {"events_total": len(records),
            "has_project": any(p.project for p in valid),
            "has_direction": any(p.direction for p in valid),
            "intervals_paired": len(pair_intervals(valid))}


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, week: str = "last",
                    project: str | None = None, start: str | None = None,
                    end: str | None = None):
    if (r := _need_login(request)):
        return r
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
    sessions = [{
        "date": iv.start.astimezone(config.TIMEZONE).strftime("%a %d.%m."),
        "employee": iv.employee, "project": iv.project or "–",
        "start": iv.start.astimezone(config.TIMEZONE).strftime("%H:%M"),
        "end": iv.end.astimezone(config.TIMEZONE).strftime("%H:%M"),
        "dur": _fmt_dur(iv.duration_hours),
    } for iv in detail_sessions(s, e, project=proj)]
    stats = _inspect_stats()
    return HTMLResponse(_tpls["dash"].render(
        **_common(request, "dash", "Dashboard"),
        week=week, project=proj, start_in=start_in, end_in=end_in,
        all_projects=_all_projects(),
        report_title=(proj or "alle Projekte"),
        period=f"{rep.start:%d.%m.%Y} – {rep.end:%d.%m.%Y}",
        report_html=render_html(rep), sessions=sessions,
        start_iso=rep.start.date().isoformat(), end_iso=rep.end.date().isoformat(),
        mail_configured=config.mail_configured(),
        has_project=stats["has_project"], has_direction=stats["has_direction"],
        events_total=stats["events_total"],
        intervals_paired=stats["intervals_paired"],
        projects_seen=rep.projects_seen))


@router.post("/send")
async def send_now(request: Request, project: str = Form(""),
                   start: str = Form(""), end: str = Form("")):
    if (r := _need_login(request)):
        return r
    try:
        s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
        result = mailer.deliver(build_report(s, e, project=project or None))
        request.session["flash"] = (
            f"Bericht an {', '.join(result['recipients'])} versendet."
            if result.get("mailed")
            else f"Als Datei gespeichert: {result.get('saved_path')}")
    except Exception as exc:
        request.session["flash"] = f"Fehler beim Senden: {exc}"
        request.session["flash_class"] = "err"
    return RedirectResponse(
        f"/?week=custom&project={project}&start={start}&end={end}", status_code=303)


# --- Log / Buchungsansicht -------------------------------------------------

@router.get("/log", response_class=HTMLResponse)
async def log_page(request: Request, employee: str = "", project: str = "",
                   start: str = "", end: str = ""):
    if (r := _need_login(request)):
        return r
    s = e = None
    if start:
        try:
            s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        except ValueError:
            s = None
    if end:
        try:
            e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
        except ValueError:
            e = None
    intervals = filter_intervals(s, e, project=project, employee=employee)
    total_hours = sum(iv.duration_hours for iv in intervals)
    # Offene Sessions (optional gefiltert)
    opens = []
    for o in collect_open():
        if employee and employee.lower() not in o.employee.lower():
            continue
        if project and (not o.project or project.lower() not in o.project.lower()):
            continue
        opens.append({"employee": o.employee, "project": o.project or "–",
                      "start": o.start.astimezone(config.TIMEZONE).strftime("%a %d.%m. %H:%M")})
    hidden = sorted(manual.hidden_ids()) if _role(request) == "admin" else []
    return HTMLResponse(_tpls["log"].render(
        **_common(request, "log", "Log"),
        all_employees=_all_employees(), all_projects=_all_projects(),
        employee=employee, project=project, start_in=start, end_in=end,
        sessions=[_session_view(iv) for iv in intervals],
        open_sessions=opens, hidden=hidden,
        count=len(intervals), total=_fmt_dur(total_hours)))


def _parse_dt(date: str, t: str) -> datetime:
    return datetime.fromisoformat(f"{date}T{t}").replace(tzinfo=config.TIMEZONE)


def _find_interval(iid: str):
    for iv in collect_intervals():
        if iv.id == iid:
            return iv
    return None


@router.get("/log/edit", response_class=HTMLResponse)
async def log_edit(request: Request, iid: str = ""):
    if (r := _need_admin(request)):
        return r
    now = datetime.now(config.TIMEZONE)
    f = {"employee": "", "project": "", "date": now.strftime("%Y-%m-%d"),
         "start_time": "08:00", "end_time": "17:00", "note": ""}
    heading, is_correction = "Eintrag hinzufügen", False
    if iid.startswith("man:"):
        e = manual.get_entry(iid[4:])
        if e:
            st = datetime.fromisoformat(e["start"]).astimezone(config.TIMEZONE)
            en = datetime.fromisoformat(e["end"]).astimezone(config.TIMEZONE)
            f = {"employee": e["employee"], "project": e["project"],
                 "date": st.strftime("%Y-%m-%d"),
                 "start_time": st.strftime("%H:%M"),
                 "end_time": en.strftime("%H:%M"), "note": e.get("note", "")}
            heading = "Eintrag bearbeiten"
    elif iid.startswith("wh:"):
        iv = _find_interval(iid)
        if iv:
            st = iv.start.astimezone(config.TIMEZONE)
            en = iv.end.astimezone(config.TIMEZONE)
            f = {"employee": iv.employee, "project": iv.project or "",
                 "date": st.strftime("%Y-%m-%d"),
                 "start_time": st.strftime("%H:%M"),
                 "end_time": en.strftime("%H:%M"), "note": ""}
            heading, is_correction = "TimeMoto-Buchung korrigieren", True
    return HTMLResponse(_tpls["log_form"].render(
        **_common(request, "log", heading), iid=iid, f=f, heading=heading,
        is_correction=is_correction, all_employees=_all_employees(),
        all_projects=_all_projects()))


@router.post("/log/save")
async def log_save(request: Request, iid: str = Form(""),
                   employee: str = Form(""), project: str = Form(""),
                   date: str = Form(""), start_time: str = Form(""),
                   end_time: str = Form(""), note: str = Form("")):
    if (r := _need_admin(request)):
        return r
    user = _user(request)
    try:
        start_dt = _parse_dt(date, start_time)
        end_dt = _parse_dt(date, end_time)
        if end_dt <= start_dt:
            raise ValueError("Geht muss nach Kommt liegen.")
    except ValueError as exc:
        request.session["flash"], request.session["flash_class"] = \
            f"Ungültige Zeit: {exc}", "err"
        return RedirectResponse(f"/log/edit?iid={iid}", status_code=303)

    data = {"employee": employee, "project": project,
            "start": start_dt.isoformat(), "end": end_dt.isoformat(), "note": note}
    label = f"{employee} / {project} {date} {start_time}-{end_time}"
    if iid.startswith("man:"):
        manual.update_entry(iid[4:], data)
        audit.log(user, "bearbeitet", label)
        request.session["flash"] = "Eintrag gespeichert."
    elif iid.startswith("wh:"):
        data["replaces"] = iid
        manual.add_entry(data, user)
        manual.hide(iid)
        audit.log(user, "korrigiert", f"{label} (ersetzt {iid})")
        request.session["flash"] = "Korrektur gespeichert (Original ausgeblendet)."
    else:
        manual.add_entry(data, user)
        audit.log(user, "hinzugefügt", label)
        request.session["flash"] = "Eintrag hinzugefügt."
    return RedirectResponse("/log", status_code=303)


@router.post("/log/delete")
async def log_delete(request: Request, iid: str = Form("")):
    if (r := _need_admin(request)):
        return r
    user = _user(request)
    if iid.startswith("man:"):
        manual.delete_entry(iid[4:])
        audit.log(user, "gelöscht", iid)
        request.session["flash"] = "Eintrag gelöscht."
    elif iid.startswith("wh:"):
        manual.hide(iid)
        audit.log(user, "ausgeblendet", iid)
        request.session["flash"] = "TimeMoto-Buchung ausgeblendet."
    return RedirectResponse("/log", status_code=303)


@router.post("/log/restore")
async def log_restore(request: Request, iid: str = Form("")):
    if (r := _need_admin(request)):
        return r
    manual.unhide(iid)
    audit.log(_user(request), "wieder eingeblendet", iid)
    request.session["flash"] = "Buchung wieder eingeblendet."
    return RedirectResponse("/log", status_code=303)


@router.get("/export.xlsx")
async def export_xlsx(request: Request, employee: str = "", project: str = "",
                      start: str = "", end: str = ""):
    if (r := _need_login(request)):
        return r
    import openpyxl
    s = e = None
    try:
        if start:
            s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        if end:
            e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
    except ValueError:
        pass
    intervals = filter_intervals(s, e, project=project, employee=employee)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Buchungen"
    ws.append(["Datum", "Mitarbeiter", "Projekt", "Kommt", "Geht",
               "Dauer (Std:Min)", "Stunden (dez.)", "Quelle"])
    total = 0.0
    for iv in intervals:
        st = iv.start.astimezone(config.TIMEZONE)
        en = iv.end.astimezone(config.TIMEZONE)
        total += iv.duration_hours
        ws.append([st.strftime("%d.%m.%Y"), iv.employee, iv.project or "",
                   st.strftime("%H:%M"), en.strftime("%H:%M"),
                   _fmt_dur(iv.duration_hours).replace(" h", ""),
                   round(iv.duration_hours, 2),
                   "manuell" if iv.source == "manual" else "TimeMoto"])
    ws.append([])
    ws.append(["", "", "", "", "Summe", _fmt_dur(total).replace(" h", ""),
               round(total, 2), ""])
    for col, width in zip("ABCDEFGH", (12, 22, 34, 8, 8, 16, 14, 10)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    fname = f"buchungen_{datetime.now(config.TIMEZONE):%Y%m%d}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/anleitung", response_class=HTMLResponse)
async def anleitung(request: Request):
    if (r := _need_login(request)):
        return r
    return HTMLResponse(_tpls["anleitung"].render(**_common(request, "help", "Anleitung")))


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request):
    if (r := _need_admin(request)):
        return r
    entries = []
    for a in audit.list_entries():
        try:
            when = datetime.fromisoformat(a["ts"]).astimezone(
                config.TIMEZONE).strftime("%d.%m.%Y %H:%M")
        except Exception:
            when = a.get("ts", "")
        entries.append({"when": when, "user": a.get("user", "?"),
                        "action": a.get("action", ""), "detail": a.get("detail", "")})
    return HTMLResponse(_tpls["audit"].render(
        **_common(request, "audit", "Änderungen"), entries=entries))


# --- Konto -----------------------------------------------------------------

@router.get("/account", response_class=HTMLResponse)
async def account_form(request: Request):
    if (r := _need_login(request)):
        return r
    return HTMLResponse(_tpls["account"].render(**_common(request, "account", "Konto")))


@router.post("/account")
async def account_submit(request: Request, current: str = Form(""),
                         new1: str = Form(""), new2: str = Form("")):
    username = _user(request)
    if not username:
        return RedirectResponse("/login", status_code=303)
    if not users.verify_login(username, current):
        request.session["flash"], request.session["flash_class"] = \
            "Aktuelles Passwort ist falsch.", "err"
    elif len(new1) < 8:
        request.session["flash"], request.session["flash_class"] = \
            "Neues Passwort braucht mind. 8 Zeichen.", "err"
    elif new1 != new2:
        request.session["flash"], request.session["flash_class"] = \
            "Die neuen Passwörter stimmen nicht überein.", "err"
    else:
        users.set_password(username, new1)
        request.session["flash"] = "Passwort geändert."
    return RedirectResponse("/account", status_code=303)


# --- Benutzerverwaltung ----------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    if (r := _need_admin(request)):
        return r
    return HTMLResponse(_tpls["users"].render(
        **_common(request, "users", "Benutzer"),
        userlist=users.list_users(), base_url=str(request.base_url)))


@router.post("/users/create")
async def users_create(request: Request, username: str = Form(""),
                       role: str = Form("user")):
    if (r := _need_admin(request)):
        return r
    token = users.create_invite(username, role)
    if token is None:
        request.session["flash"], request.session["flash_class"] = \
            "Benutzername leer oder bereits vergeben.", "err"
    else:
        request.session["flash"] = f"Einladung: {request.base_url}invite/{token}"
    return RedirectResponse("/users", status_code=303)


@router.post("/users/delete")
async def users_delete(request: Request, username: str = Form("")):
    if (r := _need_admin(request)):
        return r
    if username == _user(request):
        request.session["flash"], request.session["flash_class"] = \
            "Sich selbst kann man nicht löschen.", "err"
    elif users.delete_user(username):
        request.session["flash"] = f"Benutzer {username} gelöscht."
    else:
        request.session["flash"], request.session["flash_class"] = \
            "Löschen nicht möglich (letzter Admin?).", "err"
    return RedirectResponse("/users", status_code=303)


# --- Berichte-Verwaltung ---------------------------------------------------

_DAYS = [("mon", "Montag"), ("tue", "Dienstag"), ("wed", "Mittwoch"),
         ("thu", "Donnerstag"), ("fri", "Freitag"), ("sat", "Samstag"),
         ("sun", "Sonntag")]


def _report_view(cfg):
    cfg = dict(cfg)
    cfg["day_label"] = settings.day_label(cfg["day_of_week"])
    return cfg


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    if (r := _need_admin(request)):
        return r
    return HTMLResponse(_tpls["reports"].render(
        **_common(request, "reports", "Berichte"),
        reports=[_report_view(c) for c in settings.list_reports()]))


@router.get("/reports/new", response_class=HTMLResponse)
async def reports_new(request: Request):
    if (r := _need_admin(request)):
        return r
    blank = {"id": "", "name": "", "projects": [], "recipients": [],
             "day_of_week": "mon", "hour": 7, "minute": 0, "enabled": True}
    return HTMLResponse(_tpls["report_form"].render(
        **_common(request, "reports", "Neuer Bericht"),
        r=blank, action="/reports/new", days=_DAYS, all_projects=_all_projects(),
        projects_text="", recipients_text=""))


@router.post("/reports/new")
async def reports_create(request: Request, name: str = Form(""),
                         projects: str = Form(""), recipients: str = Form(""),
                         day_of_week: str = Form("mon"), hour: str = Form("7"),
                         minute: str = Form("0"), enabled: str = Form("")):
    if (r := _need_admin(request)):
        return r
    settings.add_report({"name": name, "projects": projects,
                         "recipients": recipients, "day_of_week": day_of_week,
                         "hour": hour, "minute": minute,
                         "enabled": bool(enabled)})
    scheduler.reschedule()
    request.session["flash"] = "Bericht angelegt."
    return RedirectResponse("/reports", status_code=303)


@router.get("/reports/{rid}/edit", response_class=HTMLResponse)
async def reports_edit(request: Request, rid: str):
    if (r := _need_admin(request)):
        return r
    cfg = settings.get_report(rid)
    if not cfg:
        return RedirectResponse("/reports", status_code=303)
    return HTMLResponse(_tpls["report_form"].render(
        **_common(request, "reports", "Bericht bearbeiten"),
        r=cfg, action=f"/reports/{rid}/edit", days=_DAYS,
        all_projects=_all_projects(),
        projects_text="\n".join(cfg["projects"]),
        recipients_text=", ".join(cfg["recipients"])))


@router.post("/reports/{rid}/edit")
async def reports_update(request: Request, rid: str, name: str = Form(""),
                         projects: str = Form(""), recipients: str = Form(""),
                         day_of_week: str = Form("mon"), hour: str = Form("7"),
                         minute: str = Form("0"), enabled: str = Form("")):
    if (r := _need_admin(request)):
        return r
    settings.update_report(rid, {"name": name, "projects": projects,
                                "recipients": recipients,
                                "day_of_week": day_of_week, "hour": hour,
                                "minute": minute, "enabled": bool(enabled)})
    scheduler.reschedule()
    request.session["flash"] = "Bericht gespeichert."
    return RedirectResponse("/reports", status_code=303)


@router.post("/reports/{rid}/delete")
async def reports_delete(request: Request, rid: str):
    if (r := _need_admin(request)):
        return r
    settings.delete_report(rid)
    scheduler.reschedule()
    request.session["flash"] = "Bericht gelöscht."
    return RedirectResponse("/reports", status_code=303)


@router.post("/reports/{rid}/send")
async def reports_send(request: Request, rid: str):
    if (r := _need_admin(request)):
        return r
    cfg = settings.get_report(rid)
    if not cfg:
        return RedirectResponse("/reports", status_code=303)
    s, e = previous_week_range()
    rep = build_grouped(s, e, cfg["projects"], name=cfg["name"])
    result = mailer.send(subject_grouped(rep), render_grouped_text(rep),
                         render_grouped_html(rep), cfg["recipients"],
                         label=cfg["name"])
    request.session["flash"] = (
        f"'{cfg['name']}' an {', '.join(result['recipients'])} versendet."
        if result.get("mailed")
        else f"'{cfg['name']}' als Datei gespeichert (kein Mailversand): "
             f"{result.get('saved_path')}")
    return RedirectResponse("/reports", status_code=303)


# --- Einladung -------------------------------------------------------------

@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_form(request: Request, token: str):
    u = users.find_by_invite(token)
    if not u:
        return HTMLResponse(_base_tpl.render(
            title="Einladung", user=None, flash_class="err",
            flash="Einladungslink ungültig oder bereits verwendet."),
            status_code=404)
    return HTMLResponse(_tpls["invite"].render(
        title="Einladung", user=None, flash=None, flash_class="",
        invite_user=escape(u["username"]), token=token))


@router.post("/invite/{token}")
async def invite_submit(request: Request, token: str, new1: str = Form(""),
                        new2: str = Form("")):
    u = users.find_by_invite(token)
    if not u:
        return HTMLResponse("Einladungslink ungültig.", status_code=404)
    if len(new1) < 8 or new1 != new2:
        request.session["flash"], request.session["flash_class"] = \
            "Passwort min. 8 Zeichen und beide Felder gleich.", "err"
        return RedirectResponse(f"/invite/{token}", status_code=303)
    users.set_password(u["username"], new1)
    request.session["user"] = u["username"]
    request.session["role"] = u.get("role", "user")
    request.session["flash"] = "Konto aktiviert. Willkommen!"
    return RedirectResponse("/", status_code=303)
