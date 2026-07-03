"""
Dokumentation: Anleitung (alle Funktionen) + Admin-Dokumentation.

Der Inhalt ist strukturiert hinterlegt und wird in der Online-Hilfe
(/anleitung) gerendert.

Blocktypen: p, h3, ul, ol, code, note, table, fig.
"""

from __future__ import annotations

BRAND = "#92c57a"
DEEP = "#2f6b1f"
INK = "#1b2a20"

# --- Abbildungen (Inline-SVG, nur Online-Hilfe) -----------------------------

def _fig_flow() -> str:
    box = ("<rect x='{x}' y='{y}' width='{w}' height='46' rx='10' "
           "fill='{f}' stroke='{s}' stroke-width='1.5'/>"
           "<text x='{tx}' y='{ty}' text-anchor='middle' font-size='13' "
           "font-weight='700' fill='{tf}'>{t}</text>")
    arrow = ("<path d='M{x1} {y} h{l}' stroke='#9aad93' stroke-width='2' "
             "fill='none'/><path d='M{x2} {ym} l-7 -4 v8 z' fill='#9aad93'/>")
    parts = ["<svg viewBox='0 0 660 150' xmlns='http://www.w3.org/2000/svg' "
             "style='max-width:100%;height:auto' role='img' "
             "aria-label='Datenfluss'>"]
    parts.append(box.format(x=6, y=50, w=120, f="#eef5e8", s=BRAND,
                            tx=66, ty=78, tf=DEEP, t="TimeMoto"))
    parts.append(arrow.format(x1=128, y=73, l=40, x2=170, ym=73))
    parts.append(box.format(x=172, y=50, w=110, f="#fff", s="#d5ddd0",
                            tx=227, ty=78, tf=INK, t="Webhook"))
    parts.append(arrow.format(x1=284, y=73, l=40, x2=326, ym=73))
    parts.append(box.format(x=328, y=50, w=130, f=BRAND, s=BRAND,
                            tx=393, ty=78, tf="#16330f", t="FBE Intranet"))
    for i, label in enumerate(("E-Mail-Berichte", "Excel-Export",
                               "Amprion-CSV")):
        y = 8 + i * 50
        parts.append(f"<path d='M460 73 C500 73 500 {y+23} 520 {y+23}' "
                     "stroke='#9aad93' stroke-width='2' fill='none'/>")
        parts.append(box.format(x=522, y=y, w=132, f="#fff", s="#d5ddd0",
                                tx=588, ty=y + 28, tf=INK, t=label))
    parts.append("</svg>")
    return "".join(parts)


def _fig_nav() -> str:
    pill = ("<rect x='{x}' y='16' width='{w}' height='30' rx='15' "
            "fill='{f}'/><text x='{tx}' y='36' text-anchor='middle' "
            "font-size='12.5' font-weight='600' fill='{tf}'>{t}</text>")
    return (
        "<svg viewBox='0 0 660 62' xmlns='http://www.w3.org/2000/svg' "
        "style='max-width:100%;height:auto' role='img' aria-label='Kopfleiste'>"
        f"<rect x='0' y='0' width='660' height='62' rx='12' fill='{BRAND}'/>"
        "<rect x='14' y='14' width='64' height='34' rx='9' fill='#fff' "
        "opacity='.95'/><text x='46' y='36' text-anchor='middle' "
        f"font-size='13' font-weight='800' fill='{DEEP}'>FBE</text>"
        + pill.format(x=92, w=104, f="#ffffff", tf=DEEP, t="Dashboard",
                      tx=144)
        + pill.format(x=202, w=160, f="none", tf="#ffffff",
                      t="Projektabrechnung ▾", tx=282)
        + pill.format(x=366, w=86, f="none", tf="#ffffff", t="Tickets ▾",
                      tx=409)
        + "<circle cx='598' cy='31' r='15' fill='#fff'/>"
        f"<text x='598' y='36' text-anchor='middle' font-size='11' "
        f"font-weight='800' fill='{DEEP}'>DM</text>"
        "<circle cx='556' cy='31' r='13' fill='none' stroke='#fff' "
        "stroke-width='1.6'/><text x='556' y='36' text-anchor='middle' "
        "font-size='13' font-weight='700' fill='#fff'>?</text>"
        "</svg>")


