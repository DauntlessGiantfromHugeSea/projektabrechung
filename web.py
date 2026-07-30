"""
Web-Interface: Login, Dashboard (Bericht + Einzelbuchungen), Konto,
Benutzerverwaltung und online konfigurierbare Berichte (Projekte/Empfaenger/
Zeitplan). Design: dunkelgrüne Topbar + helle Cards im FBE-Look (#92c57a),
Split-Screen-Login und Dashboard – angelehnt an das Teilnahmemanagement.

Templates inline (Jinja2), damit das Image schlank bleibt.
"""

from __future__ import annotations

import io
import shutil
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import pyotp
import secrets
import segno
from fastapi import APIRouter, File, Form, Request, UploadFile
import json

from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Template

import activities
import audit
import config
import csvout
import docs
import docfiles
import downloads
import mailer
import manual
import msauth
import scheduler
import settings
import tickets
import users
import vcards
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
LOGO_URL_WHITE = "https://fb-eng.de/wp-content/uploads/2024/10/FBE_white.png"
_ICON_URL = "https://fb-eng.de/wp-content/uploads/2024/10/cropped-FBE_midnight.png"

# Web-App (PWA): Manifest + minimaler Service-Worker (installierbar auf
# Handy/Desktop, Startseite /start).
_MANIFEST = {
    "name": "FBE Intranet",
    "short_name": "FBE Intranet",
    "description": "Internes Tool der Flüssigboden Engineering GmbH – "
                   "Zeiten, Projektabrechnung, Tickets & Exporte.",
    "lang": "de",
    "start_url": "/start",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait-primary",
    "background_color": "#ffffff",
    "theme_color": "#92c57a",
    "icons": [
        {"src": _ICON_URL, "sizes": "192x192", "type": "image/png",
         "purpose": "any"},
        {"src": _ICON_URL, "sizes": "512x512", "type": "image/png",
         "purpose": "any"},
        {"src": _ICON_URL, "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ],
}

# Netzwerk-first, ohne Caching -> keine veralteten Inhalte, aber installierbar.
_SW_JS = (
    "self.addEventListener('install',function(e){self.skipWaiting();});"
    "self.addEventListener('activate',function(e){"
    "e.waitUntil(self.clients.claim());});"
    "self.addEventListener('fetch',function(e){"
    "e.respondWith(fetch(e.request).catch(function(){"
    "return new Response('',{status:504});}));});"
)

_BASE = """
<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} – {{ texts.app_title }}</title>
<link rel="icon" href="https://fb-eng.de/wp-content/uploads/2024/10/cropped-FBE_midnight.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="https://fb-eng.de/wp-content/uploads/2024/10/cropped-FBE_midnight.png">
<meta name="theme-color" content="#92c57a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="FBE Intranet">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{
    --fg:#1b2a20; --muted:#6a7870; --brand:#92c57a; --brand-d:#6fa84f;
    --brand-deep:#2f6b1f; --brand-bright:#a4d65e; --accent-text:#16330f;
    --bar:#92c57a; --bar-2:#85ba6b;
    --link:#44772f; --danger:#b3372a;
    --line:#e6eae1; --line-soft:#eef1ea; --card:#ffffff; --bg:#f8faf6;
    --shadow:0 1px 2px rgba(18,38,24,.04),0 8px 28px rgba(18,38,24,.06);
    --radius:18px;
  }
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;color:var(--fg);
    font:15px/1.6 Inter,-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,Segoe UI,Roboto,sans-serif;
    background:var(--bg);-webkit-font-smoothing:antialiased;
    text-rendering:optimizeLegibility;}
  a{color:var(--link);text-decoration:none}
  a:hover{text-decoration:underline}
  svg{width:18px;height:18px;flex:0 0 auto;vertical-align:-3px}
  .glass,.card{background:var(--card);
    border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);}
  header{position:sticky;top:0;z-index:30;padding:.55rem 1.5rem;
    display:flex;align-items:center;justify-content:flex-start;
    flex-wrap:wrap;gap:.4rem;
    background:linear-gradient(180deg,var(--bar-2),var(--bar));
    box-shadow:0 4px 18px rgba(16,40,24,.18);}
  header .brand{display:flex;align-items:center;gap:.6rem}
  header .brand img{height:34px;display:block}
  nav{display:flex;align-items:center;gap:.15rem;flex-wrap:wrap;margin-left:1rem}
  .navpill{color:#fff;font-size:.92rem;font-weight:600;
    padding:.5rem 1rem;border-radius:999px;white-space:nowrap;transition:.14s}
  .navpill:hover{background:rgba(255,255,255,.20);color:#fff;text-decoration:none}
  .navpill.active{background:#fff;color:#2f6b1f;
    box-shadow:0 4px 12px rgba(16,40,24,.18)}
  .topright{display:flex;align-items:center;gap:.35rem;margin-left:auto}
  .iconbtn{width:38px;height:38px;border-radius:50%;display:inline-flex;
    align-items:center;justify-content:center;color:rgba(255,255,255,.85)}
  .iconbtn:hover{background:rgba(255,255,255,.15);color:#fff;text-decoration:none}
  .iconbtn svg{width:20px;height:20px}
  .impbar{position:sticky;top:0;z-index:29;display:flex;align-items:center;
    justify-content:space-between;gap:1rem;flex-wrap:wrap;
    padding:.55rem 1.5rem;background:#8a4b12;color:#fff;font-size:.9rem;
    box-shadow:0 3px 12px rgba(120,60,10,.25)}
  .impbar b{font-weight:800}
  .impbar svg{width:16px;height:16px;color:#fff;vertical-align:-3px}
  .impbar button{background:#fff;color:#8a4b12;box-shadow:none;font-weight:800;
    padding:.4rem .9rem;font-size:.85rem}
  .impbar button:hover{background:#fdf3e8;transform:none;box-shadow:none}
  .menu{position:relative}
  .menu>summary{list-style:none;display:inline-flex;align-items:center;gap:.55rem;
    cursor:pointer;padding:.32rem .5rem;border-radius:999px;
    color:#fff;font-weight:700;font-size:.92rem}
  .menu>summary:hover{background:rgba(255,255,255,.20)}
  .menu>summary::-webkit-details-marker{display:none}
  .menu.tab>summary{font-weight:600;color:#fff}
  .menu.tab>summary.active{color:#2f6b1f;background:#fff;
    box-shadow:0 4px 12px rgba(16,40,24,.18)}
  .menu.tab .panel{left:0;right:auto;min-width:210px}
  .menu .panel{position:absolute;right:0;top:122%;min-width:240px;background:#fff;
    border:1px solid var(--line);border-radius:14px;
    box-shadow:0 10px 36px rgba(18,38,24,.16),0 2px 6px rgba(18,38,24,.06);
    padding:.35rem;display:none;z-index:40}
  .menu[open] .panel{display:block}
  .menu .panel a{display:flex;align-items:center;gap:.65rem;padding:.6rem .7rem;
    border-radius:11px;color:var(--fg);font-weight:600;margin:0;font-size:.92rem}
  .menu .panel a:hover{background:#eef4e9;text-decoration:none}
  .menu .panel a.danger{color:var(--danger)}
  .menu .panel a.danger:hover{background:#fdecec}
  .menu .panel button.panelitem{display:flex;align-items:center;gap:.55rem;
    width:100%;background:none;color:var(--fg);border:0;box-shadow:none;
    padding:.6rem .7rem;border-radius:11px;font-weight:600;font-size:.92rem;
    cursor:pointer;justify-content:flex-start;text-align:left}
  .menu .panel button.panelitem:hover{background:#eef4e9;transform:none}
  .menu .panel button.panelitem.danger{color:var(--danger)}
  .menu .panel button.panelitem.danger:hover{background:#fdecec}
  .menu .panel form{margin:0}
  .menu .panel svg{width:17px;height:17px;color:var(--muted);flex:0 0 auto}
  .phead{padding:.55rem .7rem .25rem}
  .phead .muted{font-size:.82rem}
  .plabel{font-size:.72rem;letter-spacing:.7px;text-transform:uppercase;
    color:#94a3b8;padding:.65rem .7rem .25rem;font-weight:800}
  .pdiv{border-top:1px solid var(--line);margin:.35rem 0}
  .avatar{width:30px;height:30px;border-radius:50%;color:#2f6b1f;font-size:.78rem;
    background:#fff;display:inline-flex;align-items:center;
    justify-content:center;font-weight:800}
  main{max-width:1180px;margin:1.6rem auto;padding:0 1.2rem}
  .card{padding:1.3rem 1.4rem;margin-bottom:1.3rem}
  h1{font-size:1.4rem;margin:.1rem 0 1rem}
  h2{font-size:1.1rem;margin:0 0 .9rem}
  h3{font-size:1rem;margin:1rem 0 .4rem}
  label{display:block;font-size:.83rem;color:var(--muted);margin:.7rem 0 .25rem;
    font-weight:600}
  input,select,textarea{width:100%;padding:.6rem .85rem;border-radius:12px;
    border:1px solid #dbe1d5;background:#fff;
    font:inherit;color:var(--fg);outline:none;
    transition:border-color .15s,box-shadow .15s}
  input:hover,select:hover,textarea:hover{border-color:#c6d0bf}
  input:focus,select:focus,textarea:focus{border-color:var(--brand-d);
    box-shadow:0 0 0 3px rgba(146,197,122,.25)}
  input:disabled{background:#f4f6f2;color:var(--muted)}
  textarea{min-height:80px;resize:vertical}
  button,.btn{background:var(--brand);color:var(--accent-text);border:0;
    border-radius:12px;padding:.55rem 1.05rem;
    font:inherit;font-weight:600;cursor:pointer;
    display:inline-flex;align-items:center;justify-content:center;gap:.45rem;
    box-shadow:0 1px 2px rgba(18,38,24,.12);line-height:1.25;
    transition:background .15s,box-shadow .15s,transform .06s;
    white-space:nowrap;font-size:.9rem}
  button:hover,.btn:hover{background:#84b96b;text-decoration:none;
    box-shadow:0 3px 10px rgba(18,38,24,.14)}
  button:active,.btn:active{transform:translateY(1px)}
  button:disabled{opacity:.55;cursor:default;transform:none;box-shadow:none}
  button.ghost,.btn.ghost{background:#fff;color:var(--brand-deep);
    border:1px solid var(--line);box-shadow:0 1px 2px rgba(18,38,24,.05);
    font-weight:600}
  button.ghost:hover,.btn.ghost:hover{background:#f3f7f0;
    border-color:#cfdbc6}
  button.danger{background:#fff;color:var(--danger);
    border:1px solid #ecdad6;box-shadow:none;padding:.45rem .85rem;
    font-size:.85rem}
  button.danger:hover{background:#fdf3f1;border-color:#e3c4be}
  table{border-collapse:collapse;width:100%;margin-top:.6rem;font-size:.92rem}
  thead th{background:none;color:var(--muted);text-transform:uppercase;
    font-size:.7rem;letter-spacing:.75px;font-weight:700;
    padding:.4rem .9rem .55rem;text-align:left;white-space:nowrap;
    border-bottom:1.5px solid #dde3d6}
  th{text-align:left}
  tbody td{padding:.8rem .9rem;text-align:left;
    border-bottom:1px solid var(--line-soft)}
  tbody tr:last-child td{border-bottom:0}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .row{display:flex;gap:1rem;flex-wrap:wrap;align-items:end}
  .row>div{flex:1;min-width:150px}
  .pill{display:inline-block;padding:.16rem .6rem;border-radius:999px;
    font-size:.74rem;font-weight:600;letter-spacing:.1px}
  .ok{background:rgba(146,197,122,.35);color:#2f6b1f}
  .no{background:rgba(192,57,43,.18);color:#922}
  .role{background:rgba(99,102,241,.18);color:#3730a3}
  .inv{background:rgba(234,179,8,.22);color:#854d0e}
  .pill.s-open{background:#fef9c3;color:#854d0e}
  .pill.s-in_progress{background:#dbeafe;color:#1e40af}
  .pill.s-resolved{background:#dcfce7;color:#166534}
  .pill.s-closed{background:#e5e7eb;color:#374151}
  .pill.p-low{background:#e5e7eb;color:#374151}
  .pill.p-medium{background:#dbeafe;color:#1e40af}
  .pill.p-high{background:#ffedd5;color:#9a3412}
  .pill.p-critical{background:#fee2e2;color:#991b1b}
  .muted{color:var(--muted);font-size:.9rem}
  .chip{display:inline-block;background:rgba(146,197,122,.25);
    border:1px solid rgba(111,168,79,.35);border-radius:999px;
    padding:.15rem .6rem;margin:.15rem .25rem 0 0;font-size:.84rem}
  .chip.click{cursor:pointer}
  .flash{padding:.8rem 1rem;border-radius:12px;margin-bottom:1rem;
    background:#f0f7e9;border:1px solid #d9e8ca;
    color:#31611c;word-break:break-word;font-size:.93rem}
  .flash.err{background:#fdf4f2;border-color:#f0d6d1;color:#8f2e22}
  code{background:rgba(255,255,255,.65);padding:.12rem .4rem;border-radius:7px;
    font-size:.86em}
  .toolbar{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
  .tdetail{display:grid;grid-template-columns:1fr 330px;gap:1.2rem;align-items:start}
  .tside .card{position:sticky;top:84px;max-height:calc(100vh - 110px);overflow:auto}
  .hist{border-left:2px solid rgba(146,197,122,.5);padding:.1rem 0 .1rem .8rem;
    margin:0 0 .7rem;position:relative}
  .hist .meta{font-size:.78rem;color:var(--muted)}
  @media(max-width:900px){.tdetail{grid-template-columns:1fr}
    .tside .card{position:static;max-height:none}}
  .tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));
    gap:1.1rem;margin-top:1.3rem}
  .tile{display:block;background:var(--card);
    border:1px solid var(--line);position:relative;overflow:hidden;
    border-radius:var(--radius);padding:1.5rem;box-shadow:var(--shadow);
    color:var(--fg);transition:.2s}
  .tile:hover{transform:translateY(-4px);
    box-shadow:0 18px 40px rgba(16,40,24,.14);
    text-decoration:none;border-color:rgba(146,197,122,.7)}
  .tile .ti{width:48px;height:48px;border-radius:14px;display:flex;
    align-items:center;justify-content:center;color:var(--brand-d);
    background:rgba(146,197,122,.20);margin-bottom:.9rem}
  .tile .ti svg{width:25px;height:25px}
  .tile h3{margin:.1rem 0 .35rem;font-size:1.12rem}
  .tile p{margin:0;color:var(--muted);font-size:.92rem}
  .hero{background:linear-gradient(135deg,rgba(146,197,122,.20),rgba(146,197,122,.05));
    border-color:rgba(146,197,122,.35)}
  /* --- Dashboard --- */
  .dashhead{display:flex;align-items:baseline;justify-content:space-between;
    gap:1rem;flex-wrap:wrap;margin:.4rem 0 1.4rem}
  .dashhead h1{margin:0}
  .dashhead .date{color:var(--muted);font-size:.92rem;white-space:nowrap}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
    gap:1.1rem;margin-bottom:1.6rem}
  .stat{position:relative;overflow:hidden;background:var(--card);
    border:1px solid var(--line);border-radius:var(--radius);
    padding:1.3rem 1.4rem;box-shadow:var(--shadow)}
  .stat .lbl{color:var(--muted);font-size:.82rem;font-weight:600;
    text-transform:uppercase;letter-spacing:.5px}
  .stat .val{font-size:2rem;font-weight:800;letter-spacing:-.02em;
    margin:.35rem 0 0;line-height:1;position:relative;z-index:1}
  .stat .sub{color:var(--muted);font-size:.85rem;margin-top:.3rem}
  .sectlabel{font-size:.75rem;letter-spacing:.9px;text-transform:uppercase;
    color:var(--muted);font-weight:800;margin:.2rem 0 .7rem}
  .quick{display:flex;flex-wrap:wrap;gap:.6rem;margin-bottom:1.8rem}
  .qpill{display:inline-flex;align-items:center;gap:.5rem;background:var(--card);
    border:1px solid var(--line);border-radius:999px;padding:.6rem 1.05rem;
    font-weight:600;font-size:.92rem;color:var(--fg);box-shadow:var(--shadow);
    transition:.15s}
  .qpill:hover{transform:translateY(-2px);text-decoration:none;
    border-color:rgba(146,197,122,.7);color:var(--brand-d)}
  .qpill svg{width:17px;height:17px;color:var(--brand-d)}
  .listrow{display:flex;align-items:center;gap:.8rem;padding:.7rem 0;
    border-bottom:1px solid var(--line)}
  .listrow:last-child{border-bottom:0}
  .listrow .av{width:34px;height:34px;border-radius:50%;flex:0 0 auto;
    background:rgba(146,197,122,.22);color:var(--brand-d);font-weight:800;
    font-size:.8rem;display:inline-flex;align-items:center;justify-content:center}
  .listrow .who{font-weight:600}
  .listrow .meta{margin-left:auto;text-align:right;color:var(--muted);
    font-size:.86rem;white-space:nowrap}
  /* --- Login (Split) --- */
  .loginsplit{position:fixed;inset:0;z-index:1;display:flex}
  .loginhero{flex:1;position:relative;display:flex;flex-direction:column;
    justify-content:center;padding:5rem 4.5rem;color:#fff;overflow:hidden;
    background:linear-gradient(150deg,rgba(18,55,38,.92),rgba(24,74,49,.86)),
      var(--login-bg) center/cover no-repeat}
  .loginhero .lg{align-self:flex-start}
  .loginhero .lg img{height:52px;display:block}
  .loginhero .tagpill{display:inline-block;align-self:flex-start;
    margin:3.2rem 0 2.2rem;background:var(--brand-bright);color:#123018;
    font-weight:800;letter-spacing:1.5px;font-size:.74rem;text-transform:uppercase;
    padding:.55rem 1.2rem;border-radius:999px}
  .loginhero h1{font-size:3.1rem;line-height:1.22;margin:0;font-weight:800;
    letter-spacing:-.02em;max-width:14ch}
  .loginhero p{margin:2.4rem 0 0;max-width:42ch;color:rgba(255,255,255,.9);
    font-size:1.05rem;line-height:1.7}
  .loginpanel{flex:1;background:#fff;display:flex;align-items:center;
    justify-content:center;padding:1.5rem}
  .loginform{width:100%;max-width:370px}
  .loginform h1{margin:0 0 .3rem;font-size:1.7rem}
  .msbtn{display:flex;align-items:center;justify-content:center;gap:.6rem;
    width:100%;background:#fff;color:#3c4043;border:1px solid #dadce0;
    border-radius:12px;padding:.7rem 1rem;font-weight:600;box-shadow:none}
  .msbtn:hover{background:#f7f8f8;transform:none;box-shadow:0 2px 8px rgba(0,0,0,.08);
    text-decoration:none}
  .divider{display:flex;align-items:center;gap:.8rem;color:var(--muted);
    font-size:.8rem;margin:1.2rem 0}
  .divider::before,.divider::after{content:"";flex:1;height:1px;
    background:var(--line)}
  @media(max-width:820px){.loginhero{display:none}
    .loginpanel{flex:1}}
  .rowactions{display:flex;gap:.4rem;align-items:center;white-space:nowrap}
  .rowactions form{display:inline;margin:0}
  .tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;
    border-radius:12px}
  td form{margin:0}
  @media (max-width:680px){
    main{margin:1rem auto;padding:0 .7rem}
    header{padding:.5rem .8rem}
    nav{gap:.1rem;margin-left:.2rem}
    .navpill{padding:.42rem .6rem;font-size:.85rem}
    .menu>summary span:not(.avatar){display:none}
    .card{padding:1rem 1rem;overflow-x:auto}
    h1{font-size:1.2rem}
    table{font-size:.86rem;min-width:520px}
    .row>div{min-width:120px}
  }
  /* --- Feinschliff --- */
  h1{letter-spacing:-.02em;font-weight:700;font-size:1.45rem}
  h2{letter-spacing:-.012em;font-weight:700}
  h3{font-weight:650}
  .card{padding:1.6rem 1.7rem;margin-bottom:1.35rem}
  tbody td{vertical-align:middle}
  tbody tr{transition:background .12s}
  tbody tr:hover{background:#f5f8f2}
  .chip{transition:.12s}
  .chip:hover{background:rgba(146,197,122,.4);text-decoration:none}
  .hero{padding:1.7rem 1.8rem}
  .hero h1{font-size:1.7rem}
  ::selection{background:rgba(146,197,122,.4)}
  details.menu>summary{transition:.12s}
  .stat{padding:1.5rem 1.55rem}
  .stat .ico{position:absolute;top:1.3rem;right:1.3rem;width:38px;height:38px;
    border-radius:12px;display:flex;align-items:center;justify-content:center;
    color:var(--brand-deep);background:#eef5e8;z-index:1}
  .stat .ico svg{width:19px;height:19px}
  .stat .lbl{padding-right:3rem;position:relative;z-index:1}
  .stat .val{font-size:2.15rem;font-variant-numeric:tabular-nums}
  .quick{gap:.65rem}
  .qpill{border-radius:12px;box-shadow:0 1px 2px rgba(18,38,24,.05)}
  .qpill:hover{transform:none;background:#f6faf3;color:var(--brand-deep)}
  .tile:hover{transform:translateY(-2px)}
  .tablewrap{border:1px solid var(--line);border-radius:14px;background:#fff}
  .tablewrap table{margin-top:0}
  .tablewrap thead th{padding-top:.85rem;background:#fafcf8;
    border-bottom:1px solid var(--line)}
  .tablewrap thead th:first-child,.tablewrap tbody td:first-child{padding-left:1.15rem}
  .tablewrap thead th:last-child,.tablewrap tbody td:last-child{padding-right:1.15rem}
  tbody tr:nth-child(even){background:#fafcf8}
  tbody tr:nth-child(even):hover,tbody tr:hover{background:#f3f7ef}
  a.statlink{color:var(--fg);display:block}
  a.statlink:hover{text-decoration:none;border-color:#cbd8c2;
    box-shadow:0 3px 14px rgba(18,38,24,.10)}
  .stat.todo{border-color:#eddcab;background:#fffcf3}
  .stat.todo .ico{background:#faf0d3;color:#8a6410}
  .stat.todo .val{color:#8a6410}
  .warnhint{color:#9a6b10;font-size:.74rem;font-weight:600;margin-top:.1rem}
  .minirow{display:flex;gap:.5rem;flex-wrap:wrap;margin:.2rem 0 .9rem}
  .mini{display:inline-flex;align-items:center;gap:.4rem;background:#f4f7f1;
    border:1px solid var(--line);border-radius:999px;padding:.3rem .8rem;
    font-size:.83rem;font-weight:600;color:var(--fg)}
  .mini.warn{background:#fdf7e5;border-color:#eddcab;color:#8a6410}
  .mini b{font-weight:700}
  a.mini{transition:.12s}
  a.mini:hover{text-decoration:none;background:#ebf2e6;border-color:#cfdbc6;
    color:var(--brand-deep)}
  /* --- Dokumentation / Hilfe --- */
  .doctoc{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
    gap:1rem;margin-top:1rem}
  .doctoc ul{margin:.2rem 0 0;padding-left:1.1rem;line-height:1.95}
  .docsec h3{margin-top:1.2rem;color:var(--brand-deep)}
  .docsec ul{line-height:1.75}
  .docfig{margin:1.1rem 0;padding:1rem 1.1rem;background:#fafcf8;
    border:1px solid var(--line);border-radius:14px}
  .docfig figcaption{margin-top:.6rem;font-size:.82rem;color:var(--muted)}
  .doccode{background:#f4f7f1;border:1px solid var(--line);border-radius:10px;
    padding:.7rem .9rem;font-size:.85rem;overflow-x:auto;white-space:pre-wrap;
    word-break:break-all}
  .docnote{background:#fdf7e5;border:1px solid #eddcab;border-radius:10px;
    padding:.65rem .9rem;font-size:.9rem;color:#6d5410;margin:.6rem 0}
  .docview{width:100%;height:78vh;border:0;border-radius:10px;background:#fff}
  /* --- Tätigkeitsbeschreibung: inline bearbeiten --- */
  .descedit{min-width:200px;max-width:360px}
  .descedit>summary{list-style:none;display:flex;align-items:flex-start;gap:.4rem;
    cursor:pointer;padding:.3rem .5rem;margin:-.3rem -.5rem;border-radius:10px;
    transition:.12s}
  .descedit>summary::-webkit-details-marker{display:none}
  .descedit>summary:hover{background:rgba(146,197,122,.12)}
  .descedit .desctext{color:var(--fg);font-size:.9rem}
  .descedit .desctext::before{content:"✓";color:#2f8a2f;font-weight:900;
    margin-right:.35rem}
  .descedit .descadd{color:var(--brand-d);font-weight:700;font-size:.9rem}
  .descedit>summary svg{width:15px;height:15px;color:var(--muted);opacity:.6;
    flex:0 0 auto;margin-top:.12rem}
  .descedit>summary:hover svg{opacity:1;color:var(--brand-d)}
  .descedit[open]>summary{background:rgba(146,197,122,.14)}
  .descedit .descform{margin-top:.55rem}
  .descedit .descform textarea{min-height:58px;font-size:.9rem}
  .descedit .descbtns{margin-top:.45rem}
  .descedit .descbtns button{padding:.4rem .9rem;font-size:.85rem}
  .descedit .descbtns svg{width:15px;height:15px;vertical-align:-3px}
</style></head><body>
{% if user %}
<header>
  <a class="brand" href="/start"><img src="{{ logo_url_white }}" alt="FBE"></a>
  <nav>
    {% set pa_pages = ['dash','log','meine','abrechnung','send','reports'] %}
    <a class="navpill {{ 'active' if page=='home' }}" href="/start">Dashboard</a>
    <details class="menu tab">
      <summary class="navpill {{ 'active' if page in pa_pages }}">Projektabrechnung ▾</summary>
      <div class="panel">
        <a href="/meine-zeiten">{{ icons.chart|safe }} Meine Zeiten</a>
        {% if is_billing %}<a href="/">{{ icons.chart|safe }} Bericht</a>{% endif %}
        {% if can_fix %}<a href="/log">{{ icons.list|safe }} Log</a>{% endif %}
        {% if is_billing %}<a href="/abrechnung">{{ icons.list|safe }} Abrechnung</a>{% endif %}
        {% if role=='admin' %}<a href="/versand">{{ icons.mail|safe }} Senden</a>
        <a href="/reports">{{ icons.calendar|safe }} Berichte</a>{% endif %}
        <a href="{{ timemoto_url }}" target="_blank" rel="noopener">{{ icons.clock|safe }} Zeiterfassung &amp; Urlaub ↗</a>
      </div>
    </details>
    {% if tk_view %}
    <details class="menu tab">
      <summary class="navpill {{ 'active' if page=='tickets' }}">Tickets ▾</summary>
      <div class="panel">
        <a href="/tickets">{{ icons.list|safe }} Alle Tickets</a>
        <a href="/tickets/new">{{ icons.gear|safe }} Neues Ticket</a>
      </div>
    </details>
    {% endif %}
    <a class="navpill {{ 'active' if page=='area-iso' }}" href="/bereich/iso">ISO 9001 (FiFB)</a>
    <a class="navpill {{ 'active' if page=='area-ki-schulungen' }}" href="/bereich/ki-schulungen">KI-Schulungen</a>
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
        <a href="/einstellungen/projekte">{{ icons.list|safe }} Projekte</a>
        <a href="/einstellungen">{{ icons.gear|safe }} Einstellungen</a>
        <a href="/einstellungen/texte">{{ icons.edit|safe }} Texte</a>
        <a href="/einstellungen/visitenkarten">{{ icons.users|safe }} Visitenkarten</a>
        <a href="/audit">{{ icons.history|safe }} Verlauf</a>
        {% endif %}
        <div class="pdiv"></div>
        <a href="/logout" class="danger">{{ icons.logout|safe }} Abmelden</a>
      </div>
    </details>
  </div>
</header>
{% if impersonating %}
<div class="impbar">
  <span>{{ icons.users|safe }} <b>Support-Modus:</b> Du bist als <b>{{ display_name or user }}</b> angemeldet{% if imp_by %} (im Namen von {{ imp_by }}){% endif %}.</span>
  <form method="post" action="/impersonate/stop"><button type="submit">↩ Zurück zu meinem Account</button></form>
</div>
{% endif %}
{% endif %}
<main>
{% if flash %}<div class="flash {{ flash_class }}">{{ flash }}</div>{% endif %}
{% block body %}{% endblock %}
</main>
<script>if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){});}</script>
</body></html>
"""

_MS_LOGO = ('<svg viewBox="0 0 23 23" width="18" height="18" '
            'style="width:18px;height:18px;vertical-align:-3px">'
            '<rect x="1" y="1" width="10" height="10" fill="#f25022"/>'
            '<rect x="12" y="1" width="10" height="10" fill="#7fba00"/>'
            '<rect x="1" y="12" width="10" height="10" fill="#00a4ef"/>'
            '<rect x="12" y="12" width="10" height="10" fill="#ffb900"/></svg>')

_LOGIN = """
{% extends base %}
{% block body %}
<div class="loginsplit">
  <div class="loginhero" style="--login-bg:url('{{ bg_image }}')">
    <span class="lg"><img src="{{ logo_url_white }}" alt="FBE"></span>
    <span class="tagpill">{{ texts.login_pill }}</span>
    <h1>{{ texts.login_heading|e|replace('\n','<br>')|safe }}</h1>
    <p>{{ texts.login_desc }}</p>
  </div>
  <div class="loginpanel">
    <div class="loginform">
      <h1>{{ texts.login_welcome }}</h1>
      <p class="muted" style="margin:0 0 1.5rem;">{{ texts.login_welcome_sub }}</p>
      {% if show_local and not login_possible %}
        <div class="flash err">Noch kein Benutzer. <code>ADMIN_PASSWORD</code> in
          der .env setzen und neu starten.</div>{% endif %}
      {% if show_local %}
      <form method="post" action="/login">
        <label>Benutzer</label>
        <input name="username" autofocus autocomplete="username">
        <label>Passwort</label>
        <input name="password" type="password" autocomplete="current-password">
        <div style="margin-top:1.3rem;"><button type="submit" style="width:100%;">Anmelden</button></div>
      </form>
      <p style="margin-top:1rem;"><a href="/reset">Passwort vergessen?</a></p>
      {% if ms_enabled %}<div class="divider">ODER</div>{% endif %}
      {% endif %}
      {% if ms_enabled %}
      <a class="msbtn" href="/auth/microsoft/login">{{ ms_logo|safe }} Mit Microsoft anmelden</a>
      {% endif %}
      {% if not show_local and ms_enabled %}
      <p class="muted" style="margin-top:1.6rem;font-size:.85rem;">
        {{ texts.login_footer }}
        <a href="/login?local=1" style="display:block;margin-top:.5rem;">Mit Passwort anmelden (Admin / extern)</a></p>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
"""

_HOME = """
{% extends base %}
{% block body %}
<div class="dashhead">
  <div>
    <h1>{{ texts.dash_greeting }}, {{ first_name }}</h1>
    <p class="muted" style="margin:.2rem 0 0;">{{ texts.dash_sub }}</p>
  </div>
  <div class="date">{{ today }}</div>
</div>

<div class="stats">
  <div class="stat">
    <div class="ico">{{ icons.clock|safe }}</div>
    <div class="lbl">Meine Stunden · Woche</div>
    <div class="val">{{ week_hours }}</div>
    <div class="sub">{{ week_sessions }} Buchung{{ '' if week_sessions==1 else 'en' }} diese Woche</div>
  </div>
  {% if tk_view %}
  <div class="stat">
    <div class="ico">{{ icons.list|safe }}</div>
    <div class="lbl">Offene Tickets</div>
    <div class="val">{{ open_tickets }}</div>
    <div class="sub">in Bearbeitung &amp; offen</div>
  </div>
  {% endif %}
  <a class="stat statlink {{ 'todo' if todo_total }}" href="/meine-zeiten">
    <div class="ico">{{ icons.edit|safe }}</div>
    <div class="lbl">Zu erledigen</div>
    <div class="val">{{ todo_total }}</div>
    <div class="sub">{% if todo_total %}{{ todo_desc }} ohne Tätigkeitsbeschreibung{% else %}alles gepflegt ✓{% endif %}</div>
  </a>
  <div class="stat">
    <div class="ico">{{ icons.calendar|safe }}</div>
    <div class="lbl">Kalenderwoche</div>
    <div class="val">KW {{ kw }}</div>
    <div class="sub">{{ year }}</div>
  </div>
</div>

<div class="sectlabel">Schnellzugriff</div>
<div class="quick">
  <a class="qpill" href="/meine-zeiten">{{ icons.history|safe }} Meine Zeiten</a>
  <a class="qpill" href="/meine-zeiten/neu">{{ icons.edit|safe }} Buchung nachtragen</a>
  {% if is_billing %}<a class="qpill" href="/">{{ icons.chart|safe }} Bericht</a>{% endif %}
  {% if tk_view %}<a class="qpill" href="/tickets/new">{{ icons.list|safe }} Neues Ticket</a>{% endif %}
  {% if is_billing %}<a class="qpill" href="/abrechnung">{{ icons.calendar|safe }} Abrechnung</a>{% endif %}
  <a class="qpill" href="{{ timemoto_url }}" target="_blank" rel="noopener">{{ icons.clock|safe }} Stempeln &amp; Urlaub ↗</a>
</div>

{% if recent %}
<div class="card glass" style="margin-bottom:1.6rem;">
  <div class="toolbar" style="justify-content:space-between;margin-bottom:.3rem;">
    <h2 style="margin:0;">Meine letzten Buchungen</h2>
    <a href="/meine-zeiten" class="muted" style="font-size:.86rem;">alle ansehen →</a>
  </div>
  {% for r in recent %}
  <div class="listrow">
    <span class="av">{{ r.ini }}</span>
    <div><div class="who">{{ r.project }}</div>
      <div class="muted" style="font-size:.84rem;">{{ r.date }} · {{ r.start }}–{{ r.end }}</div></div>
    <div class="meta"><b>{{ r.dur }}</b>{% if not r.description %}<div class="warnhint">Tätigkeit fehlt</div>{% endif %}</div>
  </div>
  {% endfor %}
</div>
{% endif %}

<div class="sectlabel">Bereiche</div>
<div class="tiles">
  {% if is_billing %}
  <a class="tile" href="/">
    <div class="ti">{{ icons.chart|safe }}</div>
    <h3>Projektabrechnung</h3>
    <p>Stunden, Wochenberichte, Abrechnung &amp; Export.</p></a>
  {% endif %}
  <a class="tile" href="/meine-zeiten">
    <div class="ti">{{ icons.history|safe }}</div>
    <h3>Meine Zeiten</h3>
    <p>Eigene Buchungen &amp; Tätigkeitsbeschreibungen.</p></a>
  <a class="tile" href="{{ timemoto_url }}" target="_blank" rel="noopener">
    <div class="ti">{{ icons.clock|safe }}</div>
    <h3>Zeiterfassung &amp; Urlaub ↗</h3>
    <p>Stempeln &amp; Urlaubsanträge in TimeMoto.</p></a>
  {% if tk_view %}
  <a class="tile" href="/tickets">
    <div class="ti">{{ icons.list|safe }}</div>
    <h3>Tickets</h3>
    <p>Anfragen erfassen, bearbeiten, verfolgen.</p></a>
  {% endif %}
  {% if is_billing %}
  <a class="tile" href="/abrechnung">
    <div class="ti">{{ icons.calendar|safe }}</div>
    <h3>Abrechnung</h3>
    <p>Alle Stunden filtern &amp; als Excel/CSV exportieren.</p></a>
  {% endif %}
  {% if role=='admin' %}
  <a class="tile" href="/users">
    <div class="ti">{{ icons.users|safe }}</div>
    <h3>Benutzer</h3>
    <p>Konten, Rollen, Rechte &amp; TimeMoto-Zuordnung.</p></a>
  {% endif %}
  <a class="tile" href="/bereich/iso">
    <div class="ti">{{ icons.book|safe }}</div>
    <h3>ISO 9001 (FiFB)</h3>
    <p>Interne Prozesse &amp; QM-Dokumente ansehen.</p></a>
  <a class="tile" href="/bereich/ki-schulungen">
    <div class="ti">{{ icons.chart|safe }}</div>
    <h3>KI-Schulungen</h3>
    <p>Schulungsunterlagen &amp; Videos rund um KI.</p></a>
  <a class="tile" href="{{ teilnahme_url }}" target="_blank" rel="noopener">
    <div class="ti">{{ icons.book|safe }}</div>
    <h3>Teilnahmemanagement ↗</h3>
    <p>Flüssigboden Akademie UG – externe Plattform.</p></a>
</div>
{% endblock %}
"""

_TWOFA_VERIFY = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:380px;margin:8vh auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:46px;margin:.3rem 0 1rem;">
  <h1 style="text-align:left;">Bestätigung (2FA)</h1>
  <p class="muted" style="text-align:left;">Gib den 6-stelligen Code aus deiner
    Authenticator-App ein.</p>
  <form method="post" action="/login/2fa" style="text-align:left;">
    <label>Code</label>
    <input name="code" inputmode="numeric" autocomplete="one-time-code"
      autofocus placeholder="123456" style="letter-spacing:.3em;text-align:center;font-size:1.2rem">
    <div style="margin-top:1.1rem;"><button type="submit">Anmelden</button></div>
  </form>
  <p style="text-align:left;margin-top:1rem;"><a href="/logout">Abbrechen</a></p>
</div>
{% endblock %}
"""

_TWOFA_SETUP = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:460px;margin:{{ '2vh' if user else '7vh' }} auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:42px;margin:.3rem 0 .8rem;">
  <h1 style="text-align:left;">Zwei-Faktor-Authentifizierung einrichten</h1>
  <p class="muted" style="text-align:left;">Scanne den QR-Code mit einer
    Authenticator-App (Google Authenticator, Microsoft Authenticator, Authy …)
    und gib dann den angezeigten 6-stelligen Code ein.</p>
  <img src="{{ qr }}" alt="QR-Code" style="width:200px;height:200px;margin:.4rem auto">
  <p class="muted" style="text-align:left;">Falls du den Code nicht scannen
    kannst, gib dieses Geheimnis manuell ein:<br><code>{{ secret }}</code></p>
  <form method="post" action="/2fa/setup" style="text-align:left;">
    <label>Code aus der App</label>
    <input name="code" inputmode="numeric" autocomplete="one-time-code" autofocus
      placeholder="123456" style="letter-spacing:.3em;text-align:center;font-size:1.2rem">
    <div style="margin-top:1.1rem;"><button type="submit">Aktivieren</button></div>
  </form>
  {% if not user %}<p style="text-align:left;margin-top:1rem;"><a href="/logout">Abbrechen</a></p>{% endif %}
</div>
{% endblock %}
"""

_RESET_REQ = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:380px;margin:8vh auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:46px;margin:.3rem 0 1rem;">
  <h1 style="text-align:left;">Passwort zurücksetzen</h1>
  <p class="muted" style="text-align:left;">Gib deinen Benutzernamen oder deine
    E-Mail ein. Du bekommst einen Link per E-Mail.</p>
  <form method="post" action="/reset" style="text-align:left;">
    <label>Benutzername oder E-Mail</label>
    <input name="identifier" autofocus>
    <div style="margin-top:1.1rem;"><button type="submit">Link anfordern</button></div>
  </form>
  <p style="text-align:left;margin-top:1rem;"><a href="/login">Zurück zum Login</a></p>
</div>
{% endblock %}
"""

_RESET_FORM = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:380px;margin:8vh auto 0;text-align:center;">
  <img src="{{ logo_url }}" alt="FBE" style="height:46px;margin:.3rem 0 1rem;">
  <h1 style="text-align:left;">Neues Passwort</h1>
  <form method="post" action="/reset/{{ token }}" style="text-align:left;">
    <label>Neues Passwort (mind. 8 Zeichen)</label>
    <input name="new1" type="password" autocomplete="new-password" autofocus>
    <label>Wiederholen</label>
    <input name="new2" type="password" autocomplete="new-password">
    <div style="margin-top:1.1rem;"><button type="submit">Passwort setzen</button></div>
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
  <div class="toolbar" style="justify-content:space-between;">
    <h2 style="margin:0;">Zusammenfassung: {{ report_title }}</h2>
    <div class="toolbar" style="gap:.35rem;">
      <a class="btn ghost" href="/?week=custom&project={{ project|urlencode }}&start={{ prev_start }}&end={{ prev_end }}" title="Zeitraum zurück">‹</a>
      <a class="btn ghost" href="/?week=custom&project={{ project|urlencode }}&start={{ next_start }}&end={{ next_end }}" title="Zeitraum vor">›</a>
    </div>
  </div>
  <p class="muted" style="margin-top:.4rem;">{{ period }}</p>
  {{ report_html|safe }}
  <div class="toolbar" style="margin-top:1rem;">
    <a class="btn ghost" href="/export/amprion.csv?project={{ project|urlencode }}&start={{ start_iso }}&end={{ end_iso }}">Amprion-CSV</a>
    <a class="btn ghost" href="/export.xlsx?project={{ project|urlencode }}&start={{ start_iso }}&end={{ end_iso }}">Excel</a>
    <form method="post" action="/send" class="toolbar" style="margin:0;">
      <input type="hidden" name="project" value="{{ project }}">
      <input type="hidden" name="start" value="{{ start_iso }}">
      <input type="hidden" name="end" value="{{ end_iso }}">
      <button type="submit">Diese Ansicht jetzt senden{{ '' if mail_configured else ' (als Datei)' }}</button>
      {% if not mail_configured %}<span class="muted">SMTP nicht konfiguriert – nur Datei.</span>{% endif %}
    </form>
  </div>
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
      {% if can_fix %}<a class="btn" href="/log/edit">+ Eintrag hinzufügen</a>{% endif %}
      {% if is_billing %}<a class="btn ghost" href="/export.xlsx?employee={{ employee|urlencode }}&project={{ project|urlencode }}&start={{ start_in }}&end={{ end_in }}">Excel</a>
      <a class="btn ghost" href="/export/amprion.csv?employee={{ employee|urlencode }}&project={{ project|urlencode }}&start={{ start_in }}&end={{ end_in }}">Amprion-CSV</a>{% endif %}
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
  <div class="minirow" style="margin:1rem 0 0;">
    {% for p in presets %}<a class="mini" href="/log?employee={{ employee|urlencode }}&project={{ project|urlencode }}&start={{ p.start }}&end={{ p.end }}">{{ p.label }}</a>{% endfor %}
  </div>
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
  <div class="tablewrap"><table>
    <thead><tr><th>Datum</th><th>Mitarbeiter</th><th>Projekt</th>
      <th>Kommt</th><th>Geht</th><th class="num">Dauer</th><th>Tätigkeit</th><th>Quelle</th>
      {% if can_fix %}<th>Aktionen</th>{% endif %}</tr></thead>
    <tbody>
    {% for s in sessions %}
      <tr><td>{{ s.date }}</td><td>{{ s.employee }}</td>
        <td>{% if s.project=='–' %}<span class="pill inv">ohne Projekt</span>{% else %}{{ s.project }}{% endif %}</td>
        <td>{{ s.start }}</td><td>{{ s.end }}</td><td class="num">{{ s.dur }}</td>
        <td>{% if can_fix %}
          <details class="descedit">
            <summary>{% if s.description %}<span class="desctext">{{ s.description }}</span>{% else %}<span class="descadd">+ Tätigkeit</span>{% endif %}{{ icons.edit|safe }}</summary>
            <form method="post" action="/log/describe" class="descform">
              <input type="hidden" name="iid" value="{{ s.id }}">
              <textarea name="description" rows="2" placeholder="Was wurde gemacht? (1–2 Sätze)">{{ s.description }}</textarea>
              <div class="descbtns"><button type="submit">{{ icons.check|safe }} Speichern</button></div>
            </form>
          </details>
          {% else %}{{ s.description }}{% endif %}</td>
        <td>{% if s.source=='manual' %}<span class="pill role">manuell</span>{% else %}<span class="muted">TimeMoto</span>{% endif %}</td>
        {% if can_fix %}<td><div class="rowactions">
          <a class="btn ghost" href="/log/edit?iid={{ s.id|urlencode }}">{{ 'Bearbeiten' if s.source=='manual' else 'Korrigieren' }}</a>
          {% if s.source=='manual' %}
          <form method="post" action="/log/delete">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="danger" onclick="return confirm('Eintrag löschen?')">Löschen</button></form>
          {% else %}
          <form method="post" action="/log/delete">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="ghost" type="submit">Ausblenden</button></form>
          <form method="post" action="/log/purge">
            <input type="hidden" name="iid" value="{{ s.id }}">
            <button class="danger" onclick="return confirm('Diese TimeMoto-Buchung ENDGÜLTIG löschen?')">Löschen</button></form>
          {% endif %}
        </div></td>{% endif %}
      </tr>
    {% endfor %}
    </tbody>
  </table></div>
  {% else %}<p>Keine Buchungen für diese Filter.</p>{% endif %}
</div>

{% if can_fix and hidden %}
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
  <h1 style="margin:0 0 .4rem;">Hilfe &amp; Dokumentation</h1>
  <p class="muted">Anleitung zu allen Funktionen{% if role=='admin' %} sowie die
    Administrations-Dokumentation{% endif %}.</p>
  <div class="doctoc">
    <div>
      <div class="sectlabel">Anleitung</div>
      <ul>{% for s in sections %}<li><a href="#{{ s.id }}">{{ s.title }}</a></li>{% endfor %}</ul>
    </div>
    {% if admin_secs %}
    <div>
      <div class="sectlabel">Administration</div>
      <ul>{% for s in admin_secs %}<li><a href="#{{ s.id }}">{{ s.title }}</a></li>{% endfor %}</ul>
    </div>
    {% endif %}
  </div>
</div>

{% macro render_section(s) %}
<div class="card glass docsec" id="{{ s.id }}">
  <h2>{{ s.title }}</h2>
  {% for b in s.blocks %}
    {% if b.t == 'p' %}<p>{{ b.html|safe }}</p>
    {% elif b.t == 'h3' %}<h3>{{ b.text }}</h3>
    {% elif b.t == 'ul' %}<ul>{% for it in b['items'] %}<li>{{ it|safe }}</li>{% endfor %}</ul>
    {% elif b.t == 'ol' %}<ol>{% for it in b['items'] %}<li>{{ it|safe }}</li>{% endfor %}</ol>
    {% elif b.t == 'code' %}<pre class="doccode">{{ b.text }}</pre>
    {% elif b.t == 'note' %}<div class="docnote">{{ b.html|safe }}</div>
    {% elif b.t == 'fig' %}<figure class="docfig">{{ b.svg|safe }}<figcaption>{{ b.caption }}</figcaption></figure>
    {% elif b.t == 'table' %}
      <div class="tablewrap" style="margin-top:.6rem;"><table>
        <thead><tr>{% for h in b.head %}<th {{ 'class=num' if not loop.first }}>{{ h }}</th>{% endfor %}</tr></thead>
        <tbody>{% for row in b.rows %}<tr>{% for c in row %}<td {{ 'class=num' if not loop.first }}>{{ c|safe }}</td>{% endfor %}</tr>{% endfor %}</tbody>
      </table></div>
    {% endif %}
  {% endfor %}
</div>
{% endmacro %}

{% for s in sections %}{{ render_section(s) }}{% endfor %}
{% if admin_secs %}
<div class="sectlabel" style="margin-top:2rem;">Administration</div>
{% for s in admin_secs %}{{ render_section(s) }}{% endfor %}
{% endif %}
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
  <hr style="border:none;border-top:1px solid var(--line);margin:1.3rem 0;">
  <h2>Zwei-Faktor-Authentifizierung</h2>
  <p class="muted">Status:
    {% if twofa %}<span class="pill ok">aktiv</span>{% else %}<span class="pill no">inaktiv</span>{% endif %}</p>
  <a class="btn ghost" href="/2fa/setup">{{ '2FA neu einrichten' if twofa else '2FA einrichten' }}</a>
</div>
{% endblock %}
"""

_USERS = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Benutzer</h1>
    {% if ms_enabled %}<form method="post" action="/users/import-microsoft">
      <button type="submit" class="ghost">Aus Microsoft importieren</button></form>{% endif %}
  </div>
  <div style="margin-top:.8rem;"><table>
    <thead><tr><th>Name</th><th>Benutzer</th><th>E-Mail</th><th>TimeMoto-Name</th>
      <th>Rolle</th><th>Status</th><th>Aktionen</th></tr></thead>
    <tbody>
    {% for u in userlist %}
      <tr>
        <td><b>{{ u.name or u.username }}</b></td>
        <td class="muted">{{ u.username }}</td>
        <td class="muted">{{ u.email or '–' }}</td>
        <td>{% if u.timemoto_name %}{{ u.timemoto_name }}{% else %}<span class="pill no">nicht zugeordnet</span>{% endif %}</td>
        <td><span class="pill role">{{ u.role }}</span></td>
        <td>{% if u.status=='active' %}<span class="pill ok">aktiv</span>
            {% else %}<span class="pill inv">eingeladen</span>{% endif %}</td>
        <td style="text-align:right;">
          <details class="menu">
            <summary class="btn ghost">Aktionen ▾</summary>
            <div class="panel">
              <a href="/users/{{ u.username|urlencode }}/edit">{{ icons.gear|safe }} Bearbeiten</a>
              {% if u.username != user and u.status=='active' %}
              <form method="post" action="/users/{{ u.username|urlencode }}/impersonate">
                <button type="submit" class="panelitem">{{ icons.users|safe }} Als Benutzer anmelden</button></form>
              {% endif %}
              {% if u.status=='invited' and local_users_enabled %}
              <form method="post" action="/users/resend">
                <input type="hidden" name="username" value="{{ u.username }}">
                <button type="submit" class="panelitem">Einladung erneut senden</button></form>
              {% endif %}
              {% if u.username != user %}
              <form method="post" action="/users/delete">
                <input type="hidden" name="username" value="{{ u.username }}">
                <button type="submit" class="panelitem danger" onclick="return confirm('Benutzer {{ u.username }} löschen?')">Löschen</button></form>
              {% endif %}
            </div>
          </details>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table></div>
</div>
<div class="card glass" style="max-width:560px;">
  <h2>Externen Benutzer hinzufügen (Passwort-Login)</h2>
  <p class="muted" style="margin:-.3rem 0 .6rem;">Für Personen ohne Microsoft-Konto.
    Es wird ein Einladungslink erzeugt; die Person setzt ihr eigenes Passwort.
    Für vollen Zugriff Rolle <b>admin</b> wählen.</p>
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
    <label>Ticket-Zugriff</label>
    <select name="ticket_access">
      <option value="none">Kein Zugriff</option>
      <option value="view">Nur ansehen</option>
      <option value="edit">Ansehen &amp; bearbeiten</option>
    </select>
    <label>Zeiten korrigieren</label>
    <select name="fix_times">
      <option value="no">Nein</option>
      <option value="yes">Ja</option>
    </select>
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
    "clock": _svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    "edit": _svg('<path d="M12 20h9"/>'
                 '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
    "check": _svg('<path d="M20 6 9 17l-5-5"/>'),
}

_base_tpl = Template(_BASE)
_USER_EDIT = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:560px;">
  <h1>Benutzer bearbeiten</h1>
  <p class="muted">Benutzername: <b>{{ u.username }}</b> · Status:
    {% if u.status=='active' %}aktiv{% else %}eingeladen{% endif %}</p>
  <form method="post" action="/users/{{ u.username|urlencode }}/edit">
    <label>Benutzername (Login)</label>
    <input name="new_username" value="{{ u.username }}">
    <label>Anzeigename</label>
    <input name="name" value="{{ u.name or '' }}">
    <label>E-Mail (für Einladung, Reset &amp; Erinnerungen)</label>
    <input name="email" type="email" value="{{ u.email or '' }}">
    <label>TimeMoto-Name (Vorname Nachname – für die Stundenzuordnung)</label>
    <input name="timemoto_name" value="{{ u.timemoto_name or '' }}" list="emps"
      placeholder="{{ u.name or 'Vorname Nachname' }}">
    <datalist id="emps">{% for e in all_employees %}<option value="{{ e }}">{% endfor %}</datalist>
    <p class="muted" style="margin:.3rem 0 0;">Genau wie in TimeMoto schreiben
      (<b>Vorname Nachname</b>). Du kannst den Namen schon <b>jetzt</b> eintragen –
      sobald Buchungen mit diesem Namen eingehen, werden sie automatisch zugeordnet.
      Vorschläge stammen aus bereits erkannten Namen.</p>
    <label>Rolle</label>
    <select name="role">
      <option value="user" {{ 'selected' if u.role=='user' }}>user</option>
      <option value="buchhaltung" {{ 'selected' if u.role=='buchhaltung' }}>buchhaltung</option>
      <option value="admin" {{ 'selected' if u.role=='admin' }}>admin</option>
    </select>
    <label>Ticket-Zugriff</label>
    {% set lvl = 'edit' if u.can_edit_tickets else ('view' if u.can_view_tickets else 'none') %}
    <select name="ticket_access">
      <option value="none" {{ 'selected' if lvl=='none' }}>Kein Zugriff</option>
      <option value="view" {{ 'selected' if lvl=='view' }}>Nur ansehen</option>
      <option value="edit" {{ 'selected' if lvl=='edit' }}>Ansehen &amp; bearbeiten</option>
    </select>
    <label>Zeiten korrigieren (Log, Buchungen aller Mitarbeiter pflegen)</label>
    <select name="fix_times">
      <option value="no" {{ 'selected' if not u.can_fix_times }}>Nein</option>
      <option value="yes" {{ 'selected' if u.can_fix_times }}>Ja</option>
    </select>
    <p class="muted" style="margin:.3rem 0 0;">Admin und Buchhaltung dürfen das
      immer. Mit „Ja" bekommt auch diese Person Zugriff auf das Log inkl.
      Korrekturen (ohne Exporte/Berichte).</p>
    <div class="toolbar" style="margin-top:1.2rem;">
      <button type="submit">Speichern</button>
      <a class="btn ghost" href="/users">Abbrechen</a>
    </div>
  </form>
</div>
{% endblock %}
"""

_MEINE = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Meine Zeiten</h1>
    <a class="btn" href="/meine-zeiten/neu">+ Buchung hinzufügen</a>
  </div>
  <div class="minirow">
    <span class="mini">{{ icons.clock|safe }} Diese Woche <b>{{ week_h }}</b></span>
    <span class="mini {{ 'warn' if miss_desc }}">{{ icons.edit|safe }} <b>{{ miss_desc }}</b> ohne Tätigkeit</span>
  </div>
    <p class="muted">Buchungen der letzten {{ days }} Tage für <b>{{ tm }}</b>{% if not assigned %}
      (automatisch über deinen Namen; ein Administrator kann bei Bedarf einen
      abweichenden TimeMoto-Namen zuordnen){% endif %}.
      Bitte trage je Eintrag eine Tätigkeitsbeschreibung ein (1–2 Sätze).
      Vergessene Buchungen kannst du selbst nachtragen oder korrigieren.</p>
    {% if open_sessions %}
    <div class="flash" style="margin-bottom:1rem;">
      {{ icons.clock|safe }} <b>Läuft gerade:</b>
      {% for o in open_sessions %}{{ o.project }} seit {{ o.start }}{{ ', ' if not loop.last }}{% endfor %}
    </div>
    {% endif %}
    {% if sessions %}
    <div class="tablewrap"><table>
      <thead><tr><th>Datum</th><th>Projekt</th><th>Kommt</th><th>Geht</th>
        <th class="num">Dauer</th><th>Tätigkeitsbeschreibung</th><th></th></tr></thead>
      <tbody>
      {% for s in sessions %}
        <tr><td>{{ s.date }}</td><td>{{ s.project }}</td><td>{{ s.start }}</td>
          <td>{{ s.end }}</td><td class="num">{{ s.dur }}</td>
          <td>
            <details class="descedit">
              <summary>{% if s.description %}<span class="desctext">{{ s.description }}</span>{% else %}<span class="descadd">+ Tätigkeit eintragen</span>{% endif %}{{ icons.edit|safe }}</summary>
              <form method="post" action="/meine-zeiten/describe" class="descform">
                <input type="hidden" name="iid" value="{{ s.id }}">
                <textarea name="description" rows="2" placeholder="Was wurde gemacht? (1–2 Sätze)">{{ s.description }}</textarea>
                <div class="descbtns"><button type="submit">{{ icons.check|safe }} Speichern</button></div>
              </form>
            </details>
          </td>
          <td style="text-align:right;"><div class="rowactions">
            <a class="btn ghost" href="/meine-zeiten/neu?iid={{ s.id|urlencode }}">{{ 'Bearbeiten' if s.source=='manual' else 'Korrigieren' }}</a>
            {% if s.source=='manual' %}
            <form method="post" action="/meine-zeiten/delete">
              <input type="hidden" name="iid" value="{{ s.id }}">
              <button class="danger" onclick="return confirm('Diese Buchung löschen?')">Löschen</button></form>
            {% endif %}
          </div></td></tr>
      {% endfor %}
      </tbody>
    </table></div>
    {% elif not open_sessions %}<p>Keine Buchungen in den letzten {{ days }} Tagen.
      {% if not assigned %}Falls hier etwas fehlt, kann ein Administrator deinem
      Konto den passenden <b>TimeMoto-Namen</b> zuordnen.{% endif %}</p>{% endif %}
</div>
{% endblock %}
"""

_MY_FORM = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:560px;">
  <h1>{{ heading }}</h1>
  {% if mode=='assign' %}<p class="muted">Diese Buchung wurde ohne Projekt
    gestempelt. Wähle das Projekt – die Zeiten kannst du bei Bedarf anpassen.</p>
  {% elif mode=='correct' %}<p class="muted">Korrektur deiner TimeMoto-Buchung:
    das Original wird ausgeblendet und durch diesen Eintrag ersetzt.</p>
  {% elif mode=='new' %}<p class="muted">Für vergessene Buchungen: Zeitraum und
    Projekt eintragen – der Eintrag zählt wie eine normale Buchung.</p>{% endif %}
  <form method="post" action="/meine-zeiten/save">
    <input type="hidden" name="iid" value="{{ iid }}">
    <label>Mitarbeiter</label>
    <input value="{{ tm }}" disabled>
    <label>Projekt</label>
    <input name="project" value="{{ f.project }}" list="projs" required
      placeholder="Projekt wählen oder eintippen">
    <datalist id="projs">{% for p in all_projects %}<option value="{{ p }}">{% endfor %}</datalist>
    <div class="row">
      <div style="flex:0 0 180px;"><label>Datum</label><input type="date" name="date" value="{{ f.date }}" required></div>
      <div style="flex:0 0 130px;"><label>Kommt</label><input type="time" name="start_time" value="{{ f.start_time }}" required></div>
      <div style="flex:0 0 130px;"><label>Geht</label><input type="time" name="end_time" value="{{ f.end_time }}" required></div>
    </div>
    <label>Tätigkeitsbeschreibung (1–2 Sätze)</label>
    <textarea name="description" rows="3" placeholder="Was wurde gemacht?">{{ f.description }}</textarea>
    <div class="toolbar" style="margin-top:1.2rem;">
      <button type="submit">Speichern</button>
      <a class="btn ghost" href="/meine-zeiten">Abbrechen</a>
    </div>
  </form>
</div>
{% endblock %}
"""

_ABRECHNUNG = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1>Abrechnung</h1>
  <p class="muted">Alle Stunden über alle Projekte – nach Bedarf filtern und
    direkt als Excel oder als Amprion-CSV (Abgabeformat) herunterladen
    (kein Mailversand).</p>
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
      <button type="submit" formaction="/export/amprion.csv" class="ghost">Amprion-CSV herunterladen</button>
    </div>
  </form>
  <div class="minirow" style="margin:1rem 0 0;">
    {% for p in presets %}<a class="mini" href="/abrechnung?start={{ p.start }}&end={{ p.end }}">{{ p.label }}</a>{% endfor %}
  </div>
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

_TICKETS = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Tickets</h1>
    <a class="btn" href="/tickets/new">+ Neues Ticket</a>
  </div>
  <div style="margin-top:.6rem;">
    <a class="chip" href="/tickets">Aktiv</a>
    {% for k,v in statuses.items() %}<a class="chip" href="/tickets?status={{k}}">{{ '📦 ' if k=='closed' }}{{ v }}: <b>{{ counts[k] }}</b></a>{% endfor %}
  </div>
  <form method="get" action="/tickets" style="margin-top:.7rem;">
    <div class="row">
      <div style="flex:0 0 190px;"><label>Status</label>
        <select name="status" onchange="this.form.submit()">
          <option value="">alle</option>
          {% for k,v in statuses.items() %}<option value="{{k}}" {{ 'selected' if status==k }}>{{v}}</option>{% endfor %}
        </select></div>
      <div><label>Suche</label><input name="q" value="{{ q }}" placeholder="Titel / Beschreibung"></div>
      <div style="flex:0 0 auto;"><label>&nbsp;</label><button type="submit">Filtern</button></div>
    </div>
  </form>
</div>
<div class="card glass">
  {% if rows %}
  <div class="tablewrap"><table>
    <thead><tr><th>#</th><th>Titel</th><th>Priorität</th><th>Kategorie</th>
      <th>Status</th><th>Bearbeiter</th><th>Erstellt</th></tr></thead>
    <tbody>{% for t in rows %}
      <tr style="cursor:pointer" onclick="location.href='/tickets/{{ t.id }}'">
        <td>#{{ t.id }}</td><td><b>{{ t.title }}</b></td>
        <td><span class="pill p-{{ t.priority }}">{{ priorities[t.priority] }}</span></td>
        <td>{{ categories[t.category] }}</td>
        <td><span class="pill s-{{ t.status }}">{{ statuses[t.status] }}</span></td>
        <td class="muted">{{ t.assigned_to or '–' }}</td>
        <td class="muted">{{ t.created_disp }}</td></tr>
    {% endfor %}</tbody></table></div>
  {% else %}<p class="muted">Keine Tickets gefunden.</p>{% endif %}
</div>
{% endblock %}
"""

_TICKET_NEW = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:640px;">
  <h1>Neues Ticket</h1>
  <form method="post" action="/tickets/new">
    <label>Titel</label>
    <input name="title" required autofocus>
    <label>Beschreibung</label>
    <textarea name="description" style="min-height:120px"></textarea>
    <div class="row">
      <div><label>Priorität</label>
        <select name="priority">{% for k,v in priorities.items() %}<option value="{{k}}" {{ 'selected' if k=='medium' }}>{{v}}</option>{% endfor %}</select></div>
      <div><label>Kategorie</label>
        <select name="category">{% for k,v in categories.items() %}<option value="{{k}}">{{v}}</option>{% endfor %}</select></div>
    </div>
    <div class="toolbar" style="margin-top:1.1rem;">
      <button type="submit">Ticket anlegen</button>
      <a class="btn ghost" href="/tickets">Abbrechen</a></div>
  </form>
</div>
{% endblock %}
"""

_TICKET = """
{% extends base %}
{% block body %}
<div class="tdetail">
<div class="tmain">
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">#{{ t.id }} · {{ t.title }}</h1>
    <div class="toolbar">
      {% if can_edit %}<form method="post" action="/tickets/{{ t.id }}/delete">
        <button class="danger" onclick="return confirm('Ticket #{{ t.id }} wirklich löschen?')">Ticket löschen</button></form>{% endif %}
      <a class="btn ghost" href="/tickets">Zurück</a>
    </div>
  </div>
  <p style="margin:.5rem 0;">
    <span class="pill s-{{ t.status }}">{{ statuses[t.status] }}</span>
    <span class="pill p-{{ t.priority }}">{{ priorities[t.priority] }}</span>
    <span class="pill role">{{ categories[t.category] }}</span></p>
  <p class="muted">Erstellt von {{ t.created_by }} · {{ t.created_disp }}
    {% if t.assigned_to %} · Bearbeiter: <b>{{ t.assigned_to }}</b>{% endif %}
    · zuletzt aktualisiert {{ t.updated_disp }}</p>
  {% if can_edit %}
  <div class="toolbar" style="margin-top:.6rem;">
    {% for k,v in statuses.items() %}
      {% if k=='closed' %}
      <details class="menu">
        <summary class="btn {{ '' if t.status=='closed' else 'ghost' }}">Schließen…</summary>
        <div class="panel" style="width:320px;padding:.8rem;">
          <form method="post" action="/tickets/{{ t.id }}/close">
            <label>Lösung / Abschluss (optional – geht an den Ersteller)</label>
            <textarea name="message" placeholder="Was wurde gelöst?" style="min-height:90px"></textarea>
            <div style="margin-top:.6rem;"><button type="submit">Schließen &amp; Ersteller benachrichtigen</button></div>
          </form>
        </div>
      </details>
      {% else %}
      <form method="post" action="/tickets/{{ t.id }}/status">
        <input type="hidden" name="status" value="{{ k }}">
        <button type="submit" class="{{ '' if t.status==k else 'ghost' }}" {{ 'disabled' if t.status==k }}>{{ v }}</button>
      </form>
      {% endif %}
    {% endfor %}
    <form method="post" action="/tickets/{{ t.id }}/assign-me">
      <button type="submit" class="ghost">Mir zuweisen</button></form>
  </div>
  {% endif %}
  <div style="white-space:pre-wrap;margin-top:.8rem;">{{ t.description }}</div>
</div>

{% if can_edit %}
<div class="card glass">
  <h2>Bearbeiten</h2>
  <form method="post" action="/tickets/{{ t.id }}/edit">
    <div class="row">
      <div><label>Status</label><select name="status">{% for k,v in statuses.items() %}<option value="{{k}}" {{ 'selected' if t.status==k }}>{{v}}</option>{% endfor %}</select></div>
      <div><label>Priorität</label><select name="priority">{% for k,v in priorities.items() %}<option value="{{k}}" {{ 'selected' if t.priority==k }}>{{v}}</option>{% endfor %}</select></div>
      <div><label>Kategorie</label><select name="category">{% for k,v in categories.items() %}<option value="{{k}}" {{ 'selected' if t.category==k }}>{{v}}</option>{% endfor %}</select></div>
      <div><label>Bearbeiter</label><select name="assigned_to"><option value="">–</option>{% for a in assignees %}<option value="{{a}}" {{ 'selected' if t.assigned_to==a }}>{{a}}</option>{% endfor %}</select></div>
    </div>
    <div style="margin-top:1rem;"><button type="submit">Speichern</button></div>
  </form>
</div>
{% endif %}

<div class="card glass">
  <h2>Kommentare</h2>
  {% for c in t.comments %}
    <div style="border-bottom:1px solid var(--line);padding:.55rem 0;">
      <div class="muted" style="font-size:.85rem;">{{ c.author }} · {{ c.at_disp }}</div>
      <div style="white-space:pre-wrap;">{{ c.body }}</div></div>
  {% else %}<p class="muted">Noch keine Kommentare.</p>{% endfor %}
  <form method="post" action="/tickets/{{ t.id }}/comment" style="margin-top:.8rem;">
    <textarea name="body" placeholder="Kommentar schreiben…"></textarea>
    <div style="margin-top:.6rem;"><button type="submit">Kommentar hinzufügen</button></div>
  </form>
</div>

<div class="card glass">
  <h2>Anhänge</h2>
  <p class="muted" style="margin-top:-.3rem;">Hinweis: Anhänge werden beim
    <b>Schließen</b> des Tickets automatisch gelöscht (Speicher sparen).</p>
  {% for a in t.attachments %}
    <div style="display:flex;align-items:center;gap:.6rem;border-bottom:1px solid var(--line);padding:.45rem 0;">
      <a href="/tickets/{{ t.id }}/attachment/{{ a.id }}">{{ a.filename }}</a>
      <span class="muted" style="font-size:.85rem;">{{ a.by }}</span>
      {% if can_edit %}<form method="post" action="/tickets/{{ t.id }}/attachment/{{ a.id }}/delete" style="margin-left:auto;">
        <button class="danger" onclick="return confirm('Anhang löschen?')">löschen</button></form>{% endif %}
    </div>
  {% else %}<p class="muted">Keine Anhänge.</p>{% endfor %}
  <form method="post" action="/tickets/{{ t.id }}/attach" enctype="multipart/form-data" style="margin-top:.8rem;" class="toolbar">
    <input type="file" name="file" style="width:auto">
    <button type="submit">Hochladen</button>
  </form>
</div>

<div class="card glass">
  <h2>Bearbeitungsstand &amp; Aufwand · Summe {{ wl_hours }} Std, {{ wl_km }} km</h2>
  {% if t.worklogs %}<div class="tablewrap"><table>
    <thead><tr><th>Datum</th><th>Bearbeiter</th><th class="num">Anfahrt km</th>
      <th class="num">Stunden</th><th>Material</th><th>Tätigkeit</th>{% if can_edit %}<th></th>{% endif %}</tr></thead>
    <tbody>{% for w in t.worklogs %}<tr>
      <td>{{ w.date }}</td><td class="muted">{{ w.performed_by }}</td>
      <td class="num">{{ w.travel_km }}</td><td class="num">{{ w.hours }}</td>
      <td>{{ w.material }}</td><td>{{ w.description }}</td>
      {% if can_edit %}<td><form method="post" action="/tickets/{{ t.id }}/worklog/{{ w.id }}/delete">
        <button class="danger" onclick="return confirm('Eintrag löschen?')">löschen</button></form></td>{% endif %}
    </tr>{% endfor %}</tbody></table></div>
  {% else %}<p class="muted">Noch keine Aufwands-/Bearbeitungseinträge.</p>{% endif %}
  {% if can_edit %}
  <form method="post" action="/tickets/{{ t.id }}/worklog" style="margin-top:.8rem;">
    <div class="row">
      <div style="flex:0 0 160px;"><label>Datum</label><input type="date" name="date" value="{{ today }}"></div>
      <div style="flex:0 0 130px;"><label>Anfahrt (km)</label><input name="travel_km" value="0"></div>
      <div style="flex:0 0 130px;"><label>Stunden</label><input name="hours" value="0"></div>
      <div><label>Material</label><input name="material" placeholder="optional"></div>
    </div>
    <label>Tätigkeit</label><textarea name="description"></textarea>
    <div style="margin-top:.6rem;"><button type="submit">Aufwand erfassen</button></div>
  </form>
  {% endif %}
</div>
</div>
<aside class="tside">
  <div class="card glass">
    <h2>Verlauf</h2>
    {% for h in t.history|reverse %}
      <div class="hist">
        <div class="meta">{{ h.at_disp }} · <b>{{ h.by }}</b></div>
        <div>{{ h.text }}</div>
      </div>
    {% else %}<p class="muted">Noch keine Aktivität.</p>{% endfor %}
  </div>
</aside>
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
<div class="card glass" style="max-width:560px;">
  <h2>Test-E-Mails</h2>
  <p class="muted">Sendet je eine Beispiel-Mail (Bericht &amp; Erinnerung) an die
    Adresse – um Design und Versand zu prüfen.{% if not mail_configured %}
    <b>Hinweis:</b> SMTP/Brevo ist nicht konfiguriert – es wird nur als Datei
    gespeichert.{% endif %}</p>
  <form method="post" action="/einstellungen/testmail">
    <label>Empfänger</label>
    <input name="email" type="email" value="{{ admin_email }}" placeholder="name@firma.de">
    <div style="margin-top:1rem;"><button type="submit">Testmails senden</button></div>
  </form>
  <hr style="border:none;border-top:1px solid var(--line);margin:1.3rem 0;">
  <h2>Erinnerungen</h2>
  <p class="muted">Prüft sofort, ob Buchungen &gt;24 h ohne
    Tätigkeitsbeschreibung eine Erinnerung an den jeweiligen Mitarbeiter
    auslösen (läuft sonst stündlich automatisch).</p>
  <form method="post" action="/einstellungen/reminders-now">
    <button type="submit" class="ghost">Erinnerungen jetzt prüfen</button>
  </form>
  <hr style="border:none;border-top:1px solid var(--line);margin:1.3rem 0;">
  <h2>Texte bearbeiten</h2>
  <p class="muted">Login-Texte (inkl. der Pille oben), Begrüßung &amp; App-Name
    anpassen.</p>
  <a class="btn ghost" href="/einstellungen/texte">Texte bearbeiten</a>
  <hr style="border:none;border-top:1px solid var(--line);margin:1.3rem 0;">
  <h2>Projekte &amp; Task-Nummern</h2>
  <p class="muted">Task-Nr. je Projekt zuordnen/korrigieren (für den
    Amprion-Export).</p>
  <a class="btn ghost" href="/einstellungen/projekte">Projekte verwalten</a>
</div>
{% endblock %}
"""

_TEXTS = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:720px;">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Texte</h1>
    <a class="btn ghost" href="/einstellungen">Zurück</a>
  </div>
  <p class="muted">Passe die sichtbaren Texte an. Leeres Feld = Standardtext.
    Änderungen greifen sofort.</p>
  <form method="post" action="/einstellungen/texte">
    {% for f in fields %}
      <label>{{ f.label }}</label>
      {% if f.multiline %}
        <textarea name="{{ f.key }}" rows="3">{{ f.value }}</textarea>
      {% else %}
        <input name="{{ f.key }}" value="{{ f.value }}">
      {% endif %}
    {% endfor %}
    <div class="toolbar" style="margin-top:1.3rem;">
      <button type="submit">Speichern</button>
      <a class="btn ghost" href="/start">Vorschau (Dashboard)</a>
    </div>
  </form>
  <hr style="border:none;border-top:1px solid var(--line);margin:1.3rem 0;">
  <form method="post" action="/einstellungen/texte/reset"
        onsubmit="return confirm('Alle Texte auf Standard zurücksetzen?')">
    <button type="submit" class="danger">Auf Standard zurücksetzen</button>
  </form>
</div>
{% endblock %}
"""

_PROJECTS = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Projekte</h1>
    <a class="btn ghost" href="/einstellungen">Zurück</a>
  </div>
  <p class="muted">Ordne jedem Projekt eine <b>Task-Nr.</b> zu (für den
    Amprion-Export). Leer = automatische Erkennung aus dem Projektnamen
    (grau als Vorschlag angezeigt). Eine hier gesetzte Nummer hat immer Vorrang.</p>
  {% if not rows %}<p>Noch keine Projekte erkannt.</p>{% else %}
  <form method="post" action="/einstellungen/projekte">
    <div class="tablewrap"><table>
      <thead><tr><th>Projekt</th><th>Task-Nr. (erkannt)</th><th>Task-Nr. (manuell)</th></tr></thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td><b>{{ r.project }}</b><input type="hidden" name="proj" value="{{ r.project }}"></td>
          <td class="muted">{{ r.detected or '–' }}</td>
          <td><input name="nr" value="{{ r.value }}" placeholder="{{ r.detected }}" style="max-width:180px"></td>
        </tr>
      {% endfor %}
      </tbody>
    </table></div>
    <div style="margin-top:1.2rem;"><button type="submit">Speichern</button></div>
  </form>
  {% endif %}
</div>
{% endblock %}
"""

_AREA = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1 style="margin:0 0 .3rem;">{{ area.title }}</h1>
  <p class="muted" style="margin:0 0 .6rem;">{{ area.desc }}</p>
  {% if cats %}
  <div class="minirow">
    <a class="mini" href="{{ area.url }}" {% if not cat %}style="background:#e6f0de;border-color:#b9d3a8;color:var(--brand-deep)"{% endif %}>Alle</a>
    {% for c in cats %}<a class="mini" href="{{ area.url }}?cat={{ c|urlencode }}" {% if cat==c %}style="background:#e6f0de;border-color:#b9d3a8;color:var(--brand-deep)"{% endif %}>{{ c }}</a>{% endfor %}
  </div>
  {% endif %}
  {% if docs %}
  <div class="tablewrap"><table>
    <thead><tr><th>Titel</th><th>Kategorie</th><th>Typ</th><th class="num">Größe</th><th>Stand</th><th></th></tr></thead>
    <tbody>
    {% for d in docs %}
      <tr>
        <td><a href="{{ area.url }}/{{ d.id }}"><b>{{ d.title }}</b></a></td>
        <td>{% if d.category %}<span class="pill role">{{ d.category }}</span>{% endif %}</td>
        <td class="muted">{{ d.ext }}</td>
        <td class="num muted">{{ d.size_disp }}</td>
        <td class="muted">{{ d.at_disp }}</td>
        <td style="text-align:right;"><div class="rowactions">
          <a class="btn ghost" href="{{ area.url }}/{{ d.id }}">Ansehen</a>
          <a class="btn ghost" href="{{ area.url }}/{{ d.id }}/file?download=1">Download</a>
          {% if role=='admin' %}
          <form method="post" action="{{ area.url }}/{{ d.id }}/delete">
            <button class="danger" onclick="return confirm('Dokument löschen?')">Löschen</button></form>
          {% endif %}
        </div></td>
      </tr>
    {% endfor %}
    </tbody>
  </table></div>
  {% else %}<p class="muted">Noch keine Dokumente vorhanden.</p>{% endif %}
</div>
{% if role=='admin' %}
<div class="card glass" style="max-width:640px;">
  <h2>Dokument hochladen</h2>
  <form method="post" action="{{ area.url }}/upload" enctype="multipart/form-data">
    <div class="row">
      <div><label>Titel (leer = Dateiname)</label><input name="title"></div>
      <div style="flex:0 0 230px;"><label>Kategorie (optional)</label>
        <input name="category" list="catlist" placeholder="z. B. Prozess, Schulung">
        <datalist id="catlist">{% for c in cats %}<option value="{{ c }}">{% endfor %}</datalist></div>
    </div>
    <label>Datei</label>
    <input type="file" name="file" required>
    <p class="muted" style="margin:.4rem 0 0;">PDF, Bilder, Videos und Texte
      werden direkt im Browser angezeigt; andere Formate (z. B. Word/Excel)
      stehen als Download bereit.</p>
    <div style="margin-top:1rem;"><button type="submit">Hochladen</button></div>
  </form>
</div>
{% endif %}
{% endblock %}
"""

_AREA_VIEW = """
{% extends base %}
{% block body %}
<div class="card glass">
  <div class="toolbar" style="justify-content:space-between;">
    <div>
      <h1 style="margin:0;">{{ d.title }}</h1>
      <p class="muted" style="margin:.3rem 0 0;">{{ area.title }}{% if d.category %} · {{ d.category }}{% endif %} · {{ d.filename }} · {{ d.size_disp }} · Stand {{ d.at_disp }}</p>
    </div>
    <div class="toolbar">
      <a class="btn ghost" href="{{ area.url }}">← Zurück</a>
      <a class="btn" href="{{ area.url }}/{{ d.id }}/file?download=1">Download</a>
    </div>
  </div>
</div>
<div class="card glass" style="padding:.8rem;">
  {% if kind=='pdf' or kind=='text' %}<iframe class="docview" src="{{ file_url }}" title="{{ d.title }}"></iframe>
  {% elif kind=='image' %}<img src="{{ file_url }}" alt="{{ d.title }}" style="max-width:100%;border-radius:10px;display:block;margin:0 auto;">
  {% elif kind=='video' %}<video controls preload="metadata" style="width:100%;border-radius:10px;display:block;" src="{{ file_url }}"></video>
  {% elif kind=='audio' %}<audio controls style="width:100%;display:block;" src="{{ file_url }}"></audio>
  {% else %}<p class="muted" style="padding:1rem;">Für dieses Format gibt es
    keine Browser-Vorschau ({{ d.mime }}). Bitte über den Download-Button
    öffnen.</p>{% endif %}
</div>
{% endblock %}
"""

_VCARDS = """
{% extends base %}
{% block body %}
<div class="card glass">
  <h1 style="margin:0 0 .3rem;">Visitenkarten</h1>
  <p class="muted">Digitale Visitenkarten mit eigener öffentlicher URL – zum
    Aufdrucken/QR-Code auf die gedruckte Karte. Die öffentliche Seite zeigt
    <b>nur</b> die hier eingetragenen Angaben; ein Zugang zum Intranet ist
    darüber nicht möglich.</p>
  {% if cards %}
  <div class="tablewrap"><table>
    <thead><tr><th>Name</th><th>URL</th><th>Status</th><th></th></tr></thead>
    <tbody>
    {% for c in cards %}
      <tr>
        <td><b>{{ c.name }}</b>{% if c.title %}<div class="muted" style="font-size:.84rem;">{{ c.title }}</div>{% endif %}</td>
        <td><code>{{ c.url }}</code></td>
        <td>{% if c.enabled %}<span class="pill ok">aktiv</span>{% else %}<span class="pill no">aus</span>{% endif %}</td>
        <td style="text-align:right;"><div class="rowactions">
          {% if c.enabled %}<a class="btn ghost" href="/v/{{ c.slug }}" target="_blank" rel="noopener">Ansehen ↗</a>{% endif %}
          <a class="btn ghost" href="/einstellungen/visitenkarten/{{ c.id }}">Bearbeiten</a>
          <form method="post" action="/einstellungen/visitenkarten/{{ c.id }}/delete">
            <button class="danger" onclick="return confirm('Visitenkarte löschen?')">Löschen</button></form>
        </div></td>
      </tr>
    {% endfor %}
    </tbody>
  </table></div>
  {% else %}<p class="muted">Noch keine Visitenkarten angelegt.</p>{% endif %}
</div>
<div class="card glass" style="max-width:560px;">
  <h2>Neue Visitenkarte</h2>
  <form method="post" action="/einstellungen/visitenkarten">
    <label>Name</label>
    <input name="name" placeholder="z. B. Dustyn Model" list="usernames" required>
    <datalist id="usernames">{% for n in names %}<option value="{{ n }}">{% endfor %}</datalist>
    <div style="margin-top:1rem;"><button type="submit">Anlegen &amp; bearbeiten</button></div>
  </form>
</div>
{% endblock %}
"""

_VCARD_EDIT = """
{% extends base %}
{% block body %}
<div class="card glass" style="max-width:640px;">
  <div class="toolbar" style="justify-content:space-between;">
    <h1 style="margin:0;">Visitenkarte: {{ c.name }}</h1>
    <a class="btn ghost" href="/einstellungen/visitenkarten">Zurück</a>
  </div>
  <form method="post" action="/einstellungen/visitenkarten/{{ c.id }}" enctype="multipart/form-data">
    {% for key, label, ph in fields %}
      <label>{{ label }}</label>
      <input name="{{ key }}" value="{{ c[key] or '' }}" placeholder="{{ ph }}">
    {% endfor %}
    <label>URL-Kennung (wird gedruckt: {{ base_url }}/v/…)</label>
    <input name="slug" value="{{ c.slug }}" pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]">
    <p class="muted" style="margin:.3rem 0 0;">Nur Kleinbuchstaben, Zahlen und
      Bindestriche. Nach dem Druck nicht mehr ändern!</p>
    <label>Foto (rund angezeigt, JPG/PNG)</label>
    <input type="file" name="photo" accept="image/*">
    {% if c.photo %}<p class="muted" style="margin:.3rem 0 0;">Foto vorhanden –
      neues Foto ersetzt das alte.</p>{% endif %}
    <label style="display:flex;align-items:center;gap:.5rem;margin-top:1rem;cursor:pointer;">
      <input type="checkbox" name="enabled" value="1" {{ 'checked' if c.enabled }}
        style="width:auto;"> Karte öffentlich erreichbar (aktiv)
    </label>
    <div class="toolbar" style="margin-top:1.2rem;">
      <button type="submit">Speichern</button>
      {% if c.enabled %}<a class="btn ghost" href="/v/{{ c.slug }}" target="_blank" rel="noopener">Vorschau ↗</a>{% endif %}
    </div>
  </form>
</div>
{% if c.enabled %}
<div class="card glass" style="max-width:640px;">
  <h2>Für den Druck</h2>
  <p>URL: <code>{{ url }}</code></p>
  <p class="muted">QR-Code (Rechtsklick → „Bild speichern“ für die Druckerei):</p>
  <img src="{{ qr }}" alt="QR-Code" style="width:190px;height:190px;background:#fff;padding:10px;border:1px solid var(--line);border-radius:12px;">
</div>
{% endif %}
{% endblock %}
"""

_tpls = {n: Template(s) for n, s in {
    "login": _LOGIN, "home": _HOME, "dash": _DASH, "log": _LOG, "log_form": _LOG_FORM,
    "send": _SEND, "anleitung": _ANLEITUNG, "audit": _AUDIT,
    "account": _ACCOUNT, "users": _USERS, "invite": _INVITE,
    "reports": _REPORTS, "report_form": _REPORT_FORM, "settings": _SETTINGS,
    "texts": _TEXTS, "projects": _PROJECTS,
    "abrechnung": _ABRECHNUNG, "meine": _MEINE, "my_form": _MY_FORM,
    "user_edit": _USER_EDIT,
    "twofa_verify": _TWOFA_VERIFY, "twofa_setup": _TWOFA_SETUP,
    "reset_req": _RESET_REQ, "reset_form": _RESET_FORM,
    "tickets": _TICKETS, "ticket_new": _TICKET_NEW, "ticket": _TICKET,
    "area": _AREA, "area_view": _AREA_VIEW,
    "vcards": _VCARDS, "vcard_edit": _VCARD_EDIT,
}.items()}


class _Texts:
    """Liest die anpassbaren Anzeigetexte bei jedem Zugriff frisch aus den
    Einstellungen (damit Änderungen sofort greifen). In Templates: texts.key."""
    def __getattr__(self, key):
        return settings.get_texts().get(key, "")
    def __getitem__(self, key):
        return settings.get_texts().get(key, "")


_texts_proxy = _Texts()

for _tpl in [_base_tpl, *_tpls.values()]:
    _tpl.environment.globals["base"] = _base_tpl       # type: ignore
    _tpl.environment.globals["logo_url"] = LOGO_URL    # type: ignore
    _tpl.environment.globals["icons"] = ICONS          # type: ignore
    _tpl.environment.globals["timemoto_url"] = config.TIMEMOTO_URL  # type: ignore
    _tpl.environment.globals["teilnahme_url"] = config.TEILNAHME_URL  # type: ignore
    _tpl.environment.globals["ms_logo"] = _MS_LOGO    # type: ignore
    _tpl.environment.globals["logo_url_white"] = LOGO_URL_WHITE  # type: ignore
    _tpl.environment.globals["texts"] = _texts_proxy   # type: ignore


# Oeffentliche Visitenkarte: bewusst EIGENSTAENDIG (kein {% extends base %}),
# keine Session, keine internen Links -- nur die Kartendaten.
_VCARD_PUB = Template("""
<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{{ c.name }} – {{ c.company }}</title>
<link rel="icon" href="https://fb-eng.de/wp-content/uploads/2024/10/cropped-FBE_midnight.png">
<meta name="theme-color" content="#123726">
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;background:#f4f6f2;color:#1b2a20;
    font:16px/1.55 -apple-system,BlinkMacSystemFont,system-ui,Segoe UI,Roboto,sans-serif;
    display:flex;flex-direction:column}
  .hero{background:linear-gradient(160deg,rgba(18,55,38,.90),rgba(24,74,49,.84)),
    url('{{ bg }}') center/cover no-repeat;
    padding:3.2rem 1rem 2.6rem;text-align:center;color:#fff}
  .photo{width:128px;height:128px;border-radius:50%;object-fit:cover;
    border:4px solid rgba(255,255,255,.92);box-shadow:0 10px 30px rgba(0,0,0,.35);
    background:#fff}
  .initials{width:128px;height:128px;border-radius:50%;display:inline-flex;
    align-items:center;justify-content:center;font-size:2.4rem;font-weight:800;
    color:#2f6b1f;background:#fff;border:4px solid rgba(255,255,255,.92);
    box-shadow:0 10px 30px rgba(0,0,0,.35)}
  h1{margin:1rem 0 .2rem;font-size:1.75rem;letter-spacing:-.02em}
  .sub{margin:0;color:rgba(255,255,255,.88)}
  main{flex:1;max-width:560px;width:100%;margin:0 auto;padding:2.2rem 1.2rem}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.4rem 1rem;
    justify-items:center}
  .tile{display:flex;flex-direction:column;align-items:center;gap:.5rem;
    text-decoration:none;color:#33413a;font-size:.85rem;font-weight:600}
  .tile .ic{width:64px;height:64px;border-radius:16px;display:flex;
    align-items:center;justify-content:center;
    box-shadow:0 4px 14px rgba(20,40,25,.18);transition:.15s}
  .tile:hover .ic{transform:translateY(-3px);box-shadow:0 8px 20px rgba(20,40,25,.25)}
  .tile svg{width:30px;height:30px;stroke:#fff;fill:none;stroke-width:2;
    stroke-linecap:round;stroke-linejoin:round}
  footer{padding:1.4rem 1rem 1.8rem;text-align:center;color:#6a7870;
    font-size:.85rem}
  footer a{color:#44772f;text-decoration:none;margin:0 .5rem}
  @media(max-width:400px){.grid{gap:1.1rem .6rem}.tile .ic{width:58px;height:58px}}
</style></head><body>
<div class="hero">
  {% if has_photo %}<img class="photo" src="/v/{{ c.slug }}/foto" alt="{{ c.name }}">
  {% else %}<span class="initials">{{ initials }}</span>{% endif %}
  <h1>{{ c.name }}</h1>
  {% if c.title %}<p class="sub">{{ c.title }}</p>{% endif %}
  <p class="sub">{{ c.company }}</p>
</div>
<main>
  <div class="grid">
    <a class="tile" href="/v/{{ c.slug }}/kontakt.vcf">
      <span class="ic" style="background:#6fa84f;"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/></svg></span>
      Kontakt speichern</a>
    {% if c.linkedin %}
    <a class="tile" href="{{ c.linkedin }}" target="_blank" rel="noopener">
      <span class="ic" style="background:#0a66c2;"><svg viewBox="0 0 24 24"><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4V9h4v1.5"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></svg></span>
      LinkedIn</a>
    {% endif %}
    {% if c.email %}
    <a class="tile" href="mailto:{{ c.email }}">
      <span class="ic" style="background:#3d7ff0;"><svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 6l10 7 10-7"/></svg></span>
      E-Mail</a>
    {% endif %}
    {% if c.whatsapp %}
    <a class="tile" href="https://wa.me/{{ c.whatsapp }}" target="_blank" rel="noopener">
      <span class="ic" style="background:#25d366;"><svg viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.4L3 21l2.2-5.5A8.5 8.5 0 1 1 21 11.5z"/><path d="M8.7 9.2c.4 2.4 3 5 5.4 5.4l1.4-1.4 2 1.2c-.5 1.6-2 2-3.4 1.6-3-.8-6-3.8-6.8-6.8-.4-1.4 0-2.9 1.6-3.4l1.2 2z"/></svg></span>
      WhatsApp</a>
    {% endif %}
    {% if c.maps %}
    <a class="tile" href="{{ c.maps }}" target="_blank" rel="noopener">
      <span class="ic" style="background:#ea4335;"><svg viewBox="0 0 24 24"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/></svg></span>
      Standort</a>
    {% endif %}
    {% if c.website %}
    <a class="tile" href="{{ c.website }}" target="_blank" rel="noopener">
      <span class="ic" style="background:#123726;"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z"/></svg></span>
      Webseite</a>
    {% endif %}
  </div>
</main>
<footer>
  © {{ year }} {{ c.company }}
  <div style="margin-top:.4rem;">
    <a href="https://fb-eng.de/impressum/" target="_blank" rel="noopener">Impressum</a>
    <a href="https://fb-eng.de/datenschutz/" target="_blank" rel="noopener">Datenschutz</a>
  </div>
</footer>
</body></html>
""")


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
    imp = request.session.get("impersonator")
    return dict(user=_user(request), role=role, page=page, title=title,
                display_name=request.session.get("name"), initials=initials,
                role_label=role_label, is_billing=(role in ("admin", "buchhaltung")),
                tk_view=bool(request.session.get("tk_view") or role == "admin"),
                tk_edit=bool(request.session.get("tk_edit") or role == "admin"),
                can_fix=bool(role in ("admin", "buchhaltung")
                             or request.session.get("fix_times")),
                impersonating=bool(imp),
                imp_by=(imp or {}).get("name") if imp else None,
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


def _disp(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(
            config.TIMEZONE).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso or ""


def _to_float(x) -> float:
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


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


def _range_presets() -> list[dict]:
    """Schnellauswahl-Zeitraeume fuer Log/Abrechnung (ISO-Daten)."""
    now = datetime.now(config.TIMEZONE)
    tw_s, tw_e = this_week_range(now)
    lw_s, lw_e = previous_week_range(now)
    m_s = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return [
        {"label": "Diese Woche", "start": tw_s.date().isoformat(),
         "end": tw_e.date().isoformat()},
        {"label": "Letzte Woche", "start": lw_s.date().isoformat(),
         "end": lw_e.date().isoformat()},
        {"label": "Dieser Monat", "start": m_s.date().isoformat(),
         "end": (now + timedelta(days=1)).date().isoformat()},
        {"label": "Alles", "start": "", "end": ""},
    ]


def _need_login(request: Request):
    return None if _user(request) else RedirectResponse("/login", status_code=303)


def _deny(request: Request, msg: str):
    """Angemeldet, aber ohne Recht -> zurueck aufs Dashboard mit Hinweis
    (keine tote 'Kein Zugriff'-Seite, es gibt immer einen Weg zurueck)."""
    request.session["flash"], request.session["flash_class"] = msg, "err"
    return RedirectResponse("/start", status_code=303)


def _need_admin(request: Request):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if _role(request) != "admin":
        return _deny(request, "Dieser Bereich ist nur für Administratoren.")
    return None


def _need_billing(request: Request):
    """Admin oder Buchhaltung."""
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if _role(request) not in ("admin", "buchhaltung"):
        return _deny(request, "Dieser Bereich ist nur für Buchhaltung und "
                     "Administratoren. Deine eigenen Zeiten findest du unter "
                     "„Meine Zeiten“.")
    return None


def _need_timekeeper(request: Request):
    """Zeiten korrigieren: Admin, Buchhaltung oder Recht 'Zeiten korrigieren'."""
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if (_role(request) in ("admin", "buchhaltung")
            or request.session.get("fix_times")):
        return None
    return _deny(request, "Dieser Bereich ist nur für Personen mit dem Recht "
                 "„Zeiten korrigieren“.")


def _need_tickets(request: Request):
    """Tickets ansehen (admin oder Recht 'Tickets sehen/bearbeiten')."""
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    if not (request.session.get("tk_view") or _role(request) == "admin"):
        return HTMLResponse("Kein Zugriff auf Tickets.", status_code=403)
    return None


def _tk_edit(request: Request) -> bool:
    return _role(request) == "admin" or bool(request.session.get("tk_edit"))


# --- Web-App (PWA) ----------------------------------------------------------

@router.get("/manifest.webmanifest")
async def manifest():
    return Response(json.dumps(_MANIFEST, ensure_ascii=False),
                    media_type="application/manifest+json",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sw.js")
async def service_worker():
    return Response(_SW_JS, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


# --- Login / Logout --------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if _user(request):
        return RedirectResponse("/start", status_code=303)
    return HTMLResponse(_tpls["login"].render(
        title="Login", user=None,
        flash=request.session.pop("flash", None),
        flash_class=request.session.pop("flash_class", ""),
        ms_enabled=config.ms_enabled(), bg_image=config.LOGIN_BG_IMAGE,
        show_local=(not config.ms_enabled()
                    or bool(request.query_params.get("local"))),
        login_possible=bool(users.list_users()) or config.login_possible()))


def _finalize_login(request: Request, user: dict) -> None:
    request.session.pop("pending_user", None)
    request.session.pop("enroll_secret", None)
    role = user.get("role", "user")
    request.session["user"] = user["username"]
    request.session["role"] = role
    request.session["name"] = user.get("name") or user["username"]
    request.session["tk_view"] = bool(
        role == "admin" or user.get("can_view_tickets")
        or user.get("can_edit_tickets"))
    request.session["tk_edit"] = bool(
        role == "admin" or user.get("can_edit_tickets"))
    request.session["fix_times"] = bool(
        role in ("admin", "buchhaltung") or user.get("can_fix_times"))


@router.post("/login")
async def login_submit(request: Request, username: str = Form(""),
                       password: str = Form("")):
    user = users.verify_login(username.strip(), password)
    if not user:
        request.session["flash"] = "Benutzer oder Passwort falsch."
        request.session["flash_class"] = "err"
        return RedirectResponse("/login", status_code=303)
    # Passwort ok (lokale Konten: Admin + externe). Microsoft-Konten haben
    # kein Passwort und melden sich ohnehin per Microsoft an.
    # Passwort ok -> zweiter Faktor
    if user.get("twofa_enabled") and user.get("totp_secret"):
        request.session["pending_user"] = user["username"]
        return RedirectResponse("/login/2fa", status_code=303)
    if config.TWOFA_REQUIRED:
        # Noch keine 2FA -> jetzt einrichten (Pflicht)
        request.session["pending_user"] = user["username"]
        return RedirectResponse("/2fa/setup", status_code=303)
    _finalize_login(request, user)
    return RedirectResponse("/start", status_code=303)


@router.get("/auth/microsoft/login")
async def ms_login(request: Request):
    if not config.ms_enabled():
        return RedirectResponse("/login", status_code=303)
    state = secrets.token_urlsafe(16)
    request.session["ms_state"] = state
    return RedirectResponse(msauth.login_url(state), status_code=303)


@router.get("/auth/microsoft/callback")
async def ms_callback(request: Request, code: str = "", state: str = "",
                      error: str = ""):
    if not config.ms_enabled():
        return RedirectResponse("/login", status_code=303)
    if error or not code or state != request.session.pop("ms_state", None):
        request.session["flash"], request.session["flash_class"] = \
            "Microsoft-Anmeldung abgebrochen oder ungültig.", "err"
        return RedirectResponse("/login", status_code=303)
    info = msauth.exchange(code)
    if not info or info.get("error"):
        request.session["flash"], request.session["flash_class"] = \
            ("Diese Microsoft-Domain ist nicht freigegeben."
             if info and info.get("error") == "domain_not_allowed"
             else "Microsoft-Anmeldung fehlgeschlagen."), "err"
        return RedirectResponse("/login", status_code=303)
    user = users.upsert_oauth(info["email"], info["name"])
    _finalize_login(request, user)  # Microsoft-MFA genügt -> keine eigene 2FA
    audit.log(user["username"], "Login via Microsoft", info["email"])
    return RedirectResponse("/start", status_code=303)


@router.get("/start", response_class=HTMLResponse)
async def home(request: Request):
    if (r := _need_login(request)):
        return r
    nm = request.session.get("name") or _user(request) or ""
    first = nm.split()[0] if nm.split() else nm
    ctx = _common(request, "home", "Start")

    # Zeiten des angemeldeten Nutzers (TimeMoto-Name, sonst Anzeigename)
    rec = users.get(_user(request)) or {}
    emp = (rec.get("timemoto_name") or nm).strip()
    now = datetime.now(config.TIMEZONE)
    week_hours, week_sessions, recent = "0:00", 0, []
    todo_desc = 0
    try:
        from datetime import timedelta
        ws, we = this_week_range(now)
        if emp:
            wk = filter_intervals(ws, we, employee=emp)
            week_sessions = len(wk)
            week_hours = _fmt_dur(sum(max(iv.duration_hours, 0.0) for iv in wk)).replace(" h", "")
            horizon = now - timedelta(days=60)
            own = filter_intervals(horizon, None, employee=emp)
            todo_desc = sum(1 for iv in own if not (iv.description or "").strip())
            for iv in own[:5]:
                sv = _session_view(iv)
                p = sv["project"]
                sv["ini"] = "".join(w[0] for w in p.split()[:2]).upper() if p and p != "–" else "•"
                recent.append(sv)
    except Exception:
        pass
    open_tickets = 0
    if ctx.get("tk_view"):
        try:
            c = tickets.counts_by_status()
            open_tickets = int(c.get("open", 0)) + int(c.get("in_progress", 0))
        except Exception:
            open_tickets = 0

    wd = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
          "Samstag", "Sonntag"][now.weekday()]
    return HTMLResponse(_tpls["home"].render(
        **ctx, teilnahme_url=config.TEILNAHME_URL, first_name=first,
        today=f"{wd}, {now:%d.%m.%Y}", kw=now.isocalendar().week,
        year=now.year, week_hours=week_hours, week_sessions=week_sessions,
        open_tickets=open_tickets, recent=recent,
        todo_desc=todo_desc, todo_total=todo_desc))


@router.get("/login/2fa", response_class=HTMLResponse)
async def twofa_verify_form(request: Request):
    if not request.session.get("pending_user"):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(_tpls["twofa_verify"].render(
        title="Bestätigung", user=None,
        flash=request.session.pop("flash", None),
        flash_class=request.session.pop("flash_class", "")))


@router.post("/login/2fa")
async def twofa_verify(request: Request, code: str = Form("")):
    uname = request.session.get("pending_user")
    u = users.get(uname) if uname else None
    if not u or not u.get("totp_secret"):
        return RedirectResponse("/login", status_code=303)
    if pyotp.TOTP(u["totp_secret"]).verify(code.strip().replace(" ", ""), valid_window=1):
        _finalize_login(request, u)
        return RedirectResponse("/start", status_code=303)
    request.session["flash"], request.session["flash_class"] = \
        "Code ungültig. Bitte erneut versuchen.", "err"
    return RedirectResponse("/login/2fa", status_code=303)


@router.get("/2fa/setup", response_class=HTMLResponse)
async def twofa_setup_form(request: Request):
    uname = request.session.get("pending_user") or _user(request)
    if not uname:
        return RedirectResponse("/login", status_code=303)
    secret = request.session.get("enroll_secret")
    if not secret:
        secret = pyotp.random_base32()
        request.session["enroll_secret"] = secret
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=uname, issuer_name=config.TWOFA_ISSUER)
    qr = segno.make(uri, error="m").svg_data_uri(scale=5)
    if _user(request):
        ctx = _common(request, "account", "2FA einrichten")
    else:
        ctx = dict(title="2FA einrichten", user=None,
                   flash=request.session.pop("flash", None),
                   flash_class=request.session.pop("flash_class", ""))
    ctx.update(qr=qr, secret=secret)
    return HTMLResponse(_tpls["twofa_setup"].render(**ctx))


@router.post("/2fa/setup")
async def twofa_setup_save(request: Request, code: str = Form("")):
    uname = request.session.get("pending_user") or _user(request)
    secret = request.session.get("enroll_secret")
    if not uname or not secret:
        return RedirectResponse("/login", status_code=303)
    if not pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1):
        request.session["flash"], request.session["flash_class"] = \
            "Code ungültig – bitte aus der App erneut eingeben.", "err"
        return RedirectResponse("/2fa/setup", status_code=303)
    users.enroll_totp(uname, secret)
    audit.log(uname, "2FA eingerichtet", uname)
    u = users.get(uname)
    if request.session.get("pending_user"):
        _finalize_login(request, u)
        request.session["flash"] = "2FA aktiviert. Willkommen!"
        return RedirectResponse("/start", status_code=303)
    request.session.pop("enroll_secret", None)
    request.session["flash"] = "2FA neu eingerichtet."
    return RedirectResponse("/account", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/reset", response_class=HTMLResponse)
async def reset_request_form(request: Request):
    return HTMLResponse(_tpls["reset_req"].render(
        title="Passwort zurücksetzen", user=None,
        flash=request.session.pop("flash", None),
        flash_class=request.session.pop("flash_class", "")))


@router.post("/reset")
async def reset_request(request: Request, identifier: str = Form("")):
    u, token = users.create_reset_token(identifier)
    if u and u.get("email") and token:
        link = f"{request.base_url}reset/{token}"
        name = u.get("name") or u["username"]
        subj = "Passwort zurücksetzen – FBE Projektabrechnung"
        text = (f"Hallo {name},\n\nüber diesen Link kannst du dein Passwort neu "
                f"setzen (gültig {config.RESET_TTL_MIN} Minuten):\n{link}\n\n"
                "Wenn du das nicht angefordert hast, ignoriere diese Mail.")
        html = (f"<p>Hallo {escape(name)},</p><p>über den Button setzt du dein "
                f"Passwort neu (Link {config.RESET_TTL_MIN} Minuten gültig).</p>"
                f'<p><a href="{link}" style="display:inline-block;'
                f'background:{config.BRAND_COLOR};color:#123018;font-weight:bold;'
                'text-decoration:none;padding:12px 24px;border-radius:999px">'
                "Passwort neu setzen</a></p>"
                '<p style="color:#64748b;font-size:13px">Nicht angefordert? '
                "Dann ignoriere diese Mail.</p>")
        mailer.send(subj, text, html, [u["email"]], label="Passwort-Reset",
                    actor="System")
    request.session["flash"] = ("Falls ein Konto mit dieser Angabe existiert, "
                                "wurde ein Reset-Link per E-Mail gesendet.")
    return RedirectResponse("/login", status_code=303)


@router.get("/reset/{token}", response_class=HTMLResponse)
async def reset_form(request: Request, token: str):
    if not users.valid_reset(token):
        return HTMLResponse(_base_tpl.render(
            title="Reset", user=None, flash_class="err",
            flash="Reset-Link ungültig oder abgelaufen."), status_code=404)
    return HTMLResponse(_tpls["reset_form"].render(
        title="Neues Passwort", user=None, token=token,
        flash=request.session.pop("flash", None),
        flash_class=request.session.pop("flash_class", "")))


@router.post("/reset/{token}")
async def reset_save(request: Request, token: str, new1: str = Form(""),
                     new2: str = Form("")):
    if len(new1) < 8 or new1 != new2:
        request.session["flash"], request.session["flash_class"] = \
            "Passwort min. 8 Zeichen und beide Felder gleich.", "err"
        return RedirectResponse(f"/reset/{token}", status_code=303)
    uname = users.consume_reset(token, new1)
    if not uname:
        request.session["flash"], request.session["flash_class"] = \
            "Reset-Link ungültig oder abgelaufen.", "err"
        return RedirectResponse("/login", status_code=303)
    request.session["flash"] = "Passwort geändert. Bitte melde dich an."
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
    if (r := _need_billing(request)):
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
    span = rep.end - rep.start  # Zeitraum vor/zurueck blaettern
    prev_s, prev_e = rep.start - span, rep.start
    next_s, next_e = rep.end, rep.end + span
    return HTMLResponse(_tpls["dash"].render(
        **_common(request, "dash", "Dashboard"),
        week=week, project=proj, start_in=start_in, end_in=end_in,
        all_projects=_all_projects(),
        report_title=(proj or "alle Projekte"),
        period=f"{rep.start:%d.%m.%Y} – {rep.end:%d.%m.%Y}",
        report_html=render_html(rep), sessions=sessions,
        start_iso=rep.start.date().isoformat(), end_iso=rep.end.date().isoformat(),
        prev_start=prev_s.date().isoformat(), prev_end=prev_e.date().isoformat(),
        next_start=next_s.date().isoformat(), next_end=next_e.date().isoformat(),
        mail_configured=config.mail_configured(),
        has_project=stats["has_project"], has_direction=stats["has_direction"],
        events_total=stats["events_total"],
        intervals_paired=stats["intervals_paired"],
        projects_seen=rep.projects_seen))


@router.post("/send")
async def send_now(request: Request, project: str = Form(""),
                   start: str = Form(""), end: str = Form("")):
    if (r := _need_billing(request)):
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
    if (r := _need_timekeeper(request)):
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
    # Bearbeiter sehen auch Buchungen OHNE Projekt -> zuweisen/korrigieren
    intervals = filter_intervals(s, e, project=project, employee=employee,
                                 include_no_project=not project.strip())
    total_hours = sum(iv.duration_hours for iv in intervals)
    # Offene Sessions: nur aktuelle (alte = unvollstaendige Daten, kein echtes
    # "noch eingestempelt").
    opens = []
    cutoff = datetime.now(config.TIMEZONE) - timedelta(hours=config.OPEN_SESSION_MAX_HOURS)
    for o in collect_open():
        if o.start.astimezone(config.TIMEZONE) < cutoff:
            continue
        if employee and employee.lower() not in o.employee.lower():
            continue
        if project and (not o.project or project.lower() not in o.project.lower()):
            continue
        opens.append({"employee": o.employee, "project": o.project or "–",
                      "start": o.start.astimezone(config.TIMEZONE).strftime("%a %d.%m. %H:%M")})
    hidden = (sorted(manual.hidden_ids())
              if (_role(request) in ("admin", "buchhaltung")
                  or request.session.get("fix_times")) else [])
    return HTMLResponse(_tpls["log"].render(
        **_common(request, "log", "Log"),
        all_employees=_all_employees(), all_projects=_all_projects(),
        employee=employee, project=project, start_in=start, end_in=end,
        sessions=[_session_view(iv) for iv in intervals],
        open_sessions=opens, hidden=hidden, presets=_range_presets(),
        count=len(intervals), total=_fmt_dur(total_hours)))


def _parse_dt(date: str, t: str) -> datetime:
    return datetime.fromisoformat(f"{date}T{t}").replace(tzinfo=config.TIMEZONE)


def _find_interval(iid: str):
    for iv in collect_intervals():
        if iv.id == iid:
            return iv
    return None


def _find_interval_any(iid: str):
    """Wie _find_interval, aber inklusive Buchungen ohne Projekt."""
    for iv in collect_intervals(include_no_project=True):
        if iv.id == iid:
            return iv
    return None


@router.get("/log/edit", response_class=HTMLResponse)
async def log_edit(request: Request, iid: str = ""):
    if (r := _need_timekeeper(request)):
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
        iv = _find_interval_any(iid)
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
    if (r := _need_timekeeper(request)):
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
    if (r := _need_timekeeper(request)):
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
    if (r := _need_timekeeper(request)):
        return r
    manual.unhide(iid)
    audit.log(_user(request), "wieder eingeblendet", iid)
    request.session["flash"] = "Buchung wieder eingeblendet."
    return RedirectResponse("/log", status_code=303)


@router.post("/log/purge")
async def log_purge(request: Request, iid: str = Form("")):
    if (r := _need_timekeeper(request)):
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
    data = xlsxout.intervals_xlsx(
        filter_intervals(s, e, project=project, employee=employee),
        title="Buchungen")
    fname = f"buchungen_{datetime.now(config.TIMEZONE):%Y%m%d}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/log/describe")
async def log_describe(request: Request, iid: str = Form(""),
                       description: str = Form("")):
    if (r := _need_timekeeper(request)):
        return r
    activities.set_description(iid, description, _user(request))
    audit.log(_user(request), "Tätigkeit gesetzt", f"{iid}: {description[:80]}")
    return RedirectResponse(request.headers.get("referer") or "/log",
                            status_code=303)


@router.get("/export/amprion.csv")
async def export_amprion(request: Request, employee: str = "", project: str = "",
                         start: str = "", end: str = ""):
    """Amprion-Abgabe als CSV im vorgegebenen Format (nur Amprion-Projekte)."""
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
    data = csvout.amprion_csv(
        filter_intervals(s, e, project=project, employee=employee),
        task_map=settings.get_project_tasks())
    fname = f"amprion_abgabe_{datetime.now(config.TIMEZONE):%Y%m%d}.csv"
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
    admin_secs = []
    if _role(request) == "admin":
        webhook_url = f"{request.base_url}{config.WEBHOOK_PATH.lstrip('/')}"
        admin_secs = docs.admin_sections(webhook_url, config.SHARED_SECRET)
    return HTMLResponse(_tpls["anleitung"].render(
        **_common(request, "help", "Anleitung"),
        sections=docs.user_sections(config.ms_enabled()),
        admin_secs=admin_secs))


_TZ_ZONES = ["Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/Paris",
             "Europe/Amsterdam", "Europe/London", "Europe/Madrid", "UTC",
             "America/New_York", "Asia/Dubai"]


# --- Tickets ---------------------------------------------------------------

def _notify_ticket_assignee(request: Request, tid: int, assignee: str) -> None:
    u = users.get(assignee)
    if not u or not u.get("email"):
        return
    t = tickets.get(tid) or {}
    link = f"{config.PUBLIC_BASE_URL}/tickets/{tid}"
    title = t.get("title", "")
    subj = f"Ticket #{tid} wurde dir zugewiesen"
    text = (f"Hallo {u.get('name') or assignee},\n\ndir wurde Ticket #{tid} "
            f"„{title}“ zugewiesen.\n{link}\n")
    html = (f"<p>Hallo {escape(u.get('name') or assignee)},</p>"
            f"<p>dir wurde Ticket <b>#{tid}</b> „{escape(title)}“ zugewiesen.</p>"
            f'<p><a href="{link}" style="display:inline-block;'
            f'background:{config.BRAND_COLOR};color:#123018;font-weight:bold;'
            'text-decoration:none;padding:11px 22px;border-radius:999px">'
            "Ticket öffnen</a></p>")
    mailer.send(subj, text, html, [u["email"]], label="Ticket-Zuweisung",
                actor=_user(request))


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_list(request: Request, status: str = "", q: str = ""):
    if (r := _need_tickets(request)):
        return r
    rows = tickets.list_tickets(status=status, q=q)
    for t in rows:
        t["created_disp"] = _disp(t.get("created_at", ""))
    return HTMLResponse(_tpls["tickets"].render(
        **_common(request, "tickets", "Tickets"), rows=rows, status=status, q=q,
        statuses=tickets.STATUSES, priorities=tickets.PRIORITIES,
        categories=tickets.CATEGORIES, counts=tickets.counts_by_status()))


@router.get("/tickets/new", response_class=HTMLResponse)
async def ticket_new_form(request: Request):
    if (r := _need_tickets(request)):
        return r
    return HTMLResponse(_tpls["ticket_new"].render(
        **_common(request, "tickets", "Neues Ticket"),
        priorities=tickets.PRIORITIES, categories=tickets.CATEGORIES))


@router.post("/tickets/new")
async def ticket_new(request: Request, title: str = Form(""),
                     description: str = Form(""), priority: str = Form("medium"),
                     category: str = Form("other")):
    if (r := _need_tickets(request)):
        return r
    t = tickets.create(title, description, priority, category, _user(request))
    audit.log(_user(request), "Ticket erstellt", f"#{t['id']} {t['title']}")
    return RedirectResponse(f"/tickets/{t['id']}", status_code=303)


@router.get("/tickets/{tid:int}", response_class=HTMLResponse)
async def ticket_detail(request: Request, tid: int):
    if (r := _need_tickets(request)):
        return r
    t = tickets.get(tid)
    if not t:
        return RedirectResponse("/tickets", status_code=303)
    t = dict(t)
    t["created_disp"] = _disp(t.get("created_at", ""))
    t["updated_disp"] = _disp(t.get("updated_at", ""))
    t["comments"] = [dict(c, at_disp=_disp(c.get("at", ""))) for c in t["comments"]]
    t["history"] = [dict(h, at_disp=_disp(h.get("at", "")))
                    for h in t.get("history", [])]
    wl_hours = round(sum(_to_float(w.get("hours")) for w in t["worklogs"]), 2)
    wl_km = round(sum(_to_float(w.get("travel_km")) for w in t["worklogs"]), 1)
    assignees = [u["username"] for u in users.list_users()
                 if u.get("role") == "admin" or u.get("can_view_tickets")
                 or u.get("can_edit_tickets")]
    return HTMLResponse(_tpls["ticket"].render(
        **_common(request, "tickets", f"Ticket #{tid}"), t=t,
        can_edit=_tk_edit(request), assignees=assignees,
        statuses=tickets.STATUSES, priorities=tickets.PRIORITIES,
        categories=tickets.CATEGORIES, wl_hours=wl_hours, wl_km=wl_km,
        today=datetime.now(config.TIMEZONE).date().isoformat()))


@router.post("/tickets/{tid:int}/edit")
async def ticket_edit(request: Request, tid: int, status: str = Form(""),
                      priority: str = Form(""), category: str = Form(""),
                      assigned_to: str = Form("")):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    old = tickets.get(tid) or {}
    tickets.update_fields(tid, status=status, priority=priority,
                          category=category, assigned_to=assigned_to)
    audit.log(_user(request), "Ticket geändert", f"#{tid} -> {status}")
    who = request.session.get("name") or _user(request)
    chg = []
    if status and status != old.get("status"):
        chg.append(f"Status → {tickets.STATUSES.get(status, status)}")
    if priority and priority != old.get("priority"):
        chg.append(f"Priorität → {tickets.PRIORITIES.get(priority, priority)}")
    if category and category != old.get("category"):
        chg.append(f"Kategorie → {tickets.CATEGORIES.get(category, category)}")
    if assigned_to != old.get("assigned_to"):
        chg.append("Bearbeiter → " + (assigned_to or "—"))
    if chg:
        tickets.log_event(tid, who, "; ".join(chg))
    if (assigned_to and assigned_to != old.get("assigned_to")
            and assigned_to != _user(request)):
        _notify_ticket_assignee(request, tid, assigned_to)
    if status == "closed":
        n = tickets.purge_attachments(tid)
        if n:
            audit.log(_user(request), "Anhänge gelöscht",
                      f"#{tid}: {n} Datei(en) (Ticket geschlossen)")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/status")
async def ticket_status(request: Request, tid: int, status: str = Form("")):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    tickets.update_fields(tid, status=status)
    audit.log(_user(request), "Ticket-Status", f"#{tid} -> {status}")
    tickets.log_event(tid, request.session.get("name") or _user(request),
                      f"Status → {tickets.STATUSES.get(status, status)}")
    if status == "closed":
        n = tickets.purge_attachments(tid)
        if n:
            audit.log(_user(request), "Anhänge gelöscht",
                      f"#{tid}: {n} Datei(en) (Ticket geschlossen)")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/assign-me")
async def ticket_assign_me(request: Request, tid: int):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    tickets.update_fields(tid, assigned_to=_user(request))
    who = request.session.get("name") or _user(request)
    audit.log(_user(request), "Ticket zugewiesen", f"#{tid} -> {_user(request)}")
    tickets.log_event(tid, who, "hat sich selbst als Bearbeiter eingetragen")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/comment")
async def ticket_comment(request: Request, tid: int, body: str = Form("")):
    if (r := _need_tickets(request)):
        return r
    if tickets.add_comment(tid, _user(request), body):
        tickets.log_event(tid, request.session.get("name") or _user(request),
                          "Kommentar hinzugefügt")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/worklog")
async def ticket_worklog(request: Request, tid: int, date: str = Form(""),
                         travel_km: str = Form("0"), hours: str = Form("0"),
                         material: str = Form(""), description: str = Form("")):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    km, hrs = _to_float(travel_km), _to_float(hours)
    tickets.add_worklog(tid, _user(request), date, km, hrs, material, description)
    detail = f"Aufwand erfasst: {hrs} Std, {km} km"
    if material.strip():
        detail += f", Material: {material.strip()[:40]}"
    tickets.log_event(tid, request.session.get("name") or _user(request), detail)
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/worklog/{wid}/delete")
async def ticket_worklog_delete(request: Request, tid: int, wid: str):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    t = tickets.get(tid) or {}
    w = next((x for x in t.get("worklogs", []) if x.get("id") == wid), None)
    tickets.delete_worklog(tid, wid)
    if w:
        tickets.log_event(tid, request.session.get("name") or _user(request),
                          f"Aufwand gelöscht: {w.get('hours')} Std, "
                          f"{w.get('travel_km')} km")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/close")
async def ticket_close(request: Request, tid: int, message: str = Form("")):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    t = tickets.get(tid)
    if not t:
        return RedirectResponse("/tickets", status_code=303)
    sol = message.strip()
    tickets.update_fields(tid, status="closed")
    who = request.session.get("name") or _user(request)
    tickets.log_event(tid, who, "Ticket geschlossen" + (f": {sol}" if sol else ""))
    audit.log(_user(request), "Ticket geschlossen", f"#{tid}")
    creator = users.get(t.get("created_by"))
    notified = False
    if creator and creator.get("email"):
        link = f"{config.PUBLIC_BASE_URL}/tickets/{tid}"
        title = t.get("title", "")
        body = sol or "Das Ticket wurde geschlossen."
        subj = f"Ticket #{tid} geschlossen: {title}"
        text = (f"Hallo {creator.get('name') or t['created_by']},\n\ndein Ticket "
                f"#{tid} „{title}“ wurde geschlossen.\n\nAbschluss / Lösung:\n"
                f"{body}\n\n{link}\n")
        html = (f"<p>Hallo {escape(creator.get('name') or t['created_by'])},</p>"
                f"<p>dein Ticket <b>#{tid}</b> „{escape(title)}“ wurde "
                "<b>geschlossen</b>.</p><p><b>Abschluss / Lösung:</b><br>"
                f"{escape(body).replace(chr(10), '<br>')}</p>"
                f'<p><a href="{link}" style="display:inline-block;'
                f'background:{config.BRAND_COLOR};color:#123018;font-weight:bold;'
                'text-decoration:none;padding:11px 22px;border-radius:999px">'
                "Ticket ansehen</a></p>")
        res = mailer.send(subj, text, html, [creator["email"]],
                          label="Ticket geschlossen", actor=_user(request))
        notified = bool(res.get("mailed"))
    tickets.purge_attachments(tid)
    request.session["flash"] = (f"Ticket #{tid} geschlossen"
                                + (" – Ersteller benachrichtigt." if notified
                                   else " (Ersteller hat keine E-Mail)."))
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.post("/tickets/{tid:int}/delete")
async def ticket_delete(request: Request, tid: int):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    tickets.delete(tid)
    audit.log(_user(request), "Ticket gelöscht", f"#{tid}")
    request.session["flash"] = f"Ticket #{tid} gelöscht."
    return RedirectResponse("/tickets", status_code=303)


@router.post("/tickets/{tid:int}/attach")
async def ticket_attach(request: Request, tid: int, file: UploadFile = File(...)):
    if (r := _need_tickets(request)):
        return r
    if not tickets.get(tid):
        return RedirectResponse("/tickets", status_code=303)
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        request.session["flash"], request.session["flash_class"] = \
            "Datei zu groß (max. 20 MB).", "err"
        return RedirectResponse(f"/tickets/{tid}", status_code=303)
    safe = "".join(ch for ch in (file.filename or "datei")
                   if ch.isalnum() or ch in "._- ").strip() or "datei"
    from pathlib import Path
    d = config.TICKET_FILES_DIR / str(tid)
    d.mkdir(parents=True, exist_ok=True)
    stored = d / f"{secrets.token_hex(8)}_{safe}"
    stored.write_bytes(content)
    tickets.add_attachment(tid, safe, str(stored), _user(request))
    audit.log(_user(request), "Ticket-Anhang", f"#{tid}: {safe}")
    tickets.log_event(tid, request.session.get("name") or _user(request),
                      f"Anhang hochgeladen: {safe}")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.get("/tickets/{tid:int}/attachment/{att_id}")
async def ticket_attachment(request: Request, tid: int, att_id: str):
    if (r := _need_tickets(request)):
        return r
    a = tickets.find_attachment(tid, att_id)
    from pathlib import Path
    if not a or not Path(a["stored"]).exists():
        return HTMLResponse("Anhang nicht gefunden.", status_code=404)
    return FileResponse(a["stored"], filename=a.get("filename", "datei"))


@router.post("/tickets/{tid:int}/attachment/{att_id}/delete")
async def ticket_attachment_delete(request: Request, tid: int, att_id: str):
    if (r := _need_tickets(request)):
        return r
    if not _tk_edit(request):
        return HTMLResponse("Keine Bearbeitungsrechte.", status_code=403)
    a = tickets.delete_attachment(tid, att_id)
    if a:
        from pathlib import Path
        try:
            Path(a["stored"]).unlink(missing_ok=True)
        except Exception:
            pass
        tickets.log_event(tid, request.session.get("name") or _user(request),
                          f"Anhang gelöscht: {a.get('filename', '')}")
    return RedirectResponse(f"/tickets/{tid}", status_code=303)


@router.get("/einstellungen", response_class=HTMLResponse)
async def settings_page(request: Request):
    if (r := _need_admin(request)):
        return r
    tz = settings.get_timezone()
    zones = _TZ_ZONES if tz in _TZ_ZONES else [tz, *_TZ_ZONES]
    now = datetime.now(config.TIMEZONE).strftime("%A, %d.%m.%Y %H:%M:%S (%Z)")
    u = users.get(_user(request)) or {}
    admin_email = u.get("email") or (config.REPORT_RECIPIENTS[0]
                                     if config.REPORT_RECIPIENTS else "")
    return HTMLResponse(_tpls["settings"].render(
        **_common(request, "settings", "Einstellungen"),
        zones=zones, tz=tz, now=now, admin_email=admin_email,
        mail_configured=bool(config.BREVO_API_KEY or config.SMTP_HOST)))


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


@router.get("/einstellungen/texte", response_class=HTMLResponse)
async def texts_page(request: Request):
    if (r := _need_admin(request)):
        return r
    vals = settings.get_texts()
    fields = [{"key": k, "label": lbl, "multiline": ml, "value": vals.get(k, "")}
              for k, _d, lbl, ml in settings.TEXT_FIELDS]
    return HTMLResponse(_tpls["texts"].render(
        **_common(request, "settings", "Texte"), fields=fields))


@router.post("/einstellungen/texte")
async def texts_save(request: Request):
    if (r := _need_admin(request)):
        return r
    form = await request.form()
    values = {k: str(form.get(k, "")) for k, _d, _lbl, _ml in settings.TEXT_FIELDS}
    settings.set_texts(values)
    audit.log(_user(request), "Texte geändert", ", ".join(
        k for k in values if values[k].strip()))
    request.session["flash"] = "Texte gespeichert."
    return RedirectResponse("/einstellungen/texte", status_code=303)


@router.post("/einstellungen/texte/reset")
async def texts_reset(request: Request):
    if (r := _need_admin(request)):
        return r
    settings.reset_texts()
    audit.log(_user(request), "Texte zurückgesetzt", "Standard")
    request.session["flash"] = "Texte auf Standard zurückgesetzt."
    return RedirectResponse("/einstellungen/texte", status_code=303)


@router.get("/einstellungen/projekte", response_class=HTMLResponse)
async def projects_page(request: Request):
    if (r := _need_admin(request)):
        return r
    overrides = settings.get_project_tasks()
    projects = sorted(set(_all_projects()) | set(overrides.keys()),
                      key=lambda p: p.lower())
    rows = [{"project": p,
             "detected": csvout.resolve_task(p),  # ohne Override -> Auto-Erkennung
             "value": overrides.get(p, "")}
            for p in projects]
    return HTMLResponse(_tpls["projects"].render(
        **_common(request, "settings", "Projekte"), rows=rows))


@router.post("/einstellungen/projekte")
async def projects_save(request: Request):
    if (r := _need_admin(request)):
        return r
    form = await request.form()
    projs = form.getlist("proj")
    nrs = form.getlist("nr")
    pairs = {p: n for p, n in zip(projs, nrs)}
    settings.set_project_tasks(pairs)
    audit.log(_user(request), "Projekt-Task-Nrn. gespeichert",
              ", ".join(f"{p}={n}" for p, n in pairs.items() if n.strip())[:200])
    request.session["flash"] = "Projekt-Zuordnungen gespeichert."
    return RedirectResponse("/einstellungen/projekte", status_code=303)


def _my_timemoto(request: Request) -> tuple[str, bool]:
    """Effektiver TimeMoto-Name des angemeldeten Nutzers.
    Rückgabe: (Name, zugeordnet?). Ist kein TimeMoto-Name gepflegt, wird der
    Anzeigename als Fallback genutzt (passt bei Microsoft-Konten meist)."""
    u = users.get(_user(request)) or {}
    tm = (u.get("timemoto_name") or "").strip()
    if tm:
        return tm, True
    return (request.session.get("name") or _user(request) or "").strip(), False




# --- Dokument-Bereiche (ISO 9001, KI-Schulungen) -----------------------------

_AREAS = {
    "iso": {"slug": "iso", "url": "/bereich/iso", "page": "area-iso",
            "title": "ISO 9001 (FiFB)",
            "desc": "Interne Prozesse, Verfahrensanweisungen und "
                    "QM-Dokumente – zum Ansehen und Herunterladen."},
    "ki-schulungen": {"slug": "ki-schulungen", "url": "/bereich/ki-schulungen",
                      "page": "area-ki-schulungen", "title": "KI-Schulungen",
                      "desc": "Schulungsunterlagen, Anleitungen und Videos "
                              "rund um den Einsatz von KI bei FBE."},
}


def _fmt_size(n: int) -> str:
    n = int(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n/1:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _doc_view(d: dict) -> dict:
    d = dict(d)
    d["size_disp"] = _fmt_size(d.get("size", 0))
    d["at_disp"] = _disp(d.get("at", ""))[:10]
    d["ext"] = (Path(d.get("filename", "")).suffix or "").lstrip(".").upper() or "–"
    return d


@router.get("/bereich/{slug}", response_class=HTMLResponse)
async def area_page(request: Request, slug: str, cat: str = ""):
    if (r := _need_login(request)):
        return r
    area = _AREAS.get(slug)
    if not area:
        return RedirectResponse("/start", status_code=303)
    docs_list = [_doc_view(d) for d in docfiles.list_docs(slug, category=cat)]
    return HTMLResponse(_tpls["area"].render(
        **_common(request, area["page"], area["title"]), area=area,
        docs=docs_list, cats=docfiles.categories(slug), cat=cat))


@router.post("/bereich/{slug}/upload")
async def area_upload(request: Request, slug: str, title: str = Form(""),
                      category: str = Form(""), file: UploadFile = File(...)):
    if (r := _need_admin(request)):
        return r
    area = _AREAS.get(slug)
    if not area:
        return RedirectResponse("/start", status_code=303)
    safe = docfiles.safe_name(file.filename or "datei")
    target_dir = config.DOC_FILES_DIR / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / f"{secrets.token_hex(6)}_{safe}"
    with stored.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    doc = docfiles.add(slug, title, category, safe, str(stored),
                       stored.stat().st_size, _user(request))
    audit.log(_user(request), "Dokument hochgeladen",
              f"{area['title']}: {doc['title']} ({safe})")
    request.session["flash"] = f"„{doc['title']}“ hochgeladen."
    return RedirectResponse(area["url"], status_code=303)


@router.get("/bereich/{slug}/{did}", response_class=HTMLResponse)
async def area_view(request: Request, slug: str, did: str):
    if (r := _need_login(request)):
        return r
    area = _AREAS.get(slug)
    d = docfiles.get(did)
    if not area or not d or d.get("area") != slug:
        return RedirectResponse(area["url"] if area else "/start",
                                status_code=303)
    return HTMLResponse(_tpls["area_view"].render(
        **_common(request, area["page"], d["title"]), area=area,
        d=_doc_view(d), kind=docfiles.viewer_kind(d.get("mime", "")),
        file_url=f"{area['url']}/{did}/file"))


@router.get("/bereich/{slug}/{did}/file")
async def area_file(request: Request, slug: str, did: str, download: int = 0):
    if (r := _need_login(request)):
        return r
    d = docfiles.get(did)
    if not d or d.get("area") != slug or not Path(d["stored"]).exists():
        return HTMLResponse("Datei nicht gefunden.", status_code=404)
    return FileResponse(
        d["stored"], media_type=d.get("mime") or "application/octet-stream",
        filename=d.get("filename", "datei"),
        content_disposition_type="attachment" if download else "inline")


@router.post("/bereich/{slug}/{did}/delete")
async def area_delete(request: Request, slug: str, did: str):
    if (r := _need_admin(request)):
        return r
    area = _AREAS.get(slug)
    removed = docfiles.delete(did)
    if area and removed:
        audit.log(_user(request), "Dokument gelöscht",
                  f"{area['title']}: {removed.get('title')}")
        request.session["flash"] = "Dokument gelöscht."
    return RedirectResponse(area["url"] if area else "/start", status_code=303)




# --- Digitale Visitenkarten --------------------------------------------------

@router.get("/einstellungen/visitenkarten", response_class=HTMLResponse)
async def vcards_page(request: Request):
    if (r := _need_admin(request)):
        return r
    cards = [dict(c, url=vcards.public_url(c)) for c in vcards.list_cards()]
    names = [u.get("name") or u["username"] for u in users.list_users()]
    return HTMLResponse(_tpls["vcards"].render(
        **_common(request, "settings", "Visitenkarten"),
        cards=cards, names=sorted(set(names), key=str.lower)))


@router.post("/einstellungen/visitenkarten")
async def vcards_create(request: Request, name: str = Form("")):
    if (r := _need_admin(request)):
        return r
    if not name.strip():
        return RedirectResponse("/einstellungen/visitenkarten", status_code=303)
    c = vcards.add(name)
    audit.log(_user(request), "Visitenkarte angelegt", c["name"])
    return RedirectResponse(f"/einstellungen/visitenkarten/{c['id']}",
                            status_code=303)


@router.get("/einstellungen/visitenkarten/{cid}", response_class=HTMLResponse)
async def vcard_edit(request: Request, cid: str):
    if (r := _need_admin(request)):
        return r
    c = vcards.get(cid)
    if not c:
        return RedirectResponse("/einstellungen/visitenkarten", status_code=303)
    url = vcards.public_url(c)
    qr = segno.make(url).svg_data_uri(scale=5) if c.get("enabled") else ""
    return HTMLResponse(_tpls["vcard_edit"].render(
        **_common(request, "settings", "Visitenkarte"),
        c=c, fields=vcards.FIELDS, url=url, qr=qr,
        base_url=config.PUBLIC_BASE_URL))


@router.post("/einstellungen/visitenkarten/{cid}")
async def vcard_save(request: Request, cid: str):
    if (r := _need_admin(request)):
        return r
    c = vcards.get(cid)
    if not c:
        return RedirectResponse("/einstellungen/visitenkarten", status_code=303)
    form = await request.form()
    values = {k: str(form.get(k, "") or "").strip()
              for k, _l, _p in vcards.FIELDS}
    slug = str(form.get("slug", "") or "").strip().lower()
    if not vcards.valid_slug(slug):
        request.session["flash"], request.session["flash_class"] = \
            "Ungültige URL-Kennung (nur a-z, 0-9, Bindestriche).", "err"
        return RedirectResponse(f"/einstellungen/visitenkarten/{cid}",
                                status_code=303)
    if vcards.slug_taken(slug, except_id=cid):
        request.session["flash"], request.session["flash_class"] = \
            "Diese URL-Kennung ist bereits vergeben.", "err"
        return RedirectResponse(f"/einstellungen/visitenkarten/{cid}",
                                status_code=303)
    values["slug"] = slug
    values["enabled"] = form.get("enabled") == "1"
    photo = form.get("photo")
    if photo is not None and getattr(photo, "filename", ""):
        ext = Path(photo.filename).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            request.session["flash"], request.session["flash_class"] = \
                "Foto bitte als JPG, PNG oder WebP hochladen.", "err"
            return RedirectResponse(f"/einstellungen/visitenkarten/{cid}",
                                    status_code=303)
        config.VCARD_FILES_DIR.mkdir(parents=True, exist_ok=True)
        stored = config.VCARD_FILES_DIR / f"{cid}{ext}"
        with stored.open("wb") as out:
            shutil.copyfileobj(photo.file, out)
        if c.get("photo") and c["photo"] != str(stored):
            Path(c["photo"]).unlink(missing_ok=True)
        values["photo"] = str(stored)
    vcards.update(cid, values)
    audit.log(_user(request), "Visitenkarte gespeichert",
              f"{values.get('name') or c['name']} (/v/{slug}, "
              f"{'aktiv' if values['enabled'] else 'aus'})")
    request.session["flash"] = "Visitenkarte gespeichert."
    return RedirectResponse(f"/einstellungen/visitenkarten/{cid}",
                            status_code=303)


@router.post("/einstellungen/visitenkarten/{cid}/delete")
async def vcard_delete(request: Request, cid: str):
    if (r := _need_admin(request)):
        return r
    removed = vcards.delete(cid)
    if removed:
        audit.log(_user(request), "Visitenkarte gelöscht",
                  removed.get("name", ""))
        request.session["flash"] = "Visitenkarte gelöscht."
    return RedirectResponse("/einstellungen/visitenkarten", status_code=303)


# Oeffentliche Karten-Routen: KEIN Login, aber strikt auf die Karte begrenzt.
# Es werden ausschliesslich die vom Admin gepflegten Kartendaten ausgeliefert.

_PUB_HEADERS = {"X-Robots-Tag": "noindex, nofollow",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff"}


@router.get("/v/{slug}", response_class=HTMLResponse)
async def vcard_public(slug: str):
    c = vcards.by_slug(slug)
    if not c:
        return HTMLResponse("Nicht gefunden.", status_code=404,
                            headers=_PUB_HEADERS)
    nm = (c.get("name") or "?").split()
    initials = "".join(w[0] for w in nm[:2]).upper() or "?"
    html = _VCARD_PUB.render(
        c=c, has_photo=bool(c.get("photo") and Path(c["photo"]).exists()),
        initials=initials, bg=config.LOGIN_BG_IMAGE,
        year=datetime.now(config.TIMEZONE).year)
    return HTMLResponse(html, headers=_PUB_HEADERS)


@router.get("/v/{slug}/foto")
async def vcard_public_photo(slug: str):
    c = vcards.by_slug(slug)
    if not c or not c.get("photo") or not Path(c["photo"]).exists():
        return HTMLResponse("Nicht gefunden.", status_code=404,
                            headers=_PUB_HEADERS)
    return FileResponse(c["photo"], headers=_PUB_HEADERS,
                        content_disposition_type="inline")


@router.get("/v/{slug}/kontakt.vcf")
async def vcard_public_vcf(slug: str):
    c = vcards.by_slug(slug)
    if not c:
        return HTMLResponse("Nicht gefunden.", status_code=404,
                            headers=_PUB_HEADERS)
    fname = f"{(c.get('name') or 'kontakt').replace(' ', '_')}.vcf"
    return Response(vcards.build_vcf(c),
                    media_type="text/vcard; charset=utf-8",
                    headers={**_PUB_HEADERS,
                             "Content-Disposition":
                             f'attachment; filename="{fname}"'})


@router.get("/meine-zeiten", response_class=HTMLResponse)
async def meine_zeiten(request: Request):
    if (r := _need_login(request)):
        return r
    from datetime import timedelta
    tm, assigned = _my_timemoto(request)
    days = 60
    sessions, opens = [], []
    if tm:
        start = datetime.now(config.TIMEZONE) - timedelta(days=days)
        ivs = filter_intervals(start, None, employee=tm)
        sessions = [_session_view(iv) for iv in ivs]
        # Laufende (offene) Buchungen – nur aktuelle, wie im Log
        cutoff = datetime.now(config.TIMEZONE) - timedelta(
            hours=config.OPEN_SESSION_MAX_HOURS)
        for o in collect_open(include_no_project=True):
            if o.start.astimezone(config.TIMEZONE) < cutoff:
                continue
            if tm.lower() not in (o.employee or "").lower():
                continue
            opens.append({"project": o.project or "ohne Projekt",
                          "start": o.start.astimezone(config.TIMEZONE)
                          .strftime("%a %d.%m. %H:%M")})
    ws, we = this_week_range()
    week_h = _fmt_dur(sum(
        max(iv.duration_hours, 0.0)
        for iv in filter_intervals(ws, we, employee=tm))) if tm else "0:00 h"
    miss_desc = sum(1 for s in sessions if not (s.get("description") or "").strip())
    return HTMLResponse(_tpls["meine"].render(
        **_common(request, "meine", "Meine Zeiten"), tm=tm, assigned=assigned,
        sessions=sessions, open_sessions=opens,
        week_h=week_h, miss_desc=miss_desc, days=days))


@router.post("/meine-zeiten/describe")
async def meine_describe(request: Request, iid: str = Form(""),
                         description: str = Form("")):
    if (r := _need_login(request)):
        return r
    tm, _assigned = _my_timemoto(request)
    tm = tm.lower()
    iv = _find_interval(iid)
    if not tm or not iv or (iv.employee or "").lower() != tm:
        return HTMLResponse("Kein Zugriff auf diese Buchung.", status_code=403)
    activities.set_description(iid, description, _user(request))
    audit.log(_user(request), "Tätigkeit (eigene)", f"{iid}: {description[:80]}")
    request.session["flash"] = ("Tätigkeit gespeichert." if description.strip()
                                else "Tätigkeit entfernt.")
    return RedirectResponse("/meine-zeiten", status_code=303)


def _own_interval(request: Request, iid: str):
    """Eigene Buchung (auch ohne Projekt) holen -- None wenn fremd/unbekannt."""
    tm, _assigned = _my_timemoto(request)
    if not tm:
        return None
    iv = _find_interval_any(iid)
    if not iv or (iv.employee or "").lower() != tm.lower():
        return None
    return iv


@router.get("/meine-zeiten/neu", response_class=HTMLResponse)
async def meine_new(request: Request, iid: str = ""):
    if (r := _need_login(request)):
        return r
    tm, _assigned = _my_timemoto(request)
    now = datetime.now(config.TIMEZONE)
    f = {"project": "", "date": now.strftime("%Y-%m-%d"),
         "start_time": "08:00", "end_time": "17:00", "description": ""}
    heading, mode = "Buchung nachtragen", "new"
    if iid:
        iv = _own_interval(request, iid)
        if not iv:
            request.session["flash"], request.session["flash_class"] = \
                "Buchung nicht gefunden oder gehört nicht zu dir.", "err"
            return RedirectResponse("/meine-zeiten", status_code=303)
        st = iv.start.astimezone(config.TIMEZONE)
        en = iv.end.astimezone(config.TIMEZONE)
        f = {"project": iv.project or "", "date": st.strftime("%Y-%m-%d"),
             "start_time": st.strftime("%H:%M"), "end_time": en.strftime("%H:%M"),
             "description": iv.description or ""}
        if not (iv.project or "").strip():
            heading, mode = "Projekt zuweisen", "assign"
        elif iv.source == "manual":
            heading, mode = "Buchung bearbeiten", "edit"
        else:
            heading, mode = "Buchung korrigieren", "correct"
    return HTMLResponse(_tpls["my_form"].render(
        **_common(request, "meine", heading), heading=heading, mode=mode,
        iid=iid, f=f, tm=tm, all_projects=_all_projects()))


@router.post("/meine-zeiten/save")
async def meine_save(request: Request, iid: str = Form(""),
                     project: str = Form(""), date: str = Form(""),
                     start_time: str = Form(""), end_time: str = Form(""),
                     description: str = Form("")):
    if (r := _need_login(request)):
        return r
    tm, _assigned = _my_timemoto(request)
    user = _user(request)
    project = project.strip()
    if not tm:
        request.session["flash"], request.session["flash_class"] = \
            "Deinem Konto ist kein Name zugeordnet.", "err"
        return RedirectResponse("/meine-zeiten", status_code=303)
    if not project:
        request.session["flash"], request.session["flash_class"] = \
            "Bitte ein Projekt angeben.", "err"
        return RedirectResponse(f"/meine-zeiten/neu?iid={iid}", status_code=303)
    try:
        start_dt = _parse_dt(date, start_time)
        end_dt = _parse_dt(date, end_time)
        if end_dt <= start_dt:
            raise ValueError("Geht muss nach Kommt liegen.")
    except ValueError as exc:
        request.session["flash"], request.session["flash_class"] = \
            f"Ungültige Zeit: {exc}", "err"
        return RedirectResponse(f"/meine-zeiten/neu?iid={iid}", status_code=303)

    data = {"employee": tm, "project": project,
            "start": start_dt.isoformat(), "end": end_dt.isoformat(),
            "note": "selbst erfasst"}
    label = f"{tm} / {project} {date} {start_time}-{end_time}"
    if iid.startswith("man:"):
        e = manual.get_entry(iid[4:])
        if not e or (e.get("employee") or "").lower() != tm.lower():
            return HTMLResponse("Kein Zugriff auf diese Buchung.", status_code=403)
        manual.update_entry(iid[4:], data)
        target = iid
        audit.log(user, "Buchung bearbeitet (selbst)", label)
        request.session["flash"] = "Buchung gespeichert."
    elif iid.startswith("wh:"):
        iv = _own_interval(request, iid)
        if not iv:
            return HTMLResponse("Kein Zugriff auf diese Buchung.", status_code=403)
        data["replaces"] = iid
        e = manual.add_entry(data, user)
        manual.hide(iid)
        target = f"man:{e['id']}"
        audit.log(user, "Buchung korrigiert (selbst)", f"{label} (ersetzt {iid})")
        request.session["flash"] = ("Projekt zugewiesen."
                                    if not (iv.project or "").strip()
                                    else "Korrektur gespeichert.")
    else:
        e = manual.add_entry(data, user)
        target = f"man:{e['id']}"
        audit.log(user, "Buchung nachgetragen (selbst)", label)
        request.session["flash"] = "Buchung nachgetragen."
    if description.strip():
        activities.set_description(target, description.strip(), user)
    return RedirectResponse("/meine-zeiten", status_code=303)


@router.post("/meine-zeiten/delete")
async def meine_delete(request: Request, iid: str = Form("")):
    if (r := _need_login(request)):
        return r
    tm, _assigned = _my_timemoto(request)
    if not iid.startswith("man:"):
        return HTMLResponse("Nur selbst erfasste Buchungen löschbar.",
                            status_code=403)
    e = manual.get_entry(iid[4:])
    if not e or not tm or (e.get("employee") or "").lower() != tm.lower():
        return HTMLResponse("Kein Zugriff auf diese Buchung.", status_code=403)
    manual.delete_entry(iid[4:])
    audit.log(_user(request), "Buchung gelöscht (selbst)",
              f"{e.get('employee')} / {e.get('project')} {e.get('start')}")
    request.session["flash"] = "Buchung gelöscht."
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
        presets=_range_presets(),
        count=len(ivs), total=_fmt_dur(total)))


@router.post("/einstellungen/testmail")
async def settings_testmail(request: Request, email: str = Form("")):
    if (r := _need_admin(request)):
        return r
    to = (email or "").strip()
    if not to:
        request.session["flash"], request.session["flash_class"] = \
            "Bitte eine Empfänger-Adresse angeben.", "err"
        return RedirectResponse("/einstellungen", status_code=303)
    report_html = (
        "<h2>Beispiel-Projektbericht</h2>"
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse'><thead><tr style='background:#eef5e9'>"
        "<th align='left'>Mitarbeiter</th><th>Stunden</th><th>Sessions</th></tr></thead>"
        "<tbody><tr><td>Max Mustermann</td><td style='text-align:right'>8:30 h</td>"
        "<td style='text-align:right'>1</td></tr></tbody></table>")
    r1 = mailer.send("Testmail: Projektbericht", "Beispiel-Projektbericht.",
                     report_html, [to], label="Testmail",
                     message="Dies ist eine Test-E-Mail (Bericht-Design).",
                     actor=_user(request))
    rem_html = ("<p>Hallo Max,</p><p>für deine Buchung am <b>06.06.2026</b> "
                "(26344 - Arcadis, 8:30 h) fehlt noch die "
                "<b>Tätigkeitsbeschreibung</b>. Bitte kurz nachtragen.</p>")
    mailer.send("Testmail: Erinnerung Tätigkeitsbeschreibung",
                "Beispiel-Erinnerung.", rem_html, [to], label="Testmail",
                message="Dies ist eine Test-E-Mail (Erinnerung-Design).",
                actor=_user(request))
    if r1.get("mailed"):
        request.session["flash"] = f"2 Testmails an {to} gesendet."
    else:
        request.session["flash"], request.session["flash_class"] = (
            f"Nicht versendet ({r1.get('reason')}) – als Datei gespeichert.", "err")
    return RedirectResponse("/einstellungen", status_code=303)


@router.post("/einstellungen/reminders-now")
async def settings_reminders_now(request: Request):
    if (r := _need_admin(request)):
        return r
    res = scheduler.run_reminders()
    n = res.get("sent", 0)
    request.session["flash"] = (
        f"{n} Erinnerung(en) versendet." if n else
        "Keine offenen Buchungen ohne Tätigkeit im Zeitfenster (24 h–7 Tage).")
    return RedirectResponse("/einstellungen", status_code=303)


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
        current_name=u.get("name") or _user(request),
        twofa=u.get("twofa_enabled", False)))


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
        userlist=users.list_users(), base_url=str(request.base_url),
        ms_enabled=config.ms_enabled(),
        local_users_enabled=config.LOCAL_USERS_ENABLED))


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


