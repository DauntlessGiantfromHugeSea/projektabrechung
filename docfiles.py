"""
Dokument-Bereiche (z. B. ISO 9001, KI-Schulungen): Dateien hochladen,
online ansehen (PDF/Bild/Video/Text im Browser) und herunterladen.

Speicherung analog zu Tickets: JSON-Index (DOCFILES_FILE) + Dateien
unter DOC_FILES_DIR/<bereich>/.
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

_LOCK = threading.Lock()


def _load() -> dict[str, Any]:
    path = config.DOCFILES_FILE
    if not path.exists():
        return {"docs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("docs", [])
        return data
    except Exception:
        return {"docs": []}


def _save(data: dict[str, Any]) -> None:
    path = config.DOCFILES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(filename: str) -> str:
    name = re.sub(r"[^\w.\- äöüÄÖÜß]", "_", filename or "datei").strip()
    return name[:120] or "datei"


def list_docs(area: str, category: str = "") -> list[dict[str, Any]]:
    """Dokumente eines Bereichs, optional nach Kategorie gefiltert.
    Sortierung: Kategorie, dann Titel."""
    docs = [d for d in _load()["docs"] if d.get("area") == area]
    if category:
        docs = [d for d in docs if (d.get("category") or "") == category]
    docs.sort(key=lambda d: ((d.get("category") or "").lower(),
                             (d.get("title") or "").lower()))
    return docs


def categories(area: str) -> list[str]:
    return sorted({d.get("category") or "" for d in _load()["docs"]
                   if d.get("area") == area and (d.get("category") or "")},
                  key=str.lower)


def get(doc_id: str) -> dict[str, Any] | None:
    for d in _load()["docs"]:
        if d.get("id") == doc_id:
            return d
    return None


def add(area: str, title: str, category: str, filename: str,
        stored: str, size: int, by: str) -> dict[str, Any]:
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    doc = {"id": secrets.token_hex(8), "area": area,
           "title": (title or filename).strip(), "category": category.strip(),
           "filename": filename, "stored": stored, "mime": mime,
           "size": int(size), "by": by, "at": _now()}
    with _LOCK:
        data = _load()
        data["docs"].append(doc)
        _save(data)
    return doc


def delete(doc_id: str) -> dict[str, Any] | None:
    """Eintrag + Datei loeschen. Liefert den entfernten Eintrag."""
    removed: dict[str, Any] = {}
    with _LOCK:
        data = _load()
        for d in data["docs"]:
            if d.get("id") == doc_id:
                removed = d
        data["docs"] = [d for d in data["docs"] if d.get("id") != doc_id]
        if removed:
            _save(data)
    if removed:
        try:
            Path(removed["stored"]).unlink(missing_ok=True)
        except Exception:
            pass
    return removed or None


def viewer_kind(mime: str) -> str:
    """Wie kann die Datei im Browser angezeigt werden?
    pdf | image | video | audio | text | none"""
    m = (mime or "").lower()
    if m == "application/pdf":
        return "pdf"
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    if m.startswith("text/"):
        return "text"
    return "none"
