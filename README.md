# TimeMoto Webhook Logger

Ein winziger Dienst, der **jeden** eingehenden Webhook von TimeMoto komplett
mitschreibt. Ziel ist nicht die fertige App, sondern die eine wichtige Frage
zu klären:

> **Sehe ich die Events – und steht der Projektcode drin?**

Der Logger ist absichtlich format-agnostisch: Er protokolliert Header, rohen
Body und (falls JSON) formatiertes JSON. So siehst du exakt, was TimeMoto
schickt, ganz egal wie die Payload aufgebaut ist.

## 1. Starten

```bash
docker compose up --build -d
docker compose logs -f      # Live-Ausgabe der eingehenden Events
```

Health-Check: `http://<server>:8080/health`
Webhook-Endpoint: `http://<server>:8080/timemoto`

Eingehende Events landen zusätzlich dauerhaft in `./data/events.jsonl`
(eine JSON-Zeile pro Event).

## 2. Öffentlich + HTTPS erreichbar machen

TimeMoto muss deinen Endpoint von außen erreichen, in der Regel **per HTTPS**.
Zwei übliche Wege:

- **Reverse-Proxy mit TLS** (empfohlen, dauerhaft): z. B. Caddy, Traefik oder
  nginx vor dem Container. Caddy-Beispiel:
  ```
  webhook.deinedomain.de {
      reverse_proxy 127.0.0.1:8080
  }
  ```
  Dann in der Compose-Datei den Port auf `127.0.0.1:8080:8080` binden.

- **Tunnel für einen schnellen Test**: z. B. `cloudflared tunnel` – liefert
  sofort eine öffentliche HTTPS-URL ohne DNS/Zertifikat-Aufwand.

## 3. Webhook in TimeMoto eintragen

In der TimeMoto Cloud (Plus-Plan) unter den Entwickler-/Webhook-Einstellungen
die volle URL eintragen, z. B.:

```
https://webhook.deinedomain.de/timemoto
```

Falls TimeMoto ein Secret oder einen Signatur-Header anbietet: eintragen und
denselben Wert als `SHARED_SECRET` in `docker-compose.yml` setzen. In der
Erkundungsphase verwirft der Logger nichts – er zeigt nur an, ob der Wert
mitkam (`secret_ok`).

## 4. Events erzeugen und ansehen

1. Ein paar Test-Stempelungen machen – **wichtig: unter einem Projekt**
   ein- und ausstempeln.
2. In den Logs / in `data/events.jsonl` nachsehen.
3. Gezielt prüfen:
   - Kommt **je** ein Event für Ein- und Ausstempeln?
   - Steht ein **Projektfeld / Projektcode** in der Payload?
   - Welche Mitarbeiter-/Zeit-/Standortfelder gibt es?

Schnell durchsuchen:

```bash
cat data/events.jsonl | jq '.body_json'
# nach einem Projektfeld fahnden (Beispiel):
cat data/events.jsonl | jq '.body_json' | grep -i project
```

## Wie es danach weitergeht

Sobald wir aus echten Events wissen, welche Felder ankommen – vor allem ob der
Projektbezug dabei ist – bauen wir darauf auf:

- **Wenn der Projektcode in der Payload ist:** Events paaren (in/out),
  Dauer berechnen, pro Projekt summieren, in einer DB ablegen, Dashboard
  mit Projektfilter.
- **Wenn nicht:** Plan B – die Stunden über den Projekt-/Timesheet-Export
  der Cloud beziehen und im eigenen Interface darstellen.
