#!/bin/sh
# Richtet den Caddy-Dienst des Servers für intern.rss-fb.com ein
# (FBE Intranet + E-Mail-Verteiler unter /verteiler/).
#
# Ersetzt in /etc/caddy/Caddyfile den Block "intern.rss-fb.com { ... }" durch
# deploy/caddy-intern.snippet. Alle anderen Seiten bleiben unverändert.
#
# Sicherheitsnetz:
# - prüft vorher: Snippet vorhanden, genau EIN intern-Block, neue Config gültig
#   (caddy validate auf einer Kopie) – sonst wird nichts geändert
# - legt ein Backup an (Caddyfile.bak-<Datum>)
# - lädt Caddy neu und ruft danach /health auf; schlägt das fehl, wird der
#   alte Stand automatisch zurückgespielt
#
# Aufruf auf dem Server:  sh /root/projektabrechung/deploy/caddy-einrichten.sh
set -eu

CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
CADDY="${CADDY:-caddy}"
RELOAD="${RELOAD:-systemctl reload caddy}"
HEALTH_URL="${HEALTH_URL:-https://intern.rss-fb.com/health}"

DIR=$(cd "$(dirname "$0")" && pwd)
SNIP="$DIR/caddy-intern.snippet"

fehler() { echo "ABGEBROCHEN: $*"; exit 1; }

[ -f "$SNIP" ] && grep -q "forward_auth" "$SNIP" || fehler "$SNIP fehlt – nichts geändert."
[ -f "$CADDYFILE" ] || fehler "$CADDYFILE nicht gefunden – nichts geändert."
anzahl=$(grep -c '^intern\.rss-fb\.com[[:space:]]*{' "$CADDYFILE" || true)
[ "$anzahl" = 1 ] || fehler "erwartet genau 1 Block 'intern.rss-fb.com {' in $CADDYFILE, gefunden: $anzahl – nichts geändert."

NEU=$(mktemp)
trap 'rm -f "$NEU"' EXIT

# Block ersetzen – mit Markierungen (nach dem ersten Lauf) oder ohne (Erstlauf).
awk -v SNIP="$SNIP" '
function einfuegen(  l) { while ((getline l < SNIP) > 0) print l; close(SNIP); n++ }
skip == 1 { if ($0 ~ /^# <<< Ende Block intern\.rss-fb\.com/) skip = 0; next }
skip == 2 { if ($0 ~ /^}[ \t]*$/) skip = 0; next }
/^# >>> Block intern\.rss-fb\.com/ { einfuegen(); skip = 1; next }
/^intern\.rss-fb\.com[ \t]*\{/     { einfuegen(); skip = 2; next }
{ print }
END { if (n != 1 || skip != 0) exit 3 }
' "$CADDYFILE" > "$NEU" || fehler "Block konnte nicht ersetzt werden – nichts geändert."

[ "$(grep -c '^intern\.rss-fb\.com[[:space:]]*{' "$NEU")" = 1 ] || fehler "Ergebnis unplausibel – nichts geändert."

if ! "$CADDY" validate --config "$NEU" --adapter caddyfile >/dev/null 2>&1; then
    "$CADDY" validate --config "$NEU" --adapter caddyfile 2>&1 | tail -3
    fehler "neue Konfiguration ungültig – nichts geändert."
fi

BAK="$CADDYFILE.bak-$(date +%F-%H%M%S)"
cp -p "$CADDYFILE" "$BAK"
cat "$NEU" > "$CADDYFILE"

zurueck() {
    cat "$BAK" > "$CADDYFILE"
    $RELOAD || true
    fehler "$1 – alter Stand aus $BAK wiederhergestellt."
}

$RELOAD || zurueck "Caddy konnte nicht neu geladen werden"
sleep 3
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" || true)
[ "$code" = 200 ] || zurueck "$HEALTH_URL antwortet mit '$code' statt 200"

echo "FERTIG: Caddy neu geladen, $HEALTH_URL antwortet mit 200. Backup: $BAK"
