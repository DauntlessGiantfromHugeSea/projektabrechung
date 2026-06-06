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

import activities
import audit
import config
import csvout
import downloads
import mailer
import manual
import scheduler
import settings
import users
import xlsxout
from events import delete_interval, load_records, normalize, pair_intervals
from fastapi.responses import FileResponse
from report import (build_attachment, build_grouped, build_report,
                    collect_intervals, collect_open, detail_sessions,
                    filter_intervals, previous_week_range, render_grouped_html,
                    render_grouped_text, render_html, render_text,
                    scope_intervals, subject_grouped, this_week_range)
from report import subject as report_subject

router = APIRouter()

LOGO_URL = "https://fb-eng.de/wp-content/uploads/2024/10/FBE_green.png"

_BASE = """
<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} – Projektabrechnung</title>
<style>
  :root{
    --fg:#1e293b; --muted:#64748b; --brand:#92c57a; --brand-d:#6fa84f;
    --accent-text:#123018; --link:#4d8838; --danger:#c0392b;
    --line:#e6eaef; --card:#ffffff;
    --shadow:0 1px 2px rgba(16,40,20,.05),0 8px 24px rgba(16,40,20,.07);
    --radius:18px;
  }
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;color:var(--fg);
    font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    background:#f5f7f9;
    background-image:radial-gradient(900px 360px at 100% -5%, rgba(146,197,122,.13) 0%, transparent 60%);
    background-attachment:fixed;}
  a{color:var(--link);text-decoration:none}
  a:hover{text-decoration:underline}
  svg{width:18px;height:18px;flex:0 0 auto;vertical-align:-3px}
  .glass,.card{background:var(--card);border:1px solid var(--line);
    border-radius:var(--radius);box-shadow:var(--shadow);}
  header{position:sticky;top:0;z-index:30;padding:.5rem 1.4rem;
    display:flex;align-items:center;justify-content:flex-start;
    flex-wrap:wrap;gap:.5rem;background:rgba(255,255,255,.9);
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    border-bottom:1px solid var(--line);}
  header .brand{display:flex;align-items:center;gap:.6rem;font-weight:800;
    letter-spacing:.2px;color:var(--fg)}
  header .brand img{height:30px;display:block}
  nav{display:flex;align-items:center;gap:.2rem;flex-wrap:wrap;margin-left:.7rem}
  .navpill{color:var(--muted);font-size:.93rem;font-weight:600;padding:.5rem .95rem;
    border-radius:999px;white-space:nowrap}
  .navpill:hover{background:#eef4e9;color:var(--brand-d);text-decoration:none}
  .navpill.active{background:rgba(146,197,122,.25);color:#2f6b1f}
  .topright{display:flex;align-items:center;gap:.3rem;margin-left:auto}
  .iconbtn{width:38px;height:38px;border-radius:50%;display:inline-flex;
    align-items:center;justify-content:center;color:var(--muted)}
  .iconbtn:hover{background:#eef4e9;color:var(--brand-d);text-decoration:none}
  .iconbtn svg{width:20px;height:20px}
  .menu{position:relative}
  .menu>summary{list-style:none;display:inline-flex;align-items:center;gap:.55rem;
    cursor:pointer;padding:.3rem .45rem;border-radius:999px;color:var(--fg);
    font-weight:700;font-size:.92rem}
  .menu>summary:hover{background:#eef4e9}
  .menu>summary::-webkit-details-marker{display:none}
  .menu .panel{position:absolute;right:0;top:122%;min-width:240px;background:#fff;
    border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);
    padding:.4rem;display:none;z-index:40}
  .menu[open] .panel{display:block}
  .menu .panel a{display:flex;align-items:center;gap:.65rem;padding:.6rem .7rem;
    border-radius:11px;color:var(--fg);font-weight:600;margin:0;font-size:.92rem}
  .menu .panel a:hover{background:#eef4e9;text-decoration:none}
  .menu .panel a.danger{color:var(--danger)}
  .menu .panel a.danger:hover{background:#fdecec}
  .menu .panel svg{width:17px;height:17px;color:var(--muted);flex:0 0 auto}
  .phead{padding:.55rem .7rem .25rem}
  .phead .muted{font-size:.82rem}
  .plabel{font-size:.72rem;letter-spacing:.7px;text-transform:uppercase;
    color:#94a3b8;padding:.65rem .7rem .25rem;font-weight:800}
  .pdiv{border-top:1px solid var(--line);margin:.35rem 0}
  .avatar{width:30px;height:30px;border-radius:50%;color:#fff;font-size:.78rem;
    background:var(--brand-d);display:inline-flex;align-items:center;
    justify-content:center;font-weight:800}
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
  .tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  @media (max-width:680px){
    main{margin:1rem auto;padding:0 .7rem}
    header{padding:.5rem .8rem}
    header .brand span{display:none}
    nav{gap:.1rem;margin-left:.2rem}
    .navpill{padding:.42rem .6rem;font-size:.85rem}
    .menu>summary span:not(.avatar){display:none}
    .card{padding:1rem 1rem;overflow-x:auto}
    h1{font-size:1.2rem}
    table{font-size:.86rem;min-width:520px}
    .row>div{min-width:120px}
  }
</style></head><body>
{% if user %}
<header>
  <a class="brand" href="/"><img src="{{ logo_url }}" alt="FBE"><span>Projektabrechnung</span></a>
  <nav>
    <a href="/meine-zeiten" class="navpill {{ 'active' if page=='meine' }}">Meine Zeiten</a>
    <a href="/" class="navpill {{ 'active' if page=='dash' }}">Bericht</a>
    <a href="/log" class="navpill {{ 'active' if page=='log' }}">Log</a>
    {% if is_billing %}<a href="/abrechnung" class="navpill {{ 'active' if page=='abrechnung' }}">Abrechnung</a>{% endif %}
    {% if role=='admin' %}
    <a href="/versand" class="navpill {{ 'active' if page=='send' }}">Senden</a>
    <a href="/reports" class="navpill {{ 'active' if page=='reports' }}">Berichte</a>
    {% endif %}
  </nav>
  <div class="topright">
    <a class="iconbtn" href="/anleitung" title="Hilfe &amp; Anleitung">{{ icons.help|safe }}</a>
    <details class="menu">
      <summary><span>{{ display_name or user }}</span><span class="avatar">{{ initials }}</span></summary>
      <div class="panel">
        <div class="phead"><b>{{ display_name or user }}</b><div class="muted">{{ role_label }}</div></div>
        <a href="/account">{{ icons.gear|safe }} Mein Konto</a>
        <a href="/anleitung">{{ icons.book|safe }} Hilfe &amp; Anleitung</a>
        {% if role=='admin' %}
        <div class="plabel">Administration</div>
        <a href="/users">{{ icons.users|safe }} Benutzer</a>
        <a href="/einstellungen">{{ icons.gear|safe }} Einstellungen</a>
        <a href="/audit">{{ icons.history|safe }} Verlauf</a>
        {% endif %}
        <div class="pdiv"></div>
        <a href="/logout" class="danger">{{ icons.logout|safe }} Abmelden</a>
      </div>
    </details>
  </div>
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
      <a class="btn ghost" href="/export.xlsx?employee={{ employee|urlencode }}&project={{ project|urlencode }}&start={{ start_in }}&end={{ end_in }}">Excel</a>
      <a class="btn ghost" href="/export/arcadis.csv?employee={{ employee|urlencode }}&project={{ project|urlencode }}&start={{ start_in }}&end={{ end_in }}">Arcadis-CSV</a>
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
      <th>Kommt</th><th>Geht</th><th class="num">Dauer</th><th>Tätigkeit</th><th>Quelle</th>
      {% if role=='admin' %}<th></th>{% endif %}</tr></thead>
    <tbody>
    {% for s in sessions %}
      <tr><td>{{ s.date }}</td><td>{{ s.employee }}</td><td>{{ s.project }}</td>
        <td>{{ s.start }}</td><td>{{ s.end }}</td><td class="num">{{ s.dur }}</td>
        <td>{% if role=='admin' %}
          <form method="post" action="/log/describe" style="display:flex;gap:.3rem;align-items:center">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <input name="description" value="{{ s.description }}" placeholder="Tätigkeit…" style="min-width:180px">
            <button class="ghost" type="submit" title="Speichern">✓</button>
          </form>
          {% else %}{{ s.description }}{% endif %}</td>
        <td>{% if s.source=='manual' %}<span class="pill role">manuell</span>{% else %}<span class="muted">TimeMoto</span>{% endif %}</td>
        {% if role=='admin' %}<td class="toolbar">
          <a class="btn ghost" href="/log/edit?iid={{ s.id|urlencode }}">{{ 'bearbeiten' if s.source=='manual' else 'korrigieren' }}</a>
          {% if s.source=='manual' %}
          <form method="post" action="/log/delete" style="display:inline;">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="danger" onclick="return confirm('Eintrag löschen?')">löschen</button></form>
          {% else %}
          <form method="post" action="/log/delete" style="display:inline;">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="ghost" type="submit">ausblenden</button></form>
          <form method="post" action="/log/purge" style="display:inline;">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="danger" onclick="return confirm('Diese TimeMoto-Buchung ENDGÜLTIG löschen? Die zugrunde liegenden Events werden entfernt.')">löschen</button></form>
          {% endif %}
        </td>{% endif %}
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

_SEND = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:680px;">
  <h1>Bericht senden</h1>
  <p class="muted">Projekte, Zeitraum und Empfänger zusammenstellen und sofort
    als E-Mail verschicken.{% if not mail_configured %} <b>Achtung:</b> SMTP ist
    nicht konfiguriert – der Bericht wird dann nur als Datei gespeichert.{% endif %}</p>
  <form method="post" action="/versand">
    <label>Betreff / Name</label>
    <input name="name" value="{{ f.name }}" placeholder="z. B. Projektzeiten Arcadis">
    <label>Projekte (eine pro Zeile oder Komma; leer = alle Projekte)</label>
    <textarea name="projects">{{ f.projects }}</textarea>
    {% if all_projects %}<div style="margin-top:.3rem;"><span class="muted">Erkannt:</span>
      {% for p in all_projects %}<span class="chip click" onclick="addP(this.innerText)">{{ p }}</span>{% endfor %}</div>{% endif %}
    <label>Empfänger (Mailadressen, Komma/Zeile)</label>
    <textarea name="recipients">{{ f.recipients }}</textarea>
    <label>Nachricht in der Mail (optional, erscheint über der Tabelle)</label>
    <textarea name="message" placeholder="z. B. Anbei die Projektzeiten der letzten Woche.">{{ f.message }}</textarea>
    <div class="row">
      <div style="flex:0 0 180px;"><label>Von</label><input type="date" name="start" value="{{ f.start }}"></div>
      <div style="flex:0 0 180px;"><label>Bis</label><input type="date" name="end" value="{{ f.end }}"></div>
    </div>
    <div style="margin-top:1.2rem;" class="toolbar">
      <button type="submit">Jetzt senden</button>
      <a class="btn ghost" href="/">Abbrechen</a></div>
  </form>
</div>
<script>function addP(t){var a=document.getElementsByName('projects')[0];
  a.value=(a.value.trim()?a.value.trim()+'\\n':'')+t;}</script>
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
      eigenes Passwort), Anzeigename + Rollen <b>admin</b>/<b>user</b>, Löschen.</li>
    <li>Eigenes Passwort und Anzeigename jederzeit unter <b>Konto</b> ändern.</li>
  </ul>

  {% if role=='admin' %}
  <hr style="border:none;border-top:1px solid var(--line);margin:1.4rem 0;">
  <h2>{{ icons.gear|safe }} Webhook einrichten (Admin)</h2>
  <p>In der <b>TimeMoto Cloud</b> (Plus-Plan) unter <b>Einstellungen →
    Webhooks</b> einen Webhook anlegen und als Ziel-URL eintragen:</p>
  <p><code>{{ webhook_url }}</code></p>
  <p>Als Ereignisse die <b>An-/Abwesenheits-Stempelungen</b> (attendance:
    Ein- und Ausstempeln) wählen.</p>
  <p>Hinterlegtes <b>Secret</b> (in TimeMoto identisch eintragen / dort generiert):</p>
  <p><code>{{ secret if secret else 'kein Secret gesetzt (SHARED_SECRET in .env)' }}</code></p>
  <p class="muted">Test: einmal unter einem Projekt ein- und ausstempeln –
    die Buchung erscheint im <b>Log</b> (offene Stempelungen unter „Läuft
    gerade“). Das Secret/den Endpoint änderst du über die <code>.env</code>
    auf dem Server.</p>
  {% endif %}
</div>
{% endblock %}
"""

