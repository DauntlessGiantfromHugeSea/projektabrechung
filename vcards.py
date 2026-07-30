"""
Digitale Visitenkarten: pro Person eine oeffentliche Karte unter /v/<slug>.

SICHERHEITSMODELL:
- Die oeffentliche Seite zeigt AUSSCHLIESSLICH die hier explizit vom Admin
  eingetragenen Felder (Name, Titel, Kontaktlinks, Foto) -- niemals Daten
  aus der Benutzerverwaltung, Zeiterfassung o. ae.
- Kein Login, keine Session, keine Links in den internen Bereich.
- Nur Karten mit enabled=True werden ausgeliefert; alles andere -> 404.
- Slugs sind streng validiert ([a-z0-9-]); Fotos liegen in einem eigenen
  Verzeichnis (VCARD_FILES_DIR) getrennt von allen anderen Daten.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

_LOCK = threading.Lock()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")

# Felder, die der Admin pflegen kann (Key, Label, Platzhalter)
FIELDS = [
    ("name", "Name", "z. B. Dustyn Model"),
    ("title", "Untertitel / Position", "z. B. Projektmanagement"),
    ("company", "Firma", "Flüssigboden Engineering GmbH"),
    ("email", "E-Mail", "d.model@fb-eng.de"),
    ("phone", "Telefon (für Kontakt/vCard)", "+49 …"),
    ("whatsapp", "WhatsApp-Nummer (international, z. B. 4915…)", "49151…"),
    ("linkedin", "LinkedIn-URL", "https://www.linkedin.com/in/…"),
    ("maps", "Google-Maps-URL (Standort)", "https://maps.app.goo.gl/…"),
    ("website", "Webseite", "https://fb-eng.de"),
]


def _load() -> dict[str, Any]:
    path = config.VCARDS_FILE
    if not path.exists():
        return {"cards": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("cards", [])
        return data
    except Exception:
        return {"cards": []}


def _save(data: dict[str, Any]) -> None:
    path = config.VCARDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or f"karte-{secrets.token_hex(3)}"


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def list_cards() -> list[dict[str, Any]]:
    cards = _load()["cards"]
    cards.sort(key=lambda c: (c.get("name") or "").lower())
    return cards


def get(card_id: str) -> dict[str, Any] | None:
    for c in _load()["cards"]:
        if c.get("id") == card_id:
            return c
    return None


def by_slug(slug: str) -> dict[str, Any] | None:
    """Karte fuer die OEFFENTLICHE Auslieferung: nur aktive Karten."""
    if not valid_slug(slug):
        return None
    for c in _load()["cards"]:
        if c.get("slug") == slug and c.get("enabled"):
            return c
    return None


def slug_taken(slug: str, except_id: str = "") -> bool:
    return any(c.get("slug") == slug and c.get("id") != except_id
               for c in _load()["cards"])


def add(name: str) -> dict[str, Any]:
    slug = slugify(name)
    if slug_taken(slug):
        slug = f"{slug}-{secrets.token_hex(2)}"
    card = {"id": secrets.token_hex(8), "slug": slug, "enabled": False,
            "name": (name or "").strip(), "title": "",
            "company": "Flüssigboden Engineering GmbH",
            "email": "", "phone": "", "whatsapp": "", "linkedin": "",
            "maps": "", "website": "https://fb-eng.de",
            "photo": "", "created_at": _now(), "updated_at": _now()}
    with _LOCK:
        data = _load()
        data["cards"].append(card)
        _save(data)
    return card


def update(card_id: str, values: dict[str, Any]) -> bool:
    allowed = {k for k, _l, _p in FIELDS} | {"slug", "enabled", "photo"}
    with _LOCK:
        data = _load()
        for c in data["cards"]:
            if c.get("id") == card_id:
                for k, v in values.items():
                    if k in allowed:
                        c[k] = v
                c["updated_at"] = _now()
                _save(data)
                return True
    return False


def delete(card_id: str) -> dict[str, Any] | None:
    removed: dict[str, Any] = {}
    with _LOCK:
        data = _load()
        for c in data["cards"]:
            if c.get("id") == card_id:
                removed = c
        data["cards"] = [c for c in data["cards"] if c.get("id") != card_id]
        if removed:
            _save(data)
    if removed and removed.get("photo"):
        try:
            Path(removed["photo"]).unlink(missing_ok=True)
        except Exception:
            pass
    return removed or None


def public_url(card: dict[str, Any]) -> str:
    return f"{config.PUBLIC_BASE_URL}/v/{card.get('slug', '')}"


def build_vcf(card: dict[str, Any]) -> str:
    """vCard 3.0 fuer den 'Kontakt speichern'-Button."""
    name = (card.get("name") or "").strip()
    parts = name.split()
    last = parts[-1] if parts else ""
    first = " ".join(parts[:-1]) if len(parts) > 1 else ""
    lines = ["BEGIN:VCARD", "VERSION:3.0",
             f"N:{last};{first};;;", f"FN:{name}"]
    if card.get("company"):
        lines.append(f"ORG:{card['company']}")
    if card.get("title"):
        lines.append(f"TITLE:{card['title']}")
    if card.get("phone"):
        lines.append(f"TEL;TYPE=CELL:{card['phone']}")
    if card.get("email"):
        lines.append(f"EMAIL;TYPE=WORK:{card['email']}")
    if card.get("website"):
        lines.append(f"URL:{card['website']}")
    lines.append(f"URL:{public_url(card)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"
