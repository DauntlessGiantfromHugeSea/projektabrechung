"""
Tests der Kernlogik. Start (im Ordner verteiler/):

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import beispieldaten as bsp  # noqa: E402
from verteiler_core import db, imports, queries  # noqa: E402
from verteiler_core.fileio import lese_csv, lese_datei  # noqa: E402
from verteiler_core.normalize import (  # noqa: E402
    email_fehler, normalize_datum, normalize_email, parse_anzahl, report_status_erkennen,
    spalte_erkennen,
)

KONTAKT_ZUORDNUNG = {"email": "E-Mail", "vorname": "Vorname", "nachname": "Nachname",
                     "firma": "Firma", "einwilligung_art": "Einwilligung",
                     "einwilligung_datum": "Einwilligungsdatum"}
REPORT_ZUORDNUNG = {"email": "E-Mail", "vorname": "Vorname", "nachname": "Nachname",
                    "geoeffnet": "Geöffnet", "geklickt": "Geklickt", "status": "Status"}


def auto_status(tabelle):
    return {k: auto for k, (_t, _n, auto) in
            imports.report_statuswerte(tabelle.zeilen, "Status").items()}


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dbp = Path(self.tmp.name) / "verteiler.db"
        self.bak = Path(self.tmp.name) / "backups"
        db.connect(self.dbp).close()

    def tearDown(self):
        self.tmp.cleanup()

    def conn(self):
        return closing(db.connect(self.dbp))

    def lade_bestand_und_sperrliste(self):
        imports.importiere_kontakte(self.dbp, self.bak, "bestand.csv",
                                    lese_csv(bsp.als_csv(bsp.BESTAND)).zeilen,
                                    {"email": "E-Mail", "vorname": "Vorname", "nachname": "Nachname",
                                     "quelle": "Quelle"})
        imports.importiere_sperrliste(self.dbp, self.bak, "sperre.csv",
                                      [{"E-Mail": a} for a in bsp.GESPERRT],
                                      {"email": "E-Mail"}, "bounce_hart")

    def report(self, name, datum, eintraege, kampagne_id=None):
        t = lese_csv(bsp.reach_report(eintraege))
        kampagne = {"id": kampagne_id} if kampagne_id else {"name": name, "betreff": name,
                                                             "gesendet_am": datum}
        return imports.importiere_report(self.dbp, self.bak, f"{name}.csv", t.zeilen,
                                         REPORT_ZUORDNUNG, auto_status(t), kampagne)

    def status(self, email):
        with self.conn() as c:
            r = c.execute("SELECT status FROM contacts WHERE email = ?", (email,)).fetchone()
        return r["status"] if r else None

    def gesperrt(self, email):
        with self.conn() as c:
            r = c.execute("SELECT grund FROM suppression_list WHERE email = ?", (email,)).fetchone()
        return r["grund"] if r else None


# ------------------------------------------------------------ Normalisierung

class TestNormalisierung(unittest.TestCase):
    def test_email(self):
        self.assertEqual(normalize_email("  Max.Muster@Firma.DE "), "max.muster@firma.de")
        self.assertEqual(normalize_email("Max <MAX@firma.de>"), "max@firma.de")
        self.assertEqual(normalize_email("mailto:max@firma.de"), "max@firma.de")
        self.assertEqual(normalize_email("﻿max@firma.de​"), "max@firma.de")
        for gut in ("a@b.de", "vor.nach+tag@sub.firma.co.uk", "o'neil@example.com"):
            self.assertIsNone(email_fehler(gut), gut)
        for adr in bsp.UNGUELTIG:
            self.assertIsNotNone(email_fehler(normalize_email(adr)), adr)

    def test_datum_und_zahlen(self):
        self.assertEqual(normalize_datum("15.03.2026"), ("2026-03-15", True))
        self.assertEqual(normalize_datum("2026-03-15 10:00:00"), ("2026-03-15", True))
        self.assertEqual(normalize_datum("46096"), ("2026-03-15", True))  # Excel-Seriennummer
        self.assertEqual(normalize_datum("irgendwann"), ("irgendwann", False))
        self.assertEqual(parse_anzahl("3"), (3, True))
        self.assertEqual(parse_anzahl("Ja"), (1, True))
        self.assertEqual(parse_anzahl(""), (0, True))
        self.assertEqual(parse_anzahl("viel"), (0, False))

    def test_status_und_spalten(self):
        self.assertEqual(report_status_erkennen("Unzustellbar"), "unzustellbar")
        self.assertEqual(report_status_erkennen("Soft-Bounce"), "soft_bounce")
        self.assertEqual(report_status_erkennen("Nicht zugestellt"), "nicht_zugestellt")
        self.assertEqual(report_status_erkennen("Abgemeldet"), "abgemeldet")
        self.assertIsNone(report_status_erkennen("Irgendwas"))
        kopf = ["E-Mail", "Vorname", "Nachname", "Geöffnet", "Geklickt", "Status"]
        self.assertEqual(spalte_erkennen("email", kopf), "E-Mail")
        self.assertEqual(spalte_erkennen("geoeffnet", kopf), "Geöffnet")


# ------------------------------------------------------------- Dateien

class TestDateien(unittest.TestCase):
    def test_bom_und_trennzeichen(self):
        for trenn in (";", ","):
            daten = "﻿E-Mail{0}Vorname\r\nä@example.com{0}Jörg\r\n".format(trenn).encode("utf-8")
            t = lese_csv(daten)
            self.assertEqual(t.trennzeichen, trenn)
            self.assertEqual(t.kopfzeilen, ["E-Mail", "Vorname"])
            self.assertEqual(t.zeilen[0]["Vorname"], "Jörg")

    def test_ohne_bom_und_windows1252(self):
        t = lese_csv("E-Mail;Name\nx@example.com;Jörg\n".encode("cp1252"))
        self.assertEqual(t.zeilen[0]["Name"], "Jörg")
        self.assertTrue(t.hinweise)

    def test_kommas_in_feldern(self):
        t = lese_csv(b'E-Mail,Firma\nx@example.com,"M\xc3\xbcller, Meier & Co"\n')
        self.assertEqual(t.zeilen[0]["Firma"], "Müller, Meier & Co")

    def test_xlsx(self):
        puffer = io.BytesIO()
        with zipfile.ZipFile(puffer, "w") as z:
            z.writestr("xl/workbook.xml",
                       '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                       '<sheets><sheet name="A" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
            z.writestr("xl/sharedStrings.xml",
                       '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<si><t>E-Mail</t></si><si><t>Datum</t></si><si><t>A@Example.com</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>46096</v></c></row>'
                       '</sheetData></worksheet>')
        t = lese_datei("liste.xlsx", puffer.getvalue())
        self.assertEqual(t.kopfzeilen, ["E-Mail", "Datum"])
        self.assertEqual(t.zeilen[0], {"E-Mail": "A@Example.com", "Datum": "46096"})


# ------------------------------------------------- 1. Kontaktliste importieren

class TestKontaktImport(Basis):
    def test_vorschau_je_20(self):
        """Die geforderte Probe: je 20 Zeilen neu / Dublette / ungültig / gesperrt."""
        self.lade_bestand_und_sperrliste()
        zeilen = lese_csv(bsp.als_csv(bsp.kontaktliste())).zeilen
        self.assertEqual(len(zeilen), 80)
        with self.conn() as c:
            plan = imports.analysiere_kontakte(c, zeilen, KONTAKT_ZUORDNUNG, {"quelle": "Webinar"})
        z = plan.zahlen()
        self.assertEqual((z["neu"], z["dublette"], z["ungueltig"], z["gesperrt"]), (20, 20, 20, 20))
        self.assertEqual(z["dublette_in_datei"], 10)
        self.assertEqual(z["dublette_bestand_aktualisiert"], 10)

        ergebnis = imports.importiere_kontakte(self.dbp, self.bak, "liste.csv", zeilen,
                                               KONTAKT_ZUORDNUNG, {"quelle": "Webinar"})
        self.assertEqual(ergebnis["neu"], 20)
        self.assertTrue(Path(ergebnis["backup"]).exists())
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 30)
            # Keine gesperrte Adresse als Kontakt angelegt
            self.assertEqual(c.execute("SELECT COUNT(*) FROM contacts c JOIN suppression_list s "
                                       "ON s.email = c.email").fetchone()[0], 0)
            k = c.execute("SELECT * FROM contacts WHERE email = 'bestand01@example.org'").fetchone()
            self.assertEqual(k["firma"], "Bestandsfirma 1")       # ergänzt
            self.assertEqual(k["vorname"], bsp.VORNAMEN[0])  # nicht überschrieben
            n = c.execute("SELECT * FROM contacts WHERE email = 'neu01@example.com'").fetchone()
            self.assertEqual(n["einwilligung_datum"], "2026-03-15")
            self.assertEqual(n["quelle"], "Webinar")
            log = c.execute("SELECT * FROM import_log WHERE dateiname = 'liste.csv'").fetchone()
            self.assertEqual((log["neu"], log["aktualisiert"], log["uebersprungen"]), (20, 10, 40))

    def test_zweiter_import_ist_idempotent(self):
        zeilen = lese_csv(bsp.als_csv(bsp.kontaktliste())).zeilen
        imports.importiere_kontakte(self.dbp, self.bak, "a.csv", zeilen, KONTAKT_ZUORDNUNG)
        e2 = imports.importiere_kontakte(self.dbp, self.bak, "a.csv", zeilen, KONTAKT_ZUORDNUNG)
        self.assertEqual(e2["neu"], 0)
        self.assertEqual(e2["dublette_bestand_aktualisiert"], 0)

    def test_ueberschreiben(self):
        self.lade_bestand_und_sperrliste()
        zeilen = [{"E-Mail": "bestand01@example.org", "Vorname": "Neu"}]
        imports.importiere_kontakte(self.dbp, self.bak, "x.csv", zeilen,
                                    {"email": "E-Mail", "vorname": "Vorname"}, modus="ueberschreiben")
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT vorname FROM contacts WHERE email = "
                                       "'bestand01@example.org'").fetchone()[0], "Neu")

    def test_backup_vor_jedem_import(self):
        self.lade_bestand_und_sperrliste()
        self.assertEqual(len(list(self.bak.glob("verteiler_*.db"))), 2)

    def test_rollback_bei_fehler(self):
        self.lade_bestand_und_sperrliste()
        zeilen = lese_csv(bsp.als_csv(bsp.kontaktliste())).zeilen
        echt = imports._log

        def kaputt(*a, **k):
            echt(*a, **k)
            raise RuntimeError("Absturz mitten im Import")

        with mock.patch.object(imports, "_log", kaputt):
            with self.assertRaises(RuntimeError):
                imports.importiere_kontakte(self.dbp, self.bak, "liste.csv", zeilen, KONTAKT_ZUORDNUNG)
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 10)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM import_log WHERE dateiname = "
                                       "'liste.csv'").fetchone()[0], 0)


# ------------------------------------------------ 2. Kampagnen-Report

class TestReport(Basis):
    def setUp(self):
        super().setUp()
        self.lade_bestand_und_sperrliste()

    def test_statusverarbeitung(self):
        e = self.report("Juni", "2026-06-01", [
            ("bestand01@example.org", "Anna", "Abel", 3, 1, "Zugestellt"),
            ("bestand02@example.org", "", "", 0, 0, "Unzustellbar"),
            ("bestand03@example.org", "", "", 1, 0, "Abgemeldet"),
            ("bestand04@example.org", "", "", 0, 0, "Soft-Bounce"),
            ("bestand05@example.org", "", "", 0, 0, "Nicht zugestellt"),
            ("bestand06@example.org", "", "", 0, 0, "Irgendwas"),
            ("fremd@example.com", "Fritz", "Fremd", 0, 0, "Zugestellt"),
            ("gesperrt01@example.net", "", "", 0, 0, "Zugestellt"),
            ("kaputt@", "", "", 0, 0, "Zugestellt"),
        ])
        self.assertEqual(self.status("bestand01@example.org"), "aktiv")
        self.assertEqual(self.status("bestand02@example.org"), "bounce_hart")
        self.assertEqual(self.gesperrt("bestand02@example.org"), "bounce_hart")
        self.assertEqual(self.status("bestand03@example.org"), "abgemeldet")
        self.assertEqual(self.gesperrt("bestand03@example.org"), "abgemeldet")
        self.assertEqual(self.status("bestand04@example.org"), "bounce_weich")
        self.assertIsNone(self.gesperrt("bestand04@example.org"))
        self.assertEqual(self.status("bestand05@example.org"), "aktiv")
        self.assertEqual(self.status("fremd@example.com"), "aktiv")         # neu angelegt
        self.assertEqual(self.status("gesperrt01@example.net"), "bounce_hart")  # nicht reaktiviert
        self.assertEqual(e["status_unbekannt"], 1)
        self.assertEqual(e["ungueltig"], 1)
        self.assertEqual(e["neue_kontakte"], 2)  # fremd@ + gesperrt01@ (als gesperrter Kontakt)
        with self.conn() as c:
            k = c.execute("SELECT * FROM campaigns").fetchone()
            self.assertEqual(k["empfaenger_anzahl"], 7)
            ev = c.execute("SELECT geoeffnet, geklickt FROM campaign_events e JOIN contacts c "
                           "ON c.id = e.contact_id WHERE c.email = 'bestand01@example.org'").fetchone()
            self.assertEqual(tuple(ev), (3, 1))

    def test_drei_soft_bounces_in_folge(self):
        adr = "bestand01@example.org"
        self.report("K1", "2026-01-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        self.assertEqual(self.status(adr), "bounce_weich")
        self.report("K2", "2026-02-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        self.assertEqual(self.status(adr), "bounce_weich")
        e = self.report("K3", "2026-03-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        self.assertEqual(e["soft_bounce_3x"], 1)
        self.assertEqual(self.status(adr), "bounce_hart")
        self.assertEqual(self.gesperrt(adr), "bounce_hart")

    def test_soft_bounce_serie_wird_unterbrochen(self):
        adr = "bestand01@example.org"
        self.report("K1", "2026-01-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        self.report("K2", "2026-02-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        self.report("K3", "2026-03-01", [(adr, "", "", 1, 0, "Zugestellt")])
        self.assertEqual(self.status(adr), "aktiv")
        self.report("K4", "2026-04-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        self.assertEqual(self.status(adr), "bounce_weich")
        self.assertIsNone(self.gesperrt(adr))

    def test_erneuter_import_zaehlt_nicht_doppelt(self):
        adr = "bestand01@example.org"
        e = self.report("K1", "2026-01-01", [(adr, "", "", 0, 0, "Soft-Bounce")])
        for _ in range(3):
            self.report("K1", "", [(adr, "", "", 0, 0, "Soft-Bounce")], kampagne_id=e["kampagne_id"])
        self.assertEqual(self.status(adr), "bounce_weich")
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM campaign_events").fetchone()[0], 1)

    def test_vorschau_aendert_nichts(self):
        t = lese_csv(bsp.reach_report([("bestand01@example.org", "", "", 0, 0, "Unzustellbar")]))
        with self.conn() as c:
            plan = imports.analysiere_report(c, t.zeilen, REPORT_ZUORDNUNG, auto_status(t), "2026-06-01")
        self.assertEqual(plan.zahlen()["neu_gesperrt_bounce_hart"], 1)
        self.assertIsNone(self.gesperrt("bestand01@example.org"))


# ------------------------------------------------ 3./4. Sperrliste und Export

class TestSperrlisteUndExport(Basis):
    def setUp(self):
        super().setUp()
        self.lade_bestand_und_sperrliste()

    def test_sperrliste_import(self):
        e = imports.importiere_sperrliste(
            self.dbp, self.bak, "abmeldungen.csv",
            [{"Mail": "BESTAND01@example.org", "Grund": "Abgemeldet"},
             {"Mail": "bestand02@example.org", "Grund": ""},
             {"Mail": "gesperrt01@example.net", "Grund": "Abgemeldet"},
             {"Mail": "nicht-gueltig", "Grund": ""}],
            {"email": "Mail", "grund": "Grund"}, "bounce_hart")
        self.assertEqual((e["neu_gesperrt"], e["bereits_gesperrt"], e["ungueltig"]), (2, 1, 1))
        self.assertEqual(self.status("bestand01@example.org"), "abgemeldet")
        self.assertEqual(self.status("bestand02@example.org"), "bounce_hart")
        self.assertEqual(self.gesperrt("gesperrt01@example.net"), "bounce_hart")  # erster Grund bleibt

    def test_export_niemals_gesperrt(self):
        self.report_daten()
        with self.conn() as c:
            gesperrt = {r[0] for r in c.execute("SELECT email FROM suppression_list")}
            for seg in queries.SEGMENTE:
                emails = {r["email"] for r in queries.segment_kontakte(c, seg, 90, date(2026, 6, 10))}
                self.assertFalse(emails & gesperrt, seg)

    def report_daten(self):
        self.report("Alt", "2025-11-01", [(f"bestand{i:02d}@example.org", "", "", 1 if i <= 2 else 0, 0,
                                           "Zugestellt") for i in range(1, 11)])
        self.report("Neu", "2026-06-01", [
            ("bestand01@example.org", "", "", 2, 1, "Zugestellt"),
            ("bestand03@example.org", "", "", 1, 0, "Zugestellt"),
            ("bestand04@example.org", "", "", 0, 0, "Zugestellt"),
            ("bestand05@example.org", "", "", 1, 0, "Unzustellbar"),  # geöffnet, aber gesperrt
            ("bestand06@example.org", "", "", 0, 0, "Abgemeldet"),
        ])

    def test_segmente(self):
        self.report_daten()
        heute = date(2026, 6, 10)
        with self.conn() as c:
            alle = {r["email"] for r in queries.segment_kontakte(c, "alle_aktiven", heute=heute)}
            eng = {r["email"] for r in queries.segment_kontakte(c, "engagierte", 90, heute)}
            ina = {r["email"] for r in queries.segment_kontakte(c, "inaktive", 180, heute)}
        self.assertEqual(len(alle), 8)  # 10 Bestand – 05 (bounce) – 06 (abgemeldet)
        self.assertEqual(eng, {"bestand01@example.org", "bestand03@example.org"})
        # Im Zeitraum (180 Tage) nichts geöffnet, aber schon vorher angeschrieben:
        self.assertEqual(ina, {f"bestand{i:02d}@example.org" for i in (2, 4, 7, 8, 9, 10)})

    def test_export_csv(self):
        with self.conn() as c:
            daten = queries.export_csv(queries.segment_kontakte(c, "alle_aktiven"), ",")
        self.assertTrue(daten.startswith(b"\xef\xbb\xbf"))
        t = lese_csv(daten)
        self.assertEqual(t.kopfzeilen, ["E-Mail", "Vorname", "Nachname"])
        self.assertEqual(len(t.zeilen), 10)

    def test_formel_injection(self):
        queries.kontakt_anlegen(self.dbp, {"email": "f@example.com", "vorname": "=HYPERLINK(1)"})
        with self.conn() as c:
            t = lese_csv(queries.export_csv(queries.segment_kontakte(c, "alle_aktiven")))
        z = [r for r in t.zeilen if r["E-Mail"] == "f@example.com"][0]
        self.assertEqual(z["Vorname"], "'=HYPERLINK(1)")

    def test_kennzahlen(self):
        self.report_daten()
        with self.conn() as c:
            k = queries.kampagnen_kennzahlen(c)[0]  # neueste zuerst
        self.assertEqual(k["name"], "Neu")
        self.assertAlmostEqual(k["bounce_rate"], 1 / 5)
        self.assertTrue(k["warnung"])
        self.assertAlmostEqual(k["oeffnungsrate"], 3 / 5)
        self.assertAlmostEqual(k["oeffnungsrate_zugestellt"], 3 / 4)


# --------------------------------------- 6. Kontaktpflege und Schutzregeln

class TestSchutz(Basis):
    def setUp(self):
        super().setUp()
        self.lade_bestand_und_sperrliste()

    def test_trigger_schuetzen_sperrliste(self):
        with self.conn() as c:
            for sql in ("DELETE FROM suppression_list",
                        "UPDATE suppression_list SET email = 'x@example.com'"):
                with self.assertRaises(sqlite3.DatabaseError):
                    c.execute(sql)
            with db.transaction(c):
                imports.sperren(c, "bestand01@example.org", "manuell")
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("UPDATE contacts SET status = 'aktiv' WHERE email = 'bestand01@example.org'")
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("DELETE FROM contacts WHERE email = 'bestand01@example.org'")
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("INSERT INTO contacts (email, status, erstellt_am, geaendert_am) "
                          "VALUES ('gesperrt02@example.net', 'aktiv', 'x', 'x')")
        self.assertEqual(self.gesperrt("bestand01@example.org"), "manuell")

    def test_manuell_anlegen_gesperrt_verweigert(self):
        with self.assertRaises(imports.ImportFehler):
            queries.kontakt_anlegen(self.dbp, {"email": "Gesperrt03@example.net"})

    def test_bearbeiten_und_sperren(self):
        with self.conn() as c:
            kid = c.execute("SELECT id FROM contacts WHERE email = 'bestand01@example.org'").fetchone()[0]
        queries.kontakt_aktualisieren(self.dbp, kid, {"einwilligung_art": "Double-Opt-In",
                                                      "einwilligung_datum": "01.02.2026"})
        with self.conn() as c:
            k = queries.kontakt(c, kid)
        self.assertEqual((k["einwilligung_art"], k["einwilligung_datum"]), ("Double-Opt-In", "2026-02-01"))
        self.assertTrue(queries.kontakt_sperren(self.dbp, kid))
        self.assertEqual(self.status("bestand01@example.org"), "gesperrt")

    def test_dsgvo_loeschung(self):
        with self.conn() as c:
            kid = c.execute("SELECT id FROM contacts WHERE email = 'bestand01@example.org'").fetchone()[0]
        with self.assertRaises(imports.ImportFehler):
            queries.kontakt_dsgvo_loeschen(self.dbp, kid, "falsch@example.org")
        queries.kontakt_dsgvo_loeschen(self.dbp, kid, "bestand01@example.org", sperre_behalten=True)
        self.assertIsNone(self.status("bestand01@example.org"))
        self.assertEqual(self.gesperrt("bestand01@example.org"), "manuell")
        # Erneuter Import der Altliste bringt die Adresse nicht zurück
        e = imports.importiere_kontakte(self.dbp, self.bak, "alt.csv",
                                        [{"E-Mail": "bestand01@example.org"}], {"email": "E-Mail"})
        self.assertEqual((e["neu"], e["gesperrt"]), (0, 1))
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM dsgvo_freigabe").fetchone()[0], 0)
            log = c.execute("SELECT details FROM import_log WHERE art = 'dsgvo_loeschung'").fetchone()
        self.assertNotIn("bestand01", log["details"])

    def test_dsgvo_loeschung_ohne_sperre(self):
        with self.conn() as c:
            kid = c.execute("SELECT id FROM contacts WHERE email = 'bestand02@example.org'").fetchone()[0]
        queries.kontakt_sperren(self.dbp, kid)
        queries.kontakt_dsgvo_loeschen(self.dbp, kid, "bestand02@example.org", sperre_behalten=False)
        self.assertIsNone(self.gesperrt("bestand02@example.org"))
        self.assertIsNone(self.status("bestand02@example.org"))


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------ Server-Betrieb: Anmeldung

class TestAnmeldung(unittest.TestCase):
    """Prüft verteiler_core.auth gegen einen kleinen Fake-Intranet-Server."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                cookie = self.headers.get("Cookie", "")
                if "admin-ok" in cookie:
                    self.send_response(204)
                    self.send_header("X-Verteiler-User", "m%C3%BCller%40fb-eng.de")
                elif "mitarbeiter" in cookie:
                    self.send_response(403)
                else:
                    self.send_response(303)
                    self.send_header("Location", "/login")
                self.end_headers()

            def log_message(self, *a):
                pass

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/auth/verteiler"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_ergebnisse(self):
        from verteiler_core import auth
        ok = auth.pruefen("projektabrechnung_session=admin-ok", self.url)
        self.assertEqual((ok.erlaubt, ok.benutzer), (True, "müller@fb-eng.de"))
        self.assertEqual(auth.pruefen("x=mitarbeiter", self.url).grund, "kein_recht")
        self.assertEqual(auth.pruefen("x=irgendwas", self.url).grund, "nicht_angemeldet")
        self.assertEqual(auth.pruefen("", self.url).grund, "nicht_angemeldet")
        # Intranet nicht erreichbar -> gesperrt (fail closed)
        self.assertEqual(auth.pruefen("x=admin-ok", "http://127.0.0.1:1/auth").grund, "fehler")

    def test_servermodus_ohne_url_gesperrt(self):
        from verteiler_core import auth
        with mock.patch.dict("os.environ", {"VERTEILER_MODUS": "server", "VERTEILER_AUTH_URL": ""}):
            self.assertFalse(auth.pruefen("x=admin-ok").erlaubt)
        with mock.patch.dict("os.environ", {"VERTEILER_MODUS": "", "VERTEILER_AUTH_URL": ""}):
            self.assertTrue(auth.pruefen("").erlaubt)  # lokaler Windows-Betrieb

    def test_migration_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "alt.db"
            c = sqlite3.connect(p)
            c.executescript(db.SCHEMA.replace("    details       TEXT NOT NULL DEFAULT '',\n"
                                              "    benutzer      TEXT NOT NULL DEFAULT ''\n",
                                              "    details       TEXT NOT NULL DEFAULT ''\n"))
            c.execute("PRAGMA user_version = 1")
            c.close()
            with closing(db.connect(p)) as c2:
                spalten = [r[1] for r in c2.execute("PRAGMA table_info(import_log)")]
                self.assertIn("benutzer", spalten)
                self.assertEqual(c2.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)


