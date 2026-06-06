"""
Aenderungsprotokoll (Audit-Log).

Haelt fest, wer wann welche manuelle Aenderung vorgenommen hat
(Eintrag hinzugefuegt/bearbeitet/geloescht, Buchung ausgeblendet/wieder
eingeblendet). Wird im Admin-Bereich angezeigt.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

import config

_LOCK = threading.Lock()
_MAX = 1000  # aeltere Eintraege werden gekappt


def _load() -> list[dict[str, Any]]:
    path = config.AUDIT_FILE
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list[dict[str, Any]]) -> None:
    path = config.AUDIT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def log(user: str, action: str, detail: str) -> None:
    with _LOCK:
        entries = _load()
        entries.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user or "?", "action": action, "detail": detail,
        })
        if len(entries) > _MAX:
            entries = entries[-_MAX:]
        _save(entries)


def list_entries(limit: int = 300) -> list[dict[str, Any]]:
    """Neueste zuerst."""
    return list(reversed(_load()))[:limit]
