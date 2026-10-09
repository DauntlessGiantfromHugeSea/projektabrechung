"""
Dateien lesen und schreiben: CSV (UTF-8 mit/ohne BOM, Trennzeichen ; oder ,)
und XLSX (nur Standardbibliothek, ohne openpyxl).
"""

from __future__ import annotations

import csv
import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

MAX_DATEI_BYTES = 50 * 1024 * 1024        # Upload-Grenze
MAX_XLSX_ENTPACKT = 300 * 1024 * 1024     # Schutz vor "Zip-Bomben"
MAX_ZEILEN = 500_000
MAX_SPALTEN = 500                          # breitere Tabellen sind kein Kontaktimport
MAX_ZELLEN = 5_000_000                     # Zeilen x Spalten (Speicherschutz)


class DateiFehler(ValueError):
    """Datei kann nicht gelesen werden (Meldung ist für Nutzer gedacht)."""


@dataclass
class Tabelle:
    kopfzeilen: list[str]
    zeilen: list[dict[str, str]]
    trennzeichen: str = ""
    kodierung: str = ""
    hinweise: list[str] = field(default_factory=list)


def lese_datei(dateiname: str, daten: bytes) -> Tabelle:
    """Liest CSV oder XLSX anhand der Dateiendung."""
    if len(daten) > MAX_DATEI_BYTES:
        raise DateiFehler(f"Datei ist größer als {MAX_DATEI_BYTES // (1024 * 1024)} MB.")
    name = (dateiname or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        return lese_xlsx(daten)
    if name.endswith(".xls"):
        raise DateiFehler("Altes Excel-Format (.xls) wird nicht unterstützt – bitte in "
                          "Excel als .xlsx oder CSV (UTF-8) speichern.")
    return lese_csv(daten)


# ---------------------------------------------------------------- CSV

def _dekodieren(daten: bytes) -> tuple[str, str, list[str]]:
    try:
        # utf-8-sig entfernt ein vorhandenes BOM und liest auch UTF-8 ohne BOM.
        return daten.decode("utf-8-sig"), "UTF-8", []
    except UnicodeDecodeError:
        text = daten.decode("cp1252", errors="replace")
        return text, "Windows-1252", [
            "Die Datei ist nicht UTF-8-kodiert und wurde als Windows-1252 gelesen. "
            "Bitte Umlaute in der Vorschau prüfen und künftig als „CSV UTF-8“ speichern."]


def erkenne_trennzeichen(text: str) -> str:
    """Wählt ; oder , – das Zeichen, das die Kopfzeile in mehr Spalten teilt."""
    erste = ""
    for zeile in text.splitlines():
        if zeile.strip():
            erste = zeile
            break
    if erste.lower().startswith("sep=") and len(erste) >= 5:
        return erste[4]
    besten, max_spalten = ";", 0
    for kandidat in (";", ","):
        try:
            n = len(next(csv.reader([erste], delimiter=kandidat)))
        except (csv.Error, StopIteration):
            n = 0
        if n > max_spalten:
            besten, max_spalten = kandidat, n
    return besten


def _kopfzeilen_bereinigen(roh: list[str]) -> list[str]:
    ergebnis: list[str] = []
    gesehen: dict[str, int] = {}
    for i, k in enumerate(roh, start=1):
        k = (k or "").replace("﻿", "").strip() or f"Spalte {i}"
        if k in gesehen:
            gesehen[k] += 1
            k = f"{k} ({gesehen[k]})"
        else:
            gesehen[k] = 1
        ergebnis.append(k)
    return ergebnis


def _tabelle_aus_zeilen(roh_zeilen: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    zeilen_iter = iter(roh_zeilen)
    kopf_roh = None
    for z in zeilen_iter:
        if any((c or "").strip() for c in z):
            kopf_roh = z
            break
    if kopf_roh is None:
        raise DateiFehler("Die Datei ist leer.")
    # Leere Spalten rechts abschneiden; zu breite Köpfe ablehnen (Speicherschutz,
    # Sicherheits-Audit 2026-10: winzige Dateien konnten GB-weise RAM belegen).
    kopf_roh = list(kopf_roh)
    while kopf_roh and not (kopf_roh[-1] or "").strip():
        kopf_roh.pop()
    if len(kopf_roh) > MAX_SPALTEN:
        raise DateiFehler(f"Mehr als {MAX_SPALTEN} Spalten – das ist keine Kontaktliste.")
    kopf = _kopfzeilen_bereinigen(kopf_roh)
    max_zeilen = min(MAX_ZEILEN, MAX_ZELLEN // max(len(kopf), 1))
    daten: list[dict[str, str]] = []
    for z in zeilen_iter:
        if not any((c or "").strip() for c in z):
            continue
        if len(daten) >= max_zeilen:
            raise DateiFehler(f"Mehr als {max_zeilen} Zeilen – bitte Datei aufteilen.")
        werte = list(z)[:len(kopf)] + [""] * (len(kopf) - len(z))
        daten.append({k: (werte[i] or "") for i, k in enumerate(kopf)})
    return kopf, daten


def lese_csv(daten: bytes) -> Tabelle:
    text, kodierung, hinweise = _dekodieren(daten)
    trenn = erkenne_trennzeichen(text)
    zeilen_text = text.splitlines()
    if zeilen_text and zeilen_text[0].lower().startswith("sep="):
        text = "\n".join(zeilen_text[1:])
    try:
        roh = list(csv.reader(io.StringIO(text, newline=""), delimiter=trenn))
    except csv.Error as exc:
        raise DateiFehler(f"CSV konnte nicht gelesen werden: {exc}") from exc
    kopf, zeilen = _tabelle_aus_zeilen(roh)
    return Tabelle(kopf, zeilen, trennzeichen=trenn, kodierung=kodierung, hinweise=hinweise)


def schreibe_csv(kopfzeilen: list[str], zeilen: list[list[str]], trennzeichen: str = ";") -> bytes:
    """CSV als UTF-8 mit BOM (Excel-tauglich), Zeilenende CRLF."""
    puffer = io.StringIO(newline="")
    w = csv.writer(puffer, delimiter=trennzeichen, quoting=csv.QUOTE_MINIMAL,
                   lineterminator="\r\n")
    w.writerow(kopfzeilen)
    w.writerows(zeilen)
    return ("﻿" + puffer.getvalue()).encode("utf-8")


# ---------------------------------------------------------------- XLSX

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _spalten_index(zellbezug: str) -> int:
    n = 0
    for ch in zellbezug:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _xml(zf: zipfile.ZipFile, pfad: str) -> ET.Element:
    try:
        return ET.fromstring(zf.read(pfad))
    except KeyError as exc:
        raise DateiFehler(f"XLSX unvollständig ({pfad} fehlt).") from exc
    except ET.ParseError as exc:
        raise DateiFehler("XLSX-Datei ist beschädigt.") from exc


def _zahl_als_text(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return v
    if f.is_integer() and abs(f) < 1e15:
        return str(int(f))
    return v


def lese_xlsx(daten: bytes) -> Tabelle:
    """Liest das erste Tabellenblatt einer .xlsx-Datei."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile as exc:
        raise DateiFehler("Keine gültige XLSX-Datei.") from exc
    with zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_XLSX_ENTPACKT:
            raise DateiFehler("XLSX-Datei ist entpackt zu groß.")

        wb = _xml(zf, "xl/workbook.xml")
        blatt = wb.find("m:sheets/m:sheet", _NS)
        if blatt is None:
            raise DateiFehler("XLSX enthält kein Tabellenblatt.")
        rid = blatt.get(f"{{{_NS['r']}}}id")
        ziel = "worksheets/sheet1.xml"
        rels = _xml(zf, "xl/_rels/workbook.xml.rels")
        for rel in rels.findall("rel:Relationship", _NS):
            if rel.get("Id") == rid:
                ziel = rel.get("Target", ziel)
                break
        blatt_pfad = ziel.lstrip("/") if ziel.startswith("/") else posixpath.normpath(
            posixpath.join("xl", ziel))

        geteilt: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            for si in _xml(zf, "xl/sharedStrings.xml").findall("m:si", _NS):
                geteilt.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))

        sheet = _xml(zf, blatt_pfad)
        roh: list[list[str]] = []
        for row in sheet.iter(f"{{{_NS['m']}}}row"):
            werte: dict[int, str] = {}
            naechste = 0
            for c in row.findall("m:c", _NS):
                ref = c.get("r")
                idx = _spalten_index(ref) if ref else naechste
                naechste = idx + 1
                typ = c.get("t", "n")
                v = c.find("m:v", _NS)
                if typ == "s" and v is not None and v.text is not None:
                    try:
                        text = geteilt[int(v.text)]
                    except (ValueError, IndexError):
                        text = ""
                elif typ == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
                elif typ == "b":
                    text = "WAHR" if (v is not None and v.text == "1") else "FALSCH"
                elif v is not None and v.text is not None:
                    text = v.text if typ in ("str", "e") else _zahl_als_text(v.text)
                else:
                    text = ""
                if not text.strip():
                    continue          # leere/nur formatierte Zellen bestimmen nicht die Breite
                if not 0 <= idx < MAX_SPALTEN:
                    raise DateiFehler(f"Mehr als {MAX_SPALTEN} Spalten – das ist keine Kontaktliste.")
                werte[idx] = text
            if werte:
                breite = max(werte) + 1
                roh.append([werte.get(i, "") for i in range(breite)])
            else:
                roh.append([])
            if len(roh) > MAX_ZEILEN + 1:
                raise DateiFehler(f"Mehr als {MAX_ZEILEN} Zeilen – bitte Datei aufteilen.")

    kopf, zeilen = _tabelle_aus_zeilen(roh)
    return Tabelle(kopf, zeilen, trennzeichen="", kodierung="XLSX")