# ------------------------------------------------ Abo-Status (Subscription Status)

class TestAboStatus(Basis):
    def test_subscribed_unsubscribed(self):
        self.lade_bestand_und_sperrliste()
        kopf = ["Email", "First Name", "Last Name", "Subscribed At", "Subscription Status"]
        self.assertEqual(spalte_erkennen("abo_status", kopf), "Subscription Status")
        self.assertEqual(spalte_erkennen("einwilligung_datum", kopf), "Subscribed At")
        zeilen = [
            {"Email": "neu1@example.com", "Subscribed At": "2025-03-01", "Subscription Status": "subscribed"},
            {"Email": "neu2@example.com", "Subscribed At": "", "Subscription Status": "unsubscribed"},
            {"Email": "neu3@example.com", "Subscribed At": "", "Subscription Status": "pending"},
            {"Email": "neu4@example.com", "Subscribed At": "", "Subscription Status": ""},
            # gleiche Adresse zweimal, einmal abgemeldet -> abgemeldet gewinnt
            {"Email": "neu5@example.com", "Subscribed At": "", "Subscription Status": "subscribed"},
            {"Email": "NEU5@example.com", "Subscribed At": "", "Subscription Status": "Unsubscribed"},
            # bestehender aktiver Kontakt meldet sich ab -> gesperrt
            {"Email": "bestand01@example.org", "Subscribed At": "", "Subscription Status": "unsubscribed"},
            # steht schon auf der Sperrliste
            {"Email": "gesperrt01@example.net", "Subscribed At": "", "Subscription Status": "subscribed"},
        ]
        zuo = {"email": "Email", "einwilligung_datum": "Subscribed At", "abo_status": "Subscription Status"}
        e = imports.importiere_kontakte(self.dbp, self.bak, "reach.csv", zeilen, zuo)
        self.assertEqual((e["neu"], e["abo_abgemeldet"], e["abo_unklar"], e["gesperrt"]), (2, 3, 1, 1))
        self.assertEqual(self.status("neu1@example.com"), "aktiv")
        self.assertEqual(self.status("neu4@example.com"), "aktiv")
        self.assertIsNone(self.status("neu2@example.com"))      # nicht als Kontakt angelegt …
        self.assertEqual(self.gesperrt("neu2@example.com"), "abgemeldet")  # … aber gesperrt
        self.assertEqual(self.gesperrt("neu5@example.com"), "abgemeldet")
        self.assertIsNone(self.status("neu3@example.com"))      # pending: übersprungen
        self.assertEqual(self.status("bestand01@example.org"), "abgemeldet")
        with self.conn() as c:
            d = c.execute("SELECT einwilligung_datum FROM contacts WHERE email = 'neu1@example.com'").fetchone()[0]
            emails = {r["email"] for r in queries.segment_kontakte(c, "alle_aktiven")}
        self.assertEqual(d, "2025-03-01")
        self.assertFalse({"neu2@example.com", "neu5@example.com", "bestand01@example.org"} & emails)


