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
cd ~/projektabrechung && git pull
cd deploy
docker compose up --build -d
docker compose ps        # "projektabrechnung" muss "Up" sein
```

Lokaler Funktionstest (umgeht den Proxy):

```bash
curl http://127.0.0.1:8080/health
```

## 2. Block in fbe-caddy eintragen

Die Vorlage liegt in `deploy/fbe-caddy.snippet`. Inhalt an die bestehende
Caddyfile anhängen:

```bash
cat ~/projektabrechung/deploy/fbe-caddy.snippet >> /opt/fbe-tools/Caddyfile
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
cd ~/projektabrechung && git pull
cd deploy && docker compose up --build -d
```
