# E-Mail-Verteiler (Reach)

Lokales Werkzeug, das den E-Mail-Verteiler in **einer** SQLite-Datei
(`verteiler.db`) verwaltet: die Datenbank ist die *Single Source of Truth*.
Statt vor jeder Kampagne alte Listen neu in Reach hochzuladen, wird aus der
Datenbank ein bereinigtes Segment exportiert. Unzustellbare, abgemeldete und
gesperrte Adressen kommen dabei **nie** wieder mit.

Anlass: Die letzte Kampagne hatte 26,8 % harte Bounces (1.399 von 5.220),
Hostinger warnt vor einer Versandsperre.

- Python 3.10+, SQLite, läuft unter Windows
- Oberfläche: Streamlit, auf dem Server hinter dem Intranet-Login
- Abhängigkeiten: nur `pandas` und `streamlit` (XLSX wird ohne Zusatzpaket gelesen)

---

## Starten

### Auf dem Server (Standard)

Der Verteiler läuft als Container `verteiler` neben dem Intranet unter
**<https://intern.rss-fb.com/verteiler/>** (Menüpunkt „E-Mail-Verteiler“ für
Administratoren). Anmeldung über das Intranet (Microsoft-Login, 2FA), Zugriff
nur für Administratoren. Einrichtung und Updates: `deploy/DEPLOY.md`,
Abschnitt „E-Mail-Verteiler“. Im Import-Protokoll steht, wer importiert,
gesperrt oder gelöscht hat.

### Lokal unter Windows (optional)

1. Python 3 installieren (python.org, beim Setup „Add Python to PATH“ anhaken).
2. Ordner `verteiler` an einen festen Ort kopieren, z. B. `C:\Verteiler\`.
   **Nicht** in einen synchronisierten OneDrive-/SharePoint-Ordner legen –
   die Datenbank enthält personenbezogene Daten, und die Synchronisierung
   kann die Datenbankdatei beschädigen.
3. Doppelklick auf **`start.bat`**.
   Beim ersten Start wird eine eigene Python-Umgebung (`.venv`) angelegt und
   pandas/streamlit installiert, das dauert ein paar Minuten.
4. Der Browser öffnet <http://localhost:8501>. Falls die Seite noch nicht
   lädt, nach ein paar Sekunden neu laden.

Beenden: das schwarze Fenster schließen.

### Manuell (Windows, macOS, Linux)

```bash
cd verteiler
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Optional lassen sich die Pfade per Umgebungsvariable ändern:
`VERTEILER_DB` (Datenbankdatei) und `VERTEILER_BACKUPS` (Backup-Ordner).
Im Container: `VERTEILER_MODUS=server` und `VERTEILER_AUTH_URL` (siehe
`deploy/docker-compose.yml`).

---

## Erstes Einrichten (einmalig)

1. **Kontaktliste importieren** – die bestehende Gesamtliste (CSV/XLSX).
   Spalten zuordnen, bei „Quelle für leere Zeilen“ z. B. `Altliste` eintragen.
   Die Vorschau zeigt *neu / Dublette / ungültig / gesperrt*, erst danach wird
   geschrieben.
2. **Kampagnen-Report importieren** – den Empfänger-Export der letzten
   Kampagne (die mit den 26,8 % Bounces). Kampagnenname und Versanddatum
   eintragen. Danach stehen alle 1.399 unzustellbaren Adressen auf der
   Sperrliste.
3. Falls vorhanden: **Sperrliste importieren** – weitere Listen mit
   Abgemeldeten/Unzustellbaren (z. B. aus Reach oder älteren Aktionen).
4. **Export für Reach → „Alle aktiven“** herunterladen und in Reach als
   **neue** Liste hochladen. Die alte Reach-Liste nicht mehr verwenden.

## Ablauf nach jeder Kampagne

1. In Reach bei der Kampagne die Registerkarte **Empfänger** als CSV
   exportieren (sinnvoll ca. 3–7 Tage nach dem Versand, wenn Bounces und
   Öffnungen vollständig sind).
2. Im Tool **Kampagnen-Report importieren**: neue Kampagne anlegen (Name,
   Betreff, Versanddatum), Datei hochladen, Statuswerte prüfen, importieren.
   - *Unzustellbar* → sofort Sperrliste (harter Bounce)
   - *Abgemeldet* → Sperrliste (abgemeldet)
   - *Soft-Bounce* → Zähler; beim **3. Soft-Bounce in Folge** wie ein harter Bounce
   - Später exportierter Report derselben Kampagne? „Bestehende Kampagne“
     wählen – die Werte werden aktualisiert, nichts wird doppelt gezählt.