@router.post("/users/import-microsoft")
async def users_import_ms(request: Request):
    if (r := _need_admin(request)):
        return r
    if not config.ms_enabled():
        request.session["flash"], request.session["flash_class"] = \
            "Microsoft ist nicht konfiguriert.", "err"
        return RedirectResponse("/users", status_code=303)
    entries, err = msauth.list_tenant_users()
    if err and not entries:
        request.session["flash"], request.session["flash_class"] = \
            f"Import fehlgeschlagen (Berechtigung User.Read.All + Admin-Consent?): {err}", "err"
        return RedirectResponse("/users", status_code=303)
    created, total = users.import_microsoft(entries)
    audit.log(_user(request), "Microsoft-Import", f"{created} neu / {total} gesamt")
    msg = f"{total} Tenant-Nutzer geprüft, {created} neu angelegt."
    if err:
        msg += f" (teilweiser Abruf: {err})"
    request.session["flash"] = msg
    return RedirectResponse("/users", status_code=303)


@router.post("/users/create")
async def users_create(request: Request, username: str = Form(""),
                       role: str = Form("user"), name: str = Form(""),
                       email: str = Form(""), timemoto_name: str = Form(""),
                       ticket_access: str = Form("none"),
                       fix_times: str = Form("no")):
    if (r := _need_admin(request)):
        return r
    token = users.create_invite(
        username, role, name, email, timemoto_name,
        can_view_tickets=ticket_access in ("view", "edit"),
        can_edit_tickets=ticket_access == "edit")
    if token is not None and fix_times == "yes":
        users.set_profile(username, name, email, timemoto_name,
                          can_fix_times=True)
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