_AUDIT = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1>Verlauf</h1>
  <p class="muted">Alle Änderungen und versendeten Mails – wer, wann, was.</p>
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
  <h1>Konto</h1>
  <p class="muted">Angemeldet als <b>{{ user }}</b></p>
  <form method="post" action="/account/name" style="margin-bottom:1.4rem;">
    <label>Anzeigename</label>
    <input name="name" value="{{ current_name }}">
    <div style="margin-top:.8rem;"><button type="submit">Name speichern</button></div>
  </form>
  <hr style="border:none;border-top:1px solid var(--line);">
  <h2 style="margin-top:1.2rem;">Passwort ändern</h2>
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
    <thead><tr><th>Name</th><th>Benutzer</th><th>E-Mail</th><th>TimeMoto</th>
      <th>Rolle</th><th>Status</th><th></th></tr></thead>
    <tbody>
    {% for u in userlist %}
      <tr>
        <td><b>{{ u.name or u.username }}</b></td>
        <td>{{ u.username }}</td>
        <td class="muted">{{ u.email or '–' }}</td>
        <td class="muted">{{ u.timemoto_name or '–' }}</td>
        <td><span class="pill role">{{ u.role }}</span></td>
        <td>{% if u.status=='active' %}<span class="pill ok">aktiv</span>
            {% else %}<span class="pill inv">eingeladen</span>{% endif %}</td>
        <td class="toolbar">
          {% if u.status=='invited' %}
            <form method="post" action="/users/resend" style="display:inline;">
              <input type="hidden" name="username" value="{{ u.username }}">
              <button class="ghost" type="submit">Einladung senden</button></form>
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
      <div><label>Anzeigename</label><input name="name" placeholder="z. B. Max Mustermann"></div>
      <div><label>Benutzername</label><input name="username" placeholder="z. B. m.mustermann"></div>
      <div style="flex:0 0 160px;"><label>Rolle</label>
        <select name="role"><option value="user">user</option>
          <option value="buchhaltung">buchhaltung</option>
          <option value="admin">admin</option></select></div>
    </div>
    <div class="row">
      <div><label>E-Mail (für Einladung &amp; Erinnerungen)</label><input name="email" type="email" placeholder="max@firma.de"></div>
      <div><label>TimeMoto-Name (für Stundenzuordnung)</label><input name="timemoto_name" placeholder="z. B. Max Mustermann"></div>
    </div>
    <p class="muted" style="margin:.5rem 0 0">Ist eine E-Mail angegeben, wird die
      Einladung direkt per Mail versendet (Link 5 Tage gültig).</p>
    <div style="margin-top:1rem;"><button type="submit">Einladung erstellen</button></div>
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

    <label>Nachricht in der Mail (optional, erscheint über der Tabelle)</label>
    <textarea name="message" placeholder="z. B. Anbei die Projektzeiten der letzten Woche.">{{ r.message }}</textarea>

    <div class="row">
      <div><label>CC (optional, Komma/Zeile)</label>
        <textarea name="cc" style="min-height:48px">{{ cc_text }}</textarea></div>
      <div style="flex:0 0 200px;"><label>Dateiformat</label>
        <select name="format">
          <option value="excel" {{ 'selected' if r.format!='csv' }}>Excel (.xlsx)</option>
          <option value="csv" {{ 'selected' if r.format=='csv' }}>Arcadis-CSV</option>
        </select></div>
    </div>

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