# ------------------------------------------------ Postfach (Microsoft, simuliert)

class FakeMicrosoft:
    """Kleiner Fake von login.microsoftonline.com + graph.microsoft.com (delegiert)."""

    def __init__(self, mails):
        import http.server
        import threading
        import urllib.parse as up
        fake = self
        fake.mails = mails
        fake.anfragen = []
        fake.refresh_gueltig = {"r1"}
        fake.zugriff_erlaubt = True

        class Handler(http.server.BaseHTTPRequestHandler):
            def _json(self, code, daten):
                body = json.dumps(daten).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                felder = dict(up.parse_qsl(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()))
                if felder.get("client_secret") != "geheim":
                    return self._json(401, {"error": "invalid_client"})
                if "offline_access" not in felder.get("scope", ""):
                    return self._json(400, {"error": "invalid_scope"})
                if felder.get("grant_type") == "authorization_code":
                    if felder.get("code") != "gutercode" or felder.get("redirect_uri") != "https://intern.example/verteiler/":
                        return self._json(400, {"error": "invalid_grant"})
                    return self._json(200, {"access_token": "tok", "refresh_token": "r1", "expires_in": 3600})
                if felder.get("grant_type") == "refresh_token":
                    rt = felder.get("refresh_token")
                    if rt not in fake.refresh_gueltig:
                        return self._json(400, {"error": "invalid_grant"})
                    neu = "r" + str(int(rt[1:]) + 1)  # Microsoft tauscht das Refresh-Token aus
                    fake.refresh_gueltig = {neu}
                    return self._json(200, {"access_token": "tok", "refresh_token": neu, "expires_in": 3600})
                return self._json(400, {"error": "unsupported_grant_type"})

            def do_GET(self):
                fake.anfragen.append(self.path)
                if self.headers.get("Authorization") != "Bearer tok":
                    return self._json(401, {"error": {"code": "InvalidAuthenticationToken"}})
                if self.path.startswith("/v1.0/me"):
                    return self._json(200, {"mail": "D.Model@fb-eng.de"})
                if "/users/verteiler@fb-eng.de/mailFolders/inbox/messages" not in self.path:
                    return self._json(404, {"error": {"code": "ErrorItemNotFound"}})
                if not fake.zugriff_erlaubt:
                    return self._json(403, {"error": {"code": "ErrorAccessDenied"}})
                if "seite=2" in self.path:
                    return self._json(200, {"value": fake.mails[1:]})
                return self._json(200, {"value": fake.mails[:1],
                                        "@odata.nextLink": fake.basis + "/v1.0/users/verteiler@fb-eng.de"
                                        "/mailFolders/inbox/messages?seite=2"})

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.basis = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def app(self, secret="geheim"):
        from verteiler_core import postfach
        return postfach.MsApp(client_id="app", client_secret=secret, tenant_id="tenant",
                              redirect_uri="https://intern.example/verteiler/",
                              login_url=self.basis, graph_url=self.basis + "/v1.0")

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def graph_mail(nr, von, an, cc, text, betreff="Projekt"):
    def adr(a):
        name, email = a
        return {"emailAddress": {"name": name, "address": email}}
    return {"id": f"AAMk{nr}", "internetMessageId": f"<{nr}@mail>", "subject": betreff,
            "receivedDateTime": f"2026-10-0{nr}T08:00:00Z", "from": adr(von),
            "toRecipients": [adr(a) for a in an], "ccRecipients": [adr(a) for a in cc],
            "body": {"contentType": "text", "content": text}}


