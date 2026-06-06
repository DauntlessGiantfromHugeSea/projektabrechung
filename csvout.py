"""
CSV im Arcadis-Stundennachweis-Format:
    Datum;Nachname;Vorname;Stunden;Taetigkeitsbeschreibung
- Semikolon-getrennt (deutsches Excel), Stunden mit Dezimalkomma, KEIN Preis.
- UTF-8 mit BOM, damit Excel Umlaute korrekt anzeigt.
"""

from __future__ import annotations

import csv
import io

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