def _fig_desc() -> str:
    return (
        "<svg viewBox='0 0 660 170' xmlns='http://www.w3.org/2000/svg' "
        "style='max-width:100%;height:auto' role='img' "
        "aria-label='Tätigkeitsbeschreibung bearbeiten'>"
        "<rect x='0' y='0' width='660' height='44' rx='10' fill='#fff' "
        "stroke='#e6eae1'/>"
        "<text x='16' y='27' font-size='12.5' fill='#1b2a20'>Mi 01.07.  ·  "
        "Amprion – HE1 32005  ·  08:00–16:00  ·  8:00 h</text>"
        f"<text x='452' y='27' font-size='12.5' font-weight='700' "
        f"fill='{DEEP}'>+ Tätigkeit eintragen</text>"
        "<path d='M598 18 l8 -8 m-8 8 l-3 1 1 -3 8 -8 2 2 z' "
        "stroke='#6a7870' stroke-width='1.4' fill='none'/>"
        "<path d='M60 52 v10' stroke='#9aad93' stroke-width='2'/>"
        "<rect x='0' y='66' width='660' height='100' rx='10' fill='#fdfefc' "
        "stroke='#d5ddd0'/>"
        "<rect x='14' y='78' width='500' height='44' rx='8' fill='#fff' "
        "stroke='#dbe1d5'/>"
        "<text x='24' y='104' font-size='12' fill='#6a7870'>Bauüberwachung "
        "Abschnitt Nord, Doku und Abstimmung mit ARGE.</text>"
        f"<rect x='14' y='130' width='104' height='26' rx='8' fill='{BRAND}'/>"
        "<text x='66' y='147' text-anchor='middle' font-size='12' "
        "font-weight='700' fill='#16330f'>✓ Speichern</text>"
        "</svg>")


def _fig_roles() -> str:
    row = ("<rect x='{x}' y='{y}' width='{w}' height='34' rx='9' fill='{f}' "
           "stroke='{s}'/><text x='{tx}' y='{ty}' font-size='12' "
           "font-weight='700' fill='{tf}'>{t}</text>"
           "<text x='{dx}' y='{ty}' font-size='11.5' fill='#4c5a50'>{d}</text>")
    return (
        "<svg viewBox='0 0 660 140' xmlns='http://www.w3.org/2000/svg' "
        "style='max-width:100%;height:auto' role='img' aria-label='Rollen'>"
        + row.format(x=0, y=0, w=660, f="#eef5e8", s=BRAND, tx=14, ty=22,
                     tf=DEEP, t="admin", dx=140,
                     d="alles – zusätzlich Benutzer, Einstellungen, Texte, Projekte")
        + row.format(x=0, y=44, w=660, f="#f6f9f3", s="#cfdbc6", tx=14,
                     ty=66, tf=DEEP, t="buchhaltung", dx=140,
                     d="Bericht, Log, Abrechnung, Exporte, Zeiten korrigieren")
        + row.format(x=0, y=88, w=660, f="#fff", s="#d5ddd0", tx=14, ty=110,
                     tf=INK, t="user", dx=140,
                     d="Meine Zeiten, eigene Buchungen nachtragen, Tickets (je nach Recht)")
        + "</svg>")


# --- Inhalt: Anleitung (alle Funktionen) ------------------------------------