class TestPostfach(Basis):
    def setUp(self):
        super().setUp()
        from verteiler_core import postfach
        self.pf = postfach
        self.lade_bestand_und_sperrliste()
        self.ms = FakeMicrosoft([
            graph_mail(1, ("Daniel Model", "d.model@fb-eng.de"),
                       [("Verteiler", "verteiler@fb-eng.de")], [("Kunde, Karl", "Karl.Kunde@kunde.de")],
                       "Von: Anna Schmidt <anna.schmidt@planer.de>\nAn: Bernd Bau <b.bau@bau-ag.de>\n"
                       "Bitte info@stadtwerke.de und noreply@system.de informieren. "
                       "Gesperrt: gesperrt01@example.net, bekannt: bestand01@example.org"),
            graph_mail(2, ("Ida Imhof", "ida@imhof.de"), [("Verteiler", "verteiler@fb-eng.de")], [],
                       "Kein weiterer Kontakt. image001.png@01DA1234.5678ABCD", betreff="Anfrage"),
        ])
        self.speicher = postfach.TokenSpeicher(Path(self.tmp.name) / "token.json")

    def tearDown(self):
        self.ms.stop()
        super().tearDown()

    def verbinden(self, benutzer="admin"):
        url = self.pf.verbinden_url(self.dbp, self.ms.app(), benutzer)
        state = dict(__import__("urllib.parse").parse.parse_qsl(url.split("?", 1)[1]))["state"]
        return self.pf.verbindung_abschliessen(self.dbp, self.ms.app(), self.speicher, "gutercode", state, benutzer)

    def test_verbinden_und_abrufen(self):
        import os
        import stat
        url = self.pf.verbinden_url(self.dbp, self.ms.app(), "admin")
        self.assertIn("redirect_uri=https%3A%2F%2Fintern.example%2Fverteiler%2F", url)
        self.assertIn("Mail.Read", url)
        self.assertNotIn("geheim", url)
        # Neuladen der Seite nutzt denselben State
        self.assertEqual(url, self.pf.verbinden_url(self.dbp, self.ms.app(), "admin"))
        konto = self.verbinden()
        self.assertEqual(konto, "d.model@fb-eng.de")
        self.assertEqual(stat.S_IMODE(os.stat(self.speicher.pfad).st_mode), 0o600)
        self.assertNotIn("refresh_token", json.dumps(self.speicher.status()))
        with self.conn() as c:  # Postfach-Adresse wurde mit dem Konto vorbelegt
            self.assertEqual(db.einstellung(c, "postfach_adresse"), "d.model@fb-eng.de")
        self.pf.einstellungen_speichern(self.dbp, "Verteiler@FB-Eng.de", "", True, "admin")

        e = self.pf.abrufen(self.dbp, self.bak, self.ms.app(), self.speicher, benutzer="test")
        self.assertEqual(e.mails, 2)
        self.assertEqual(e.neu, 5)  # karl, anna, bernd, info@stadtwerke, ida
        self.assertEqual((e.bekannt, e.gesperrt), (1, 1))
        self.assertEqual(e.ignoriert, 4)  # d.model (intern), verteiler (2x Postfach), noreply
        self.assertEqual(self.speicher.laden()["refresh_token"], "r2")  # Austausch gespeichert
        with self.conn() as c:
            k = c.execute("SELECT * FROM contacts WHERE email = 'karl.kunde@kunde.de'").fetchone()
            self.assertEqual((k["vorname"], k["nachname"], k["quelle"]), ("Karl", "Kunde", "Postfach: Projekt"))
            self.assertIsNone(c.execute("SELECT 1 FROM contacts WHERE email = 'd.model@fb-eng.de'").fetchone())
            self.assertIsNone(c.execute("SELECT 1 FROM contacts WHERE email = 'gesperrt01@example.net'").fetchone())
            self.assertEqual(c.execute("SELECT COUNT(*) FROM mail_eingang").fetchone()[0], 2)
            zeilen = " ".join(str(tuple(r)) for r in c.execute("SELECT * FROM mail_eingang"))
            self.assertNotIn("@kunde.de", zeilen)
        # Token steht weder in der DB noch in den Backups
        for datei in [self.dbp, *self.bak.glob("*.db")]:
            self.assertNotIn(b"r2", Path(datei).read_bytes().replace(b"r2@", b""))
        self.assertTrue(any("seite=2" in a for a in self.ms.anfragen))
        e2 = self.pf.abrufen(self.dbp, self.bak, self.ms.app(), self.speicher)
        self.assertEqual((e2.mails, e2.neu), (0, 0))

    def test_state_schutz(self):
        url = self.pf.verbinden_url(self.dbp, self.ms.app(), "admin")
        state = dict(__import__("urllib.parse").parse.parse_qsl(url.split("?", 1)[1]))["state"]
        with self.assertRaises(self.pf.PostfachFehler):  # anderer Benutzer
            self.pf.verbindung_abschliessen(self.dbp, self.ms.app(), self.speicher, "gutercode", state, "eve")
        with self.assertRaises(self.pf.PostfachFehler):  # State ist jetzt verbraucht
            self.pf.verbindung_abschliessen(self.dbp, self.ms.app(), self.speicher, "gutercode", state, "admin")
        with self.assertRaises(self.pf.PostfachFehler):  # erfundener State
            self.pf.verbindung_abschliessen(self.dbp, self.ms.app(), self.speicher, "gutercode", "vtxyz", "admin")
        self.assertIsNone(self.speicher.laden())

    def test_abgelaufen_und_kein_zugriff(self):
        self.verbinden()
        self.pf.einstellungen_speichern(self.dbp, "verteiler@fb-eng.de", "fb-eng.de, rss-fb.com", True, "admin")
        self.ms.zugriff_erlaubt = False
        with self.assertRaises(self.pf.PostfachFehler) as ctx:
            self.pf.abrufen(self.dbp, self.bak, self.ms.app(), self.speicher)
        self.assertIn("Vollzugriff", str(ctx.exception))
        self.ms.refresh_gueltig = set()  # Zugang widerrufen
        with self.assertRaises(self.pf.PostfachFehler) as ctx:
            self.pf.abrufen(self.dbp, self.bak, self.ms.app(), self.speicher)
        self.assertIn("neu verbinden", str(ctx.exception))
        self.assertIn("neu verbinden", self.speicher.status()["fehler"])
        self.pf.trennen(self.dbp, self.speicher, "admin")
        self.assertIsNone(self.speicher.laden())

    def test_ungueltige_einstellungen(self):
        with self.assertRaises(self.pf.PostfachFehler):
            self.pf.einstellungen_speichern(self.dbp, "kein-postfach", "", True, "admin")
        with self.assertRaises(self.pf.PostfachFehler):
            self.pf.einstellungen_speichern(self.dbp, "verteiler@fb-eng.de", "fb eng .de", True, "admin")


