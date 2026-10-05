"""
Hintergrund-Abgleich (eigener Container „verteiler-hintergrund“).

Läuft in einer Schleife und erledigt alle VERTEILER_HINTERGRUND_MIN Minuten
(Standard 10):
- Postfach abrufen, wenn im Backend eingeschaltet und mit Microsoft verbunden,
- Abgleich mit dem Mailing-Tool, wenn im Backend eingeschaltet und
  MAILING_SYNC_TOKEN gesetzt ist.

Fehler werden protokolliert (ohne Adressen und Geheimnisse); der nächste
Durchlauf versucht es erneut.

Start:  python -m verteiler_core.hintergrund
"""

from __future__ import annotations

import logging
import os
import sys
import time

from . import db, mailing, postfach

LOG = logging.getLogger("verteiler.hintergrund")


def ein_durchlauf(db_path: str, backup_dir: str) -> None:
    conn = db.connect(db_path)
    try:
        pf = postfach.einstellungen_lesen(conn)
        ml = mailing.einstellungen_lesen(conn)
    finally:
        conn.close()

    if pf.bereit:
        try:
            LOG.info("Postfach: %s", postfach.abrufen(db_path, backup_dir, benutzer="Hintergrund",
                                                    nur_wenn_aktiv=True).text())
        except postfach.PostfachFehler as exc:
            LOG.error("Postfach: %s", exc)
        except Exception as exc:  # nie abstürzen
            LOG.error("Postfach: unerwarteter Fehler %s", type(exc).__name__)

    if ml.aktiv:
        try:
            LOG.info("Mailing-Tool: %s", mailing.abgleichen(db_path, backup_dir, benutzer="Hintergrund").text())
        except mailing.MailingFehler as exc:
            LOG.error("Mailing-Tool: %s", exc)
        except Exception as exc:
            LOG.error("Mailing-Tool: unerwarteter Fehler %s", type(exc).__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    db_path = os.environ.get("VERTEILER_DB", "verteiler.db")
    backup_dir = os.environ.get("VERTEILER_BACKUPS", "backups")
    try:
        minuten = max(1, min(1440, int(os.environ.get("VERTEILER_HINTERGRUND_MIN", "10"))))
    except ValueError:
        minuten = 10
    LOG.info("Hintergrund-Abgleich gestartet, alle %s Minuten.", minuten)
    while True:
        ein_durchlauf(db_path, backup_dir)
        time.sleep(minuten * 60)


if __name__ == "__main__":
    main()