def user_sections(ms_enabled: bool = True) -> list[dict]:
    s: list[dict] = []
    s.append({"id": "ueberblick", "title": "Überblick", "blocks": [
        {"t": "p", "html": "Das <b>FBE Intranet</b> ist das interne Tool der "
         "Flüssigboden Engineering GmbH. Es übernimmt die Zeitbuchungen "
         "automatisch aus TimeMoto und macht daraus Projektberichte, "
         "Abrechnungen und Exporte – dazu kommen ein Ticketsystem und "
         "Verwaltungsfunktionen."},
        {"t": "fig", "svg": _fig_flow(),
         "caption": "Datenfluss: TimeMoto liefert Stempelungen per Webhook; "
                    "das Intranet erzeugt Berichte und Exporte."},
        {"t": "ul", "items": [
            "Erreichbar unter <code>https://intern.rss-fb.com</code> – am "
            "PC, Tablet und Handy.",
            "Korrekturen, die in <b>TimeMoto</b> gemacht werden (Zeiten, "
            "Projekt, Löschen), übernimmt das Tool automatisch.",
            "Das Tool lässt sich als <b>App installieren</b> (siehe unten)."]},
    ]})
    login_items = []
    if ms_enabled:
        login_items.append("<b>Mit Microsoft anmelden</b> – Firmen-Konto; "
                           "die Sicherheit (MFA) übernimmt Microsoft.")
    login_items += [
        "<b>Passwort-Login</b> (Admins / externe Konten) über den Link "
        "„Mit Passwort anmelden“. Nach dem Passwort folgt die "
        "<b>Zwei-Faktor-Bestätigung</b> (6-stelliger Code aus einer "
        "Authenticator-App; Einrichtung per QR-Code bei der ersten Anmeldung).",
        "<b>Passwort vergessen?</b> – Link auf der Login-Seite; der "
        "Reset-Link kommt per E-Mail (60 Minuten gültig).",
        "<b>Abmelden</b> über das Avatar-Menü oben rechts."]
    s.append({"id": "anmeldung", "title": "Anmeldung & Sicherheit",
              "blocks": [{"t": "ul", "items": login_items}]})
    s.append({"id": "dashboard", "title": "Start / Dashboard", "blocks": [
        {"t": "p", "html": "Nach der Anmeldung landest du auf dem Dashboard. "
         "Über die grüne Kopfleiste erreichst du alle Bereiche:"},
        {"t": "fig", "svg": _fig_nav(),
         "caption": "Kopfleiste: Dashboard, Projektabrechnung, Tickets – "
                    "rechts Hilfe (?) und dein Konto."},
        {"t": "ul", "items": [
            "<b>Statistik-Karten</b>: Meine Stunden (Woche), Offene Tickets, "
            "<b>Zu erledigen</b> (Buchungen ohne Tätigkeitsbeschreibung – "
            "Klick öffnet „Meine Zeiten“) und Kalenderwoche.",
            "<b>Schnellzugriff</b>: Meine Zeiten, Buchung nachtragen, "
            "Stempeln &amp; Urlaub (TimeMoto) u. a.",
            "<b>Meine letzten Buchungen</b> mit Hinweis, wenn die "
            "Tätigkeitsbeschreibung fehlt.",
            "<b>Bereiche</b>-Kacheln – je nach deinen Rechten."]},
    ]})
    s.append({"id": "meine", "title": "Meine Zeiten", "blocks": [
        {"t": "p", "html": "Zeigt <b>deine eigenen Buchungen</b> der letzten "
         "60 Tage (Zuordnung über deinen TimeMoto-Namen). Oben siehst du "
         "Status-Chips (Stunden dieser Woche, fehlende Tätigkeiten); „Läuft "
         "gerade“ zeigt offene Stempelungen."},
        {"t": "h3", "text": "Tätigkeitsbeschreibung eintragen"},
        {"t": "p", "html": "Je Buchung ist eine kurze Beschreibung (1–2 "
         "Sätze) Pflicht – sie wird für Arcadis/Amprion gebraucht. Klicke in "
         "der Spalte „Tätigkeitsbeschreibung“ auf den Stift bzw. auf "
         "„+ Tätigkeit eintragen“:"},
        {"t": "fig", "svg": _fig_desc(),
         "caption": "Stift öffnet das Textfeld; nach dem Speichern steht der "
                    "Text mit ✓ in der Zeile."},
        {"t": "note", "html": "Fehlt die Beschreibung 24 h nach der Buchung, "
         "erinnert dich das Tool per E-Mail (max. 7 Tage zurück)."},
        {"t": "h3", "text": "Buchung vergessen?"},
        {"t": "ul", "items": [
            "<b>+ Buchung hinzufügen</b>: Projekt, Datum, Kommt/Geht und "
            "Tätigkeit eintragen – der Eintrag zählt wie eine normale "
            "Buchung und ist als „manuell“ gekennzeichnet.",
            "Eigene nachgetragene Buchungen kannst du <b>bearbeiten</b> und "
            "<b>löschen</b>; eigene TimeMoto-Buchungen kannst du "
            "<b>korrigieren</b> (das Original wird ersetzt).",
            "Falsches Projekt oder falsche Zeit gestempelt? Am einfachsten "
            "direkt <b>in TimeMoto korrigieren</b> – die Änderung übernimmt "
            "das Intranet automatisch."]},
    ]})
    s.append({"id": "tickets", "title": "Tickets", "blocks": [
        {"t": "ul", "items": [
            "<b>Neues Ticket</b>: Titel, Beschreibung, Priorität, Kategorie.",
            "Im Ticket: <b>Status</b> wechseln (Offen / In Arbeit / Gelöst / "
            "Geschlossen), <b>Mir zuweisen</b>, <b>Kommentare</b> schreiben, "
            "<b>Anhänge</b> hochladen.",
            "<b>Aufwände</b> je Ticket erfassen: Datum, Anfahrt (km), "
            "Stunden, Material, Tätigkeit – mit automatischer Summe.",
            "<b>Schließen</b>: optional mit Lösungstext – der Ersteller "
            "bekommt eine E-Mail, das Ticket wandert ins <b>Archiv</b> "
            "(Filter „Geschlossen“); Anhänge werden dabei entfernt.",
            "Rechte Seitenleiste: <b>Verlauf</b> aller Änderungen (wer hat "
            "wann was geändert)."]},
        {"t": "note", "html": "Ticket-Zugriff wird je Person vergeben: kein "
         "Zugriff / nur ansehen / ansehen &amp; bearbeiten."},
    ]})
    s.append({"id": "konto", "title": "Mein Konto", "blocks": [
        {"t": "ul", "items": [
            "<b>Passwort ändern</b> (nur Passwort-Konten).",
            "<b>Zwei-Faktor</b> neu einrichten – z. B. bei neuem Handy.",
            "Benutzername und Anzeigename ändert nur ein Administrator."]},
    ]})
    s.append({"id": "webapp", "title": "Als App installieren", "blocks": [
        {"t": "ul", "items": [
            "<b>iPhone/iPad</b> (Safari): Teilen-Symbol → „Zum "
            "Home-Bildschirm“.",
            "<b>Android</b> (Chrome): Menü → „App installieren“.",
            "<b>PC/Mac</b> (Chrome/Edge): Installieren-Symbol rechts in der "
            "Adressleiste.",
            "Die App startet im Vollbild direkt auf dem Dashboard."]},
    ]})
    s.append({"id": "rechte", "title": "Wer darf was?", "blocks": [
        {"t": "fig", "svg": _fig_roles(), "caption": "Die drei Rollen im "
         "Überblick – Zusatzrechte vergibt der Admin je Person."},
        {"t": "table",
         "head": ["Funktion", "user", "buchhaltung", "admin"],
         "rows": [
            ["Meine Zeiten, Buchung nachtragen", "✓", "✓", "✓"],
            ["Tickets (je nach Ticket-Recht)", "✓", "✓", "✓"],
            ["Bericht, Log, Abrechnung, Exporte", "–", "✓", "✓"],
            ["Zeiten aller Mitarbeiter korrigieren", "–*", "✓", "✓"],
            ["Benutzer, Einstellungen, Texte, Projekte", "–", "–", "✓"]]},
        {"t": "note", "html": "* Admins können einzelnen Personen zusätzlich "
         "das Recht <b>„Zeiten korrigieren“</b> geben – dann sehen sie das "
         "Log und dürfen Buchungen pflegen (ohne Exporte/Berichte)."},
    ]})
    return s


