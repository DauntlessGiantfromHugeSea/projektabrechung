"""
Events einlesen, normalisieren und zu Arbeitsintervallen paaren.

Hintergrund: Wir wissen (noch) nicht sicher, wie TimeMoto die Webhook-Payload
aufbaut und ob ueberhaupt ein Projektbezug mitkommt. Darum ist dieses Modul
bewusst tolerant: Es durchsucht die JSON-Payload rekursiv nach den
*ueblichen* Feldnamen fuer Zeitpunkt, Mitarbeiter, Projekt und Richtung
(ein-/ausstempeln) und kommt auch mit fehlenden Feldern klar.

Sobald aus echten Events klar ist, wie die Felder wirklich heissen, kann man
die Kandidatenlisten unten praezisieren oder per PROJECT_FIELD ueberschreiben.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import config

# Feldnamen-Kandidaten (alles lowercase verglichen). Reihenfolge = Prioritaet.
_TIME_KEYS = [
    "timestamp", "datetime", "date_time", "punchtime", "punch_time",
    "eventtime", "event_time", "occurredat", "occurred_at", "time", "date",
    "clocktime", "clock_time", "createdat", "created_at",
]
_EMPLOYEE_KEYS = [
    "employeename", "employee_name", "username", "user_name", "fullname",
    "full_name", "employee", "user", "name", "employeeid", "employee_id",
    "userid", "user_id", "personid", "person_id", "badge",
]
_PROJECT_KEYS = [
    "projectcode", "project_code", "projectname", "project_name", "project",
    "workcode", "work_code", "costcenter", "cost_center", "job", "jobcode",
    "task", "activity", "projectid", "project_id",
]
_DIRECTION_KEYS = [
    "direction", "inout", "in_out", "punchtype", "punch_type", "action",
    "type", "event", "eventtype", "event_type", "status", "state", "kind",
]

# Wertemuster, die "kommt rein" bzw. "geht raus" bedeuten.
_IN_VALUES = {"in", "clockin", "clock_in", "checkin", "check_in", "start",
              "started", "begin", "punchin", "punch_in", "1", "i", "enter"}
_OUT_VALUES = {"out", "clockout", "clock_out", "checkout", "check_out", "stop",
               "stopped", "end", "ended", "punchout", "punch_out", "0", "o",
               "leave", "exit"}


@dataclass
class Punch:
    """Eine normalisierte Stempelung."""
    time: datetime
    employee: str
    project: str | None
    direction: str | None  # "in" | "out" | None
    raw: dict[str, Any]


@dataclass
class Interval:
    """Ein gepaartes Arbeitsintervall (von Einstempeln bis Ausstempeln)."""
    employee: str
    project: str | None
    start: datetime
    end: datetime

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


# --- Hilfsfunktionen: rekursive Feldsuche ----------------------------------

def _iter_pairs(obj: Any) -> Iterable[tuple[str, Any]]:
    """Alle (key, value)-Paare rekursiv durch dicts/listen hindurch."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _iter_pairs(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_pairs(item)


def _find_first(obj: Any, candidate_keys: list[str]) -> Any:
    """Ersten Wert finden, dessen Key (case-insensitive) in candidate_keys ist."""
    # Erst exakte Treffer in Prioritaetsreihenfolge, ueber alle Ebenen.
    pairs = list(_iter_pairs(obj))
    lowered = {k.lower(): v for k, v in pairs}
    for key in candidate_keys:
        if key in lowered and lowered[key] not in (None, "", []):
            return lowered[key]
    return None


def _parse_time(value: Any) -> datetime | None:
    """Verschiedene Zeitformate tolerant nach UTC-aware datetime parsen."""
    if value is None:
        return None
    # Epoch (Sekunden oder Millisekunden)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # sieht nach Millisekunden aus
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # ISO 8601 (inkl. "Z")
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                    "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _parse_direction(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower().replace(" ", "")
    if s in _IN_VALUES:
        return "in"
    if s in _OUT_VALUES:
        return "out"
    # Teilstring-Heuristik als letzter Versuch
    if "in" in s and "out" not in s:
        return "in"
    if "out" in s:
        return "out"
    return None


# --- Oeffentliche API ------------------------------------------------------

def load_records(log_file: Path | None = None) -> list[dict[str, Any]]:
    """Roh-Events (eine JSON-Zeile pro Event) aus der JSONL-Datei laden."""
    path = log_file or config.LOG_FILE
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def normalize(record: dict[str, Any]) -> Punch | None:
    """Ein gespeichertes Webhook-Record in einen Punch ueberfuehren.

    Liefert None, wenn kein verwertbarer Zeitpunkt gefunden wurde.
    """
    body = record.get("body_json")
    if not isinstance(body, (dict, list)):
        return None

    when = _parse_time(_find_first(body, _TIME_KEYS))
    if when is None:
        # Fallback: Empfangszeit des Webhooks
        when = _parse_time(record.get("received_at"))
    if when is None:
        return None

    employee = _find_first(body, _EMPLOYEE_KEYS)
    employee = str(employee) if employee is not None else "unbekannt"

    project_keys = [config.PROJECT_FIELD.lower()] if config.PROJECT_FIELD else _PROJECT_KEYS
    project = _find_first(body, project_keys)
    project = str(project) if project not in (None, "") else None

    direction = _parse_direction(_find_first(body, _DIRECTION_KEYS))

    return Punch(time=when, employee=employee, project=project,
                 direction=direction, raw=body if isinstance(body, dict) else {"_": body})


def pair_intervals(punches: list[Punch]) -> list[Interval]:
    """Stempelungen pro Mitarbeiter zeitlich paaren (in -> out).

    Strategie:
    - Pro Mitarbeiter chronologisch sortieren.
    - Wenn Richtungen bekannt sind: 'in' oeffnet, naechstes 'out' schliesst.
    - Wenn Richtungen unbekannt sind: paarweise (1./2., 3./4., ...) paaren.
    Das Projekt des Intervalls stammt aus der Einstempel-Stempelung (oder,
    falls dort leer, aus der Ausstempel-Stempelung).
    """
    by_employee: dict[str, list[Punch]] = {}
    for p in punches:
        by_employee.setdefault(p.employee, []).append(p)

    intervals: list[Interval] = []
    for employee, plist in by_employee.items():
        plist.sort(key=lambda x: x.time)
        have_directions = any(p.direction for p in plist)

        if have_directions:
            open_in: Punch | None = None
            for p in plist:
                if p.direction == "in":
                    open_in = p
                elif p.direction == "out" and open_in is not None:
                    intervals.append(Interval(
                        employee=employee,
                        project=open_in.project or p.project,
                        start=open_in.time, end=p.time))
                    open_in = None
        else:
            # Ohne Richtungsinfo: schlicht paarweise.
            for i in range(0, len(plist) - 1, 2):
                a, b = plist[i], plist[i + 1]
                intervals.append(Interval(
                    employee=employee,
                    project=a.project or b.project,
                    start=a.time, end=b.time))

    return intervals
