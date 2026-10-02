"""
Datenbankschicht: Schema, Verbindung, Transaktionen, Backup.

Die Datenbank ist eine einzelne SQLite-Datei (Standard: verteiler.db neben
app.py). Schutzregeln liegen zusätzlich als Trigger direkt in der DB, damit
sie auch bei einem Programmierfehler oder einem Zugriff mit einem anderen
SQLite-Werkzeug greifen:

- Einträge der Sperrliste können weder geändert noch gelöscht werden.
- Ein Kontakt, dessen Adresse auf der Sperrliste steht, kann nicht gelöscht
  und nicht wieder auf "aktiv" / "bounce_weich" gesetzt werden.
- Ausnahme ist nur die DSGVO-Löschung: Sie trägt die Adresse für die Dauer
  ihrer Transaktion in `dsgvo_freigabe` ein und entfernt sie danach wieder.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

KONTAKT_STATUS = ("aktiv", "bounce_hart", "bounce_weich", "abgemeldet", "gesperrt")
ZUSTELLSTATUS = ("zugestellt", "unzustellbar", "soft_bounce", "nicht_zugestellt", "abgemeldet")
SPERRGRUENDE = ("bounce_hart", "abgemeldet", "beschwerde", "manuell")

# Welcher Kontaktstatus gehört zu welchem Sperrgrund.
STATUS_FUER_SPERRGRUND = {
    "bounce_hart": "bounce_hart",
    "abgemeldet": "abgemeldet",
    "beschwerde": "gesperrt",
    "manuell": "gesperrt",
}


def _liste(werte: tuple[str, ...]) -> str:
    return ", ".join(f"'{w}'" for w in werte)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS contacts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    email              TEXT NOT NULL UNIQUE
                       CHECK (email <> '' AND email = lower(trim(email))),
    vorname            TEXT NOT NULL DEFAULT '',
    nachname           TEXT NOT NULL DEFAULT '',
    firma              TEXT NOT NULL DEFAULT '',
    quelle             TEXT NOT NULL DEFAULT '',
    einwilligung_art   TEXT NOT NULL DEFAULT '',
    einwilligung_datum TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'aktiv'
                       CHECK (status IN ({_liste(KONTAKT_STATUS)})),
    soft_bounce_folge  INTEGER NOT NULL DEFAULT 0 CHECK (soft_bounce_folge >= 0),
    erstellt_am        TEXT NOT NULL,
    geaendert_am       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL CHECK (name <> ''),
    betreff           TEXT NOT NULL DEFAULT '',
    gesendet_am       TEXT NOT NULL,
    empfaenger_anzahl INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS campaign_events (
    contact_id    INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    geoeffnet     INTEGER NOT NULL DEFAULT 0 CHECK (geoeffnet >= 0),
    geklickt      INTEGER NOT NULL DEFAULT 0 CHECK (geklickt >= 0),
    zustellstatus TEXT NOT NULL CHECK (zustellstatus IN ({_liste(ZUSTELLSTATUS)})),
    PRIMARY KEY (contact_id, campaign_id)
);
CREATE INDEX IF NOT EXISTS idx_events_campaign ON campaign_events(campaign_id);

CREATE TABLE IF NOT EXISTS suppression_list (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE CHECK (email <> '' AND email = lower(trim(email))),
    grund TEXT NOT NULL CHECK (grund IN ({_liste(SPERRGRUENDE)})),
    datum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    zeitpunkt     TEXT NOT NULL,
    art           TEXT NOT NULL,
    dateiname     TEXT NOT NULL DEFAULT '',
    neu           INTEGER NOT NULL DEFAULT 0,
    aktualisiert  INTEGER NOT NULL DEFAULT 0,
    uebersprungen INTEGER NOT NULL DEFAULT 0,
    details       TEXT NOT NULL DEFAULT ''
);

-- Nur während einer DSGVO-Löschung befüllt (innerhalb derselben Transaktion).
CREATE TABLE IF NOT EXISTS dsgvo_freigabe (
    email TEXT PRIMARY KEY
);

CREATE TRIGGER IF NOT EXISTS sperrliste_kein_update
BEFORE UPDATE ON suppression_list
BEGIN
    SELECT RAISE(ABORT, 'Sperrliste: Einträge dürfen nicht geändert werden');
END;

CREATE TRIGGER IF NOT EXISTS sperrliste_kein_delete
BEFORE DELETE ON suppression_list
WHEN NOT EXISTS (SELECT 1 FROM dsgvo_freigabe f WHERE f.email = OLD.email)
BEGIN
    SELECT RAISE(ABORT, 'Sperrliste: Einträge dürfen nur per DSGVO-Löschung entfernt werden');
END;

CREATE TRIGGER IF NOT EXISTS kontakt_gesperrt_kein_delete
BEFORE DELETE ON contacts
WHEN EXISTS (SELECT 1 FROM suppression_list s WHERE s.email = OLD.email)
 AND NOT EXISTS (SELECT 1 FROM dsgvo_freigabe f WHERE f.email = OLD.email)
BEGIN
    SELECT RAISE(ABORT, 'Kontakt steht auf der Sperrliste und darf nicht gelöscht werden');
END;

CREATE TRIGGER IF NOT EXISTS kontakt_gesperrt_nicht_aktivieren
BEFORE UPDATE OF status ON contacts
WHEN NEW.status IN ('aktiv', 'bounce_weich')
 AND EXISTS (SELECT 1 FROM suppression_list s WHERE s.email = NEW.email)
BEGIN
    SELECT RAISE(ABORT, 'Kontakt steht auf der Sperrliste und darf nicht aktiviert werden');
END;

CREATE TRIGGER IF NOT EXISTS kontakt_gesperrt_nicht_anlegen
BEFORE INSERT ON contacts
WHEN NEW.status IN ('aktiv', 'bounce_weich')
 AND EXISTS (SELECT 1 FROM suppression_list s WHERE s.email = NEW.email)
BEGIN
    SELECT RAISE(ABORT, 'Adresse steht auf der Sperrliste und darf nicht aktiv angelegt werden');
END;

CREATE TRIGGER IF NOT EXISTS kontakt_email_unveraenderlich
BEFORE UPDATE OF email ON contacts
WHEN NEW.email <> OLD.email
BEGIN
    SELECT RAISE(ABORT, 'Die E-Mail-Adresse eines Kontakts kann nicht geändert werden');
END;
"""


