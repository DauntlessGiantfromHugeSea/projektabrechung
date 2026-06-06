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
from zoneinfo import ZoneInfo

import config

# Feldnamen-Kandidaten (alles lowercase verglichen). Reihenfolge = Prioritaet.
# Die ersten Eintraege sind die von TimeMoto v2 Cloud tatsaechlich genutzten.
_TIME_KEYS = [
    # TimeMoto: timeInserted ist sauberes UTC ("...Z"), timeLogged lokal.
    "timeinserted", "timelogged", "timeloggedrounded",
    "timestamp", "datetime", "date_time", "punchtime", "punch_time",
    "eventtime", "event_time", "occurredat", "occurred_at",
    "time", "date", "clocktime", "clock_time", "createdat", "created_at",
    "dispatchedat",
]
_EMPLOYEE_KEYS = [
    # TimeMoto: userFullName ("Vorname Nachname").
    "userfullname", "employeename", "employee_name", "fullname", "full_name",
    "username", "user_name", "userfirstname", "useremployeenumber",
    "employee", "user", "name", "employeeid", "employee_id",
    "userid", "user_id", "personid", "person_id", "badge",
]
_PROJECT_KEYS = [
    # TimeMoto: projectName ("26344 - ..."), projectCode ("5543"), projectId.
    "projectname", "project_name", "projectcode", "project_code", "project",
    "workcode", "work_code", "costcenter", "cost_center", "job", "jobcode",
    "task", "activity", "projectid", "project_id",
]
_DIRECTION_KEYS = [
    # TimeMoto: clockingType ("In"/"Out").
    "clockingtype", "direction", "inout", "in_out", "punchtype", "punch_type",
    "action", "type", "event", "eventtype", "event_type", "status", "state",
    "kind",
]
# Schluessel, der Ein-/Ausstempeln eines Vorgangs verbindet (TimeMoto liefert
# das selbst -> exakte Paarung statt Heuristik).
_PAIR_KEYS = ["clockingpairid", "pairid", "pair_id", "sessionid", "session_id"]
# Zeitzonen-Feld (fuer Zeitstempel ohne explizite Zone).
_TZ_KEYS = ["timezone", "time_zone", "tz"]

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
    pair_id: str | None    # verbindet Ein-/Ausstempeln eines Vorgangs
    raw: dict[str, Any]


@dataclass
class Interval:
    """Ein gepaartes Arbeitsintervall (von Einstempeln bis Ausstempeln)."""
    employee: str
    project: str | None
    start: datetime
    end: datetime
    id: str = ""             # stabile Kennung (fuer Ausblenden/Korrigieren)
    source: str = "webhook"  # "webhook" | "manual"
    description: str = ""     # Taetigkeitsbeschreibung (Arcadis-Pflicht)

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


@dataclass
class OpenPunch:
    """Eine offene Stempelung (eingestempelt, noch nicht ausgestempelt)."""
    employee: str
    project: str | None
    start: datetime


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


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(str(name))
    except Exception:
        return None


def _parse_time(value: Any, tz_name: str | None = None) -> datetime | None:
    """Verschiedene Zeitformate tolerant nach aware datetime parsen.

    Zeitstempel ohne explizite Zone werden in tz_name interpretiert (falls
    angegeben), sonst als UTC.
    """
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
        dt: datetime | None = None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
                        "%d.%m.%Y %H:%M", "%Y/%m/%d %H:%M:%S",
                        "%m/%d/%Y %H:%M:%S"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_zone(tz_name) or timezone.utc)
        return dt
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


def delete_interval(interval_id: str, log_file: Path | None = None) -> int:
    """Loescht ENDGUELTIG alle Webhook-Events, die zur angegebenen Interval-ID
    gehoeren, aus der JSONL-Datei (fuer Testdaten/Fehlbuchungen). Liefert die
    Anzahl entfernter Zeilen. Manuelle Eintraege sind hier nicht betroffen."""
    path = log_file or config.LOG_FILE
    if not path.exists():
        return 0
    kept: list[str] = []
    removed = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except json.JSONDecodeError:
                kept.append(s)
                continue
            p = normalize(rec)
            match = False
            if p is not None:
                if p.pair_id and f"wh:{p.employee}:{p.pair_id}" == interval_id:
                    match = True
                elif (not p.pair_id
                      and f"wh:{p.employee}:{p.time.isoformat()}" == interval_id):
                    match = True
            if match:
                removed += 1
            else:
                kept.append(s)
    if removed:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        tmp.replace(path)
    return removed


