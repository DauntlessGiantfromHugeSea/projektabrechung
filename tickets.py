"""
Ticketsystem (dateibasiert, analog zur restlichen App).

Ein Ticket hat Titel, Beschreibung, Priorität, Kategorie, Status, Ersteller,
optional Bearbeiter (assigned_to), Kommentare und Aufwandseinträge (WorkLog:
Datum, Anfahrt km, Stunden, Material, Tätigkeit). Datei-Anhänge folgen separat.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

import config

_LOCK = threading.Lock()

PRIORITIES = {"low": "Niedrig", "medium": "Mittel", "high": "Hoch",
              "critical": "Kritisch"}
CATEGORIES = {"hardware": "Hardware", "software": "Software",
              "network": "Netzwerk", "account": "Account / Zugang",
              "other": "Sonstiges"}
STATUSES = {"open": "Offen", "in_progress": "In Arbeit",
            "resolved": "Gelöst", "closed": "Geschlossen"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if not config.TICKETS_FILE.exists():
        return {"next_id": 1, "tickets": []}
    try:
        data = json.loads(config.TICKETS_FILE.read_text(encoding="utf-8"))
        data.setdefault("next_id", 1)
        data.setdefault("tickets", [])
        return data
    except Exception:
        return {"next_id": 1, "tickets": []}


def _save(data: dict[str, Any]) -> None:
    config.TICKETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.TICKETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.TICKETS_FILE)


def list_tickets(status: str = "", q: str = "", mine: str = "") -> list[dict]:
    out = _load()["tickets"]
    if status:
        out = [t for t in out if t.get("status") == status]
    if mine:
        out = [t for t in out
               if t.get("created_by") == mine or t.get("assigned_to") == mine]
    if q:
        ql = q.lower()
        out = [t for t in out if ql in (t.get("title", "") + " "
               + t.get("description", "")).lower()]
    return sorted(out, key=lambda t: t.get("created_at", ""), reverse=True)


def get(ticket_id: int) -> dict | None:
    for t in _load()["tickets"]:
        if t.get("id") == ticket_id:
            return t
    return None


def create(title: str, description: str, priority: str, category: str,
           created_by: str) -> dict:
    with _LOCK:
        data = _load()
        tid = data["next_id"]
        data["next_id"] = tid + 1
        ticket = {
            "id": tid, "title": title.strip() or f"Ticket {tid}",
            "description": description.strip(),
            "priority": priority if priority in PRIORITIES else "medium",
            "category": category if category in CATEGORIES else "other",
            "status": "open", "created_by": created_by, "assigned_to": None,
            "created_at": _now(), "updated_at": _now(),
            "comments": [], "worklogs": [], "attachments": [],
        }
        data["tickets"].append(ticket)
        _save(data)
    return ticket


def _update(ticket_id: int, fn) -> bool:
    with _LOCK:
        data = _load()
        for t in data["tickets"]:
            if t.get("id") == ticket_id:
                fn(t)
                t["updated_at"] = _now()
                _save(data)
                return True
    return False


def update_fields(ticket_id: int, status=None, priority=None, category=None,
                  assigned_to=None) -> bool:
    def fn(t):
        if status in STATUSES:
            t["status"] = status
        if priority in PRIORITIES:
            t["priority"] = priority
        if category in CATEGORIES:
            t["category"] = category
        if assigned_to is not None:
            t["assigned_to"] = assigned_to or None
    return _update(ticket_id, fn)


def add_comment(ticket_id: int, author: str, body: str) -> bool:
    if not body.strip():
        return False
    return _update(ticket_id, lambda t: t["comments"].append(
        {"id": secrets.token_hex(6), "author": author,
         "body": body.strip(), "at": _now()}))


def add_worklog(ticket_id: int, performed_by: str, date: str, travel_km: float,
                hours: float, material: str, description: str) -> bool:
    return _update(ticket_id, lambda t: t["worklogs"].append(
        {"id": secrets.token_hex(6), "performed_by": performed_by,
         "date": date, "travel_km": travel_km, "hours": hours,
         "material": material.strip(), "description": description.strip(),
         "at": _now()}))


def delete_worklog(ticket_id: int, wid: str) -> bool:
    return _update(ticket_id, lambda t: t.__setitem__(
        "worklogs", [w for w in t["worklogs"] if w.get("id") != wid]))


def add_attachment(ticket_id: int, filename: str, stored: str, by: str) -> bool:
    return _update(ticket_id, lambda t: t["attachments"].append(
        {"id": secrets.token_hex(6), "filename": filename, "stored": stored,
         "by": by, "at": _now()}))


def find_attachment(ticket_id: int, att_id: str) -> dict | None:
    t = get(ticket_id)
    if not t:
        return None
    for a in t.get("attachments", []):
        if a.get("id") == att_id:
            return a
    return None


def counts_by_status() -> dict[str, int]:
    c = {k: 0 for k in STATUSES}
    for t in _load()["tickets"]:
        c[t.get("status", "open")] = c.get(t.get("status", "open"), 0) + 1
    return c