def _svg(paths: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            f'{paths}</svg>')


ICONS = {
    "chart": _svg('<path d="M3 3v18h18"/><path d="M7 15l3-4 3 2 4-6"/>'),
    "list": _svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
    "calendar": _svg('<rect x="3" y="4" width="18" height="17" rx="2"/>'
                     '<path d="M16 2v4M8 2v4M3 10h18"/>'),
    "mail": _svg('<rect x="2" y="4" width="20" height="16" rx="2"/>'
                 '<path d="M2 6l10 7 10-7"/>'),
    "users": _svg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
                  '<circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'),
    "history": _svg('<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/>'
                    '<path d="M12 7v5l3 2"/>'),
    "help": _svg('<circle cx="12" cy="12" r="10"/>'
                 '<path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'),
    "book": _svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
                 '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
    "gear": _svg('<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3'
                 'M1 14h6M9 8h6M17 16h6"/>'),
    "logout": _svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
                   '<path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>'),
}

_base_tpl = Template(_BASE)
_MEINE = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1>Meine Zeiten</h1>
  {% if not tm %}
    <p class="muted">Deinem Konto ist noch kein <b>TimeMoto-Name</b> zugeordnet.
      Bitte wende dich an einen Administrator, damit deine Buchungen hier
      erscheinen.</p>
  {% else %}
    <p class="muted">Buchungen der letzten {{ days }} Tage für <b>{{ tm }}</b>.
      Bitte trage je Eintrag eine Tätigkeitsbeschreibung ein (1–2 Sätze).</p>
    {% if sessions %}
    <table>
      <thead><tr><th>Datum</th><th>Projekt</th><th>Kommt</th><th>Geht</th>
        <th class="num">Dauer</th><th>Tätigkeitsbeschreibung</th></tr></thead>
      <tbody>
      {% for s in sessions %}
        <tr><td>{{ s.date }}</td><td>{{ s.project }}</td><td>{{ s.start }}</td>
          <td>{{ s.end }}</td><td class="num">{{ s.dur }}</td>
          <td><form method="post" action="/meine-zeiten/describe" style="display:flex;gap:.3rem;align-items:center">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <input name="description" value="{{ s.description }}" placeholder="Was wurde gemacht?" style="min-width:240px">
            <button type="submit" title="Speichern">✓</button></form></td></tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}<p>Keine Buchungen in den letzten {{ days }} Tagen.</p>{% endif %}
  {% endif %}