def normalize(record: dict[str, Any]) -> Punch | None:
    """Ein gespeichertes Webhook-Record in einen Punch ueberfuehren.

    Liefert None, wenn kein verwertbarer Zeitpunkt gefunden wurde.
    """
    body = record.get("body_json")
    if not isinstance(body, (dict, list)):
        return None

    tz_name = _find_first(body, _TZ_KEYS)
    when = _parse_time(_find_first(body, _TIME_KEYS), tz_name)
    if when is None:
        # Fallback: Empfangszeit des Webhooks
        when = _parse_time(record.get("received_at"))
    if when is None:
        return None

    employee = _find_first(body, _EMPLOYEE_KEYS)
    employee = str(employee).strip() if employee is not None else "unbekannt"

    project_keys = [config.PROJECT_FIELD.lower()] if config.PROJECT_FIELD else _PROJECT_KEYS
    project = _find_first(body, project_keys)
    project = str(project).strip() if project not in (None, "") else None

    direction = _parse_direction(_find_first(body, _DIRECTION_KEYS))

    pair_id = _find_first(body, _PAIR_KEYS)
    pair_id = str(pair_id) if pair_id not in (None, "") else None

    return Punch(time=when, employee=employee, project=project,
                 direction=direction, pair_id=pair_id,
                 raw=body if isinstance(body, dict) else {"_": body})


def pair_intervals(punches: list[Punch]) -> list[Interval]:
    """Stempelungen zu Arbeitsintervallen paaren.

    Bevorzugt wird der von TimeMoto gelieferte ``clockingPairId``: alle
    Stempelungen mit derselben pair_id gehoeren zu einem Vorgang -> Start =
    fruehestes Ein-/erstes Event, Ende = spaetestes Aus-/letztes Event. Das
    ist robust gegen doppelt zugestellte Events.

    Gibt es keine pair_id, faellt es auf die Heuristik zurueck: pro
    Mitarbeiter chronologisch, 'in' oeffnet und 'out' schliesst (bzw. ohne
    Richtungsinfo paarweise).
    """
    paired = [p for p in punches if p.pair_id]
    unpaired = [p for p in punches if not p.pair_id]
    intervals: list[Interval] = []

    # 1) Exakte Paarung ueber pair_id
    groups: dict[tuple[str, str], list[Punch]] = {}
    for p in paired:
        groups.setdefault((p.employee, p.pair_id), []).append(p)  # type: ignore[arg-type]
    for (employee, pid), plist in groups.items():
        plist.sort(key=lambda x: x.time)
        ins = [p for p in plist if p.direction == "in"]
        outs = [p for p in plist if p.direction == "out"]
        if ins and outs:
            start, end = min(p.time for p in ins), max(p.time for p in outs)
        elif len(plist) >= 2:
            start, end = plist[0].time, plist[-1].time
        else:
            continue  # offener Vorgang (nur Ein- oder nur Ausstempeln)
        project = next((p.project for p in plist if p.project), None)
        intervals.append(Interval(employee, project, start, end,
                                  id=f"wh:{employee}:{pid}"))

    # 2) Heuristik fuer Events ohne pair_id
    by_employee: dict[str, list[Punch]] = {}
    for p in unpaired:
        by_employee.setdefault(p.employee, []).append(p)
    for employee, plist in by_employee.items():
        plist.sort(key=lambda x: x.time)
        if any(p.direction for p in plist):
            open_in: Punch | None = None
            for p in plist:
                if p.direction == "in":
                    open_in = p
                elif p.direction == "out" and open_in is not None:
                    intervals.append(Interval(
                        employee, open_in.project or p.project,
                        open_in.time, p.time,
                        id=f"wh:{employee}:{open_in.time.isoformat()}"))
                    open_in = None
        else:
            for i in range(0, len(plist) - 1, 2):
                a, b = plist[i], plist[i + 1]
                intervals.append(Interval(
                    employee, a.project or b.project, a.time, b.time,
                    id=f"wh:{employee}:{a.time.isoformat()}"))

    return intervals


def open_punches(punches: list[Punch]) -> list[OpenPunch]:
    """Offene Stempelungen finden: eingestempelt, aber (noch) kein Ausstempeln.

    Erkennt pro clockingPairId Gruppen mit 'in' aber ohne 'out', sowie ein
    abschliessendes unverbundenes 'in' in der Heuristik-Kette."""
    opens: list[OpenPunch] = []
    paired = [p for p in punches if p.pair_id]
    unpaired = [p for p in punches if not p.pair_id]

    groups: dict[tuple[str, str], list[Punch]] = {}
    for p in paired:
        groups.setdefault((p.employee, p.pair_id), []).append(p)  # type: ignore[arg-type]
    for (employee, _pid), plist in groups.items():
        ins = [p for p in plist if p.direction == "in"]
        outs = [p for p in plist if p.direction == "out"]
        if ins and not outs:
            first = min(ins, key=lambda p: p.time)
            opens.append(OpenPunch(employee, first.project, first.time))

    by_emp: dict[str, list[Punch]] = {}
    for p in unpaired:
        by_emp.setdefault(p.employee, []).append(p)
    for employee, plist in by_emp.items():
        plist.sort(key=lambda x: x.time)
        if any(p.direction for p in plist):
            depth = 0
            last_in: Punch | None = None
            for p in plist:
                if p.direction == "in":
                    depth += 1
                    last_in = p
                elif p.direction == "out" and depth > 0:
                    depth -= 1
            if depth > 0 and last_in is not None:
                opens.append(OpenPunch(employee, last_in.project, last_in.time))

    return opens
