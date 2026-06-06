# FBE Intranet

Internes Tool der Flüssigboden Engineering GmbH: **Projektabrechnung** (TimeMoto-
Zeiten, Berichte, Arcadis-CSV), **Ticketsystem** und **Buchhaltungs-Exporte** –
mit Microsoft-Login, 2FA und rollenbasierten Rechten.

Ursprünglich ein kleiner Dienst, der TimeMoto-Webhooks mitschreibt **und** daraus
automatisch einen **wöchentlichen Projekt-Zeitbericht** erzeugt: pro
Mitarbeiter summierte Stunden für ein Projekt, jede Woche per Mail (oder als
Datei, solange noch kein Mailversand eingerichtet ist).

Er ist aus dem ursprünglichen *Webhook-Logger* hervorgegangen und bleibt
absichtlich tolerant: Da (noch) nicht sicher ist, wie TimeMoto die Payload
aufbaut und ob ein Projektcode mitkommt, werden die relevanten Felder
(Zeitpunkt, Mitarbeiter, Projekt, ein-/ausstempeln) **automatisch erkannt**.
Der Endpoint `/report/inspect` zeigt dir, was tatsächlich ankommt.

## Was der Dienst tut

1. **Webhook-Empfang** unter `WEBHOOK_PATH` (Default `/timemoto`): jedes Event
   wird geloggt und als JSON-Zeile in `LOG_FILE` (Default
   `/data/events.jsonl`) gespeichert – das ist die Datenbasis.
2. **Wochenbericht**: Aus den gesammelten Events werden Ein-/Ausstempelungen
   pro Mitarbeiter zu Arbeitsintervallen gepaart, die Dauer berechnet, nach
   Projekt gefiltert (`PROJECT_CODE`) und pro Mitarbeiter summiert.
3. **Auslösung**: Ein eingebauter Scheduler (APScheduler) fährt den Bericht
   automatisch – Default **jeden Montag 07:00** für die *vorige* Woche.
4. **Zustellung**: Per **SMTP-Mail**, sofern konfiguriert; sonst wird der
   Bericht als `.txt`/`.html` in `REPORT_DIR` abgelegt und geloggt. So
   funktioniert alles schon jetzt – Mail aktivierst du später per Env-Var.

## 1. Starten

```bash
docker compose up --build -d
docker compose logs -f
```

- Health: `http://<server>:8080/health`
- Webhook: `http://<server>:8080/timemoto`

## 2. Öffentlich + HTTPS erreichbar machen

TimeMoto muss den Webhook von außen per HTTPS erreichen. Übliche Wege:

- **Reverse-Proxy mit TLS** (empfohlen): z. B. Caddy/Traefik/nginx vor dem
  Container. Caddy-Beispiel:
  ```
  webhook.deinedomain.de {
      reverse_proxy 127.0.0.1:8080
  }
  ```
  Dann in `docker-compose.yml` den Port auf `127.0.0.1:8080:8080` binden.
- **Tunnel für den schnellen Test**: z. B. `cloudflared tunnel`.

## 3. Webhook in TimeMoto eintragen

In der TimeMoto Cloud unter den Entwickler-/Webhook-Einstellungen die volle
URL eintragen, z. B. `https://webhook.deinedomain.de/timemoto`. Falls ein
Secret angeboten wird: eintragen und denselben Wert als `SHARED_SECRET`
setzen (wird geprüft und als `secret_ok` protokolliert, Events werden nicht
verworfen).

## 4. Erst prüfen: kommt der Projektbezug an?

Nach ein paar Test-Stempelungen **unter einem Projekt** (ein- und
ausstempeln):

```bash
curl http://localhost:8080/report/inspect | jq
```

Die Antwort zeigt u. a.:

- `has_project_field` – wird ein Projekt erkannt?
- `has_direction_field` – sind ein-/ausstempeln unterscheidbar?
- `intervals_paired` – wie viele Arbeitsintervalle ließen sich bilden?
- `detected` – pro Event die erkannten Felder (Zeit/Mitarbeiter/Projekt/Richtung)

