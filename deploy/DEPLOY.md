# Deployment auf deinem Server (Docker + Caddy + HTTPS)

Ziel: Der Dienst läuft als Docker-Container hinter Caddy und ist unter
`https://intern.rss-fb.com/` erreichbar. TimeMoto schickt seine Webhooks an
`https://intern.rss-fb.com/timemoto`.

## Voraussetzungen

- Ein Server mit **öffentlicher IPv4** (und optional IPv6) und Docker +
  Docker-Compose-Plugin.
- Zugriff auf die **DNS-Verwaltung der Zone `rss-fb.com`**.
- Die Firewall erlaubt eingehend **TCP 80 und 443** auf den Server.
  (Port 80 wird für die Let's-Encrypt-Prüfung und den HTTPS-Redirect
  gebraucht, danach läuft alles über 443.)

## 1. DNS setzen

Lege in der Zone `rss-fb.com` einen **A-Record** für den Host `intern` an,
der auf die **öffentliche IP deines Servers** zeigt:

| Typ | Name (Host) | Wert / Ziel              | TTL  | Proxy |
|-----|-------------|--------------------------|------|-------|
| A   | `intern`    | `<ÖFFENTLICHE_IPV4>`     | 3600 | aus   |

- „Name" ist nur der Host-Teil; viele Provider hängen die Zone automatisch an
  → Ergebnis ist `intern.rss-fb.com`. (Falls dein Panel den vollen Namen
  will: `intern.rss-fb.com`.)
- Hast du **IPv6**, zusätzlich einen **AAAA-Record** `intern` → `<IPV6>`.
- **Cloudflare-Nutzer:** Die orange Wolke (Proxy) für den ersten Start besser
  **auf „DNS only" (grau)** stellen, damit Caddy das Zertifikat sauber per
  HTTP-Challenge zieht. Danach kannst du den Proxy optional wieder einschalten.
- **Kein** CNAME nötig — bei dieser Variante zeigt der Host direkt per A/AAAA
  auf die Server-IP.

Prüfen, dass es greift (kann je nach TTL ein paar Minuten dauern):

```bash
dig +short intern.rss-fb.com        # muss deine Server-IP zeigen
```

## 2. Code auf den Server holen

```bash
git clone https://github.com/DauntlessGiantfromHugeSea/projektabrechung.git
cd projektabrechung
git checkout claude/relaxed-hawking-VJjx3
cd deploy
```

## 3. Konfiguration prüfen

- In `Caddyfile` ggf. die `email`-Zeile auf eine echte Kontaktadresse setzen.
- In `docker-compose.yml` bei Bedarf `PROJECT_CODE`, Zeitzone und Cron-Zeiten
  anpassen. SMTP kann vorerst leer bleiben (Bericht wird dann nur als Datei in
  `deploy/data/reports/` abgelegt).

## 4. Starten

```bash
docker compose up --build -d
docker compose logs -f          # Caddy holt jetzt das Zertifikat
```

Im Caddy-Log sollte eine Zeile wie „certificate obtained successfully" für
`intern.rss-fb.com` auftauchen. Test:

```bash
curl https://intern.rss-fb.com/health
```

## 5. Webhook in TimeMoto eintragen

In der TimeMoto Cloud als Webhook-Ziel eintragen:

```
https://intern.rss-fb.com/timemoto
```

Danach ein paar Test-Stempelungen machen und prüfen, was ankommt
(intern, z. B. per SSH-Tunnel oder aus dem LAN — von außen sind die
`/report/*`-Endpoints absichtlich gesperrt):

```bash
curl https://intern.rss-fb.com/report/inspect   # nur aus internem Netz erlaubt
```

## Sicherheit / Hinweise

- **`/report/*` ist von außen mit 403 gesperrt** (siehe `Caddyfile`), weil
  diese Endpoints keine eigene Authentifizierung haben. Öffentlich erreichbar
  sind nur `/timemoto` (Webhook) und `/health`.
- Setzt TimeMoto ein **Secret**, trag denselben Wert in `SHARED_SECRET` ein.
- Das Volume **`caddy_data` nicht löschen** — dort liegen die Zertifikate
  (sonst drohen Let's-Encrypt-Rate-Limits beim Neuausstellen).
- Die Roh-Events und Berichte liegen in `deploy/data/` — bei Bedarf ins Backup
  aufnehmen.

## Update einspielen

```bash
cd projektabrechung && git pull
cd deploy && docker compose up --build -d
```

> Der Compose-Projektname ist auf **`projektabrechnung`** gesetzt (`name:` in
> `docker-compose.yml`), der App-Container heißt ebenfalls `projektabrechnung`.