@router.get("/users/{username}/edit", response_class=HTMLResponse)
async def users_edit_form(request: Request, username: str):
    if (r := _need_admin(request)):
        return r
    u = users.get(username)
    if not u:
        return RedirectResponse("/users", status_code=303)
    return HTMLResponse(_tpls["user_edit"].render(
        **_common(request, "users", "Benutzer bearbeiten"),
        u=u, all_employees=_all_employees()))


@router.post("/users/{username}/edit")
async def users_edit_save(request: Request, username: str,
                          new_username: str = Form(""), name: str = Form(""),
                          email: str = Form(""), timemoto_name: str = Form(""),
                          role: str = Form("user"),
                          ticket_access: str = Form("none"),
                          fix_times: str = Form("no")):
    if (r := _need_admin(request)):
        return r
    target = username
    nu = (new_username or "").strip()
    if nu and nu != username:
        ok, err = users.rename(username, nu)
        if ok:
            tickets.rename_user(username, nu)
            if _user(request) == username:
                request.session["user"] = nu
            target = nu
        else:
            request.session["flash"], request.session["flash_class"] = err, "err"
            return RedirectResponse(f"/users/{username}/edit", status_code=303)
    if users.set_profile(target, name, email, timemoto_name, role,
                         can_view_tickets=ticket_access in ("view", "edit"),
                         can_edit_tickets=ticket_access == "edit",
                         can_fix_times=fix_times == "yes"):
        audit.log(_user(request), "Benutzer bearbeitet",
                  f"{username} (Rolle {role}, TimeMoto '{timemoto_name}')")
        request.session["flash"] = f"Benutzer {username} gespeichert."
    else:
        request.session["flash"], request.session["flash_class"] = \
            "Benutzer nicht gefunden.", "err"
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


