---
title: "Sicherheits-Audit Intranet, Verteiler, Mailing-Tool, Ticket-System 2026-10-09"
date: 2026-10-09
tags: [projekt/fbe-intranet, sicherheit, audit, verteiler, mailing, ticket-system, changelog]
aliases: ["Sicherheits-Audit 2026-10", "Security-Audit"]
status: ausgeliefert
branch: main
url: https://intern.rss-fb.com
---

# Sicherheits-Audit (09.10.2026)

> [!summary] Kurzfassung
> Alle drei Tools wurden nach dem **Cloudflare security-audit-skill** (Profil
> *standard*) geprüft: Recon, Hunter-Wellen mit Critic, unabhängige Prüfung jedes
> Befunds (Phase 3) und eine zweite, frische Prüfung jedes Ergebnisses (Phase 5).
> Geprüft wurde nur Quelltext plus lokale Sandbox – **kein** Test gegen die
> laufenden Server.
> **Alle Befunde sind behoben bzw. gehärtet, getestet und gepusht.**
> Vorher: [[2026-10-09 Verteiler – Postfach per Zertifikat]]

## Ergebnis

| Tool | bestätigt | davon hoch / mittel / niedrig | „Needs validation“ |
|---|---|---|---|
| Intranet + Verteiler (`projektabrechung`) | 16 | 3 / 5 / 8 | 6 |
| Mailing-Tool (`mailing`) | 6 | 0 / 2 / 4 | 4 |
| Ticket-System (`ticket-system`) | 0 | – | 6 |

„Needs validation“ heißt: im Code plausibel, aber ein Betriebsfakt fehlt (z. B.
Caddy- oder DEBUG-Einstellung auf dem Server). Auch dafür ist eine Härtung drin.

Vollständige Berichte (je Repo unter `docs/sicherheits-audit-2026-10/`):
`REPORT.md` (Übersicht), `FINDINGS-DETAIL.md` (Trace + Reproduktion + Fix),
`NEEDS-VALIDATION.md` (offene Hinweise).

> [!warning] Teilprüfung
> Ein paar Bereiche wurden nicht bis zum Ende gejagt (Wellenlimit bzw.
> abgebrochene Läufe) und stehen in den Berichten als *deferred*:
> Intranet – Uploads/Formulare vor Login (trotzdem gehärtet, s. u.);
> Mailing – öffentliche Endpunkte vor Login, CSV-Import/Vorschau-Größen;
> Ticket-System – Backup/Restore, Ticket-Seiten im Browser.

## Die wichtigsten Befunde und Fixes

### Intranet (hoch)
- **TimeMoto-Webhook ohne Secret** – jeder konnte Buchungen fälschen.
  → `SHARED_SECRET` ist jetzt Pflicht (sonst 503), max. 64 KiB je Anfrage.
- **Ein kaputter Zeitstempel legte das Dashboard lahm.** → Zeitstempel werden
  geprüft, defekte Einträge einzeln übersprungen.
- **2FA-Einrichtung nach reinem Passwortschritt** konnte eine bestehende 2FA
  ersetzen. → nur bei Erst-Einrichtung bzw. mit aktuellem Code; 5 Fehlversuche
  beim 2FA-Login beenden den Versuch.

### Intranet (mittel)
- Rollen/Deaktivierung wirkten erst nach Ablauf der Sitzung (14 Tage).
  → Prüfung bei jeder Anfrage, Sitzung 12 h, Logout/Passwortwechsel beenden alte Sitzungen.
- „Meine Zeiten“ ordnete über den selbst änderbaren Anzeigenamen zu.
  → nur noch admin-gepflegter TimeMoto-Name.
- Starlette-Version mit bekanntem DoS. → fastapi 0.143 / starlette 1.7.
- Webhook-Log wuchs unbegrenzt. → Größenlimit, nur nötige Header gespeichert.
- **Verteiler:** Externe Absender landeten über das Postfach ohne Einwilligung
  in Segmenten. → Postfach-Kontakte ohne Einwilligung werden nicht mehr angeschrieben.

### Intranet (niedrig) und Härtungen
`/health` ohne Konfigurationsdetails · Reset-Mail im Hintergrund und max. 1 Link
pro 5 min · Login gleich schnell für unbekannte Namen · kein Reset für
Microsoft-Konten · Escaping in Erinnerungsmails · CSV/XLSX ohne Formel-Injection ·
Jinja2-Autoescape · Schutz gegen Formulare fremder Seiten + Frame-Verbot ·
Microsoft-Login an oid/Tenant gebunden · Links nur aus `PUBLIC_BASE_URL` ·
Upload-Limit (60 MB App, 64 MB Caddy, Dokumente 50 MB) · Verteiler-Import mit
Spalten-/Zellenlimit · Postfach-Abruf blieb nach 200 bekannten Mails hängen.
**DSGVO-Löschung im Verteiler wird jetzt an das Mailing-Tool weitergegeben** und
dort ebenfalls ausgeführt (Abmeldelinks bleiben gültig).

