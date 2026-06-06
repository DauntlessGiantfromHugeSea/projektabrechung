"""
Einfache, dateibasierte Benutzerverwaltung.

- Speichert Nutzer in einer JSON-Datei (USERS_FILE).
- Passwoerter werden als PBKDF2-HMAC-SHA256-Hash mit Salt abgelegt
  (nur Standardbibliothek, keine Zusatzabhaengigkeit).
- Rollen: "admin" (darf Nutzer verwalten) und "user".
- Einladung: Admin legt einen Nutzer an, dieser bekommt einen Einladungs-Token;
  ueber /invite/<token> setzt er sein eigenes Passwort (funktioniert ohne Mail).

Bewusst schlicht gehalten (kleine Nutzerzahl, geringe Last). Schreibzugriffe
sind selten und unkritisch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

import config

_LOCK = threading.Lock()
_ITERATIONS = 200_000


# --- Persistenz ------------------------------------------------------------

def _load() -> dict[str, dict[str, Any]]:
    path = config.USERS_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(users: dict[str, dict[str, Any]]) -> None:
    path = config.USERS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Passwort-Hashing ------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --- Verwaltung ------------------------------------------------------------

def bootstrap_admin() -> None:
    """Beim Start: falls noch keine Nutzer existieren und ADMIN_PASSWORD
    gesetzt ist, einen Admin aus den Env-Vars anlegen (Migration vom
    bisherigen Einzel-Login)."""
    with _LOCK:
        users = _load()
        if users:
            return
        if not config.ADMIN_PASSWORD:
            return
        users[config.ADMIN_USER] = {
            "username": config.ADMIN_USER,
            "name": config.ADMIN_USER,
            "email": "",
            "timemoto_name": "",
            "role": "admin",
            "password": hash_password(config.ADMIN_PASSWORD),
            "status": "active",
            "invite_token": None,
            "totp_secret": None,
            "twofa_enabled": False,
            "can_view_tickets": True,
            "can_edit_tickets": True,
            "created_at": _now(),
        }
        _save(users)


def verify_login(username: str, password: str) -> dict[str, Any] | None:
    user = _load().get(username)
    if not user or user.get("status") != "active":
        return None
    if verify_password(password, user.get("password")):
        return user
    return None


def get(username: str) -> dict[str, Any] | None:
    return _load().get(username)


def list_users() -> list[dict[str, Any]]:
    return sorted(_load().values(), key=lambda u: u["username"].lower())


def count_admins(users: dict[str, dict[str, Any]] | None = None) -> int:
    users = users if users is not None else _load()
    return sum(1 for u in users.values()
               if u.get("role") == "admin" and u.get("status") == "active")


def set_password(username: str, new_password: str) -> bool:
    with _LOCK:
        users = _load()
        if username not in users:
            return False
        users[username]["password"] = hash_password(new_password)
        users[username]["status"] = "active"
        users[username]["invite_token"] = None
        _save(users)
        return True


def create_invite(username: str, role: str = "user", name: str = "",
                  email: str = "", timemoto_name: str = "",
                  can_view_tickets: bool = False,
                  can_edit_tickets: bool = False) -> str | None:
    """Neuen Nutzer als 'invited' anlegen, Einladungs-Token zurueckgeben.
    None, wenn der Name schon existiert."""
    username = username.strip()
    role = role if role in ("admin", "user", "buchhaltung") else "user"
    with _LOCK:
        users = _load()
        if not username or username in users:
            return None
        token = secrets.token_urlsafe(32)
        users[username] = {
            "username": username,
            "name": (name or username).strip(),
            "email": email.strip(),
            "timemoto_name": timemoto_name.strip(),
            "role": role,
            "password": None,
            "status": "invited",
            "invite_token": token,
            "can_view_tickets": bool(can_view_tickets),
            "can_edit_tickets": bool(can_edit_tickets),
            "created_at": _now(),
        }
        _save(users)
        return token


def set_name(username: str, name: str) -> bool:
    with _LOCK:
        users = _load()
        if username not in users:
            return False
        users[username]["name"] = (name or username).strip()
        _save(users)
        return True


def set_profile(username: str, name: str, email: str, timemoto_name: str,
                role: str | None = None, can_view_tickets: bool | None = None,
                can_edit_tickets: bool | None = None) -> bool:
    """Vom Admin pflegbare Stammdaten setzen (inkl. Rolle + Ticket-Rechte)."""
    with _LOCK:
        users = _load()
        if username not in users:
            return False
        u = users[username]
        u["name"] = (name or username).strip()
        u["email"] = email.strip()
        u["timemoto_name"] = timemoto_name.strip()
        if can_view_tickets is not None:
            u["can_view_tickets"] = bool(can_view_tickets)
        if can_edit_tickets is not None:
            u["can_edit_tickets"] = bool(can_edit_tickets)
        if role in ("admin", "user", "buchhaltung"):
            # Letzten AKTIVEN Admin nicht herabstufen
            is_last_active_admin = (u.get("role") == "admin"
                                    and u.get("status") == "active"
                                    and count_admins(users) <= 1)
            if not (role != "admin" and is_last_active_admin):
                u["role"] = role
        _save(users)
        return True


def enroll_totp(username: str, secret: str) -> bool:
    with _LOCK:
        users = _load()
        if username not in users:
            return False
        users[username]["totp_secret"] = secret
        users[username]["twofa_enabled"] = True
        _save(users)
        return True


def _reset_age_min(u: dict[str, Any]) -> float:
    try:
        d = datetime.fromisoformat(u.get("reset_at", ""))
        return (datetime.now(timezone.utc) - d).total_seconds() / 60.0
    except Exception:
        return 1e9


def create_reset_token(identifier: str) -> tuple[dict[str, Any] | None, str | None]:
    """Reset-Token fuer aktiven Nutzer (per Benutzername ODER E-Mail) erzeugen."""
    ident = identifier.strip().lower()
    if not ident:
        return None, None
    with _LOCK:
        users = _load()
        for uname, u in users.items():
            if u.get("status") != "active":
                continue
            if uname.lower() == ident or (u.get("email", "").strip().lower() == ident):
                token = secrets.token_urlsafe(24)
                u["reset_token"] = token
                u["reset_at"] = _now()
                _save(users)
                return u, token
    return None, None


def valid_reset(token: str) -> str | None:
    if not token:
        return None
    for uname, u in _load().items():
        if u.get("reset_token") and hmac.compare_digest(u["reset_token"], token):
            return uname if _reset_age_min(u) <= config.RESET_TTL_MIN else None
    return None


def consume_reset(token: str, new_password: str) -> str | None:
    with _LOCK:
        users = _load()
        for uname, u in users.items():
            if u.get("reset_token") and hmac.compare_digest(u["reset_token"], token):
                if _reset_age_min(u) > config.RESET_TTL_MIN:
                    return None
                u["password"] = hash_password(new_password)
                u["reset_token"] = None
                u["status"] = "active"
                _save(users)
                return uname
    return None


def by_email(email: str) -> dict[str, Any] | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    for u in _load().values():
        if (u.get("email") or "").strip().lower() == email:
            return u
    return None


def upsert_oauth(email: str, name: str) -> dict[str, Any]:
    """Microsoft-Konto: vorhandenen Nutzer (per E-Mail) zurueckgeben oder neu
    anlegen (Rolle 'user', ohne Passwort/2FA -- Anmeldung nur via Microsoft)."""
    existing = by_email(email)
    if existing:
        return existing
    with _LOCK:
        users = _load()
        uname = email
        if uname not in users:
            users[uname] = {
                "username": uname, "name": (name or email).strip(),
                "email": email.strip().lower(), "timemoto_name": "",
                "role": "user", "password": None, "status": "active",
                "invite_token": None, "totp_secret": None,
                "twofa_enabled": False, "can_view_tickets": False,
                "can_edit_tickets": False, "auth": "microsoft",
                "created_at": _now(),
            }
            _save(users)
        return users[uname]


def by_timemoto(timemoto_name: str) -> dict[str, Any] | None:
    if not timemoto_name:
        return None
    for u in _load().values():
        if (u.get("timemoto_name") or "").strip().lower() == timemoto_name.strip().lower():
            return u
    return None


def find_by_invite(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    for u in _load().values():
        if u.get("invite_token") and hmac.compare_digest(u["invite_token"], token):
            try:
                created = datetime.fromisoformat(u.get("created_at", ""))
                if (datetime.now(timezone.utc) - created).days > config.INVITE_TTL_DAYS:
                    return None  # abgelaufen
            except Exception:
                pass
            return u
    return None


def renew_invite(username: str) -> str | None:
    """Neuen Einladungs-Token mit frischem Ablauf erzeugen (erneut einladen)."""
    with _LOCK:
        users = _load()
        u = users.get(username)
        if not u or u.get("status") != "invited":
            return None
        token = secrets.token_urlsafe(32)
        u["invite_token"] = token
        u["created_at"] = _now()
        _save(users)
        return token


def delete_user(username: str) -> bool:
    with _LOCK:
        users = _load()
        if username not in users:
            return False
        # Letzten aktiven Admin nicht loeschen
        if (users[username].get("role") == "admin"
                and users[username].get("status") == "active"
                and count_admins(users) <= 1):
            return False
        del users[username]
        _save(users)
        return True
