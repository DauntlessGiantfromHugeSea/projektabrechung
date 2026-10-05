"""
Export für Reach, Dashboard-Kennzahlen und Kontaktpflege
(suchen, bearbeiten, manuell sperren, DSGVO-Löschung).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import db
from .fileio import schreibe_csv
from .imports import KONTAKT_FELDER, ImportFehler, _log, sperren
from .normalize import clean_text, csv_sicher, email_fehler, normalize_datum, normalize_email

SEGMENTE = {
    "alle_aktiven": "Alle aktiven",
    "engagierte": "Engagierte (geöffnet oder geklickt im Zeitraum)",
    "inaktive": "Inaktive (im Zeitraum nichts geöffnet/geklickt)",
}

# Status, die angeschrieben werden dürfen. bounce_weich bleibt im Verteiler,
# sonst könnte die Soft-Bounce-Serie nie die Grenze von 3 erreichen.
VERSANDFAEHIG = ("aktiv", "bounce_weich")

_NICHT_GESPERRT = ("NOT EXISTS (SELECT 1 FROM suppression_list s WHERE s.email = c.email)")
_ENGAGIERT_SEIT = ("EXISTS (SELECT 1 FROM campaign_events e JOIN campaigns k ON k.id = e.campaign_id "
                   "WHERE e.contact_id = c.id AND (e.geoeffnet > 0 OR e.geklickt > 0) "
                   "AND k.gesendet_am >= :stichtag)")
_ZUGESTELLT_VOR = ("EXISTS (SELECT 1 FROM campaign_events e JOIN campaigns k ON k.id = e.campaign_id "
                   "WHERE e.contact_id = c.id AND e.zustellstatus = 'zugestellt' "
                   "AND k.gesendet_am < :stichtag)")


# ------------------------------------------------------------- Export

def segment_kontakte(conn: sqlite3.Connection, segment: str, tage: int = 90,
                     heute: date | None = None) -> list[sqlite3.Row]:
    """Versandfähige Kontakte eines Segments. Gesperrte Adressen sind nie enthalten.

    - alle_aktiven: Status aktiv/bounce_weich, nicht auf der Sperrliste
    - engagierte:   zusätzlich in einer Kampagne der letzten `tage` Tage geöffnet/geklickt
    - inaktive:     hat schon vor dem Zeitraum Mails bekommen, aber im Zeitraum
                    nichts geöffnet/geklickt (Zielgruppe für eine Reaktivierungsmail)
    """
    if segment not in SEGMENTE:
        raise ImportFehler("Unbekanntes Segment.")
    tage = int(tage)
    if not 1 <= tage <= 3650:
        raise ImportFehler("Zeitraum muss zwischen 1 und 3650 Tagen liegen.")
    stichtag = ((heute or date.today()) - timedelta(days=tage)).isoformat()

    params = {"stichtag": stichtag}
    status_platzhalter = []
    for i, s in enumerate(VERSANDFAEHIG):
        params[f"s{i}"] = s
        status_platzhalter.append(f":s{i}")
    bedingungen = [f"c.status IN ({', '.join(status_platzhalter)})", _NICHT_GESPERRT]
    if segment == "engagierte":
        bedingungen.append(_ENGAGIERT_SEIT)
    elif segment == "inaktive":
        bedingungen += [f"NOT {_ENGAGIERT_SEIT}", _ZUGESTELLT_VOR]
    sql = ("SELECT c.email, c.vorname, c.nachname, c.firma FROM contacts c WHERE "
           + " AND ".join(bedingungen) + " ORDER BY c.email")
    zeilen = conn.execute(sql, params).fetchall()

    # Zweite, unabhängige Absicherung gegen gesperrte Adressen.
    gesperrt = {r[0] for r in conn.execute("SELECT email FROM suppression_list")}
    return [z for z in zeilen if z["email"] not in gesperrt and not email_fehler(z["email"])]


def export_csv(zeilen: list[sqlite3.Row], trennzeichen: str = ",") -> bytes:
    if trennzeichen not in (",", ";"):
        raise ImportFehler("Trennzeichen muss , oder ; sein.")
    daten = [[z["email"], csv_sicher(z["vorname"]), csv_sicher(z["nachname"])] for z in zeilen]
    return schreibe_csv(["E-Mail", "Vorname", "Nachname"], daten, trennzeichen)


# ---------------------------------------------------------- Dashboard

def status_zahlen(conn: sqlite3.Connection) -> dict[str, int]:
    zahlen = {s: 0 for s in db.KONTAKT_STATUS}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM contacts GROUP BY status"):
        zahlen[r["status"]] = r["n"]
    return zahlen


def sperrlisten_zahlen(conn: sqlite3.Connection) -> dict[str, int]:
    zahlen = {g: 0 for g in db.SPERRGRUENDE}
    for r in conn.execute("SELECT grund, COUNT(*) AS n FROM suppression_list GROUP BY grund"):
        zahlen[r["grund"]] = r["n"]
    return zahlen


def kampagnen_kennzahlen(conn: sqlite3.Connection) -> list[dict]:
    """Je Kampagne: Zustellung, Bounce-Rate, Öffnungsrate.

    Basis "versendet" = alle Empfänger außer "nicht_zugestellt".
    Bounce-Rate = (hart + weich) / versendet.
    Öffnungsrate = Empfänger mit ≥1 Öffnung / versendet,
    zusätzlich bezogen auf tatsächlich zugestellte Mails.
    """
    rows = conn.execute(
        "SELECT k.id, k.name, k.betreff, k.gesendet_am, "
        "COUNT(e.contact_id) AS empfaenger, "
        "COALESCE(SUM(e.zustellstatus IN ('zugestellt', 'abgemeldet')), 0) AS zugestellt, "
        "COALESCE(SUM(e.zustellstatus = 'unzustellbar'), 0) AS bounce_hart, "
        "COALESCE(SUM(e.zustellstatus = 'soft_bounce'), 0) AS bounce_weich, "
        "COALESCE(SUM(e.zustellstatus = 'nicht_zugestellt'), 0) AS nicht_zugestellt, "
        "COALESCE(SUM(e.zustellstatus = 'abgemeldet'), 0) AS abgemeldet, "
        "COALESCE(SUM(e.geoeffnet > 0), 0) AS geoeffnet, "
        "COALESCE(SUM(e.geklickt > 0), 0) AS geklickt "
        "FROM campaigns k LEFT JOIN campaign_events e ON e.campaign_id = k.id "
        "GROUP BY k.id ORDER BY k.gesendet_am DESC, k.id DESC").fetchall()
    ergebnis = []
    for r in rows:
        d = dict(r)
        versendet = d["empfaenger"] - d["nicht_zugestellt"]
        d["versendet"] = versendet
        d["bounce_rate"] = (d["bounce_hart"] + d["bounce_weich"]) / versendet if versendet else 0.0
        d["hard_bounce_rate"] = d["bounce_hart"] / versendet if versendet else 0.0
        d["oeffnungsrate"] = d["geoeffnet"] / versendet if versendet else 0.0
        d["oeffnungsrate_zugestellt"] = d["geoeffnet"] / d["zugestellt"] if d["zugestellt"] else 0.0
        d["klickrate"] = d["geklickt"] / versendet if versendet else 0.0
        d["warnung"] = d["bounce_rate"] > 0.02
        ergebnis.append(d)
    return ergebnis


def import_protokoll(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute("SELECT zeitpunkt, art, benutzer, dateiname, neu, aktualisiert, uebersprungen, details "
                        "FROM import_log ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()


def kampagnen(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM campaigns ORDER BY gesendet_am DESC, id DESC").fetchall()


# ------------------------------------------------------ Kontaktpflege

def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def kontakte_suchen(conn: sqlite3.Connection, suchtext: str = "", status: str | None = None,
                    limit: int = 500) -> list[sqlite3.Row]:
    sql = "SELECT * FROM contacts WHERE 1 = 1"
    params: list = []
    s = clean_text(suchtext, 200).lower()
    if s:
        sql += (" AND (email LIKE ? ESCAPE '\\' OR lower(vorname) LIKE ? ESCAPE '\\' "
                "OR lower(nachname) LIKE ? ESCAPE '\\' OR lower(firma) LIKE ? ESCAPE '\\')")
        params += [_like(s)] * 4
    if status:
        if status not in db.KONTAKT_STATUS:
            raise ImportFehler("Unbekannter Status.")
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY email LIMIT ?"
    params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def sperrliste_suchen(conn: sqlite3.Connection, suchtext: str = "", limit: int = 500) -> list[sqlite3.Row]:
    s = clean_text(suchtext, 200).lower()
    return conn.execute("SELECT email, grund, datum FROM suppression_list WHERE email LIKE ? ESCAPE '\\' "
                        "ORDER BY datum DESC, email LIMIT ?", (_like(s), int(limit))).fetchall()


def kontakt(conn: sqlite3.Connection, contact_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM contacts WHERE id = ?", (int(contact_id),)).fetchone()


def kontakt_sperre(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT grund, datum FROM suppression_list WHERE email = ?", (email,)).fetchone()


def kontakt_historie(conn: sqlite3.Connection, contact_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT k.gesendet_am, k.name, e.zustellstatus, e.geoeffnet, e.geklickt "
        "FROM campaign_events e JOIN campaigns k ON k.id = e.campaign_id "
        "WHERE e.contact_id = ? ORDER BY k.gesendet_am DESC, k.id DESC", (int(contact_id),)).fetchall()


def kontakt_anlegen(db_path, daten: dict) -> int:
    email = normalize_email(daten.get("email"))
    fehler = email_fehler(email)
    if fehler:
        raise ImportFehler(f"Ungültige E-Mail-Adresse ({fehler}).")
    werte = {f: clean_text(daten.get(f, "")) for f in KONTAKT_FELDER}
    if werte["einwilligung_datum"]:
        werte["einwilligung_datum"], ok = normalize_datum(werte["einwilligung_datum"])
        if not ok:
            raise ImportFehler("Einwilligungsdatum nicht erkannt (Format TT.MM.JJJJ).")
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            if conn.execute("SELECT 1 FROM suppression_list WHERE email = ?", (email,)).fetchone():
                raise ImportFehler("Diese Adresse steht auf der Sperrliste und wird nicht angelegt.")
            if conn.execute("SELECT 1 FROM contacts WHERE email = ?", (email,)).fetchone():
                raise ImportFehler("Diese Adresse ist bereits als Kontakt vorhanden.")
            jetzt = db.jetzt()
            return conn.execute(
                "INSERT INTO contacts (email, vorname, nachname, firma, quelle, einwilligung_art, "
                "einwilligung_datum, status, erstellt_am, geaendert_am) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'aktiv', ?, ?)",
                (email, *[werte[f] for f in KONTAKT_FELDER], jetzt, jetzt)).lastrowid
    finally:
        conn.close()


def kontakt_aktualisieren(db_path, contact_id: int, daten: dict) -> None:
    """Stammdaten und Einwilligung ändern. E-Mail und Status sind hier nicht änderbar."""
    werte = {f: clean_text(daten[f]) for f in KONTAKT_FELDER if f in daten}
    if werte.get("einwilligung_datum"):
        werte["einwilligung_datum"], ok = normalize_datum(werte["einwilligung_datum"])
        if not ok:
            raise ImportFehler("Einwilligungsdatum nicht erkannt (Format TT.MM.JJJJ).")
    if not werte:
        return
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            if kontakt(conn, contact_id) is None:
                raise ImportFehler("Kontakt nicht gefunden.")
            spalten = ", ".join(f"{f} = ?" for f in werte)  # Feldnamen aus KONTAKT_FELDER
            conn.execute(f"UPDATE contacts SET {spalten}, geaendert_am = ? WHERE id = ?",
                         (*werte.values(), db.jetzt(), int(contact_id)))
    finally:
        conn.close()


def kontakt_sperren(db_path, contact_id: int, grund: str = "manuell", benutzer: str = "") -> bool:
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            k = kontakt(conn, contact_id)
            if k is None:
                raise ImportFehler("Kontakt nicht gefunden.")
            neu = sperren(conn, k["email"], grund)
            _log(conn, "manuell_gesperrt", "", 0, 1 if neu else 0, 0, {"grund": grund}, benutzer)
            return neu
    finally:
        conn.close()


def adresse_sperren(db_path, email_roh: str, grund: str = "manuell", benutzer: str = "") -> bool:
    """Einzelne Adresse sperren – auch wenn sie (noch) kein Kontakt ist."""
    email = normalize_email(email_roh)
    fehler = email_fehler(email)
    if fehler:
        raise ImportFehler(f"Ungültige E-Mail-Adresse ({fehler}).")
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            neu = sperren(conn, email, grund)
            _log(conn, "manuell_gesperrt", "", 1 if neu else 0, 0, 0, {"grund": grund}, benutzer)
            return neu
    finally:
        conn.close()


def kontakt_dsgvo_loeschen(db_path, contact_id: int, bestaetigung: str,
                           sperre_behalten: bool = True, benutzer: str = "") -> dict:
    """Kontakt vollständig löschen (DSGVO Art. 17).

    - bestaetigung muss exakt der E-Mail-Adresse des Kontakts entsprechen.
    - sperre_behalten=True (empfohlen): Die Adresse bleibt bzw. kommt auf die
      Sperrliste (Grund "manuell"), damit sie nicht über eine alte Liste wieder
      hereinkommt. Gespeichert bleibt dann nur die E-Mail-Adresse.
    - sperre_behalten=False: Auch ein Sperrlisteneintrag wird entfernt.
    Kampagnenereignisse des Kontakts werden mitgelöscht.
    Hinweis: Ältere Backups im Ordner backups/ enthalten den Kontakt weiterhin.
    """
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            k = kontakt(conn, contact_id)
            if k is None:
                raise ImportFehler("Kontakt nicht gefunden.")
            if normalize_email(bestaetigung) != k["email"]:
                raise ImportFehler("Bestätigung stimmt nicht mit der E-Mail-Adresse überein.")
            email = k["email"]
            if sperre_behalten:
                sperren(conn, email, "manuell")
            conn.execute("INSERT OR IGNORE INTO dsgvo_freigabe (email) VALUES (?)", (email,))
            events = conn.execute("DELETE FROM campaign_events WHERE contact_id = ?",
                                  (k["id"],)).rowcount
            conn.execute("DELETE FROM contacts WHERE id = ?", (k["id"],))
            sperre_entfernt = 0
            if not sperre_behalten:
                sperre_entfernt = conn.execute("DELETE FROM suppression_list WHERE email = ?",
                                               (email,)).rowcount
            conn.execute("DELETE FROM dsgvo_freigabe WHERE email = ?", (email,))
            # Protokoll ohne personenbezogene Daten.
            _log(conn, "dsgvo_loeschung", "", 0, 0, 0,
                 {"ereignisse_geloescht": events, "sperre_behalten": sperre_behalten,
                  "sperre_entfernt": sperre_entfernt}, benutzer)
        return {"ereignisse_geloescht": events, "sperre_behalten": sperre_behalten}
    finally:
        conn.close()