def jetzt() -> str:
    """Aktueller lokaler Zeitpunkt als ISO-Text (sekundengenau)."""
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def connect(db_path: str | os.PathLike) -> sqlite3.Connection:
    """Öffnet die Datenbank, legt das Schema an und aktiviert Fremdschlüssel.

    isolation_level=None: Transaktionen werden ausschließlich explizit über
    `transaction()` gesteuert, nichts wird implizit geöffnet oder committet.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        # Schema komplett oder gar nicht anlegen.
        try:
            conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA
                               + f"\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
            raise
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Schreibtransaktion: COMMIT bei Erfolg, ROLLBACK bei jedem Fehler.

    BEGIN IMMEDIATE sperrt die DB sofort für andere Schreiber, damit die
    Prüfung (z. B. "steht die Adresse auf der Sperrliste?") und das Schreiben
    atomar zusammengehören.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def backup(db_path: str | os.PathLike, backup_dir: str | os.PathLike,
           behalten: int = 100) -> Path | None:
    """Kopiert die DB konsistent nach backups/verteiler_JJJJMMTT_HHMMSS.db.

    Nutzt die SQLite-Backup-API (sicher auch bei geöffneter DB). Es werden
    die neuesten `behalten` Sicherungen aufbewahrt, ältere gelöscht.
    Gibt den Pfad zurück, oder None, wenn noch keine DB existiert.
    """
    src_path = Path(db_path)
    if not src_path.exists():
        return None
    ziel_dir = Path(backup_dir)
    ziel_dir.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    ziel = ziel_dir / f"verteiler_{stempel}.db"
    n = 1
    while ziel.exists():
        n += 1
        ziel = ziel_dir / f"verteiler_{stempel}_{n}.db"

    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(ziel))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    if behalten > 0:
        alle = sorted(ziel_dir.glob("verteiler_*.db"), key=lambda p: p.stat().st_mtime)
        for alt in alle[:-behalten]:
            try:
                alt.unlink()
            except OSError:
                pass
    return ziel
