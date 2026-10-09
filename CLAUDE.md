# Projektkontext / Notizen für Claude

## Obsidian-Vault des Nutzers
- **Vault-Pfad (lokaler Windows-Rechner):**
  `C:\Users\dm\OneDrive - Flüssigboden Engineering GmbH\Desktop\FBE`
- Updates/Änderungsprotokolle sollen als **Obsidian-taugliche Markdown-Notizen**
  in dieses Vault (bestehendes Projekt) gehören.
- **Wichtig:** Läuft Claude Code in der **Cloud** (dieser Container), ist dieser
  lokale Pfad **nicht** erreichbar. Dann: Notiz erzeugen, ins Repo unter `docs/`
  ablegen **und** dem Nutzer als Datei schicken (er kopiert sie ins Vault; via
  OneDrive synchronisiert sie sich). Läuft Claude Code **lokal** auf seinem PC,
  kann direkt in den Pfad geschrieben werden.

## Tool
- **FBE Intranet** – internes Tool der Flüssigboden Engineering GmbH
  (TimeMoto-Zeiten, Projektabrechnung, Tickets, Exporte).
- Deploy: `https://intern.rss-fb.com` hinter dem **Caddy-Systemdienst** des
  Servers (`/etc/caddy/Caddyfile`, Caddy 2.6, Apps über `127.0.0.1:<port>`).
  Der Container `fbe-caddy` bekommt keinen Verkehr.
- **Pfad auf dem Server:** `/root/projektabrechung/`. Update/Einrichtung von
  Intranet, Verteiler und Mailing-Tool in einem Schritt:
  `cd /root/projektabrechung && git pull origin main && sh deploy/einrichten.sh`.
- Hauptbranch: `main` (der frühere Entwicklungs-Branch
  `claude/relaxed-hawking-VJjx3` ist darin aufgegangen).
- **E-Mail-Verteiler** (`verteiler/`): eigener Container `verteiler`
  (Streamlit, SQLite im Volume `verteiler-daten`) unter
  `https://intern.rss-fb.com/verteiler/`. Zugriff nur für Intranet-Admins
  (Caddy `forward_auth` + Prüfung in der App über `/auth/verteiler`).
  Einrichtung: `deploy/DEPLOY.md`, Abschnitt „E-Mail-Verteiler“;
  Caddy-Block per `deploy/caddy-einrichten.sh`. Zweiter Container
  `verteiler-hintergrund`: Postfach abrufen (empfohlen per Zertifikat/App-only,
  Schlüssel `/data/postfach_zertifikat.key`, eigene App „FBE Verteiler Postfach“,
  Exchange-RBAC auf ein Postfach; alternativ Microsoft-Login des Intranets mit
  Umleitungs-URI `https://intern.rss-fb.com/verteiler/`) und Abgleich mit dem Mailing-Tool
  (`mailing.rss-fb.com`, Repo `DauntlessGiantfromHugeSea/mailing`,
  `POST /api/integration/verteiler`, Token `MAILING_SYNC_TOKEN` =
  `VERTEILER_SYNC_TOKEN` dort). Einstellungen dazu im Backend des Verteilers.
- Secrets nur in `deploy/.env` – niemals committen.
