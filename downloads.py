"""
Tokenisierte Datei-Downloads fuer Mail-Links.

Statt Anhaengen (Brevo kann/soll keine Anhaenge senden) wird eine Datei lokal
abgelegt und ueber einen nicht erratbaren Token-Link bereitgestellt:
  /download/<token>
Der Link liefert AUSSCHLIESSLICH diese eine registrierte Datei. Alle anderen
Seiten erfordern Login -- vom Link aus kommt man also nirgendwo anders hin.
Tokens laufen nach DOWNLOAD_TTL_DAYS ab.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

import config

_LOCK = threading.Lock()


def _load() -> dict[str, Any]:
    if not config.DOWNLOADS_FILE.exists():
        return {}
    try:
        return json.loads(config.DOWNLOADS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    config.DOWNLOADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.DOWNLOADS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.DOWNLOADS_FILE)


def register(content: bytes, filename: str,
             media_type: str = "application/octet-stream") -> str:
    """Datei ablegen und Token zurueckgeben."""
    token = secrets.token_urlsafe(24)
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = config.DOWNLOAD_DIR / token
    stored.write_bytes(content)
    with _LOCK:
        data = _load()
        data[token] = {
            "path": str(stored), "filename": filename,
            "media_type": media_type,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        _save(data)
    return token


def resolve(token: str) -> dict[str, Any] | None:
    """Eintrag zu einem Token liefern (oder None, wenn unbekannt/abgelaufen)."""
    entry = _load().get(token)
    if not entry:
        return None
    try:
        created = datetime.fromisoformat(entry["created"])
        age_days = (datetime.now(timezone.utc) - created).days
        if age_days > config.DOWNLOAD_TTL_DAYS:
            return None
    except Exception:
        pass
    return entry


def link(base_url: str, token: str) -> str:
    return f"{(base_url or config.PUBLIC_BASE_URL).rstrip('/')}/download/{token}"