@router.post("/users/{username}/impersonate")
async def users_impersonate(request: Request, username: str):
    """Support: Als anderer Benutzer anmelden. Nur Admin. Die eigene
    Identität wird gesichert, ein Banner erlaubt den Rücksprung."""
    if (r := _need_admin(request)):
        return r
    target = users.get(username)
    if not target or target.get("status") != "active":
        request.session["flash"], request.session["flash_class"] = \
            "Benutzer nicht gefunden oder nicht aktiv.", "err"
        return RedirectResponse("/users", status_code=303)
    if username == _user(request):
        return RedirectResponse("/users", status_code=303)
    # Original-Identität nur beim ersten Wechsel sichern -> Rücksprung zum echten Admin
    if not request.session.get("impersonator"):
        request.session["impersonator"] = {
            "user": request.session.get("user"),
            "role": request.session.get("role"),
            "name": request.session.get("name"),
            "tk_view": request.session.get("tk_view"),
            "tk_edit": request.session.get("tk_edit"),
        }
    orig = request.session["impersonator"]["user"] or "?"
    _finalize_login(request, target)
    audit.log(orig, "Support: Identität übernommen",
              f"{orig} → {target['username']}")
    request.session["flash"] = (
        f"Support-Modus: Du bist jetzt als "
        f"{target.get('name') or target['username']} angemeldet.")
    return RedirectResponse("/start", status_code=303)


