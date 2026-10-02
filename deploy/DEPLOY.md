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

Schutz:
- fbe-caddy prüft **jede** Anfrage an `/verteiler/*` per `forward_auth`
  gegen `/auth/verteiler` im Intranet. Ohne Login geht es zum Login, wer kein
  Admin ist, bekommt 403. Microsoft-Login und 2FA gelten wie im Intranet.
- Die App prüft das Login zusätzlich selbst (`VERTEILER_AUTH_URL`) und ist
  damit auch dann gesperrt, wenn jemand den Container im Docker-Netz direkt
  anspricht. Ist das Intranet nicht erreichbar, bleibt der Verteiler gesperrt.
- Auf dem Host wird kein Port veröffentlicht. Der Container läuft nicht als root.
- Daten im Docker-Volume `projektabrechnung_verteiler-daten`
  (`verteiler.db` + `backups/`), bleiben bei Updates erhalten.

### Einmalig einrichten

```bash
# 1. Code holen (der Server stand bisher auf claude/relaxed-hawking-VJjx3)
cd /root/projektabrechung
git fetch origin
git checkout main
git pull origin main

# 2. Container bauen/starten (Intranet wird mit aktualisiert, kurzer Neustart)
cd deploy
docker compose up --build -d
docker compose ps            # projektabrechnung + verteiler: "Up" / "healthy"

# 3. Caddy-Block für intern.rss-fb.com ersetzen – bricht ab, BEVOR etwas
#    überschrieben wird, wenn eine Datei fehlt oder die neue Config ungültig ist.
cd /opt/fbe-tools
SNIP=/root/projektabrechung/deploy/fbe-caddy.snippet
test -f "$SNIP" && grep -q "forward_auth" "$SNIP" \
  && [ "$(grep -c 'Block fuer die TimeMoto-Projektabrechnung' Caddyfile)" = 1 ] \
  && [ "$(grep -c 'Ende Block TimeMoto-Projektabrechnung' Caddyfile)" = 1 ] \
  && cp Caddyfile Caddyfile.bak-$(date +%F-%H%M) \
  && sed '/# >>> Block fuer die TimeMoto-Projektabrechnung >>>/,/# <<< Ende Block TimeMoto-Projektabrechnung <<</d' Caddyfile > /tmp/Caddyfile.neu \
  && cat "$SNIP" >> /tmp/Caddyfile.neu \
  && grep -q "intern.rss-fb.com" /tmp/Caddyfile.neu \
  && docker cp /tmp/Caddyfile.neu fbe-caddy:/tmp/Caddyfile.neu \
  && docker exec fbe-caddy caddy validate --config /tmp/Caddyfile.neu --adapter caddyfile \
  && cat /tmp/Caddyfile.neu > Caddyfile \
  && docker exec fbe-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile \
  && echo "FERTIG: Caddy neu geladen" \
  || echo "ABGEBROCHEN – Ausgabe oben prüfen"
# "cat … > Caddyfile" ersetzt nur den Inhalt, die Datei bleibt dieselbe (Bind-Mount!).
```

Falls die beiden `grep -c` **nicht** je 1 ergeben (Block ohne Markierungen
eingefügt): den alten `intern.rss-fb.com { … }`-Block in der Caddyfile von
Hand durch den Inhalt von `deploy/fbe-caddy.snippet` ersetzen.
**Nicht** `sed -i` direkt auf die Caddyfile anwenden, denn das legt eine neue
Datei an, und der Container sieht dann weiter die alte.

### Prüfen

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://intern.rss-fb.com/verteiler/   # 303 (zum Login)
curl -s https://intern.rss-fb.com/health                                         # Intranet ok
```

Im Browser als Admin anmelden → Menü **E-Mail-Verteiler**.

Zurück zum alten Stand, falls etwas nicht passt:
`cat Caddyfile.bak-… > Caddyfile` und erneut `caddy reload`.

### Datensicherung

Vor jedem Import legt der Verteiler selbst ein Backup im Volume an. Zusätzlich
lässt sich die Datenbank vom Server holen:

```bash
docker cp verteiler:/data/verteiler.db /root/verteiler-$(date +%F).db
```

Logs: `docker compose logs -f verteiler`