</div>
{% endblock %}
"""

_ABRECHNUNG = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1>Abrechnung</h1>
  <p class="muted">Alle Stunden über alle Projekte – nach Bedarf filtern und
    direkt als Excel oder Arcadis-CSV herunterladen (kein Mailversand).</p>
  <form method="get">
    <div class="row">
      <div><label>Mitarbeiter</label>
        <select name="employee"><option value="">– alle –</option>
          {% for e in all_employees %}<option value="{{ e }}">{{ e }}</option>{% endfor %}
        </select></div>
      <div><label>Projekt</label>
        <input name="project" placeholder="leer = alle" list="projs">
        <datalist id="projs">{% for p in all_projects %}<option value="{{ p }}">{% endfor %}</datalist></div>
      <div style="flex:0 0 160px;"><label>Von</label><input type="date" name="start" value="{{ start_in }}"></div>
      <div style="flex:0 0 160px;"><label>Bis</label><input type="date" name="end" value="{{ end_in }}"></div>
    </div>
    <div style="margin-top:1.2rem;" class="toolbar">
      <button type="submit" formaction="/export.xlsx">Excel herunterladen</button>
      <button type="submit" formaction="/export/arcadis.csv" class="ghost">Arcadis-CSV herunterladen</button>
    </div>
  </form>
</div>
<div class="card glass">
  <h2>Vorschau ({{ count }} Buchungen · {{ total }})</h2>
  {% if sessions %}
  <table><thead><tr><th>Datum</th><th>Mitarbeiter</th><th>Projekt</th>
    <th>Kommt</th><th>Geht</th><th class="num">Dauer</th><th>Tätigkeit</th></tr></thead>
  <tbody>{% for s in sessions %}<tr><td>{{ s.date }}</td><td>{{ s.employee }}</td>
    <td>{{ s.project }}</td><td>{{ s.start }}</td><td>{{ s.end }}</td>
    <td class="num">{{ s.dur }}</td><td>{{ s.description }}</td></tr>{% endfor %}</tbody></table>
  {% else %}<p class="muted">Keine Buchungen im Filter.</p>{% endif %}
</div>
{% endblock %}
"""

