"""
Importe: Kontaktliste, Kampagnen-Report aus Reach, Sperrliste.

Jeder Import besteht aus zwei Schritten:
- analysiere_*  : nur lesend, liefert einen Plan mit Zahlen für die Vorschau
- importiere_*  : legt ein Backup an, rechnet den Plan innerhalb der
                  Schreibtransaktion neu (damit nichts Veraltetes geschrieben
                  wird) und schreibt alles atomar – bei einem Fehler Rollback.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from . import db
from .normalize import (
    clean_text, email_fehler, normalize_datum, normalize_email, parse_anzahl,
    report_status_erkennen, sperrgrund_erkennen, status_schluessel,
)

KONTAKT_FELDER = ("vorname", "nachname", "firma", "quelle",
                  "einwilligung_art", "einwilligung_datum")

# Erzwingt die Grenze "ab 3 Soft-Bounces in Folge = harter Bounce".
SOFT_BOUNCE_GRENZE = 3

# Bei mehrfach vorkommender Adresse im Report gewinnt der "schlechteste" Status.
_REPORT_RANG = {"unzustellbar": 6, "beschwerde": 5, "abgemeldet": 4, "soft_bounce": 3,
                "zugestellt": 2, "nicht_zugestellt": 1}

SPERRGRUND_FUER_REPORT = {"unzustellbar": "bounce_hart", "abgemeldet": "abgemeldet",
                          "beschwerde": "beschwerde"}


class ImportFehler(ValueError):
    """Fachlicher Fehler, der dem Nutzer angezeigt wird."""


# ------------------------------------------------------------------ Hilfen

def _gesperrte(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["email"]: r["grund"] for r in conn.execute("SELECT email, grund FROM suppression_list")}


def _kontakte_nach_email(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["email"]: r for r in conn.execute("SELECT * FROM contacts")}


def _zelle(zeile: dict[str, str], spalte: str | None) -> str:
    return zeile.get(spalte, "") if spalte else ""


def _log(conn: sqlite3.Connection, art: str, dateiname: str, neu: int,
         aktualisiert: int, uebersprungen: int, details: dict, benutzer: str = "") -> None:
    conn.execute(
        "INSERT INTO import_log (zeitpunkt, art, dateiname, neu, aktualisiert, uebersprungen, details, "
        "benutzer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (db.jetzt(), art, clean_text(dateiname, 255), neu, aktualisiert, uebersprungen,
         json.dumps(details, ensure_ascii=False), clean_text(benutzer, 200)))


def sperren(conn: sqlite3.Connection, email: str, grund: str, datum: str | None = None) -> bool:
    """Adresse auf die Sperrliste setzen und Kontaktstatus angleichen.

    Gibt True zurück, wenn die Adresse neu gesperrt wurde. Ein bestehender
    Eintrag bleibt unverändert (der erste Grund gilt).
    """
    if grund not in db.SPERRGRUENDE:
        raise ImportFehler(f"Unbekannter Sperrgrund: {grund}")
    if email_fehler(email):
        raise ImportFehler(f"Ungültige Adresse: {email}")
    cur = conn.execute(
        "INSERT OR IGNORE INTO suppression_list (email, grund, datum) VALUES (?, ?, ?)",
        (email, grund, datum or db.jetzt()))
    tatsaechlich = conn.execute("SELECT grund FROM suppression_list WHERE email = ?",
                                (email,)).fetchone()["grund"]
    status = db.STATUS_FUER_SPERRGRUND[tatsaechlich]
    conn.execute(
        "UPDATE contacts SET status = ?, geaendert_am = ? WHERE email = ? AND status <> ?",
        (status, db.jetzt(), email, status))
    return cur.rowcount == 1


def soft_bounce_serie(conn: sqlite3.Connection, contact_id: int) -> int:
    """Anzahl der Soft-Bounces in Folge, von der neuesten Kampagne rückwärts.

    "nicht_zugestellt" (nicht versendet) unterbricht die Serie nicht.
    """
    serie = 0
    for r in conn.execute(
            "SELECT e.zustellstatus FROM campaign_events e JOIN campaigns k ON k.id = e.campaign_id "
            "WHERE e.contact_id = ? ORDER BY k.gesendet_am DESC, k.id DESC", (contact_id,)):
        if r["zustellstatus"] == "nicht_zugestellt":
            continue
        if r["zustellstatus"] != "soft_bounce":
            break
        serie += 1
    return serie


def status_neu_berechnen(conn: sqlite3.Connection, contact_id: int) -> str:
    """Kontaktstatus aus Sperrliste und Kampagnenhistorie ableiten."""
    k = conn.execute("SELECT email, status, soft_bounce_folge FROM contacts WHERE id = ?",
                     (contact_id,)).fetchone()
    serie = soft_bounce_serie(conn, contact_id)
    sperre = conn.execute("SELECT grund FROM suppression_list WHERE email = ?",
                          (k["email"],)).fetchone()
    if sperre is None and serie >= SOFT_BOUNCE_GRENZE:
        sperren(conn, k["email"], "bounce_hart")
        sperre = {"grund": "bounce_hart"}

    if sperre is not None:
        status = db.STATUS_FUER_SPERRGRUND[sperre["grund"]]
    elif serie > 0:
        status = "bounce_weich"
    elif k["status"] == "bounce_weich":
        status = "aktiv"
    else:
        status = k["status"]

    if status != k["status"] or serie != k["soft_bounce_folge"]:
        conn.execute("UPDATE contacts SET status = ?, soft_bounce_folge = ?, geaendert_am = ? "
                     "WHERE id = ?", (status, serie, db.jetzt(), contact_id))
    return status


def _backup(db_path, backup_dir) -> str:
    pfad = db.backup(db_path, backup_dir)
    return str(pfad) if pfad else ""


# ======================================================= 1. Kontaktliste

@dataclass
class KontaktPlan:
    neu: list[dict] = field(default_factory=list)
    aktualisieren: list[tuple[int, str, dict]] = field(default_factory=list)  # (id, email, änderungen)
    dublette_unveraendert: list[str] = field(default_factory=list)
    dubletten_in_datei: list[dict] = field(default_factory=list)
    ungueltig: list[dict] = field(default_factory=list)
    gesperrt: list[dict] = field(default_factory=list)
    datum_unklar: list[dict] = field(default_factory=list)
    zeilen: int = 0

    @property
    def anzahl_dubletten(self) -> int:
        return (len(self.dubletten_in_datei) + len(self.aktualisieren)
                + len(self.dublette_unveraendert))

    def zahlen(self) -> dict[str, int]:
        return {
            "zeilen": self.zeilen,
            "neu": len(self.neu),
            "dublette": self.anzahl_dubletten,
            "dublette_in_datei": len(self.dubletten_in_datei),
            "dublette_bestand_aktualisiert": len(self.aktualisieren),
            "dublette_bestand_unveraendert": len(self.dublette_unveraendert),
            "ungueltig": len(self.ungueltig),
            "gesperrt": len(self.gesperrt),
            "datum_unklar": len(self.datum_unklar),
        }


def analysiere_kontakte(conn: sqlite3.Connection, zeilen: list[dict[str, str]],
                        zuordnung: dict[str, str | None], standardwerte: dict[str, str] | None = None,
                        modus: str = "ergaenzen") -> KontaktPlan:
    """Plan für den Import einer Kontaktliste.

    zuordnung: Feld -> Spaltenname (mindestens "email").
    standardwerte: Werte für leere/nicht zugeordnete Felder (z. B. quelle).
    modus: "ergaenzen" füllt bei Dubletten nur leere Felder,
           "ueberschreiben" ersetzt vorhandene Werte durch nicht-leere neue.
    """
    if not zuordnung.get("email"):
        raise ImportFehler("Bitte die Spalte mit der E-Mail-Adresse zuordnen.")
    if modus not in ("ergaenzen", "ueberschreiben"):
        raise ImportFehler("Unbekannter Modus.")
    standard = {f: clean_text((standardwerte or {}).get(f, "")) for f in KONTAKT_FELDER}

    plan = KontaktPlan(zeilen=len(zeilen))
    gesperrt = _gesperrte(conn)
    bestand = _kontakte_nach_email(conn)
    aus_datei: dict[str, dict] = {}

    for nr, zeile in enumerate(zeilen, start=2):  # Zeile 1 = Kopfzeile
        roh = _zelle(zeile, zuordnung["email"])
        email = normalize_email(roh)
        fehler = email_fehler(email)
        if fehler:
            plan.ungueltig.append({"zeile": nr, "email": clean_text(roh), "grund": fehler})
            continue
        if email in gesperrt:
            plan.gesperrt.append({"zeile": nr, "email": email, "grund": gesperrt[email]})
            continue

        satz = {"email": email}
        for f in KONTAKT_FELDER:
            wert = clean_text(_zelle(zeile, zuordnung.get(f))) or standard[f]
            if f == "einwilligung_datum" and wert:
                wert, ok = normalize_datum(wert)
                if not ok:
                    plan.datum_unklar.append({"zeile": nr, "email": email, "wert": wert})
            satz[f] = wert

        if email in aus_datei:  # Dublette innerhalb der Datei -> zusammenführen
            vorhanden = aus_datei[email]
            for f in KONTAKT_FELDER:
                if not vorhanden[f] and satz[f]:
                    vorhanden[f] = satz[f]
            plan.dubletten_in_datei.append({"zeile": nr, "email": email})
        else:
            aus_datei[email] = satz

    for email, satz in aus_datei.items():
        alt = bestand.get(email)
        if alt is None:
            plan.neu.append(satz)
            continue
        aenderungen = {}
        for f in KONTAKT_FELDER:
            neu_wert = satz[f]
            if not neu_wert or neu_wert == alt[f]:
                continue
            if modus == "ueberschreiben" or not alt[f]:
                aenderungen[f] = neu_wert
        if aenderungen:
            plan.aktualisieren.append((alt["id"], email, aenderungen))
        else:
            plan.dublette_unveraendert.append(email)
    return plan


def importiere_kontakte(db_path, backup_dir, dateiname: str, zeilen: list[dict[str, str]],
                        zuordnung: dict[str, str | None], standardwerte: dict[str, str] | None = None,
                        modus: str = "ergaenzen", benutzer: str = "") -> dict:
    sicherung = _backup(db_path, backup_dir)
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            plan = analysiere_kontakte(conn, zeilen, zuordnung, standardwerte, modus)
            jetzt = db.jetzt()
            for s in plan.neu:
                conn.execute(
                    "INSERT INTO contacts (email, vorname, nachname, firma, quelle, einwilligung_art, "
                    "einwilligung_datum, status, erstellt_am, geaendert_am) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'aktiv', ?, ?)",
                    (s["email"], s["vorname"], s["nachname"], s["firma"], s["quelle"],
                     s["einwilligung_art"], s["einwilligung_datum"], jetzt, jetzt))
            for kid, _email, aend in plan.aktualisieren:
                spalten = ", ".join(f"{f} = ?" for f in aend)  # Feldnamen aus KONTAKT_FELDER
                conn.execute(f"UPDATE contacts SET {spalten}, geaendert_am = ? WHERE id = ?",
                             (*aend.values(), jetzt, kid))
            z = plan.zahlen()
            _log(conn, "kontakte", dateiname, z["neu"], z["dublette_bestand_aktualisiert"],
                 z["ungueltig"] + z["gesperrt"], z, benutzer)
    finally:
        conn.close()
    return {**plan.zahlen(), "backup": sicherung}


# ================================================== 2. Kampagnen-Report

@dataclass
class ReportPlan:
    eintraege: dict[str, dict] = field(default_factory=dict)  # email -> {ziel, geoeffnet, geklickt}
    ungueltig: list[dict] = field(default_factory=list)
    status_unbekannt: list[dict] = field(default_factory=list)
    dubletten_in_datei: int = 0
    neue_kontakte: list[str] = field(default_factory=list)
    unbekannt_uebersprungen: list[str] = field(default_factory=list)
    neue_sperren: dict[str, list[str]] = field(default_factory=dict)  # grund -> emails
    bereits_gesperrt: list[str] = field(default_factory=list)
    soft_bounce_grenze: list[str] = field(default_factory=list)
    zahl_unklar: int = 0
    zeilen: int = 0

    def zahlen(self) -> dict[str, int]:
        je_ziel: dict[str, int] = {}
        for e in self.eintraege.values():
            je_ziel[e["ziel"]] = je_ziel.get(e["ziel"], 0) + 1
        return {
            "zeilen": self.zeilen,
            "verarbeitet": len(self.eintraege),
            **{f"status_{k}": v for k, v in sorted(je_ziel.items())},
            "ungueltig": len(self.ungueltig),
            "status_unbekannt": len(self.status_unbekannt),
            "dublette_in_datei": self.dubletten_in_datei,
            "neue_kontakte": len(self.neue_kontakte),
            "unbekannt_uebersprungen": len(self.unbekannt_uebersprungen),
            "neu_gesperrt": sum(len(v) for v in self.neue_sperren.values()),
            **{f"neu_gesperrt_{k}": len(v) for k, v in sorted(self.neue_sperren.items())},
            "bereits_gesperrt": len(self.bereits_gesperrt),
            "soft_bounce_3x": len(self.soft_bounce_grenze),
            "zahl_unklar": self.zahl_unklar,
        }


def report_statuswerte(zeilen: list[dict[str, str]], spalte: str | None) -> dict[str, tuple[str, int, str | None]]:
    """Alle vorkommenden Statuswerte: schluessel -> (Beispieltext, Anzahl, automatische Zuordnung)."""
    werte: dict[str, list] = {}
    for z in zeilen:
        roh = clean_text(_zelle(z, spalte), 80)
        key = status_schluessel(roh)
        if key not in werte:
            werte[key] = [roh, 0, report_status_erkennen(roh)]
        werte[key][1] += 1
    return {k: (v[0], v[1], v[2]) for k, v in werte.items()}


def analysiere_report(conn: sqlite3.Connection, zeilen: list[dict[str, str]],
                      zuordnung: dict[str, str | None], status_zuordnung: dict[str, str | None],
                      kampagne_datum: str, kampagne_id: int | None = None,
                      unbekannte_anlegen: bool = True) -> ReportPlan:
    """Plan für den Import eines Reach-Empfänger-Reports.

    status_zuordnung: Status-Schlüssel (siehe report_statuswerte) -> Ziel
    aus normalize.REPORT_ZIELE oder None (= Zeile überspringen).
    """
    if not zuordnung.get("email"):
        raise ImportFehler("Bitte die Spalte mit der E-Mail-Adresse zuordnen.")
    if not zuordnung.get("status"):
        raise ImportFehler("Bitte die Status-Spalte zuordnen.")

    plan = ReportPlan(zeilen=len(zeilen))
    gesperrt = _gesperrte(conn)
    bestand = _kontakte_nach_email(conn)

    for nr, zeile in enumerate(zeilen, start=2):
        roh = _zelle(zeile, zuordnung["email"])
        email = normalize_email(roh)
        fehler = email_fehler(email)
        if fehler:
            plan.ungueltig.append({"zeile": nr, "email": clean_text(roh), "grund": fehler})
            continue
        status_roh = clean_text(_zelle(zeile, zuordnung["status"]), 80)
        ziel = status_zuordnung.get(status_schluessel(status_roh))
        if ziel is None:
            plan.status_unbekannt.append({"zeile": nr, "email": email, "status": status_roh})
            continue
        auf, ok1 = parse_anzahl(_zelle(zeile, zuordnung.get("geoeffnet")))
        klick, ok2 = parse_anzahl(_zelle(zeile, zuordnung.get("geklickt")))
        plan.zahl_unklar += (not ok1) + (not ok2)
        vorname = clean_text(_zelle(zeile, zuordnung.get("vorname")))
        nachname = clean_text(_zelle(zeile, zuordnung.get("nachname")))

        if email in plan.eintraege:
            plan.dubletten_in_datei += 1
            e = plan.eintraege[email]
            e["geoeffnet"] = max(e["geoeffnet"], auf)
            e["geklickt"] = max(e["geklickt"], klick)
            if _REPORT_RANG[ziel] > _REPORT_RANG[e["ziel"]]:
                e["ziel"] = ziel
            e["vorname"] = e["vorname"] or vorname
            e["nachname"] = e["nachname"] or nachname
        else:
            plan.eintraege[email] = {"ziel": ziel, "geoeffnet": auf, "geklickt": klick,
                                     "vorname": vorname, "nachname": nachname}

    for email in list(plan.eintraege):
        e = plan.eintraege[email]
        if email not in bestand:
            if unbekannte_anlegen:
                plan.neue_kontakte.append(email)
            else:
                plan.unbekannt_uebersprungen.append(email)
                del plan.eintraege[email]
                continue
        grund = SPERRGRUND_FUER_REPORT.get(e["ziel"])
        if email in gesperrt:
            plan.bereits_gesperrt.append(email)
        elif grund:
            plan.neue_sperren.setdefault(grund, []).append(email)
        elif e["ziel"] == "soft_bounce":
            kontakt = bestand.get(email)
            vorher = _serie_ohne_kampagne(conn, kontakt["id"], kampagne_datum, kampagne_id) if kontakt else 0
            if vorher + 1 >= SOFT_BOUNCE_GRENZE:
                plan.soft_bounce_grenze.append(email)
    return plan


def _serie_ohne_kampagne(conn, contact_id: int, datum: str, kampagne_id: int | None) -> int:
    """Soft-Bounce-Serie vor einer (neuen oder erneut importierten) Kampagne."""
    serie = 0
    for r in conn.execute(
            "SELECT e.zustellstatus FROM campaign_events e JOIN campaigns k ON k.id = e.campaign_id "
            "WHERE e.contact_id = ? AND k.id IS NOT ? AND k.gesendet_am <= ? "
            "ORDER BY k.gesendet_am DESC, k.id DESC", (contact_id, kampagne_id, datum)):
        if r["zustellstatus"] == "nicht_zugestellt":
            continue
        if r["zustellstatus"] != "soft_bounce":
            break
        serie += 1
    return serie


def importiere_report(db_path, backup_dir, dateiname: str, zeilen: list[dict[str, str]],
                      zuordnung: dict[str, str | None], status_zuordnung: dict[str, str | None],
                      kampagne: dict, unbekannte_anlegen: bool = True, benutzer: str = "") -> dict:
    """Schreibt einen Reach-Report.

    kampagne: {"id": <bestehende Kampagne>} oder
              {"name": ..., "betreff": ..., "gesendet_am": "JJJJ-MM-TT"}.
    Ein erneuter Import derselben Kampagne aktualisiert die Ereignisse
    (keine doppelten Einträge, Soft-Bounces werden nicht doppelt gezählt).
    """
    for ziel in status_zuordnung.values():
        if ziel is not None and ziel not in _REPORT_RANG:
            raise ImportFehler(f"Unbekanntes Statusziel: {ziel}")
    sicherung = _backup(db_path, backup_dir)
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            if kampagne.get("id"):
                k = conn.execute("SELECT id, gesendet_am FROM campaigns WHERE id = ?",
                                 (int(kampagne["id"]),)).fetchone()
                if k is None:
                    raise ImportFehler("Die gewählte Kampagne existiert nicht.")
                kid, kdatum = k["id"], k["gesendet_am"]
            else:
                name = clean_text(kampagne.get("name"))
                kdatum, ok = normalize_datum(kampagne.get("gesendet_am"))
                if not name:
                    raise ImportFehler("Bitte einen Kampagnennamen angeben.")
                if not kdatum or not ok:
                    raise ImportFehler("Bitte ein gültiges Versanddatum angeben.")
                kid = conn.execute(
                    "INSERT INTO campaigns (name, betreff, gesendet_am) VALUES (?, ?, ?)",
                    (name, clean_text(kampagne.get("betreff"), 500), kdatum)).lastrowid

            plan = analysiere_report(conn, zeilen, zuordnung, status_zuordnung, kdatum,
                                     kid if kampagne.get("id") else None, unbekannte_anlegen)
            gesperrt = _gesperrte(conn)
            jetzt = db.jetzt()
            quelle = f"Reach-Report: {clean_text(dateiname, 120)}"
            for email in plan.neue_kontakte:
                e = plan.eintraege[email]
                status = db.STATUS_FUER_SPERRGRUND[gesperrt[email]] if email in gesperrt else "aktiv"
                conn.execute(
                    "INSERT INTO contacts (email, vorname, nachname, quelle, status, erstellt_am, geaendert_am) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (email, e["vorname"], e["nachname"], quelle, status, jetzt, jetzt))

            ids = {r["email"]: r["id"] for r in conn.execute("SELECT id, email FROM contacts")}
            for email, e in plan.eintraege.items():
                zustell = "zugestellt" if e["ziel"] == "beschwerde" else e["ziel"]
                conn.execute(
                    "INSERT INTO campaign_events (contact_id, campaign_id, geoeffnet, geklickt, zustellstatus) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT (contact_id, campaign_id) DO UPDATE SET "
                    "geoeffnet = excluded.geoeffnet, geklickt = excluded.geklickt, "
                    "zustellstatus = excluded.zustellstatus",
                    (ids[email], kid, e["geoeffnet"], e["geklickt"], zustell))
                grund = SPERRGRUND_FUER_REPORT.get(e["ziel"])
                if grund:
                    sperren(conn, email, grund)

            soft_gesperrt = 0
            for email in plan.eintraege:
                vorher = conn.execute("SELECT 1 FROM suppression_list WHERE email = ?",
                                      (email,)).fetchone()
                status_neu_berechnen(conn, ids[email])
                if vorher is None and conn.execute(
                        "SELECT 1 FROM suppression_list WHERE email = ?", (email,)).fetchone():
                    soft_gesperrt += 1

            conn.execute("UPDATE campaigns SET empfaenger_anzahl = "
                         "(SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?) WHERE id = ?",
                         (kid, kid))
            z = plan.zahlen()
            z["soft_bounce_3x"] = soft_gesperrt
            z["kampagne_id"] = kid
            _log(conn, "report", dateiname, z["neue_kontakte"], z["verarbeitet"] - z["neue_kontakte"],
                 z["ungueltig"] + z["status_unbekannt"] + z["unbekannt_uebersprungen"], z, benutzer)
    finally:
        conn.close()
    return {**z, "backup": sicherung}


# ======================================================= 3. Sperrliste

@dataclass
class SperrPlan:
    neu: dict[str, tuple[str, str]] = field(default_factory=dict)  # email -> (grund, datum)
    bereits_gesperrt: list[str] = field(default_factory=list)
    ungueltig: list[dict] = field(default_factory=list)
    dubletten_in_datei: int = 0
    grund_unbekannt: int = 0
    betrifft_kontakte: int = 0
    zeilen: int = 0

    def zahlen(self) -> dict[str, int]:
        je_grund: dict[str, int] = {}
        for g, _d in self.neu.values():
            je_grund[g] = je_grund.get(g, 0) + 1
        return {
            "zeilen": self.zeilen,
            "neu_gesperrt": len(self.neu),
            **{f"neu_gesperrt_{k}": v for k, v in sorted(je_grund.items())},
            "bereits_gesperrt": len(self.bereits_gesperrt),
            "ungueltig": len(self.ungueltig),
            "dublette_in_datei": self.dubletten_in_datei,
            "grund_nicht_erkannt": self.grund_unbekannt,
            "betrifft_bestehende_kontakte": self.betrifft_kontakte,
        }


def analysiere_sperrliste(conn: sqlite3.Connection, zeilen: list[dict[str, str]],
                          zuordnung: dict[str, str | None], standard_grund: str) -> SperrPlan:
    if not zuordnung.get("email"):
        raise ImportFehler("Bitte die Spalte mit der E-Mail-Adresse zuordnen.")
    if standard_grund not in db.SPERRGRUENDE:
        raise ImportFehler("Unbekannter Sperrgrund.")
    plan = SperrPlan(zeilen=len(zeilen))
    gesperrt = _gesperrte(conn)
    bestand = _kontakte_nach_email(conn)
    gesehen: set[str] = set()
    for nr, zeile in enumerate(zeilen, start=2):
        roh = _zelle(zeile, zuordnung["email"])
        email = normalize_email(roh)
        fehler = email_fehler(email)
        if fehler:
            plan.ungueltig.append({"zeile": nr, "email": clean_text(roh), "grund": fehler})
            continue
        if email in gesehen:
            plan.dubletten_in_datei += 1
            continue
        gesehen.add(email)
        if email in gesperrt:
            plan.bereits_gesperrt.append(email)
            continue
        grund = standard_grund
        if zuordnung.get("grund"):
            roh_grund = _zelle(zeile, zuordnung["grund"])
            erkannt = sperrgrund_erkennen(roh_grund)
            if erkannt:
                grund = erkannt
            elif clean_text(roh_grund):
                plan.grund_unbekannt += 1
        datum = ""
        if zuordnung.get("datum"):
            d, ok = normalize_datum(_zelle(zeile, zuordnung["datum"]))
            datum = d if ok else ""
        plan.neu[email] = (grund, datum)
        if email in bestand:
            plan.betrifft_kontakte += 1
    return plan


def importiere_sperrliste(db_path, backup_dir, dateiname: str, zeilen: list[dict[str, str]],
                          zuordnung: dict[str, str | None], standard_grund: str,
                          benutzer: str = "") -> dict:
    sicherung = _backup(db_path, backup_dir)
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            plan = analysiere_sperrliste(conn, zeilen, zuordnung, standard_grund)
            for email, (grund, datum) in plan.neu.items():
                sperren(conn, email, grund, datum or None)
            z = plan.zahlen()
            _log(conn, "sperrliste", dateiname, z["neu_gesperrt"], z["betrifft_bestehende_kontakte"],
                 z["ungueltig"] + z["bereits_gesperrt"] + z["dublette_in_datei"], z, benutzer)
    finally:
        conn.close()
    return {**z, "backup": sicherung}
