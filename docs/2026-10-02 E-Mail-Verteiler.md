---
title: "E-Mail-Verteiler – neues Tool 2026-10-02"
date: 2026-10-02
tags: [projekt/fbe-intranet, verteiler, reach, changelog, entwicklung]
aliases: ["Verteiler-Tool", "Reach Verteiler", "E-Mail-Verteiler"]
status: ausgeliefert
branch: main
url: https://intern.rss-fb.com/verteiler/
---

# E-Mail-Verteiler – neues Tool vom 02.10.2026

> [!summary] Kurzfassung
> Neues Werkzeug im Ordner `verteiler/` (Repo `projektabrechung`,
> Branch `main`). Der E-Mail-Verteiler liegt jetzt in **einer SQLite-Datei**
> (`verteiler.db`), und diese Datenbank ist die einzige maßgebliche Quelle.
> Für Reach wird aus der Datenbank exportiert, Listen werden nicht mehr neu
> hochgeladen. Unzustellbare, abgemeldete und gesperrte Adressen kommen
> **nie** wieder in einen Export.
> Anlass: letzte Kampagne mit 26,8 % harten Bounces (1.399 von 5.220),
> Hostinger warnt vor Versandsperre.

## Start

- **Server:** <https://intern.rss-fb.com/verteiler/>, im Intranet-Menü
  „E-Mail-Verteiler“ (nur Administratoren, Login wie im Intranet inkl. 2FA)
- Eigener Container `verteiler` neben `projektabrechnung`, Daten im
  Docker-Volume `projektabrechnung_verteiler-daten`
- Optional lokal unter Windows über `verteiler/start.bat`

## Einrichtung auf dem Server

Siehe `deploy/DEPLOY.md` → „E-Mail-Verteiler“. Kurzform:

```bash
cd /root/projektabrechung && git fetch origin && git checkout main && git pull origin main
cd deploy && docker compose up --build -d
sh /root/projektabrechung/deploy/caddy-einrichten.sh   # Caddy-Dienst, mit Backup + Auto-Rücksprung
```

Sicherheit: Der Caddy-Dienst des Servers prüft jede Anfrage gegen das Intranet (`forward_auth`),
und die App prüft selbst noch einmal. Getestet: ohne Login → Login-Seite,
Mitarbeiter → 403, deaktivierter Admin → Login, gefälschter Header oder
Cookie → abgewiesen, direkter Zugriff am Proxy vorbei → gesperrt.

## Einmalig einrichten

1. **Kontaktliste importieren**: Gesamtliste, Quelle z. B. „Altliste“
2. **Kampagnen-Report importieren**: Empfänger-CSV der letzten Kampagne →
   die 1.399 Bounces landen auf der Sperrliste
3. Ggf. weitere Abmelde-/Bounce-Listen über **Sperrliste importieren**
4. **Export für Reach → Alle aktiven** als **neue** Liste in Reach hochladen

## Ablauf nach jeder Kampagne

1. Reach → Kampagne → Registerkarte **Empfänger** → CSV exportieren
   (3–7 Tage nach Versand)
2. Tool → **Kampagnen-Report importieren** (Name, Betreff, Datum, Datei,
   Statuswerte prüfen) → importieren
   - Unzustellbar → Sperrliste · Abgemeldet → Sperrliste
   - Soft-Bounce → Zähler, ab 3 in Folge wie harter Bounce
3. **Dashboard**: Bounce-Rate > 2 % wird rot gewarnt
4. Vor dem nächsten Versand: **Export für Reach** (Alle aktiven / Engagierte
   90 Tage / Inaktive 180 Tage) → neue Liste in Reach

## Schutzregeln

- Sperrliste unveränderlich – per Datenbank-Trigger erzwungen
- Gesperrte Adressen: nie Export, nie Reaktivierung, beim Import übersprungen
- Echtes Löschen nur per **„Kontakt vollständig löschen (DSGVO)“** mit
  Eingabe der Adresse als Bestätigung (Adresse bleibt standardmäßig gesperrt)
- Jede Schreiboperation in einer Transaktion, bei Fehler Rollback
- Automatisches Backup vor jedem Import in `backups/` (die letzten 100)
- `verteiler.db`, `backups/` und CSV/XLSX sind per `.gitignore` vom Git ausgeschlossen

## Test mit Beispieldaten

Kontaktliste mit 80 Zeilen, je 20 neu / Dublette / ungültig / gesperrt:

| Neu | Dublette | Ungültig | Gesperrt |
|---|---|---|---|
| 20 | 20 (10 doppelt in der Datei, 10 bestehende Kontakte ergänzt) | 20 | 20 |

- 31 automatische Tests grün (`python -m unittest discover -s tests -v`)
- Lasttest mit 5.220 Empfängern: Report-Import 0,3 s, 1.399 harte Bounces
  korrekt gesperrt, harte Bounce-Rate 26,8 %

> [!note] Ablage
> Diese Notiz liegt auch im Repo unter `docs/2026-10-02 E-Mail-Verteiler.md`.
> Die ausführliche Anleitung steht in `verteiler/README.md`.
