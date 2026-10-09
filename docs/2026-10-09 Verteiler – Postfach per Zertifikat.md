---
title: "E-Mail-Verteiler – Postfach per Zertifikat und Einrichtungs-Skript 2026-10-09"
date: 2026-10-09
tags: [projekt/fbe-intranet, verteiler, microsoft-365, sicherheit, changelog, entwicklung]
aliases: ["Verteiler Zertifikat", "Verteiler Einrichtungs-Skript"]
status: ausgeliefert
branch: main
url: https://intern.rss-fb.com/verteiler/
---

# E-Mail-Verteiler – Postfach per Zertifikat (09.10.2026)

> [!summary] Kurzfassung
> Das Verteiler-Postfach meldet sich bei Microsoft jetzt **per Zertifikat** an.
> Kein Benutzer-Login, kein ablaufendes Client-Geheimnis in `.env`, Lesezugriff
> nur auf genau das eine Postfach. Alles wird im Backend eingerichtet.
> Dazu kommt ein Einrichtungs-Skript, das Intranet, Verteiler und Mailing-Tool
> in einem Schritt aktualisiert. Vorher: [[2026-10-05 Verteiler – Abo-Status und Postfach]]

## Server aktualisieren

```bash
cd /root/projektabrechung && git pull origin main && sh deploy/einrichten.sh
```

Das Skript erledigt:
- Ordner des Mailing-Tools finden
- gemeinsames Token anlegen, ohne es anzuzeigen, mit Backups der `.env`
- Code beider Tools holen
- bauen und starten
- Caddy einrichten
- Mailing-Abgleich einschalten und einmal ausführen
- alles prüfen

Bricht ab, bevor etwas überschrieben wird, wenn Dateien von Hand geändert wurden.

> [!note] Zeilenenden
> `verteiler/start.bat` galt auf dem Server als „geändert“, weil die Datei mit
> Windows-Zeilenenden im Repo lag. Behoben in `b22ee37`. Einmalig auf dem Server:
> `git fetch origin main && git reset --hard origin/main`. Das betrifft nur Dateien
> aus dem Repo, `.env` und Daten bleiben unberührt.

## Postfach per Zertifikat – Einrichtung

Verteiler → **Postfach** → Anmeldeart „Per Zertifikat“:

1. Postfach-Adresse eintragen, z. B. `verteiler@fb-eng.de`
2. **Zertifikat erzeugen** → **.cer herunterladen**. Der private Schlüssel
   bleibt auf dem Server (`/data/postfach_zertifikat.key`, 0600, nicht in Backups).
3. Entra → App-Registrierungen → **Neu** „FBE Verteiler Postfach“ →
   Zertifikate & Geheimnisse → **.cer hochladen**. **Keine** API-Berechtigung eintragen.
4. Verzeichnis-ID und Anwendungs-ID im Verteiler eintragen
5. Exchange Online PowerShell: Die Befehle stehen mit den richtigen Werten auf
   der Seite. Sie geben Lesezugriff nur auf dieses eine Postfach.
6. **Verbindung testen** → „Automatisch abrufen“ → Speichern

> [!warning] Ablauf
> Das Zertifikat gilt 2 Jahre (bis ca. Oktober 2028). 60 Tage vorher wird es
> gelb angezeigt. Dann neu erzeugen, die neue `.cer` in Entra hochladen und
> das alte Zertifikat löschen.

## Sicherheit

- Anmeldung mit kurzlebiger, signierter Bestätigung (JWT RS256, 10 Minuten),
  Schlüssel RSA 3072
- Zugriff per Exchange-RBAC auf genau ein Postfach, nur lesend
- Alternative „Microsoft-Login“ bleibt verfügbar

## Tests

- 43 automatische Tests grün. Ein Fake-Microsoft-Server prüft die Signatur
  gegen das hochgeladene Zertifikat. Ein falsches Zertifikat wird abgelehnt.
- Oberfläche getestet: Zertifikat erzeugen, Download ohne privaten Schlüssel,
  Befehle mit Werten, Verbindungstest gegen das echte Microsoft (Antwort korrekt
  ausgewertet)

> [!note] Ablage
> Diese Notiz liegt auch im Repo unter `docs/2026-10-09 Verteiler – Postfach per Zertifikat.md`.