# --- Inhalt: Admin-Dokumentation --------------------------------------------

def admin_sections(webhook_url: str = "", secret: str = "") -> list[dict]:
    s: list[dict] = []
    s.append({"id": "adm-benutzer", "title": "Benutzerverwaltung", "blocks": [
        {"t": "p", "html": "Avatar-Menü → <b>Administration → Benutzer</b>."},
        {"t": "ul", "items": [
            "<b>Aus Microsoft importieren</b>: legt alle Tenant-Konten als "
            "Rolle <code>user</code> an; danach Rollen/Rechte je Person "
            "setzen.",
            "<b>Externe Benutzer</b>: unten anlegen – es entsteht ein "
            "Einladungslink (5 Tage gültig); die Person setzt ihr Passwort "
            "und richtet die Pflicht-2FA ein. Mit E-Mail-Adresse wird die "
            "Einladung direkt versendet.",
            "<b>Bearbeiten</b>: Benutzername (nur Admin), Anzeigename, "
            "E-Mail, <b>TimeMoto-Name</b> (exakt „Vorname Nachname“ wie in "
            "TimeMoto – verknüpft Konto und Stunden, kann vorab gesetzt "
            "werden), Rolle, Ticket-Zugriff, Recht „Zeiten korrigieren“.",
            "<b>Löschen</b> und <b>Einladung erneut senden</b> im "
            "Aktionen-Menü.",
            "Neue Rechte greifen nach der <b>nächsten Anmeldung</b> der "
            "Person."]},
        {"t": "h3", "text": "Support-Modus (Identität übernehmen)"},
        {"t": "ul", "items": [
            "Aktionen → <b>„Als Benutzer anmelden“</b>: du siehst das Tool "
            "exakt wie diese Person (zum Prüfen und Helfen).",
            "Oben erscheint ein oranges Banner mit <b>„Zurück zu meinem "
            "Account“</b>.",
            "Nur für aktive Konten; Beginn und Ende stehen im Verlauf."]},
    ]})
    s.append({"id": "adm-zeiten",
              "title": "Zeiten prüfen & korrigieren", "blocks": [
        {"t": "ul", "items": [
            "<b>Bericht</b> (Startseite der Projektabrechnung): Woche wählen "
            "oder mit ‹ › blättern, Projektfilter, Zusammenfassung je "
            "Mitarbeiter, Einzelbuchungen, „Diese Ansicht jetzt senden“, "
            "Exporte.",
            "<b>Log</b>: alle Buchungen mit Filtern und Schnellauswahl "
            "(Diese Woche / Letzte Woche / Dieser Monat). „Läuft gerade“ "
            "zeigt offene Stempelungen. Buchungen <b>ohne Projekt</b> sind "
            "markiert und können per „Korrigieren“ einem Projekt und ggf. "
            "anderem Mitarbeiter zugewiesen werden.",
            "<b>Eintrag hinzufügen</b> (für beliebige Mitarbeiter), "
            "TimeMoto-Buchungen <b>korrigieren</b> (Original wird "
            "ausgeblendet und ersetzt), <b>ausblenden</b> oder "
            "<b>endgültig löschen</b>; Ausgeblendetes lässt sich wieder "
            "einblenden.",
            "<b>Abrechnung</b>: alle Stunden filtern und als Excel oder "
            "Amprion-CSV herunterladen."]},
        {"t": "note", "html": "Korrekturen direkt <b>in TimeMoto</b> kommen "
         "automatisch über den Webhook: pro Buchung gewinnt das zuletzt "
         "empfangene Event (Zeiten und Projekt); Lösch-Events entfernen die "
         "Buchung. Manuelle Korrekturen im Tool sind dafür nicht nötig."},
    ]})
    s.append({"id": "adm-exporte", "title": "Exporte & Formate", "blocks": [
        {"t": "ul", "items": [
            "<b>Excel</b>: Buchungsliste mit Tätigkeiten plus Blatt „Je "
            "Mitarbeiter“ (Summen).",
            "<b>Amprion-CSV</b> (Abgabeformat): Semikolon-getrennt, UTF-8 "
            "mit BOM, CRLF, Stunden mit Dezimalkomma (z. B. 10,0), Name als "
            "„Nachname, Vorname“."]},
        {"t": "code", "text": "Datum;nicht relevant;Task Nr.;nicht relevant;"
         "Personen Name;Stunden;Tätigkeitbeschreibung"},
        {"t": "p", "html": "<b>Task-Nr.-Ermittlung</b> je Buchung: 1. manuelle "
         "Zuordnung aus der Projektverwaltung → 2. Amprion-Mapping "
         "(Übergreifend 35031, HE1–HE4 32005–32008) → 3. Nummer aus dem "
         "Projektnamen (z. B. „Amprion – HE4 32008“ → 32008)."},
    ]})
    s.append({"id": "adm-projekte",
              "title": "Projektverwaltung (Task-Nummern)", "blocks": [
        {"t": "ul", "items": [
            "<b>Administration → Projekte</b>: Liste aller erkannten "
            "Projekte.",
            "Grau = automatisch erkannte Task-Nr.; Feld „manuell“ "
            "überschreibt sie dauerhaft (für Projekte ohne Nummer im Namen "
            "oder zur Korrektur).",
            "Feld leeren = wieder Automatik."]},
    ]})
    s.append({"id": "adm-berichte", "title": "Automatische Berichte",
              "blocks": [
        {"t": "ul", "items": [
            "<b>Projektabrechnung → Berichte</b>: je Bericht Projekte "
            "(Teilstring genügt), Empfänger + CC, Nachricht, Format "
            "(Excel/Arcadis-CSV) sowie Wochentag + Uhrzeit festlegen.",
            "Versendet wird <b>nur</b>, was hier definiert und aktiv ist – "
            "nie automatisch „alle Projekte“.",
            "<b>jetzt senden</b> testet den Bericht sofort (Inhalt = vorige "
            "Woche). Die Mail enthält die Tabelle und einen "
            "Download-Link auf die Datei.",
            "<b>Senden</b> (Menüpunkt) verschickt einmalig einen frei "
            "definierten Zeitraum an beliebige Empfänger."]},
    ]})
    s.append({"id": "adm-texte", "title": "Texte anpassen", "blocks": [
        {"t": "ul", "items": [
            "<b>Administration → Texte</b>: Login-Texte (Pille oben, große "
            "Überschrift, Beschreibung, „Willkommen zurück“, Fußnote), "
            "Dashboard-Begrüßung + Unterzeile und App-Name.",
            "Änderungen wirken sofort; leeres Feld = Standardtext; "
            "„Auf Standard zurücksetzen“ stellt alles zurück."]},
    ]})
    s.append({"id": "adm-einstellungen",
              "title": "Einstellungen, Erinnerungen & Verlauf", "blocks": [
        {"t": "ul", "items": [
            "<b>Einstellungen</b>: Zeitzone (Wochengrenzen, Anzeige, "
            "Versandzeiten) und Test-E-Mails (Design/Versand prüfen).",
            "<b>Erinnerungen</b>: läuft stündlich automatisch – wer 24 h "
            "nach einer Buchung keine Tätigkeitsbeschreibung hat, bekommt "
            "eine Mail (max. 7 Tage zurück). „Jetzt prüfen“ stößt den Lauf "
            "sofort an.",
            "<b>Verlauf</b>: lückenloses Protokoll (Logins, Korrekturen, "
            "Mails, Rechte-Änderungen, Support-Modus …)."]},
    ]})
    wb = [
        {"t": "p", "html": "In der <b>TimeMoto Cloud</b> (Plus-Plan) unter "
         "<b>Einstellungen → Webhooks</b> diese Ziel-URL hinterlegen "
         "(Ereignisse: Ein-/Ausstempeln):"},
        {"t": "code", "text": webhook_url or "https://intern.rss-fb.com/timemoto"},
    ]
    if secret:
        wb += [{"t": "p", "html": "Hinterlegtes <b>Secret</b>:"},
               {"t": "code", "text": secret}]
    wb += [{"t": "ul", "items": [
        "Jedes Event wird roh gespeichert (<code>/data/events.jsonl</code>) "
        "– nichts geht verloren, auch Buchungen ohne Projekt.",
        "<b>Korrekturen</b> in TimeMoto senden neue Events mit derselben "
        "Vorgangs-ID – das zuletzt empfangene gewinnt. <b>Löschungen</b> "
        "werden erkannt und entfernen die Buchung.",
        "<code>/report/inspect</code> zeigt, welche Felder aus den letzten "
        "Events erkannt werden (Fehlersuche)."]}]
    s.append({"id": "adm-webhook", "title": "TimeMoto-Webhook", "blocks": wb})
    s.append({"id": "adm-server", "title": "Server & Betrieb", "blocks": [
        {"t": "p", "html": "Deployment auf dem Server (hinter "
         "<code>fbe-caddy</code>):"},
        {"t": "code", "text": "git pull origin claude/relaxed-hawking-VJjx3\n"
         "docker compose up --build -d"},
        {"t": "ul", "items": [
            "Konfiguration in <code>deploy/.env</code> (niemals ins Git): "
            "<code>BREVO_API_KEY</code> (Mail), <code>PUBLIC_BASE_URL</code>, "
            "<code>MS_CLIENT_ID / MS_CLIENT_SECRET / MS_TENANT_ID</code> "
            "(Microsoft-Login), <code>SHARED_SECRET</code> (Webhook), "
            "<code>SESSION_SECRET</code>, <code>ADMIN_USER / "
            "ADMIN_PASSWORD</code> (Bootstrap-Admin).",
            "Alle Daten liegen als JSON/JSONL unter <code>/data</code> "
            "(Events, Benutzer, Tickets, Einstellungen, Verlauf) – dieses "
            "Verzeichnis ins <b>Backup</b> aufnehmen.",
            "Logs: <code>docker compose logs -f</code>; Health-Check unter "
            "<code>/health</code>."]},
    ]})
    return s