3. **Dashboard** ansehen: Bounce-Rate über 2 % wird rot markiert.
4. Vor der nächsten Kampagne **Export für Reach**: Segment wählen,
   CSV herunterladen, in Reach als neue Liste hochladen.
   - *Alle aktiven* – Normalfall
   - *Engagierte* – in den letzten 90 Tagen geöffnet oder geklickt (einstellbar)
   - *Inaktive* – schon länger im Verteiler, aber seit 180 Tagen keine
     Öffnung/kein Klick (für eine Reaktivierungsmail; einstellbar)
5. Neue Adressen (Webinar, Messe …) jederzeit über **Kontaktliste
   importieren** oder einzeln unter **Kontakte suchen / bearbeiten** ergänzen
   – mit Quelle und Einwilligung.

---

## Funktionen

| Bereich | Was passiert |
|---|---|
| Kontaktliste importieren | CSV/XLSX (z. B. Kontakt-Export aus Reach), Spalten zuordnen, E-Mail normalisieren (klein, getrimmt), Syntax prüfen, Dubletten zusammenführen („nur leere Felder ergänzen“ oder „überschreiben“), gesperrte Adressen überspringen, **Abo-Status** auswerten (siehe unten), Vorschau vor dem Schreiben |
| Kampagnen-Report importieren | Reach-Empfänger-CSV → `campaign_events`, Kontaktstatus und Sperrliste aktualisieren |
| Sperrliste importieren | Nur Adressen sperren (mit Grund aus Datei oder einheitlichem Grund), auch einzelne Adresse |
| Export für Reach | CSV mit `E-Mail, Vorname, Nachname` (UTF-8 mit BOM, Komma oder Semikolon) |
| Dashboard | Kontakte je Status, Bounce-Rate, Öffnungsrate (bezogen auf versendet und auf zugestellt), Warnung bei > 2 % |
| Kontakte suchen / bearbeiten | Stammdaten und Einwilligung pflegen, Kampagnenhistorie, manuell sperren, DSGVO-Löschung |
| Postfach | Mit Microsoft verbinden, Adressen aus Mails an das Verteiler-Postfach (Absender, An, CC, Mailtext) automatisch übernehmen, Übersicht, Abruf per Knopf |
| Mailing-Tool | Abgleich mit `mailing.rss-fb.com`: Sperrliste hin, Empfängerliste hin, Abmeldungen/Bounces zurück |
| Sperrliste & Protokoll | Sperrliste durchsuchen, Kampagnen, Import-Protokoll, Backups |

### Abo-Status (z. B. „Subscription Status“ aus Reach)

Hat die Kontaktliste eine Spalte wie `Subscription Status`, wird sie
automatisch erkannt (`Subscribed At` wird als Einwilligungsdatum erkannt):

| Wert | Ergebnis |
|---|---|
| `subscribed` (oder leer) | normaler Import |
| `unsubscribed`, abgemeldet | Adresse kommt auf die **Sperrliste** (abgemeldet), ein bestehender Kontakt wird gesperrt |
| `bounced`, `cleaned` | Sperrliste (harter Bounce) |
| `complained`, spam | Sperrliste (Beschwerde) |
| alles andere, z. B. `pending` | **nicht** importiert (im Zweifel nicht anschreiben), in der Vorschau aufgelistet |

Steht dieselbe Adresse mehrfach in der Datei, gewinnt „abgemeldet“.

### Postfach (Microsoft 365)

Das Tool kann ein Postfach lesen, z. B. `verteiler@fb-eng.de`. Aus jeder
Mail, die dort ankommt (weitergeleitet, in CC gesetzt oder direkt geschickt),
werden alle Adressen aus **Absender, An, CC und dem Mailtext** übernommen, mit
Namen, wo einer erkennbar ist (z. B. `Max Muster <max@…>`).

- **Verbinden im Backend:** Seite **Postfach** → „Mit Microsoft verbinden“.
  Genutzt wird die Microsoft-App des Intranet-Logins mit der eigenen
  Umleitungs-URI `https://intern.rss-fb.com/verteiler/`. Postfach-Adresse,
  eigene Domains und „Automatisch abrufen“ werden dort eingestellt.
- Übersprungen werden: eigene Domains (Standard: Domain des Postfachs), das
  Postfach selbst, Systemadressen (noreply, mailer-daemon, postmaster, bounce …),
  ungültige Adressen und alles auf der Sperrliste.
- Bestehende Kontakte werden nur ergänzt (leere Namen), nie überschrieben.
- Neue Kontakte bekommen als Quelle „Postfach: <Betreff>“. **Einwilligung
  nachtragen**, bevor sie einen Newsletter bekommen (§ 7 UWG).