@router.post("/impersonate/stop")
async def impersonate_stop(request: Request):
    """Zurück zur eigenen (Admin-)Identität."""
    imp = request.session.get("impersonator")
    if not imp:
        return RedirectResponse("/start", status_code=303)
    was = _user(request)
    request.session["user"] = imp.get("user")
    request.session["role"] = imp.get("role", "user")
    request.session["name"] = imp.get("name")
    request.session["tk_view"] = imp.get("tk_view")
    request.session["tk_edit"] = imp.get("tk_edit")
    request.session.pop("impersonator", None)
    audit.log(imp.get("user") or "?", "Support: Identität verlassen",
              f"war als {was}")
    request.session["flash"] = "Zurück in deinem Account."
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
    u2 = users.get(u["username"]) or u
    # 2FA ist Pflicht: externe/lokale Konten richten sie direkt nach dem
    # Aktivieren ein (Microsoft-Konten laufen nie hier durch).
    if config.TWOFA_REQUIRED and not u2.get("twofa_enabled"):
        request.session.clear()
        request.session["pending_user"] = u2["username"]
        request.session["flash"] = "Konto aktiviert. Bitte jetzt 2FA einrichten."
        return RedirectResponse("/2fa/setup", status_code=303)
    _finalize_login(request, u2)
    request.session["flash"] = "Konto aktiviert. Willkommen!"
    return RedirectResponse("/start", status_code=303)
