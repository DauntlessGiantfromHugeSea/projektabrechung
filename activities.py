"""
Taetigkeitsbeschreibungen je Buchung.

Wird getrennt von den Webhook-Rohdaten gehalten und ueber die stabile
Interval-ID zugeordnet (gilt fuer Webhook- wie manuelle Buchungen).
Amprion/Arcadis verlangen 1-2 vollstaendige Saetze je Eintrag.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

import config

_LOCK = threading.Lock()


def _load() -> dict[str, Any]:
    if not config.ACTIVITIES_FILE.exists():
        return {}
    try:
        return json.loads(config.ACTIVITIES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    config.ACTIVITIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.ACTIVITIES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.ACTIVITIES_FILE)


def get(interval_id: str) -> str:
    e = _load().get(interval_id)
    return (e or {}).get("description", "") if isinstance(e, dict) else ""


def mapping() -> dict[str, str]:
    return {k: (v.get("description", "") if isinstance(v, dict) else "")
            for k, v in _load().items()}


def set_description(interval_id: str, description: str, by: str) -> None:
    with _LOCK:
        data = _load()
        if description.strip():
            data[interval_id] = {
                "description": description.strip(), "by": by,
                "at": datetime.now(timezone.utc).isoformat()}
        else:
            data.pop(interval_id, None)
        _save(data)


def reminded(interval_id: str) -> bool:
    e = _load().get(interval_id)
    return bool(isinstance(e, dict) and e.get("reminded"))


def mark_reminded(interval_id: str) -> None:
    with _LOCK:
        data = _load()
        e = data.get(interval_id)
        if not isinstance(e, dict):
            e = {}
        e["reminded"] = datetime.now(timezone.utc).isoformat()
        data[interval_id] = e
        _save(data)