- **Nur lesend** (Mail.Read / Mail.Read.Shared). Das Tool verschiebt oder löscht
  keine Mails. Jede Mail wird nur einmal ausgewertet. Gespeichert werden nur
  Betreff, Zeitpunkt und Zahlen (Tabelle `mail_eingang`).
- Das Refresh-Token liegt in `/data/postfach_token.json` (0600), nicht in der
  Datenbank und nicht in den Backups, und wird nie angezeigt.
- Als Anhang weitergeleitete Mails (.msg/.eml) werden nicht geöffnet. Bitte
  „normal“ weiterleiten.

### Abgleich mit dem Mailing-Tool

Seite **Mailing-Tool**: Der Verteiler gleicht sich mit `mailing.rss-fb.com` ab.
Das passiert automatisch alle 10 Minuten (wenn eingeschaltet) oder per Knopf:

- Die **Sperrliste** des Verteilers wird dort übernommen, geplante Sendungen an
  gesperrte Adressen werden abgebrochen.
- Die Empfänger des gewählten Segments (Alle aktiven oder Engagierte) landen dort
  in der Liste **„Verteiler: Alle aktiven“** (Name einstellbar). Sie wird nur bei
  Änderungen neu übertragen, sonst höchstens einmal am Tag.
- **Abmeldungen, Bounces und Beschwerden** aus dem Mailing-Tool kommen hier auf
  die Sperrliste und damit nie wieder in einen Export.
- Zugang: `MAILING_SYNC_TOKEN` in `deploy/.env` (= `VERTEILER_SYNC_TOKEN` im
  Mailing-Tool), nur über HTTPS.

Hintergrund-Container: `verteiler-hintergrund` (Postfach + Mailing-Abgleich).

### Kennzahlen

- **versendet** = alle Empfänger außer „nicht zugestellt“
- **Bounce-Rate** = (harte + weiche Bounces) / versendet
- **Öffnungsrate** = Empfänger mit mindestens einer Öffnung / versendet;
  zusätzlich / zugestellt
- Engagement-Segmente beziehen sich auf das **Versanddatum** der Kampagne,
  weil der Reach-Report keinen Öffnungszeitpunkt enthält.

### Reach-Report: erkannte Statuswerte

Die Statuswerte werden automatisch zugeordnet (Groß-/Kleinschreibung und
Bindestriche egal). Unbekannte Werte zeigt die Vorschau an. Sie werden
übersprungen, bis man sie per Auswahlfeld zuordnet.

| Reach | Ziel |
|---|---|
| Zugestellt, Delivered, Geöffnet, Geklickt | zugestellt |
| Unzustellbar, Hard Bounce, Bounced | unzustellbar → Sperrliste |
| Soft-Bounce, Soft Bounce | soft_bounce (Zähler) |
| Nicht zugestellt, Not sent, Ausstehend | nicht_zugestellt (neutral, unterbricht die Soft-Bounce-Serie nicht) |
| Abgemeldet, Unsubscribed | abgemeldet → Sperrliste |
| Beschwerde, Spam, Complaint | zugestellt + Sperrliste (Beschwerde) |

`Geöffnet`/`Geklickt` dürfen Zahlen oder Ja/Nein sein.

---

## Schutzregeln

- **Sperrliste ist endgültig.** Einträge können weder geändert noch gelöscht
  werden. Die Datenbank erzwingt das selbst (SQLite-Trigger), also auch dann,
  wenn jemand die Datei mit einem anderen Programm öffnet.
- Gesperrte Adressen werden **nie exportiert**, **nie wieder aktiviert** und
  beim Import **übersprungen**. Der Export prüft das zweimal: einmal in der
  Abfrage, einmal unabhängig davon vor der Ausgabe.
- Ein Kontakt, der auf der Sperrliste steht, kann nicht gelöscht werden.
  Einzige Ausnahme ist **„Kontakt vollständig löschen (DSGVO)“**: Dafür muss
  man die E-Mail-Adresse noch einmal eintippen. Standardmäßig bleibt dabei nur
  die Adresse auf der Sperrliste stehen, damit sie nicht über eine alte Liste
  zurückkommt. Das lässt sich abwählen.
- Jede Schreiboperation läuft in **einer Transaktion**. Bei einem Fehler wird
  alles zurückgerollt, halbe Importe gibt es nicht.
- **Vor jedem Import** legt das Tool automatisch ein Backup an:
  `backups/verteiler_JJJJMMTT_HHMMSS.db`, die neuesten 100 werden aufbewahrt.
- **Server:** Zugriff nur für angemeldete Intranet-Administratoren. Der
  Caddy-Dienst des Servers prüft jede Anfrage (`forward_auth`), und die App prüft selbst noch einmal
  über `VERTEILER_AUTH_URL`. Ist das Intranet nicht erreichbar oder die
  Variable nicht gesetzt, bleibt der Verteiler gesperrt. Der Container läuft
  ohne root, Port 8501 ist nur auf `127.0.0.1` veröffentlicht.
