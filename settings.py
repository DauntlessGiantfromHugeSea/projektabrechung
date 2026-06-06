"""
Online konfigurierbare Bericht-Definitionen (statt fester Env-Vars).

Jede Definition legt fest:
- welche Projekte (Liste von Filter-Strings; Teilstring genuegt),
- an wen (Empfaenger-Liste),
- wann (Wochentag + Uhrzeit),
- aktiv ja/nein.

Es wird NUR versendet, was hier definiert ist -- ohne Definition geht keine
automatische Mail raus (kein "alle Projekte" mehr).
Gespeichert als JSON-Datei (SETTINGS_FILE), analog zur Benutzerverwaltung.
"""

from __future__ import annotations

import json
import secrets
import threading
from typing import Any
from zoneinfo import ZoneInfo

import config

_LOCK = threading.Lock()

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _load() -> dict[str, Any]:
    path = config.SETTINGS_FILE
    if not path.exists():
        return {"reports": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("reports", [])
        return data
    except Exception:
        return {"reports": []}


def _save(data: dict[str, Any]) -> None:
    path = config.SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def _clean_list(raw: Any) -> list[str]:
    """Aus Komma-/Zeilen-getrenntem Text oder Liste eine saubere Liste machen."""
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw or "").replace("\n", ",").split(",")
    return [s.strip() for s in items if s and s.strip()]


def _normalize(cfg: dict[str, Any]) -> dict[str, Any]:
    dow = str(cfg.get("day_of_week", "mon")).lower()
    if dow not in _DAYS:
        dow = "mon"
    try:
        hour = max(0, min(23, int(cfg.get("hour", 7))))
    except (TypeError, ValueError):
        hour = 7
    try:
        minute = max(0, min(59, int(cfg.get("minute", 0))))
    except (TypeError, ValueError):
        minute = 0
    fmt = "csv" if str(cfg.get("format", "excel")).lower() == "csv" else "excel"
    return {
        "id": cfg.get("id") or secrets.token_hex(8),
        "name": (cfg.get("name") or "Bericht").strip(),
        "message": (cfg.get("message") or "").strip(),
        "projects": _clean_list(cfg.get("projects")),
        "recipients": _clean_list(cfg.get("recipients")),
        "cc": _clean_list(cfg.get("cc")),
        "format": fmt,
        "day_of_week": dow,
        "hour": hour,
        "minute": minute,
        "enabled": bool(cfg.get("enabled", True)),
    }


# --- Globale Zeitzone ------------------------------------------------------

def get_timezone() -> str:
    data = _load()
    return data.get("timezone") or str(config.TIMEZONE)


def set_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except Exception:
        return False
    with _LOCK:
        data = _load()
        data["timezone"] = name
        _save(data)
    apply_timezone()
    return True


def apply_timezone() -> None:
    """Gewaehlte Zeitzone in config.TIMEZONE uebernehmen (alle Module lesen
    config.TIMEZONE zur Laufzeit)."""
    try:
        config.TIMEZONE = ZoneInfo(get_timezone())
    except Exception:
        pass


def list_reports() -> list[dict[str, Any]]:
    return [_normalize(r) for r in _load().get("reports", [])]


def get_report(report_id: str) -> dict[str, Any] | None:
    for r in list_reports():
        if r["id"] == report_id:
            return r
    return None


def add_report(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = _normalize(cfg)
    with _LOCK:
        data = _load()
        data["reports"].append(cfg)
        _save(data)
    return cfg


def update_report(report_id: str, cfg: dict[str, Any]) -> bool:
    with _LOCK:
        data = _load()
        for i, r in enumerate(data["reports"]):
            if _normalize(r)["id"] == report_id:
                merged = {**cfg, "id": report_id}
                data["reports"][i] = _normalize(merged)
                _save(data)
                return True
    return False


def delete_report(report_id: str) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["reports"])
        data["reports"] = [r for r in data["reports"]
                           if _normalize(r)["id"] != report_id]
        if len(data["reports"]) != before:
            _save(data)
            return True
    return False


def day_label(dow: str) -> str:
    return {"mon": "Montag", "tue": "Dienstag", "wed": "Mittwoch",
            "thu": "Donnerstag", "fri": "Freitag", "sat": "Samstag",
            "sun": "Sonntag"}.get(dow, dow)
