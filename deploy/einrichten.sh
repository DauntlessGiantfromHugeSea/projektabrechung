#!/bin/sh
# Komplette Einrichtung/Aktualisierung von Intranet, E-Mail-Verteiler und
# Mailing-Tool-Abgleich auf dem Server. Gefahrlos mehrfach ausführbar.
#
# Aufruf:  sh /root/projektabrechung/deploy/einrichten.sh
#
# Was das Skript tut (jeder Schritt wird geprüft, bei Fehlern Abbruch):
#  1. findet den Ordner des Mailing-Tools (über den laufenden Container)
#  2. legt das gemeinsame Abgleich-Token an, falls noch keins existiert, und
#     trägt es in beide .env-Dateien ein (Backup vorher, Token wird nie angezeigt)
#  2b. nur wenn TIMEMOTO_WEBHOOK=1 (Standard: Webhook aus): legt das
#     TimeMoto-Webhook-Secret an, falls noch keins existiert; die fertige
#     Webhook-URL steht danach nur in deploy/timemoto-webhook-url.txt (chmod 600)
#  3. holt den neuesten Code beider Tools (bricht ab, wenn auf dem Server
#     Dateien von Hand geändert wurden)
#  4. baut und startet beide Tools neu
#  5. richtet den Caddy-Block für intern.rss-fb.com ein, falls noch nicht
#     geschehen (mit eigenem Backup und automatischem Rücksprung)
#  6. schaltet den Abgleich Verteiler <-> Mailing-Tool ein und führt ihn einmal aus
#  7. prüft alles und zeigt, was noch von Hand zu tun ist
set -u

# Das Skript liegt selbst im Repo, das es gleich aktualisiert. Damit "git pull"
# es nicht mitten im Lauf verändert, läuft es aus einer Kopie.
if [ -z "${EINRICHTEN_KOPIE:-}" ]; then
    kopie=$(mktemp /tmp/einrichten.XXXXXX) || exit 1
    cp "$0" "$kopie" && EINRICHTEN_KOPIE=1 exec sh "$kopie" "$@"
    exit 1
fi
trap 'rm -f "$0"' EXIT

VERTEILER_DIR="${VERTEILER_DIR:-/root/projektabrechung}"
DEPLOY="$VERTEILER_DIR/deploy"
MAILING_CONTAINER="${MAILING_CONTAINER:-mailing-app}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
export CADDYFILE