### Mailing-Tool
VIEWER konnte über die Vorschau Abmelde-Tokens lesen (mittel) · Kontaktfelder
ungeescaped im Mail-HTML (mittel) · SMTP-Ziel frei wählbar, auch interne Adressen ·
Login-Timing · „Neu einplanen“ startete den Versand · Abmeldelinks gelöschter
Kontakte wurden ungültig · Standard-Admin-Passwort im Seed · Freigabe hob
Abmeldungen auf (jetzt nur ADMIN) · CSRF-/Frame-Schutz.

### Ticket-System
Anhänge waren über `/media/` ohne Login erreichbar und wurden inline
ausgeliefert → eigener Download mit Besitzerprüfung, nur als Datei · Upload-Limit
10 MB / 10 Dateien · keine Mails mehr an deaktivierte Admins · kein Bootstrap-Admin
`admin/admin` mehr · `DEBUG` standardmäßig aus · gunicorn mit Threads.

## Nachtrag: TimeMoto-Webhook deaktiviert

> [!info] Stand 09.10.2026
> Der TimeMoto-Webhook ist **abgeschaltet**. `/timemoto` antwortet mit 404,
> es kommen **keine neuen Buchungen** ins Intranet; vorhandene Zeiten,
> Berichte und Korrekturen bleiben unverändert.
> Wieder einschalten: in `deploy/.env` `TIMEMOTO_WEBHOOK=1` setzen und
> `sh deploy/einrichten.sh` ausführen (legt dann das Secret an und schreibt
> die TimeMoto-URL nach `deploy/timemoto-webhook-url.txt`).
> In TimeMoto selbst den Webhook am besten ebenfalls entfernen, damit dort
> keine Fehlermeldungen auflaufen.

## Auf dem Server zu tun

> [!important] Einmal ausführen
> ```bash
> cd /root/projektabrechung && git pull origin main && sh deploy/einrichten.sh
> ```
> Das Skript holt Intranet, Verteiler **und** Mailing-Tool, baut neu, legt bei
> Bedarf das Webhook-Secret an und übernimmt das neue Caddy-Limit (mit Backup
> und automatischem Rücksprung).

1. **TimeMoto:** Der Webhook ist deaktiviert (siehe Nachtrag) – in TimeMoto
   den Webhook entfernen. Nur wenn er wieder an soll: `TIMEMOTO_WEBHOOK=1`
   setzen, Skript erneut ausführen und die URL aus
   `deploy/timemoto-webhook-url.txt` in TimeMoto eintragen.
2. In `deploy/.env` prüfen: `PUBLIC_BASE_URL=https://intern.rss-fb.com`,
   `MS_TENANT_ID=<Tenant-GUID>` (statt `organizations`), `MS_ALLOWED_DOMAINS`.
3. **Mailing-Tool:** `SEED_ADMIN_PASSWORD` nur noch mit ≥ 12 Zeichen (nur nötig,
   wenn `RUN_SEED_ON_START=1`).
4. **Ticket-System** (eigenes Repo, Branch `claude/adoring-clarke-cwqn9j`):
   `DJANGO_SECRET_KEY` (lang, zufällig) und `DJANGO_DEBUG=False` setzen;
   `BOOTSTRAP_ADMIN_PASSWORD` nur für den allerersten Admin (≥ 12 Zeichen),
   danach wieder entfernen. Container neu bauen.

## Was Nutzer merken
- Alle sind **einmal abgemeldet** (neue Sitzungsprüfung).
- Sitzungen laufen nach **12 Stunden** ab.
- Microsoft-Nutzer ohne TimeMoto-Namen sehen unter „Meine Zeiten“ nichts mehr,
  bis ein Admin den Namen in der Benutzerverwaltung einträgt.
- Kontakte, die nur über das Postfach kamen, werden erst nach eingetragener
  Einwilligung angeschrieben.
- Ein zweiter Passwort-Reset innerhalb von 5 Minuten schickt keine neue Mail;
  der erste Link bleibt gültig.

## Tests
- Intranet: `python -m unittest tests.test_sicherheit` (7), Verteiler-Suite (45),
  Render-Prüfung aller Seiten, CSRF-/Webhook-Test – alles grün.
- Mailing: `test-security`, `test-schedule`, `test-verteiler-sync` (inkl.
  DSGVO-Löschung), `tsc` – grün.
- Ticket-System: `manage.py test` (24, davon 11 neu) – grün.
