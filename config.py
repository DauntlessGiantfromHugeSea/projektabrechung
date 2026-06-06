"""
Zentrale Konfiguration -- alles per Umgebungsvariablen steuerbar.

Bewusst ohne externe Settings-Bibliothek, damit die App leichtgewichtig
bleibt. Jede Einstellung hat einen sinnvollen Default; nichts ist Pflicht,
ausser du willst wirklich Mails verschicken (dann SMTP_* + REPORT_RECIPIENTS).
"""

import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo


# Marke (fuer Web-UI und Mail-Design)
LOGO_URL = os.getenv(
    "LOGO_URL", "https://fb-eng.de/wp-content/uploads/2024/10/FBE_green.png")
BRAND_COLOR = os.getenv("BRAND_COLOR", "#92c57a")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on", "ja"}


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- Webhook-Empfang (unveraendert zur Erkundungsphase) --------------------
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/timemoto")
SHARED_SECRET = os.getenv("SHARED_SECRET", "")
LOG_FILE = Path(os.getenv("LOG_FILE", "/data/events.jsonl"))

# --- Bericht ---------------------------------------------------------------
# Verzeichnis, in dem erzeugte Berichte abgelegt werden (immer, zusaetzlich
# zum optionalen Mailversand -- so geht nie ein Bericht verloren).
REPORT_DIR = Path(os.getenv("REPORT_DIR", "/data/reports"))

# Auf welches Projekt der Bericht filtert. Leer = alle Projekte, gruppiert.
# Es genuegt ein Teilstring (case-insensitive), der zum Projektcode oder
# -namen passt, z. B. "ACME" oder "Projekt-42".
PROJECT_CODE = os.getenv("PROJECT_CODE", "").strip()

# Optionaler Override: exakter JSON-Feldname, in dem der Projektbezug steckt.
# Nur noetig, wenn die Auto-Erkennung das falsche Feld erwischt.
PROJECT_FIELD = os.getenv("PROJECT_FIELD", "").strip()

# Zeitzone fuer Wochengrenzen und Anzeige.
TIMEZONE = ZoneInfo(os.getenv("REPORT_TIMEZONE", "Europe/Berlin"))

# Wochenplan des Schedulers (Cron-Syntax von APScheduler).
# Default: jeden Montag 07:00 -> Bericht fuer die *vorige* Woche.
CRON_DAY_OF_WEEK = os.getenv("REPORT_CRON_DAY_OF_WEEK", "mon")
CRON_HOUR = int(os.getenv("REPORT_CRON_HOUR", "7"))
CRON_MINUTE = int(os.getenv("REPORT_CRON_MINUTE", "0"))
SCHEDULER_ENABLED = _bool("SCHEDULER_ENABLED", True)

# --- E-Mail (optional; "machen wir spaeter") -------------------------------
# Solange SMTP_HOST oder REPORT_RECIPIENTS leer sind, wird NICHT gemailt --
# der Bericht landet dann nur als Datei in REPORT_DIR und im Log.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()
SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)
SMTP_SSL = _bool("SMTP_SSL", False)
# Alternativer Versand ueber die Brevo-HTTP-API (Port 443) -- funktioniert auch,
# wenn der Hoster ausgehendes SMTP (25/465/587/2525) blockiert. Wenn gesetzt,
# wird die API bevorzugt. API-Key in Brevo unter "SMTP & API" -> "API Keys"
# erzeugen (beginnt mit xkeysib-).
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
REPORT_RECIPIENTS = _list("REPORT_RECIPIENTS")
REPORT_SUBJECT_PREFIX = os.getenv("REPORT_SUBJECT_PREFIX", "Projektzeiten")


def mail_configured() -> bool:
    """True, wenn genug fuer einen echten Mailversand konfiguriert ist
    (SMTP-Server ODER Brevo-API, plus Standard-Empfaenger)."""
    return bool((SMTP_HOST or BREVO_API_KEY) and REPORT_RECIPIENTS)


# --- Web-Interface / Login -------------------------------------------------
# Zugangsdaten fuer das Web-UI. Ohne gesetztes ADMIN_PASSWORD ist kein Login
# moeglich (die Login-Seite weist dann darauf hin).
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# Schluessel zum Signieren des Session-Cookies. Wenn nicht gesetzt, wird beim
# Start ein zufaelliger erzeugt -> alle werden bei jedem Neustart ausgeloggt.
# Fuer dauerhafte Sessions einen festen Wert setzen (z. B. `openssl rand -hex 32`).
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
# Cookie nur ueber HTTPS senden. Hinter fbe-caddy (HTTPS) korrekt; fuer lokales
# HTTP-Testen ggf. auf false setzen.
SESSION_HTTPS_ONLY = _bool("SESSION_HTTPS_ONLY", True)


def login_possible() -> bool:
    """True, wenn ein Passwort gesetzt ist (sonst kein Login moeglich)."""
    return bool(ADMIN_PASSWORD)


# Datei der Benutzerverwaltung (Nutzer, Passwort-Hashes, Rollen).
USERS_FILE = Path(os.getenv("USERS_FILE", "/data/users.json"))

# Datei der online konfigurierten Bericht-Definitionen (Projekte/Empfaenger/Plan).
SETTINGS_FILE = Path(os.getenv("SETTINGS_FILE", "/data/settings.json"))

# Manuelle Eintraege/Korrekturen (zusaetzliche Buchungen + ausgeblendete).
MANUAL_FILE = Path(os.getenv("MANUAL_FILE", "/data/manual.json"))
# Aenderungsprotokoll (Audit-Log): wer hat wann was geaendert.
AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "/data/audit.json"))

# Download-Links fuer Mails (Anhaenge ersetzen). Tokenisiert -> liefern nur
# genau die eine Datei, keine anderen Seiten.
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/data/downloads"))
DOWNLOADS_FILE = Path(os.getenv("DOWNLOADS_FILE", "/data/downloads.json"))
DOWNLOAD_TTL_DAYS = int(os.getenv("DOWNLOAD_TTL_DAYS", "60"))
# Oeffentliche Basis-URL fuer Links in Mails (kein Request-Kontext im Scheduler).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://intern.rss-fb.com").rstrip("/")