- **Lokal (Windows):** Die Oberfläche lauscht nur auf `localhost` und ist
  **nicht** aus dem Netzwerk erreichbar (`.streamlit/config.toml`).
- Namen im Export werden gegen Formel-Injection in Excel geschützt (Werte, die
  mit `= + - @` beginnen, bekommen ein `'` vorangestellt).
- `verteiler.db`, `backups/` und alle CSV/XLSX-Dateien im Ordner sind per
  `.gitignore` vom Repository ausgeschlossen. Echte Daten gehören nie ins Git.

### Backup zurückspielen

Server: `docker compose stop verteiler`, dann im Container-Volume das
gewünschte Backup nach `verteiler.db` kopieren (z. B. per
`docker run --rm -v projektabrechnung_verteiler-daten:/data alpine cp
/data/backups/verteiler_….db /data/verteiler.db`), `docker compose start verteiler`.

Lokal: Tool beenden, `verteiler.db` umbenennen (z. B. `verteiler_kaputt.db`), das
gewünschte Backup aus `backups/` nach `verteiler.db` kopieren, Tool starten.

### Hinweis DSGVO

Backups sind vollständige Kopien. Nach einer DSGVO-Löschung steckt der
Kontakt noch in älteren Backups. Wer das ausschließen muss, löscht die
Backups, die älter als die Löschung sind.

---

## Datenmodell

| Tabelle | Inhalt |
|---|---|
| `contacts` | id, email (UNIQUE, klein/getrimmt), vorname, nachname, firma, quelle, einwilligung_art, einwilligung_datum, status (aktiv / bounce_hart / bounce_weich / abgemeldet / gesperrt), soft_bounce_folge, erstellt_am, geaendert_am |
| `campaigns` | id, name, betreff, gesendet_am, empfaenger_anzahl |
| `campaign_events` | contact_id, campaign_id, geoeffnet, geklickt, zustellstatus (zugestellt / unzustellbar / soft_bounce / nicht_zugestellt / abgemeldet) – je Kontakt und Kampagne genau ein Eintrag |
| `suppression_list` | email (UNIQUE), grund (bounce_hart / abgemeldet / beschwerde / manuell), datum |
| `import_log` | zeitpunkt, art, benutzer, dateiname, neu, aktualisiert, uebersprungen, details (JSON mit allen Zahlen, ohne personenbezogene Daten) |
| `mail_eingang` | message_id, empfangen_am, betreff, gefunden, neu, bekannt, gesperrt, ignoriert, verarbeitet_am – ausgewertete Mails aus dem Postfach |
| `einstellungen` | Einstellungen aus dem Backend (Postfach, Mailing-Tool) – keine Geheimnisse |
| `oauth_state` | offene „Mit Microsoft verbinden“-Vorgänge (einmalig, 15 Minuten gültig) |

Kontaktstatus aus der Sperrliste: bounce_hart → `bounce_hart`,
abgemeldet → `abgemeldet`, beschwerde/manuell → `gesperrt`.
`bounce_weich` (1–2 Soft-Bounces in Folge) bleibt versandfähig, sonst könnte
die Serie die Grenze von 3 nie erreichen. Eine Zustellung setzt den Status
wieder auf `aktiv`.

Dateien: CSV werden als UTF-8 (mit oder ohne BOM) gelesen. Kommt eine Datei
in Windows-1252 an, warnt die Vorschau. Das Trennzeichen (`;` oder `,`) wird
automatisch erkannt. Exporte sind UTF-8 mit BOM.

---

## Tests

```bash
cd verteiler
python -m unittest discover -s tests -v
```

Die Tests laufen mit Beispieldaten auf einer temporären Datenbank. Darunter
ist die Probe mit je 20 Zeilen *neu, Dublette, ungültige Syntax, gesperrt*.
Außerdem geprüft werden: Report-Status, 3 Soft-Bounces in Folge,
Unterbrechung der Serie, erneuter Import ohne Doppelzählung, Export ohne
gesperrte Adressen, Segmente, Kennzahlen, Trigger-Schutz, Rollback, Backup
und DSGVO-Löschung.

`python tests/beispieldaten.py` schreibt Beispieldateien nach
`beispieldaten/` zum Ausprobieren der Oberfläche (nur Test-Domains
`example.com/.org/.net`). Empfohlene Reihenfolge: `2_sperrliste.csv`
(Sperrliste importieren), `1_bestand.csv` und
`3_kontaktliste_80_zeilen.csv` (Kontaktliste importieren),
`4_reach_report.csv` (Kampagnen-Report importieren).
