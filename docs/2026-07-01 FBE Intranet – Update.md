---
title: "FBE Intranet – Update 2026-07-01"
date: 2026-07-01
tags: [projekt/fbe-intranet, changelog, entwicklung]
aliases: ["FBE Intranet Änderungen Juli 2026", "Intranet Update"]
status: ausgeliefert
branch: claude/relaxed-hawking-VJjx3
---

# FBE Intranet – Update vom 01.07.2026

> [!summary] Kurzfassung
> Großes Update für das interne Tool **FBE Intranet** (TimeMoto-Zeiten,
> Projektabrechnung, Tickets, Exporte): komplettes **Design im Look des
> Teilnahmemanagements (in Grün)**, **Rollen-/Rechtemodell** (User sehen nur
> eigene Zeiten), **Support-Login als anderer Nutzer**, **Amprion-CSV-Export**
> korrigiert, **Projektverwaltung mit Task-Nummern**, frei **editierbare Texte**,
> installierbare **Web-App (PWA)** und mehrere Fixes.
> Alles liegt auf Branch `claude/relaxed-hawking-VJjx3`.

## Deployment

```bash
git pull origin claude/relaxed-hawking-VJjx3
docker compose up --build -d
```

- Läuft hinter `fbe-caddy` unter **https://intern.rss-fb.com**
- Secrets weiterhin nur in `deploy/.env` (nichts davon im Git)

---

## 1. Neues Design (Look „Teilnahmemanagement", in Grün)

**Was:** Oberfläche komplett überarbeitet, angelehnt an das FBA-Teilnahme­management,
aber in der Firmenfarbe statt Türkis.

- **Header** durchgehende Leiste in **Firmenfarbe `#92c57a`** mit **weißem Logo**
  (`FBE_white.png`); weiße Navigation, aktiver Punkt als weiße Pille.