ok()     { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn()   { printf '  \033[33m!\033[0m %s\n' "$*"; }
fehler() { printf '\n\033[31mABGEBROCHEN:\033[0m %s\n' "$*"; exit 1; }
schritt(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }

# ------------------------------------------------------------------ Hilfen

# Wert einer Variable aus einer .env-Datei (ohne Anführungszeichen)
env_wert() {
    grep -E "^$2=" "$1" 2>/dev/null | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

# Variable in .env setzen (vorhandene Zeile ersetzen, sonst anhängen)
env_setzen() {
    if grep -qE "^$2=" "$1"; then
        sed -i "s|^$2=.*|$2=$3|" "$1"
    else
        printf '\n%s=%s\n' "$2" "$3" >> "$1"
    fi
}

git_aktualisieren() {   # $1 = Ordner, $2 = Name
    cd "$1" || fehler "$2: Ordner $1 nicht gefunden."
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        git status --short --untracked-files=no
        fehler "$2: Im Ordner $1 wurden Dateien von Hand geändert (siehe oben). Bitte klären, bevor aktualisiert wird."
    fi
    vorher=$(git rev-parse --short HEAD)
    git pull --ff-only -q || fehler "$2: git pull fehlgeschlagen."
    nachher=$(git rev-parse --short HEAD)
    ok "$2: Code aktuell ($vorher -> $nachher, Branch $(git rev-parse --abbrev-ref HEAD))"
}

for befehl in docker git curl openssl sed grep; do
    command -v "$befehl" >/dev/null 2>&1 || fehler "Befehl '$befehl' fehlt auf dem Server."
done

# ------------------------------------------------------------------ 1.
schritt "1. Ordner finden"
[ -f "$DEPLOY/docker-compose.yml" ] || fehler "$DEPLOY/docker-compose.yml nicht gefunden (VERTEILER_DIR=…)."
[ -f "$DEPLOY/.env" ] || fehler "$DEPLOY/.env fehlt."
ok "Intranet/Verteiler: $VERTEILER_DIR"
MAILING_DIR="${MAILING_DIR:-$(docker inspect "$MAILING_CONTAINER" --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null)}"
[ -n "$MAILING_DIR" ] && [ -f "$MAILING_DIR/docker-compose.yml" ] \
    || fehler "Ordner des Mailing-Tools nicht gefunden (Container $MAILING_CONTAINER). Mit MAILING_DIR=/pfad sh $0 angeben."
[ -f "$MAILING_DIR/.env" ] || fehler "$MAILING_DIR/.env fehlt."
ok "Mailing-Tool: $MAILING_DIR"

# ------------------------------------------------------------------ 2.
schritt "2. Gemeinsames Abgleich-Token"
T_MAILING=$(env_wert "$MAILING_DIR/.env" VERTEILER_SYNC_TOKEN)
T_VERTEILER=$(env_wert "$DEPLOY/.env" MAILING_SYNC_TOKEN)
if [ ${#T_MAILING} -ge 32 ] && [ "$T_MAILING" = "$T_VERTEILER" ]; then
    ok "Token ist in beiden .env-Dateien eingetragen und gleich."
    TOKEN=$T_MAILING
else
    if [ ${#T_MAILING} -ge 32 ]; then TOKEN=$T_MAILING
    elif [ ${#T_VERTEILER} -ge 32 ]; then TOKEN=$T_VERTEILER
    else TOKEN=$(openssl rand -hex 32)
    fi
    stempel=$(date +%F-%H%M%S)
    cp -p "$MAILING_DIR/.env" "$MAILING_DIR/.env.bak-$stempel" || fehler "Backup der Mailing-.env fehlgeschlagen."
    cp -p "$DEPLOY/.env" "$DEPLOY/.env.bak-$stempel" || fehler "Backup der Verteiler-.env fehlgeschlagen."
    env_setzen "$MAILING_DIR/.env" VERTEILER_SYNC_TOKEN "$TOKEN"
    env_setzen "$DEPLOY/.env" MAILING_SYNC_TOKEN "$TOKEN"
    [ "$(env_wert "$MAILING_DIR/.env" VERTEILER_SYNC_TOKEN)" = "$TOKEN" ] \
        && [ "$(env_wert "$DEPLOY/.env" MAILING_SYNC_TOKEN)" = "$TOKEN" ] \
        || fehler "Token konnte nicht eingetragen werden (Backups: .env.bak-$stempel)."
    ok "Token erzeugt bzw. abgeglichen und in beide .env-Dateien eingetragen (Backups: .env.bak-$stempel)."
fi

# ------------------------------------------------------------------ 2b.
schritt "2b. TimeMoto-Webhook"
URL_DATEI="$DEPLOY/timemoto-webhook-url.txt"
case "$(env_wert "$DEPLOY/.env" TIMEMOTO_WEBHOOK)" in
    1|true|ja|yes|on) WEBHOOK_AN=1 ;;
    *) WEBHOOK_AN=0 ;;
esac
if [ "$WEBHOOK_AN" = 0 ]; then
    rm -f "$URL_DATEI"
    ok "TimeMoto-Webhook ist deaktiviert (in deploy/.env TIMEMOTO_WEBHOOK=1 setzen zum Einschalten)."
else
SECRET=$(env_wert "$DEPLOY/.env" SHARED_SECRET)
if [ ${#SECRET} -ge 16 ]; then
    ok "SHARED_SECRET ist gesetzt."
else
    stempel=$(date +%F-%H%M%S)
    cp -p "$DEPLOY/.env" "$DEPLOY/.env.bak-$stempel" || fehler "Backup der .env fehlgeschlagen."
    SECRET=$(openssl rand -hex 24)
    env_setzen "$DEPLOY/.env" SHARED_SECRET "$SECRET"
    [ "$(env_wert "$DEPLOY/.env" SHARED_SECRET)" = "$SECRET" ] || fehler "SHARED_SECRET konnte nicht eingetragen werden."
    warn "SHARED_SECRET neu erzeugt (Backup: .env.bak-$stempel). TimeMoto muss auf die neue URL umgestellt werden,"
    warn "sonst kommen keine neuen Buchungen an – siehe Hinweis am Ende."
    NEUES_SECRET=1
fi
BASIS=$(env_wert "$DEPLOY/.env" PUBLIC_BASE_URL); BASIS=${BASIS:-https://intern.rss-fb.com}
PFAD=$(env_wert "$DEPLOY/.env" WEBHOOK_PATH); PFAD=${PFAD:-/timemoto}
( umask 077; printf '%s%s?secret=%s\n' "${BASIS%/}" "$PFAD" "$SECRET" > "$URL_DATEI" )
ok "Webhook-URL für TimeMoto liegt in $URL_DATEI (nur für root lesbar)."
fi

# ------------------------------------------------------------------ 3.
schritt "3. Neuesten Code holen"
git_aktualisieren "$VERTEILER_DIR" "Intranet/Verteiler"
git_aktualisieren "$MAILING_DIR" "Mailing-Tool"

# ------------------------------------------------------------------ 4.
schritt "4. Bauen und starten (dauert beim ersten Mal einige Minuten)"
cd "$MAILING_DIR" && docker compose up -d --build >/tmp/einrichten-mailing.log 2>&1 \
    || { tail -n 20 /tmp/einrichten-mailing.log; fehler "Mailing-Tool konnte nicht gestartet werden (Log: /tmp/einrichten-mailing.log)."; }
ok "Mailing-Tool läuft."
cd "$DEPLOY" && docker compose up -d --build --remove-orphans >/tmp/einrichten-verteiler.log 2>&1 \
    || { tail -n 20 /tmp/einrichten-verteiler.log; fehler "Intranet/Verteiler konnten nicht gestartet werden (Log: /tmp/einrichten-verteiler.log)."; }
ok "Intranet, Verteiler und Hintergrund-Abgleich laufen."

printf '  Warte auf den Start '
for i in $(seq 1 40); do
    if curl -s -o /dev/null "http://127.0.0.1:8080/health" \
       && docker exec verteiler python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8501/verteiler/_stcore/health', timeout=3)" >/dev/null 2>&1; then
        break
    fi
    printf '.'; sleep 3
done
printf '\n'

# ------------------------------------------------------------------ 5.
schritt "5. Caddy (intern.rss-fb.com)"
if grep -q "forward_auth" "$CADDYFILE" 2>/dev/null && grep -q "max_size 64MB" "$CADDYFILE" 2>/dev/null; then
    ok "Caddy ist bereits eingerichtet."
else
    sh "$DEPLOY/caddy-einrichten.sh" || fehler "Caddy-Einrichtung abgebrochen (Ausgabe oben). Intranet läuft mit dem alten Stand weiter."
fi

# ------------------------------------------------------------------ 6.
schritt "6. Abgleich Verteiler <-> Mailing-Tool einschalten"
PORT=$(docker port "$MAILING_CONTAINER" 3000 2>/dev/null | head -n 1 | sed 's/.*://')
CODE=$(printf 'Authorization: Bearer %s\n' "$TOKEN" | curl -s -o /dev/null -w '%{http_code}' -X POST \
       -H @- -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:${PORT:-3000}/api/integration/verteiler")
[ "$CODE" = "200" ] || fehler "Schnittstelle im Mailing-Tool antwortet mit $CODE statt 200."
ok "Schnittstelle im Mailing-Tool antwortet (Token passt)."
docker exec -i verteiler python - <<'PY' || fehler "Erster Abgleich fehlgeschlagen (Ausgabe oben)."
import os, sys
from verteiler_core import db, mailing
pfad, backups = os.environ["VERTEILER_DB"], os.environ["VERTEILER_BACKUPS"]
conn = db.connect(pfad)
try:
    cfg = mailing.einstellungen_lesen(conn)
finally:
    conn.close()
cfg.aktiv = True
mailing.einstellungen_speichern(pfad, cfg, "Einrichtung")
try:
    print("  ✓ " + mailing.abgleichen(pfad, backups, benutzer="Einrichtung", liste_erzwingen=True).text())
except mailing.MailingFehler as exc:
    print("  ✗ " + str(exc))
    sys.exit(1)
PY

# ------------------------------------------------------------------ 7.
schritt "7. Prüfung"
alles_ok=1
c=$(curl -s -o /dev/null -w '%{http_code}' https://intern.rss-fb.com/health)
[ "$c" = "200" ] && ok "Intranet erreichbar (health 200)" || { warn "Intranet health: $c"; alles_ok=0; }
c=$(curl -s -o /dev/null -w '%{http_code}' https://intern.rss-fb.com/verteiler/)
[ "$c" = "303" ] && ok "Verteiler geschützt (ohne Login -> Login-Seite)" || { warn "Verteiler ohne Login: $c statt 303"; alles_ok=0; }
for name in projektabrechnung verteiler verteiler-hintergrund "$MAILING_CONTAINER" mailing-worker; do
    s=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)
    [ "$s" = "running" ] && ok "Container $name läuft" || { warn "Container $name: ${s:-fehlt}"; alles_ok=0; }
done
if docker exec verteiler python -c "import cryptography" >/dev/null 2>&1; then
    ok "Zertifikats-Anmeldung fürs Postfach verfügbar"
else
    warn "Verteiler-Image ohne cryptography – bitte erneut ausführen"; alles_ok=0
fi

schritt "Fertig"
[ "$alles_ok" = 1 ] && ok "Alles läuft. Der Abgleich mit dem Mailing-Tool läuft ab jetzt alle 10 Minuten." \
                    || warn "Bitte die Punkte mit '!' oben prüfen."
cat <<TXT

  Noch von Hand (nur einmal, Postfach per Zertifikat):
   https://intern.rss-fb.com/verteiler/ -> Postfach -> Postfach-Adresse eintragen
   -> "Zertifikat erzeugen" -> .cer herunterladen. Die Seite führt durch:
   App in Entra anlegen + .cer hochladen, IDs eintragen, Exchange-Befehl
   (wird mit deinen Werten angezeigt), "Verbindung testen", automatisch abrufen.
  Kampagnen im Mailing-Tool an die Liste "Verteiler: Alle aktiven" schicken.
TXT
if [ "${NEUES_SECRET:-0}" = 1 ]; then
cat <<TXT

  WICHTIG – TimeMoto umstellen (sonst keine neuen Buchungen):
   cat $URL_DATEI
   Diese URL in TimeMoto als Webhook-Adresse eintragen (ersetzt die alte).
TXT
fi
