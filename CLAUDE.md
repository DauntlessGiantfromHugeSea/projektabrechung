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
- Deploy: `https://intern.rss-fb.com` hinter `fbe-caddy`.
- **Pfad auf dem Server:** `/root/projektabrechnung/` (Update: dort
  `git pull origin claude/relaxed-hawking-VJjx3`, dann in `deploy/`
  `docker compose up --build -d`).
- Entwicklungs-Branch: `claude/relaxed-hawking-VJjx3`.
- Secrets nur in `deploy/.env` – niemals committen.