_SETTINGS = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:560px;">
  <h1>Einstellungen</h1>
  <p class="muted">Aktuelle Systemzeit: <b>{{ now }}</b></p>
  <form method="post" action="/einstellungen">
    <label>Zeitzone (für Wochengrenzen, Anzeige und Versandzeiten)</label>
    <select name="timezone">
      {% for z in zones %}<option value="{{ z }}" {{ 'selected' if z==tz }}>{{ z }}</option>{% endfor %}
    </select>
    <div style="margin-top:1.1rem;"><button type="submit">Speichern</button></div>
  </form>
</div>
{% endblock %}
"""

_tpls = {n: Template(s) for n, s in {
    "login": _LOGIN, "dash": _DASH, "log": _LOG, "log_form": _LOG_FORM,
    "send": _SEND, "anleitung": _ANLEITUNG, "audit": _AUDIT,
    "account": _ACCOUNT, "users": _USERS, "invite": _INVITE,
    "reports": _REPORTS, "report_form": _REPORT_FORM, "settings": _SETTINGS,
    "abrechnung": _ABRECHNUNG, "meine": _MEINE,
}.items()}
for _tpl in [_base_tpl, *_tpls.values()]:
    _tpl.environment.globals["base"] = _base_tpl       # type: ignore
    _tpl.environment.globals["logo_url"] = LOGO_URL    # type: ignore
    _tpl.environment.globals["icons"] = ICONS          # type: ignore


# --- Helfer ----------------------------------------------------------------

def _user(request: Request):
    return request.session.get("user")


def _role(request: Request) -> str:
    return request.session.get("role", "user")


def _common(request: Request, page: str, title: str):
    nm = request.session.get("name") or _user(request) or "?"
    initials = "".join(w[0] for w in nm.split()[:2]).upper() or nm[:1].upper()
    role = _role(request)
    role_label = {"admin": "Administrator", "buchhaltung": "Buchhaltung"}.get(
        role, "Benutzer")
    return dict(user=_user(request), role=role, page=page, title=title,
                display_name=request.session.get("name"), initials=initials,
                role_label=role_label, is_billing=(role in ("admin", "buchhaltung")),
                flash=request.session.pop("flash", None),
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
        "id": iv.id, "source": iv.source, "description": iv.description or "",
    }


def _fmt_dur(hours: float) -> str:
    m = round(hours * 60)
    return f"{m // 60}:{m % 60:02d} h"


def _delivery_flash(result: dict) -> tuple[str, str]:
    """Aus dem Zustell-Ergebnis eine verstaendliche Meldung bauen."""
    if result.get("mailed"):
        return f"Bericht an {', '.join(result['recipients'])} versendet.", ""
    reason = result.get("reason", "") or "unbekannt"
    if reason in ("no_smtp_host", "no_transport"):
        m = ("kein Versandweg konfiguriert – BREVO_API_KEY (empfohlen) oder "
             "SMTP_HOST in deploy/.env setzen und neu starten")
    elif reason == "no_recipients":
        m = "keine Empfänger angegeben"
    elif reason.startswith("smtp_error"):
        m = "SMTP-Fehler: " + reason.split(":", 1)[1].strip()
    else:
        m = reason
    return (f"NICHT per Mail gesendet ({m}). Als Datei gespeichert: "
            f"{result.get('saved_path', '')}", "err")


def _need_login(request: Request):
    return None if _user(request) else RedirectResponse("/login", status_code=303)


def _need_admin(request: Request):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if _role(request) != "admin":
        return HTMLResponse("Kein Zugriff (nur Admin).", status_code=403)
    return None


def _need_billing(request: Request):
    """Admin oder Buchhaltung."""
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if _role(request) not in ("admin", "buchhaltung"):
        return HTMLResponse("Kein Zugriff.", status_code=403)
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
    request.session["name"] = user.get("name") or user["username"]
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
        rep = build_report(s, e, project=project or None)
        ivs = scope_intervals(s, e, [project] if project else [])
        xlsx = xlsxout.intervals_xlsx(ivs, title=report_subject(rep))
        fname = f"{(project or 'alle')}_{s:%Y%m%d}.xlsx".replace(" ", "_")
        result = mailer.send_report(
            report_subject(rep), render_text(rep), render_html(rep),
            config.REPORT_RECIPIENTS, xlsx, fname,
            base_url=str(request.base_url), label=project or "alle",
            actor=_user(request))
        request.session["flash"], request.session["flash_class"] = \
            _delivery_flash(result)
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


@router.post("/log/purge")
async def log_purge(request: Request, iid: str = Form("")):
    if (r := _need_admin(request)):
        return r
    user = _user(request)
    if iid.startswith("wh:"):
        n = delete_interval(iid)
        manual.unhide(iid)
        audit.log(user, "endgültig gelöscht", f"{iid} ({n} Event-Zeilen)")
        request.session["flash"] = f"{n} TimeMoto-Event(s) endgültig gelöscht."
    elif iid.startswith("man:"):
        manual.delete_entry(iid[4:])
        audit.log(user, "gelöscht", iid)
        request.session["flash"] = "Eintrag gelöscht."
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


@router.post("/log/describe")
async def log_describe(request: Request, iid: str = Form(""),
                       description: str = Form("")):
    if (r := _need_admin(request)):
        return r
    activities.set_description(iid, description, _user(request))
    audit.log(_user(request), "Tätigkeit gesetzt", f"{iid}: {description[:80]}")
    return RedirectResponse(request.headers.get("referer") or "/log",
                            status_code=303)


@router.get("/export/arcadis.csv")
async def export_arcadis(request: Request, employee: str = "", project: str = "",
                         start: str = "", end: str = ""):
    if (r := _need_login(request)):
        return r
    s = e = None
    try:
        if start:
            s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        if end:
            e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
    except ValueError:
        pass
    data = csvout.arcadis_csv(filter_intervals(s, e, project=project,
                                               employee=employee))
    fname = f"arcadis_stunden_{datetime.now(config.TIMEZONE):%Y%m%d}.csv"
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/download/{token}")
async def download(token: str):
    """Oeffentlicher Download EINER tokenisierten Datei. Kein Login, aber auch
    kein Zugang zu anderen Seiten -- es wird nur diese registrierte Datei
    ausgeliefert."""
    entry = downloads.resolve(token)
    from pathlib import Path
    if not entry or not Path(entry["path"]).exists():
        return HTMLResponse("Link ungültig oder abgelaufen.", status_code=404)
    return FileResponse(
        entry["path"],
        media_type=entry.get("media_type", "application/octet-stream"),
        filename=entry.get("filename", "download.xlsx"))


@router.get("/versand", response_class=HTMLResponse)
async def versand_form(request: Request):
    if (r := _need_admin(request)):
        return r
    s, e = previous_week_range()
    f = {"name": "", "projects": "", "message": "",
         "recipients": ", ".join(config.REPORT_RECIPIENTS),
         "start": s.date().isoformat(), "end": (e.date()).isoformat()}
    return HTMLResponse(_tpls["send"].render(
        **_common(request, "send", "Senden"), f=f,
        all_projects=_all_projects(), mail_configured=config.mail_configured()))


@router.post("/versand")
async def versand_send(request: Request, name: str = Form(""),
                       projects: str = Form(""), recipients: str = Form(""),
                       message: str = Form(""), start: str = Form(""),
                       end: str = Form("")):
    if (r := _need_admin(request)):
        return r
    plist = [x.strip() for x in projects.replace("\n", ",").split(",") if x.strip()]
    rlist = [x.strip() for x in recipients.replace("\n", ",").split(",") if x.strip()]
    if not rlist:
        rlist = config.REPORT_RECIPIENTS
    if not rlist:
        request.session["flash"], request.session["flash_class"] = \
            "Bitte mindestens einen Empfänger angeben.", "err"
        return RedirectResponse("/versand", status_code=303)
    try:
        s = (datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
             if start else previous_week_range()[0])
        e = (datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
             if end else previous_week_range()[1])
    except ValueError:
        s, e = previous_week_range()

    if plist:
        rep = build_grouped(s, e, plist, name=name or "Bericht")
        subj, text, html = (subject_grouped(rep), render_grouped_text(rep),
                            render_grouped_html(rep))
    else:
        rep = build_report(s, e, project=None)
        subj = (name + " – " if name else "") + report_subject(rep)
        text, html = render_text(rep), render_html(rep)
    xlsx = xlsxout.intervals_xlsx(scope_intervals(s, e, plist), title=subj)
    fname = f"{(name or 'bericht')}_{s:%Y%m%d}.xlsx".replace(" ", "_")
    result = mailer.send_report(subj, text, html, rlist, xlsx, fname,
                                base_url=str(request.base_url),
                                label=name or "Versand", actor=_user(request),
                                message=message)
    request.session["flash"], request.session["flash_class"] = _delivery_flash(result)
    return RedirectResponse("/versand", status_code=303)


@router.get("/anleitung", response_class=HTMLResponse)
async def anleitung(request: Request):
    if (r := _need_login(request)):
        return r
    secret = config.SHARED_SECRET if _role(request) == "admin" else ""
    webhook_url = f"{request.base_url}{config.WEBHOOK_PATH.lstrip('/')}"
    return HTMLResponse(_tpls["anleitung"].render(
        **_common(request, "help", "Anleitung"),
        webhook_url=webhook_url, secret=secret))


_TZ_ZONES = ["Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/Paris",
             "Europe/Amsterdam", "Europe/London", "Europe/Madrid", "UTC",
             "America/New_York", "Asia/Dubai"]


@router.get("/einstellungen", response_class=HTMLResponse)
async def settings_page(request: Request):
    if (r := _need_admin(request)):
        return r
    tz = settings.get_timezone()
    zones = _TZ_ZONES if tz in _TZ_ZONES else [tz, *_TZ_ZONES]
    now = datetime.now(config.TIMEZONE).strftime("%A, %d.%m.%Y %H:%M:%S (%Z)")
    return HTMLResponse(_tpls["settings"].render(
        **_common(request, "settings", "Einstellungen"),
        zones=zones, tz=tz, now=now))


@router.post("/einstellungen")
async def settings_save(request: Request, timezone: str = Form("")):
    if (r := _need_admin(request)):
        return r
    if settings.set_timezone(timezone.strip()):
        scheduler.reschedule()
        audit.log(_user(request), "Zeitzone geändert", timezone.strip())
        request.session["flash"] = f"Zeitzone auf {timezone.strip()} gesetzt."
    else:
        request.session["flash"], request.session["flash_class"] = \
            "Ungültige Zeitzone.", "err"
    return RedirectResponse("/einstellungen", status_code=303)


@router.get("/meine-zeiten", response_class=HTMLResponse)
async def meine_zeiten(request: Request):
    if (r := _need_login(request)):
        return r
    u = users.get(_user(request)) or {}
    tm = (u.get("timemoto_name") or "").strip()
    days = 30
    sessions = []
    if tm:
        from datetime import timedelta
        start = datetime.now(config.TIMEZONE) - timedelta(days=days)
        ivs = filter_intervals(start, None, employee=tm)
        sessions = [_session_view(iv) for iv in ivs]
    return HTMLResponse(_tpls["meine"].render(
        **_common(request, "meine", "Meine Zeiten"), tm=tm, sessions=sessions,
        days=days))


@router.post("/meine-zeiten/describe")
async def meine_describe(request: Request, iid: str = Form(""),
                         description: str = Form("")):
    if (r := _need_login(request)):
        return r
    u = users.get(_user(request)) or {}
    tm = (u.get("timemoto_name") or "").strip().lower()
    iv = _find_interval(iid)
    if not tm or not iv or (iv.employee or "").lower() != tm:
        return HTMLResponse("Kein Zugriff auf diese Buchung.", status_code=403)
    activities.set_description(iid, description, _user(request))
    audit.log(_user(request), "Tätigkeit (eigene)", f"{iid}: {description[:80]}")
    return RedirectResponse("/meine-zeiten", status_code=303)


@router.get("/abrechnung", response_class=HTMLResponse)
async def abrechnung(request: Request, employee: str = "", project: str = "",
                     start: str = "", end: str = ""):
    if (r := _need_billing(request)):
        return r
    s = e = None
    try:
        if start:
            s = datetime.fromisoformat(start).replace(tzinfo=config.TIMEZONE)
        if end:
            e = datetime.fromisoformat(end).replace(tzinfo=config.TIMEZONE)
    except ValueError:
        pass
    ivs = filter_intervals(s, e, project=project, employee=employee)
    total = sum(iv.duration_hours for iv in ivs)
    return HTMLResponse(_tpls["abrechnung"].render(
        **_common(request, "abrechnung", "Abrechnung"),
        all_employees=_all_employees(), all_projects=_all_projects(),
        start_in=start, end_in=end,
        sessions=[_session_view(iv) for iv in ivs],
        count=len(ivs), total=_fmt_dur(total)))


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
    u = users.get(_user(request)) or {}
    return HTMLResponse(_tpls["account"].render(
        **_common(request, "account", "Konto"),
        current_name=u.get("name") or _user(request)))


@router.post("/account/name")
async def account_name(request: Request, name: str = Form("")):
    if (r := _need_login(request)):
        return r
    username = _user(request)
    users.set_name(username, name)
    request.session["name"] = (name or username).strip()
    request.session["flash"] = "Anzeigename gespeichert."
    return RedirectResponse("/account", status_code=303)


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


def _send_invite_mail(request: Request, display: str, email: str, token: str) -> bool:
    link = f"{request.base_url}invite/{token}"
    subj = "Einladung zur FBE Projektabrechnung"
    text = (f"Hallo {display},\n\nDu wurdest zur FBE Projektabrechnung "
            f"eingeladen. Lege hier dein Passwort fest (Link {config.INVITE_TTL_DAYS} "
            f"Tage gültig):\n{link}\n")
    html = (f"<p>Hallo {escape(display)},</p><p>Du wurdest zur "
            "<b>FBE Projektabrechnung</b> eingeladen. Lege über den Button dein "
            f"Passwort fest (Link {config.INVITE_TTL_DAYS} Tage gültig).</p>"
            f'<p><a href="{link}" style="display:inline-block;'
            f'background:{config.BRAND_COLOR};color:#123018;font-weight:bold;'
            'text-decoration:none;padding:12px 24px;border-radius:999px">'
            f'Konto aktivieren</a></p><p style="color:#64748b;font-size:13px">'
            f'Falls der Button nicht geht: {link}</p>')
    res = mailer.send(subj, text, html, [email], label="Einladung",
                      actor=_user(request))
    return bool(res.get("mailed"))


@router.post("/users/create")
async def users_create(request: Request, username: str = Form(""),
                       role: str = Form("user"), name: str = Form(""),
                       email: str = Form(""), timemoto_name: str = Form("")):
    if (r := _need_admin(request)):
        return r
    token = users.create_invite(username, role, name, email, timemoto_name)
    if token is None:
        request.session["flash"], request.session["flash_class"] = \
            "Benutzername leer oder bereits vergeben.", "err"
        return RedirectResponse("/users", status_code=303)
    link = f"{request.base_url}invite/{token}"
    if email.strip() and _send_invite_mail(request, name or username, email.strip(), token):
        request.session["flash"] = f"Einladung an {email.strip()} gesendet (Link 5 Tage gültig)."
    else:
        request.session["flash"] = f"Einladung erstellt. Link (5 Tage gültig): {link}"
    return RedirectResponse("/users", status_code=303)


@router.post("/users/resend")
async def users_resend(request: Request, username: str = Form("")):
    if (r := _need_admin(request)):
        return r
    token = users.renew_invite(username)
    u = users.get(username)
    if not token or not u:
        request.session["flash"], request.session["flash_class"] = \
            "Einladung nicht möglich (Benutzer aktiv?).", "err"
    elif u.get("email") and _send_invite_mail(request, u.get("name") or username,
                                              u["email"], token):
        request.session["flash"] = f"Einladung erneut an {u['email']} gesendet."
    else:
        request.session["flash"] = (f"Neuer Link (5 Tage): "
                                    f"{request.base_url}invite/{token}")
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
    blank = {"id": "", "name": "", "message": "", "projects": [],
             "recipients": [], "cc": [], "format": "excel",
             "day_of_week": "mon", "hour": 7, "minute": 0, "enabled": True}
    return HTMLResponse(_tpls["report_form"].render(
        **_common(request, "reports", "Neuer Bericht"),
        r=blank, action="/reports/new", days=_DAYS, all_projects=_all_projects(),
        projects_text="", recipients_text="", cc_text=""))


@router.post("/reports/new")
async def reports_create(request: Request, name: str = Form(""),
                         projects: str = Form(""), recipients: str = Form(""),
                         cc: str = Form(""), format: str = Form("excel"),
                         message: str = Form(""), day_of_week: str = Form("mon"),
                         hour: str = Form("7"), minute: str = Form("0"),
                         enabled: str = Form("")):
    if (r := _need_admin(request)):
        return r
    settings.add_report({"name": name, "projects": projects,
                         "recipients": recipients, "cc": cc, "format": format,
                         "message": message, "day_of_week": day_of_week,
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
        recipients_text=", ".join(cfg["recipients"]),
        cc_text=", ".join(cfg.get("cc", []))))


@router.post("/reports/{rid}/edit")
async def reports_update(request: Request, rid: str, name: str = Form(""),
                         projects: str = Form(""), recipients: str = Form(""),
                         cc: str = Form(""), format: str = Form("excel"),
                         message: str = Form(""), day_of_week: str = Form("mon"),
                         hour: str = Form("7"), minute: str = Form("0"),
                         enabled: str = Form("")):
    if (r := _need_admin(request)):
        return r
    settings.update_report(rid, {"name": name, "projects": projects,
                                "recipients": recipients, "cc": cc,
                                "format": format, "message": message,
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
    data, fname, mime = build_attachment(s, e, cfg["projects"],
                                         cfg.get("format", "excel"), cfg["name"])
    result = mailer.send_report(subject_grouped(rep), render_grouped_text(rep),
                                render_grouped_html(rep), cfg["recipients"],
                                data, fname, base_url=str(request.base_url),
                                label=cfg["name"], actor=_user(request),
                                message=cfg.get("message", ""),
                                cc=cfg.get("cc", []), mime=mime)
    request.session["flash"], request.session["flash_class"] = _delivery_flash(result)
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
    request.session["name"] = u.get("name") or u["username"]
    request.session["flash"] = "Konto aktiviert. Willkommen!"
    return RedirectResponse("/", status_code=303)