- **Split-Screen-Login**: links grüner Bereich (Logo, Pille, großer Claim
  „**Flüssigboden. / Planung. / Innovation.**", Beschreibung) über dem
  Geoponton-Foto mit leichtem Grün-Overlay; rechts weißer Bereich mit
  „Willkommen zurück", Login-Formular, **„Mit Microsoft anmelden"** (mit MS-Logo)
  und „ODER"-Trenner.
- **Dashboard (`/start`)**: Begrüßung + Datum, **Stat-Cards** (Meine Stunden/Woche,
  Offene Tickets, Kalenderwoche) mit Icon, **Schnellzugriff**-Pillen, „Meine
  letzten Buchungen", Bereichs-Kacheln.
- **Hintergrund** fast weiß (`#fbfcfa`), **moderne Tabellen** (getönte Pill-
  Kopfzeile, gerundete Container, ruhige Trenner), edlere Karten-Schatten.
- **Favicon**: `cropped-FBE_midnight.png`.

> [!note] Betroffene Commits
> `dfa58ad`, `1b68ba3`, `0b6283a`, `40faf45`

## 2. Rollen- & Rechtemodell (Datenschutz)

**Warum:** Nicht jeder soll alle Zeiten sehen.

| Rolle | Darf |
|---|---|
| **User** | nur **eigene** Zeiten (unter „Meine Zeiten") |
| **Buchhaltung** | **alles** sehen, exportieren, **Zeiten korrigieren** |
| **Admin** | wie Buchhaltung **+** Benutzerverwaltung, Einstellungen |

- **Bericht, Log, Abrechnung, Exporte, Senden** nur noch für Buchhaltung + Admin.
- **Zeitkorrekturen** (hinzufügen/korrigieren/ausblenden/löschen, Tätigkeit an
  fremden Buchungen) für **Buchhaltung + Admin** (vorher nur Admin).
- Fehlt ein Recht: **kein toter „Kein Zugriff"-Bildschirm** mehr, sondern saubere
  Weiterleitung aufs Dashboard mit Hinweis.

> [!note] Commits: `e674df1`, `9922d7c`

## 3. Support: Identität übernehmen (Impersonation)

- Als Admin: **Benutzer → Aktionen → „Als Benutzer anmelden"**.
- Man sieht danach genau die Ansicht/Rechte der Person.
- Oben ein **oranges Banner „↩ Zurück zu meinem Account"** stellt die eigene
  Admin-Identität wieder her.
- Nur Admins, nur aktive Konten, beide Aktionen im **Verlauf/Audit-Log**.

> [!note] Commit: `8de7f63`

## 4. Tätigkeitsbeschreibung – bessere Bearbeitung

- Aufklappbare Bearbeitung mit **Stift-Symbol** und **mehrzeiligem Textfeld**.
- Eingetragene Beschreibung wird mit grünem **✓** angezeigt (sofort sichtbar,
  dass etwas gespeichert ist); ohne Eintrag „**+ Tätigkeit eintragen**".
- Gilt für „Meine Zeiten" (eigene) und Log (Buchhaltung/Admin).

## 5. Amprion-CSV-Export (Abgabeformat)

**Ausgangslage:** Es gab Arcadis-CSV **und** Amprion-Excel; die CSV kam teils leer.

- Nur noch **ein** Export: **Amprion-CSV** – exakt wie die Vorlage
  (`Datum;nicht relevant;Task Nr.;nicht relevant;Personen Name;Stunden;Tätigkeitbeschreibung`),
  Semikolon-getrennt, **UTF-8 mit BOM**, **CRLF**, Stunden mit Komma (`10,0`).
- **Fix „leere CSV":** Es werden jetzt **alle gefilterten Buchungen** exportiert
  (kein stilles Verwerfen mehr).
- **Task-Nr.** wird aus dem Projektnamen erkannt – bei euren Namen wie
  „**Amprion – HE4 32008**" → **32008** (längste Ziffernfolge als Ersatz).
- Export-Buttons zusätzlich **direkt auf der Bericht-Seite** (exakt angezeigter
  Zeitraum/Projekt).

> [!note] Commits: `764f109`, `7c1a109`, `77de281`, `91e448d`
> Datei: `csvout.py` (`amprion_csv`, `resolve_task`)

## 6. Projektverwaltung mit Task-Nummern

- Neuer Admin-Bereich **Administration → Projekte**.
- Liste aller Projekte mit **erkannter** Task-Nr. (Vorschlag) und Feld für eine
  **manuelle Task-Nr.**
- **Vorrang im Export:** manuelle Zuordnung → Amprion-Mapping → Nummer aus Name.
- Damit lassen sich Projekte **ohne Nummer im Namen** korrekt zuordnen/korrigieren.

> [!note] Commit: `a53aff9` · Speicher: `settings.py` (`get/set_project_tasks`)

## 7. Editierbare Texte (Admin)

- Neuer Bereich **Administration → Texte**.
- Anpassbar: **Login-Pille oben**, großer Claim (mehrzeilig), Beschreibungstext,
  „Willkommen zurück" + Unterzeile, Login-Fußnote, **Dashboard-Begrüßung** +
  Unterzeile, **App-Name** (Tab-Titel).
- Änderungen **sofort wirksam**; leeres Feld = Standardtext; „**Auf Standard
  zurücksetzen**".

> [!note] Commit: `c942252` · Speicher: `settings.py` (`get/set_texts`)

## 8. Web-App (PWA)

- Tool ist **installierbar** (iPhone „Zum Home-Bildschirm", Android/Desktop
  „App installieren"): eigenes Icon, Firmenfarbe, Start auf `/start`, Vollbild.
- Technik: `/manifest.webmanifest`, Apple-Meta-Tags, schlanker Service-Worker
  (`/sw.js`, ohne Caching → keine veralteten Inhalte).

> [!note] Commit: `91e448d`

## 9. „Meine Zeiten" – Sichtbarkeit gefixt

**Problem:** Kollegin sah ihre Buchungen nicht.

- **Fallback:** Ohne hinterlegten TimeMoto-Namen wird der **Anzeigename** zum
  Filtern genutzt (passt bei Microsoft-Konten meist automatisch).
- **Laufende Buchungen** werden jetzt auch hier angezeigt („Läuft gerade").
- Zeitraum auf **60 Tage**; klarer Hinweis, falls doch der TimeMoto-Name durch
  einen Admin zugeordnet werden muss.
- Sicherheit: Tätigkeit-Speichern bleibt strikt (exakter Namensabgleich).

> [!note] Commit: `aa9bfab`

## 10. Kleinkram

- **Kein Gendern** mehr in der Oberfläche (z. B. „Als Benutzer anmelden").

---

## Offene Punkte / Empfehlungen

- [ ] **Unauthentifizierte API-Endpunkte** aus der Anfangszeit (`/report/preview`,
      `/report/projects`, `/report/inspect`) hinter Login/Buchhaltung legen –
      aktuell per URL erreichbar (nicht im Menü). *Auf Wunsch umsetzen.*
- [ ] Ggf. weitere editierbare Texte (Kachel-Beschriftungen, E-Mail-Fußzeile).
- [ ] Projektverwaltung optional um Felder erweitern (Kunde, Standard-Empfänger,
      aktiv/archiviert).
- [ ] TimeMoto-Namen der Mitarbeiter final zuordnen, wo Anzeigename ≠ TimeMoto-Name.

## Kontext / Technik (für später)

- **Stack:** FastAPI + uvicorn, Jinja-Templates inline in `web.py`, JSON-Dateien
  als Speicher (kein DB), APScheduler; Mailversand über **Brevo HTTP-API**.
- **Login:** Microsoft (Entra ID) + optional Passwort-Konten, **2FA Pflicht** für
  Passwort-Konten.
- **Wichtige Dateien:** `web.py` (UI/Routen), `settings.py` (Texte, Projekt-Task-
  Nrn., Zeitzone, Berichte), `csvout.py` (Amprion-CSV), `xlsxout.py`, `report.py`,
  `users.py`, `tickets.py`, `mailer.py`.

> [!tip] Ablage
> Diese Notiz liegt auch im Repo unter `docs/2026-07-01 FBE Intranet – Update.md`.