# ------------------------------------------------ Mailing-Tool (simuliert)

class FakeMailing:
    """Simuliert POST /api/integration/verteiler des Mailing-Tools."""

    def __init__(self, gesperrt_dort=None):
        import http.server
        import threading
        fake = self
        fake.anfragen = []
        fake.gesperrt_dort = gesperrt_dort or {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer " + "t" * 64:
                    code, daten = 401, {"error": "Nicht autorisiert"}
                else:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                    fake.anfragen.append(body)
                    liste = body.get("list")
                    code, daten = 200, {
                        "suppressionsAdded": len(body.get("suppress", [])), "contactsBlocked": 0, "jobsSkipped": 1,
                        "list": ({"id": "L", "name": liste["name"], "created": len(liste["contacts"]), "updated": 0,
                                  "suppressed": 0, "invalid": 0, "members": len(liste["contacts"]), "removed": 0}
                                 if liste else None),
                        "suppressions": [{"email": e, "grund": g, "since": "2026-10-05T08:00:00Z"}
                                         for e, g in fake.gesperrt_dort.items()],
                    }
                out = json.dumps(daten).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class TestMailing(Basis):
    def setUp(self):
        super().setUp()
        from verteiler_core import mailing
        self.ml = mailing
        self.lade_bestand_und_sperrliste()
        self.fake = FakeMailing({"bestand01@example.org": "abgemeldet",      # Abmeldelink im Mailing-Tool
                                 "fremd@example.com": "bounce_hart",          # nicht gefragt -> ignoriert
                                 "bestand02@example.org": "quatsch"})         # unbekannter Grund -> ignoriert
        self.zugang = mailing.Zugang(url=self.fake.url, token="t" * 64)

    def tearDown(self):
        self.fake.stop()
        super().tearDown()

    def test_abgleich(self):
        self.ml.einstellungen_speichern(self.dbp, self.ml.Einstellungen(aktiv=True, liste="Verteiler: Test"), "admin")
        e = self.ml.abgleichen(self.dbp, self.bak, self.zugang, benutzer="admin")
        anfrage = self.fake.anfragen[-1]
        self.assertEqual(len(anfrage["suppress"]), 20)            # komplette Sperrliste
        self.assertEqual(len(anfrage["list"]["contacts"]), 10)    # Segment "alle aktiven"
        self.assertEqual(anfrage["list"]["name"], "Verteiler: Test")
        self.assertEqual(len(anfrage["check"]), 10)
        self.assertFalse({s["email"] for s in anfrage["suppress"]} & {c["email"] for c in anfrage["list"]["contacts"]})
        self.assertEqual((e.liste_gesendet, e.hier_neu_gesperrt, e.rueckmeldungen), (True, 1, 1))
        self.assertEqual(self.status("bestand01@example.org"), "abgemeldet")
        self.assertEqual(self.gesperrt("bestand01@example.org"), "abgemeldet")
        self.assertIsNone(self.status("fremd@example.com"))
        self.assertEqual(self.status("bestand02@example.org"), "aktiv")
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM import_log WHERE art = 'mailing'").fetchone()[0], 1)
            self.assertIsNotNone(self.ml.letzter_stand(c))

        # Zweiter Lauf: bestand01 ist jetzt gesperrt -> Liste hat sich geändert (9 Empfänger),
        # die neue Sperre geht mit ins Mailing-Tool
        e2 = self.ml.abgleichen(self.dbp, self.bak, self.zugang)
        anfrage2 = self.fake.anfragen[-1]
        self.assertTrue(e2.liste_gesendet)
        self.assertEqual(len(anfrage2["list"]["contacts"]), 9)
        self.assertEqual(len(anfrage2["suppress"]), 21)
        # Dritter Lauf: nichts geändert -> Liste wird nicht erneut geschickt
        e3 = self.ml.abgleichen(self.dbp, self.bak, self.zugang)
        self.assertNotIn("list", self.fake.anfragen[-1])
        self.assertFalse(e3.liste_gesendet)
        # Erzwingen schickt sie trotzdem
        self.ml.abgleichen(self.dbp, self.bak, self.zugang, liste_erzwingen=True)
        self.assertEqual(len(self.fake.anfragen[-1]["list"]["contacts"]), 9)

    def test_falsches_token_und_unsichere_url(self):
        with self.assertRaises(self.ml.MailingFehler) as ctx:
            self.ml.abgleichen(self.dbp, self.bak, self.ml.Zugang(url=self.fake.url, token="x" * 64))
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn("x" * 10, str(ctx.exception))
        with self.conn() as c:
            self.assertTrue(self.ml.letzter_stand(c).fehler)
        z = self.ml.zugang_aus_env({"MAILING_URL": "http://mailing.example.com", "MAILING_SYNC_TOKEN": "t" * 64})
        self.assertFalse(z.konfiguriert)  # Token nie über http ins Netz
        z = self.ml.zugang_aus_env({"MAILING_SYNC_TOKEN": "kurz"})
        self.assertFalse(z.konfiguriert)

    def test_hintergrund_durchlauf(self):
        from verteiler_core import hintergrund
        self.ml.einstellungen_speichern(self.dbp, self.ml.Einstellungen(aktiv=True), "admin")
        with mock.patch.dict("os.environ", {"MAILING_URL": self.fake.url, "MAILING_SYNC_TOKEN": "t" * 64}):
            hintergrund.ein_durchlauf(str(self.dbp), str(self.bak))
        self.assertEqual(len(self.fake.anfragen), 1)
        self.assertEqual(self.gesperrt("bestand01@example.org"), "abgemeldet")