Daraus ergibt sich das weitere Vorgehen:

- **Projekt kommt mit** → `PROJECT_CODE` auf den gewünschten Projekt(teil)code
  setzen, fertig.
- **Falsches Feld erkannt** → exakten Feldnamen via `PROJECT_FIELD` erzwingen.
- **Kein Projekt im Webhook** → Plan B: Zeiten über die TimeMoto-Cloud
  (Projekt-/Timesheet-Export bzw. API) beziehen. Die Berichts-/Mail-/Scheduler-
  Mechanik bleibt dieselbe, nur die Datenquelle in `events.py` wird getauscht.

Welche Projekte überhaupt auftauchen, zeigt:

```bash
curl "http://localhost:8080/report/projects?start=2026-06-01&end=2026-06-08" | jq
```

## 5. Bericht ansehen und testen

```bash
# Vorschau der vorigen Woche als Text (kein Versand):
curl "http://localhost:8080/report/preview"

# Vorschau als JSON, mit explizitem Zeitraum und Projektfilter:
curl "http://localhost:8080/report/preview?fmt=json&project=ACME&start=2026-06-01&end=2026-06-08" | jq

# Bericht JETZT erzeugen UND zustellen (Mail bzw. Datei):
curl -X POST "http://localhost:8080/report/run"
```

Erzeugte Berichte liegen immer zusätzlich in `REPORT_DIR`
(`/data/reports/*.txt` und `*.html`).

## 6. Mailversand aktivieren (später)

In `docker-compose.yml` die SMTP-Werte und Empfänger setzen, dann neu starten:

```yaml
SMTP_HOST: "smtp.firma.de"
SMTP_PORT: "587"
SMTP_USER: "berichte@firma.de"
SMTP_PASSWORD: "..."
SMTP_FROM: "berichte@firma.de"
SMTP_STARTTLS: "true"      # oder SMTP_SSL: "true" für Port 465
REPORT_RECIPIENTS: "chef@firma.de,buchhaltung@firma.de"
```

Solange `SMTP_HOST` oder `REPORT_RECIPIENTS` leer sind, wird nicht gemailt –
der Bericht landet nur als Datei und im Log.

## Konfiguration (Auszug)

| Variable | Default | Bedeutung |
|---|---|---|
| `WEBHOOK_PATH` | `/timemoto` | Pfad des Webhook-Endpoints |
| `SHARED_SECRET` | – | optionaler Secret-Abgleich |
| `LOG_FILE` | `/data/events.jsonl` | Speicher der Roh-Events |
| `PROJECT_CODE` | – (alle) | Projektfilter (Teilstring genügt) |
| `PROJECT_FIELD` | – (auto) | exaktes Projekt-Feld erzwingen |
| `REPORT_DIR` | `/data/reports` | Ablage der Berichte |
| `REPORT_TIMEZONE` | `Europe/Berlin` | Zeitzone für Wochengrenzen |
| `SCHEDULER_ENABLED` | `true` | Wochen-Scheduler an/aus |
| `REPORT_CRON_DAY_OF_WEEK` | `mon` | Wochentag des Versands |
| `REPORT_CRON_HOUR` / `_MINUTE` | `7` / `0` | Uhrzeit des Versands |
| `SMTP_*`, `REPORT_RECIPIENTS` | – | Mailversand (optional) |

## Endpoints

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/health` | Health + Status |
| POST/GET/PUT | `<WEBHOOK_PATH>` | Webhook-Empfang |
| GET | `/report/preview` | Bericht ansehen (kein Versand) |
| POST | `/report/run` | Bericht erzeugen **und** zustellen |
| GET | `/report/projects` | erkannte Projekte im Zeitraum |
| GET | `/report/inspect` | erkannte Felder der letzten Events |
