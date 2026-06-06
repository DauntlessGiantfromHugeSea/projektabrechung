"""
Manuelle Eintraege und Korrekturen.

- Manuelle Buchungen (vom Admin hinzugefuegt) ergaenzen die Webhook-Daten.
- "Ausgeblendete" Webhook-Buchungen werden per stabiler Interval-ID
  ausgeschlossen (z. B. um eine Fehlbuchung zu korrigieren: Original
  ausblenden + korrigierte manuelle Buchung anlegen).

Die Webhook-Rohdaten (events.jsonl) bleiben unveraendert -- Korrekturen sind
eine getrennte Schicht obendrueber.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

import config
from events import Interval

_LOCK = threading.Lock()


def _load() -> dict[str, Any]:
    path = config.MANUAL_FILE
    if not path.exists():
        return {"entries": [], "hidden": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("entries", [])
        data.setdefault("hidden", [])
        return data
    except Exception:
        return {"entries": [], "hidden": []}


def _save(data: dict[str, Any]) -> None:
    path = config.MANUAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Manuelle Eintraege ----------------------------------------------------

def list_entries() -> list[dict[str, Any]]:
    return _load()["entries"]


def get_entry(entry_id: str) -> dict[str, Any] | None:
    for e in _load()["entries"]:
        if e["id"] == entry_id:
            return e
    return None


def add_entry(data: dict[str, Any], user: str) -> dict[str, Any]:
    entry = {
        "id": secrets.token_hex(8),
        "employee": (data.get("employee") or "").strip(),
        "project": (data.get("project") or "").strip(),
        "start": data["start"],           # ISO 8601 mit Zeitzone
        "end": data["end"],
        "note": (data.get("note") or "").strip(),
        "replaces": data.get("replaces") or None,
        "created_by": user, "created_at": _now(), "updated_at": _now(),
    }
    with _LOCK:
        d = _load()
        d["entries"].append(entry)
        _save(d)
    return entry


def update_entry(entry_id: str, data: dict[str, Any]) -> bool:
    with _LOCK:
        d = _load()
        for e in d["entries"]:
            if e["id"] == entry_id:
                e.update({
                    "employee": (data.get("employee") or "").strip(),
                    "project": (data.get("project") or "").strip(),
                    "start": data["start"], "end": data["end"],
                    "note": (data.get("note") or "").strip(),
                    "updated_at": _now(),
                })
                _save(d)
                return True
    return False


def delete_entry(entry_id: str) -> bool:
    with _LOCK:
        d = _load()
        before = len(d["entries"])
        d["entries"] = [e for e in d["entries"] if e["id"] != entry_id]
        if len(d["entries"]) != before:
            _save(d)
            return True
    return False


# --- Ausgeblendete Webhook-Buchungen ---------------------------------------

def hide(interval_id: str) -> None:
    with _LOCK:
        d = _load()
        if interval_id not in d["hidden"]:
            d["hidden"].append(interval_id)
            _save(d)


def unhide(interval_id: str) -> None:
    with _LOCK:
        d = _load()
        if interval_id in d["hidden"]:
            d["hidden"].remove(interval_id)
            _save(d)


def hidden_ids() -> set[str]:
    return set(_load()["hidden"])


# --- Umwandlung in Intervalle ----------------------------------------------

def to_intervals() -> list[Interval]:
    out: list[Interval] = []
    for e in _load()["entries"]:
        try:
            start = datetime.fromisoformat(e["start"])
            end = datetime.fromisoformat(e["end"])
        except (ValueError, KeyError):
            continue
        out.append(Interval(employee=e["employee"], project=e["project"] or None,
                            start=start, end=end, id=f"man:{e['id']}",
                            source="manual"))
    return out
