# Deployment auf dem Server (hinter dem vorhandenen `fbe-caddy`)

Auf dem Server läuft bereits ein Reverse-Proxy **`fbe-caddy`** (Caddy), der
Port 80/443 und das TLS für die anderen Dienste macht. Diese App startet
deshalb **keinen eigenen Caddy**, sondern wird in `fbe-caddy` eingehängt.

Aufbau:
- App-Container `projektabrechnung` läuft nur intern (Port 8080), im selben
  Docker-Netz wie `fbe-caddy` (`fbe-tools_default`).
- `fbe-caddy` bekommt einen Site-Block für `intern.rss-fb.com`, der an
  `projektabrechnung:8080` weiterleitet und das Zertifikat automatisch holt.
- 8080 ist zusätzlich nur auf `127.0.0.1` veröffentlicht — für lokale Tests
  und die `/report/*`-Endpoints (die von außen gesperrt sind).

## Voraussetzungen (sind hier bereits erfüllt)

- `intern.rss-fb.com` zeigt per A-Record auf den Server (`202.61.227.170`).
- `fbe-caddy` bedient 80/443 → ACME funktioniert bereits.
- Netz: `fbe-tools_default`, Caddyfile: `/opt/fbe-tools/Caddyfile`.

## 1. App starten

```bash
cd /root/projektabrechung && git pull
cd deploy
docker compose up --build -d
docker compose ps        # "projektabrechnung" muss "Up" sein
```

Lokaler Funktionstest (umgeht den Proxy):

```bash
curl http://127.0.0.1:8080/health
```

### Login fürs Web-Interface einrichten

Die Zugangsdaten kommen aus `deploy/.env` (nicht im Git, wird automatisch von
Compose gelesen). Datei anlegen — **nur das Passwort anpassen**, der
Session-Schlüssel wird automatisch erzeugt:

```bash
cd /root/projektabrechung/deploy
cat > .env <<EOF
ADMIN_USER=admin
ADMIN_PASSWORD=HierDeinPasswort
SESSION_SECRET=$(openssl rand -hex 32)
EOF
docker compose up --build -d
```

Danach Login im Browser: **`https://intern.rss-fb.com/login`**
(die nackte Domain `/` leitet ebenfalls dorthin).

## 2. Block in fbe-caddy eintragen

Die Vorlage liegt in `deploy/fbe-caddy.snippet`. Inhalt an die bestehende
Caddyfile anhängen:

```bash
cat /root/projektabrechung/deploy/fbe-caddy.snippet >> /opt/fbe-tools/Caddyfile
```

Der Block (zur Kontrolle):

```caddy
intern.rss-fb.com {
	encode gzip
	@report_extern {
		path /report/*
		not remote_ip 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 127.0.0.1/8
	}
	respond @report_extern "Forbidden" 403
	reverse_proxy projektabrechnung:8080
}
```

## 3. fbe-caddy neu laden (ohne Downtime)

```bash
docker exec fbe-caddy caddy reload --config /etc/caddy/Caddyfile
```

Dann prüfen:

```bash
curl https://intern.rss-fb.com/health
docker logs fbe-caddy --tail 20 | grep -i intern   # Zertifikat erhalten?
```

`/health` muss `{"status":"ok",...}` liefern.

## 4. Webhook in TimeMoto eintragen

```
https://intern.rss-fb.com/timemoto
```

Danach Test-Stempelungen machen und lokal prüfen, was ankommt:

```bash
curl http://127.0.0.1:8080/report/inspect      # /report/* ist von außen 403
curl http://127.0.0.1:8080/report/preview
```

## Hinweise

- **`/report/*` ist von außen gesperrt** (403), weil ohne eigene
  Authentifizierung. Nutze diese Endpoints lokal über `127.0.0.1:8080`
  (z. B. per SSH-Tunnel: `ssh -L 8080:127.0.0.1:8080 <server>`).
- **Mailversand** später über die `SMTP_*`- und `REPORT_RECIPIENTS`-Variablen
  in `docker-compose.yml`. Solange leer, landet der Bericht nur als Datei in
  `deploy/data/reports/` und im Log.

## Update einspielen

```bash
cd /root/projektabrechung && git pull origin main
cd deploy && docker compose up --build -d
```

## E-Mail-Verteiler (`/verteiler/`)

Der Verteiler (Ordner `verteiler/`) läuft als zweiter Container `verteiler`
im selben Compose-Projekt. Erreichbar ist er unter
**`https://intern.rss-fb.com/verteiler/`**, für Administratoren auch über den
Menüpunkt „E-Mail-Verteiler“ im Intranet.

> **Wichtig: Wer auf dem Server Port 443 bedient.** Auf diesem Server
> beantwortet der **Caddy-Systemdienst** (`systemctl status caddy`,
> Konfiguration `/etc/caddy/Caddyfile`, Version 2.6) die Anfragen. Er erreicht
> die Apps über `127.0.0.1:<port>`. Der Container `fbe-caddy`
> (`/opt/fbe-tools/Caddyfile`) bekommt keinen Verkehr; Änderungen dort
> wirken nicht.

Schutz:
- Caddy prüft **jede** Anfrage an `/verteiler/*` per `forward_auth` gegen
  `/auth/verteiler` im Intranet. Ohne Login geht es zum Login, wer kein Admin
  ist, bekommt 403. Microsoft-Login und 2FA gelten wie im Intranet.
- Die App prüft das Login zusätzlich selbst (`VERTEILER_AUTH_URL`) und ist
  damit auch dann gesperrt, wenn jemand den Container direkt anspricht. Ist
  das Intranet nicht erreichbar, bleibt der Verteiler gesperrt.
- Port 8501 ist nur auf `127.0.0.1` veröffentlicht. Der Container läuft nicht
  als root.
- Daten im Docker-Volume `projektabrechnung_verteiler-daten`
  (`verteiler.db` + `backups/`), bleiben bei Updates erhalten.

### Einmalig einrichten

```bash
# 1. Code holen und Container starten
cd /root/projektabrechung
git fetch origin && git checkout main && git pull origin main
cd deploy && docker compose up --build -d
docker compose ps                                            # beide "Up", verteiler "healthy"
curl -s http://127.0.0.1:8501/verteiler/_stcore/health; echo   # "ok"

# 2. Caddy-Dienst einrichten (Skript prüft alles vorher, legt ein Backup an
#    und spielt den alten Stand automatisch zurück, falls /health danach nicht 200 liefert)
sh /root/projektabrechung/deploy/caddy-einrichten.sh
```

Das Skript ersetzt in `/etc/caddy/Caddyfile` nur den Block
`intern.rss-fb.com { … }` durch `deploy/caddy-intern.snippet`. Andere Seiten
(ticket, mailing, …) bleiben unverändert. Es kann gefahrlos mehrfach laufen.

### Prüfen

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://intern.rss-fb.com/health        # 200
curl -s -o /dev/null -w "%{http_code} -> %{redirect_url}\n" https://intern.rss-fb.com/verteiler/
# erwartet: 303 -> https://intern.rss-fb.com/login
```

Im Browser als Admin anmelden → Menü **E-Mail-Verteiler**.

Zurück zum alten Stand: `cat /etc/caddy/Caddyfile.bak-<Datum> > /etc/caddy/Caddyfile`
und `systemctl reload caddy`.

### Datensicherung

Vor jedem Import legt der Verteiler selbst ein Backup im Volume an. Zusätzlich
lässt sich die Datenbank vom Server holen:

```bash
docker cp verteiler:/data/verteiler.db /root/verteiler-$(date +%F).db
```

Logs: `docker compose logs -f verteiler`
