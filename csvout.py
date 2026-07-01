"""
CSV im Arcadis-Stundennachweis-Format:
    Datum;Nachname;Vorname;Stunden;Taetigkeitsbeschreibung
- Semikolon-getrennt (deutsches Excel), Stunden mit Dezimalkomma, KEIN Preis.
- UTF-8 mit BOM, damit Excel Umlaute korrekt anzeigt.
"""

from __future__ import annotations

import csv
import io
import re

import config
from events import Interval


def _split_name(full: str) -> tuple[str, str]:
    """'Vorname [...] Nachname' -> (Nachname, Vorname)."""
    parts = (full or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def _hours(h: float) -> str:
    return f"{round(max(h, 0.0), 2):.2f}".replace(".", ",")


def _amprion_name(full: str) -> str:
    """'Vorname Nachname' -> 'Nachname, Vorname' (eine Spalte)."""
    nach, vor = _split_name(full)
    return f"{nach}, {vor}" if vor else nach


def _amprion_task(project: str) -> str | None:
    """Projekt -> Amprion-Task-Nr. anhand des Mappings, sonst None."""
    p = (project or "").lower()
    for label, nr in config.AMPRION_MAP:
        if label.lower() in p or nr in p:
            return nr
    return None


def _leading_number(project: str) -> str:
    """Erste Ziffernfolge im Projektnamen (z. B. '26344 - Arcadis …' -> '26344')."""
    m = re.search(r"\d+", project or "")
    return m.group(0) if m else ""


def _hours1(h: float) -> str:
    """Stunden mit genau einer Nachkommastelle und Dezimalkomma (z. B. '10,0')."""
    return f"{round(max(h, 0.0), 1):.1f}".replace(".", ",")


def amprion_csv(intervals: list[Interval]) -> bytes:
    """Amprion-Abgabeformat als CSV – exakt wie die Vorlage:
    Datum;nicht relevant;Task Nr.;nicht relevant;Personen Name;Stunden;Tätigkeitbeschreibung
    Semikolon-getrennt, UTF-8 mit BOM, CRLF, Stunden mit Dezimalkomma.
    Es werden ALLE übergebenen Buchungen exportiert (die Auswahl steuert der
    Filter in der Oberfläche). Die Task-Nr. kommt aus dem Amprion-Mapping;
    passt kein Mapping, wird die Projektnummer verwendet."""
    rows = []
    for iv in intervals:
        nr = _amprion_task(iv.project) or _leading_number(iv.project)
        st = iv.start.astimezone(config.TIMEZONE)
        rows.append((st, nr, _amprion_name(iv.employee),
                     _hours1(iv.duration_hours), iv.description or ""))
    rows.sort(key=lambda r: (r[0], r[2].lower()))

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n",
                   quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Datum", "nicht relevant", "Task Nr.", "nicht relevant",
                "Personen Name", "Stunden", "Tätigkeitbeschreibung"])
    for dt, nr, name, h, desc in rows:
        w.writerow([dt.strftime("%d.%m.%Y"), "",
                    int(nr) if str(nr).isdigit() else nr, "", name, h, desc])
    return buf.getvalue().encode("utf-8-sig")


def arcadis_csv(intervals: list[Interval]) -> bytes:
    rows = []
    for iv in intervals:
        nach, vor = _split_name(iv.employee)
        rows.append((iv.start.astimezone(config.TIMEZONE), nach, vor,
                     _hours(iv.duration_hours), iv.description or ""))
    rows.sort(key=lambda r: (r[0], r[1].lower(), r[2].lower()))

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n",
                   quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Datum", "Nachname", "Vorname", "Stunden",
                "Taetigkeitsbeschreibung"])
    for dt, nach, vor, h, desc in rows:
        w.writerow([dt.strftime("%d.%m.%Y"), nach, vor, h, desc])
    return buf.getvalue().encode("utf-8-sig")
