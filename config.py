"""
Zentrale Konfiguration -- alles per Umgebungsvariablen steuerbar.

Bewusst ohne externe Settings-Bibliothek, damit die App leichtgewichtig
bleibt. Jede Einstellung hat einen sinnvollen Default; nichts ist Pflicht,
ausser du willst wirklich Mails verschicken (dann SMTP_* + REPORT_RECIPIENTS).
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo


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
REPORT_RECIPIENTS = _list("REPORT_RECIPIENTS")
REPORT_SUBJECT_PREFIX = os.getenv("REPORT_SUBJECT_PREFIX", "Projektzeiten")


def mail_configured() -> bool:
    """True, wenn genug fuer einen echten Mailversand konfiguriert ist."""
    return bool(SMTP_HOST and REPORT_RECIPIENTS)
