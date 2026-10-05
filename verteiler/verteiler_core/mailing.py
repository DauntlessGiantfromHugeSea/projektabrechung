"""
Abgleich mit dem Mailing-Tool (https://mailing.rss-fb.com).

Der Verteiler bleibt die führende Datenbank. Bei jedem Abgleich

1. übergibt er seine komplette Sperrliste: Das Mailing-Tool sperrt diese
   Adressen ebenfalls und bricht geplante Sendungen an sie ab,
2. übergibt er die Empfänger des gewählten Segments: Daraus pflegt das
   Mailing-Tool die Liste „Verteiler: Alle aktiven“ (Name einstellbar), an die
   Kampagnen geschickt werden. Das passiert nur, wenn sich etwas geändert hat,
   sonst höchstens einmal am Tag,
3. fragt er für alle versandfähigen Adressen ab, ob sie im Mailing-Tool
   gesperrt sind (Abmeldelink, Bounce, Beschwerde). Solche Adressen kommen
   hier auf die Sperrliste.

Zugang: MAILING_URL und MAILING_SYNC_TOKEN in deploy/.env (das Token steht
im Mailing-Tool als VERTEILER_SYNC_TOKEN). Ein- und Ausschalten, Segment und
Listenname werden im Backend eingestellt (Seite „Mailing-Tool“).
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from . import db, imports, queries

STANDARD_URL = "https://mailing.rss-fb.com"
STANDARD_LISTE = "Verteiler: Alle aktiven"
SEGMENTE = ("alle_aktiven", "engagierte")
TIMEOUT_SEKUNDEN = 180
LISTE_SPAETESTENS_NACH = timedelta(hours=24)

GRUENDE = set(db.SPERRGRUENDE)


class MailingFehler(RuntimeError):
    """Fehler beim Abgleich (Meldung ohne Geheimnisse)."""


@dataclass
class Zugang:
    url: str = ""
    token: str = field(default="", repr=False)

    @property
    def konfiguriert(self) -> bool:
        return bool(self.url and len(self.token) >= 32)


def zugang_aus_env(env: dict | None = None) -> Zugang:
    env = os.environ if env is None else env
    url = (env.get("MAILING_URL") or STANDARD_URL).strip().rstrip("/")
    teile = urllib.parse.urlsplit(url)
    lokal = teile.hostname in ("127.0.0.1", "localhost")
    if teile.scheme != "https" and not (teile.scheme == "http" and lokal):
        url = ""  # Token nie unverschlüsselt über das Netz schicken
    return Zugang(url=url, token=(env.get("MAILING_SYNC_TOKEN") or "").strip())


@dataclass
class Einstellungen:
    aktiv: bool = False
    segment: str = "alle_aktiven"
    tage: int = 90
    liste: str = STANDARD_LISTE


def einstellungen_lesen(conn) -> Einstellungen:
    segment = db.einstellung(conn, "mailing_segment", "alle_aktiven")
    try:
        tage = max(1, min(3650, int(db.einstellung(conn, "mailing_tage", "90"))))
    except ValueError:
        tage = 90
    return Einstellungen(
        aktiv=db.einstellung(conn, "mailing_aktiv", "0") == "1",
        segment=segment if segment in SEGMENTE else "alle_aktiven",
        tage=tage,
        liste=(db.einstellung(conn, "mailing_liste", STANDARD_LISTE).strip() or STANDARD_LISTE)[:120],
    )


def einstellungen_speichern(db_path, e: Einstellungen, benutzer: str = "") -> None:
    if e.segment not in SEGMENTE:
        raise MailingFehler("Unbekanntes Segment.")
    liste = " ".join(str(e.liste).split())[:120]
    if not liste:
        raise MailingFehler("Bitte einen Listennamen angeben.")
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            db.einstellungen_setzen(conn, {
                "mailing_aktiv": "1" if e.aktiv else "0",
                "mailing_segment": e.segment,
                "mailing_tage": str(max(1, min(3650, int(e.tage)))),
                "mailing_liste": liste,
                "mailing_liste_hash": "",  # neue Einstellungen -> Liste beim nächsten Mal senden
            }, benutzer)
    finally:
        conn.close()


@dataclass
class Ergebnis:
    zeitpunkt: str = ""
    liste_gesendet: bool = False
    liste_mitglieder: int = 0
    liste_neu: int = 0
    liste_entfernt: int = 0
    sperren_uebergeben: int = 0
    sperren_dort_neu: int = 0
    sendungen_abgebrochen: int = 0
    rueckmeldungen: int = 0
    hier_neu_gesperrt: int = 0
    fehler: str = ""
    backup: str = ""

    def text(self) -> str:
        if self.fehler:
            return f"Abgleich fehlgeschlagen: {self.fehler}"
        teile = [f"{self.sperren_uebergeben} Sperren übergeben ({self.sperren_dort_neu} dort neu"
                 + (f", {self.sendungen_abgebrochen} geplante Sendungen abgebrochen" if self.sendungen_abgebrochen else "")
                 + ")"]
        if self.liste_gesendet:
            teile.append(f"Liste: {self.liste_mitglieder} Empfänger (+{self.liste_neu}, -{self.liste_entfernt})")
        else:
            teile.append("Liste unverändert")
        teile.append(f"{self.hier_neu_gesperrt} Abmeldungen/Bounces aus dem Mailing-Tool hier gesperrt")
        return "Abgleich erfolgreich: " + "; ".join(teile) + "."


def letzter_stand(conn) -> Ergebnis | None:
    roh = db.einstellung(conn, "mailing_letzter_stand", "")
    if not roh:
        return None
    try:
        return Ergebnis(**{k: v for k, v in json.loads(roh).items() if k in Ergebnis.__dataclass_fields__})
    except (ValueError, TypeError):
        return None


def _senden(zugang: Zugang, nutzlast: dict) -> dict:
    daten = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{zugang.url}/api/integration/verteiler", data=daten, method="POST",
        headers={"Authorization": f"Bearer {zugang.token}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "FBE-Verteiler"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEKUNDEN) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with exc:
            meldung = ""
            try:
                meldung = str(json.loads(exc.read().decode("utf-8", "replace")).get("error", ""))[:200]
            except Exception:
                pass
        hinweis = {401: "Token stimmt nicht (MAILING_SYNC_TOKEN / VERTEILER_SYNC_TOKEN)",
                   503: "Schnittstelle im Mailing-Tool ist abgeschaltet (VERTEILER_SYNC_TOKEN fehlt)"}
        raise MailingFehler(f"Mailing-Tool antwortet mit HTTP {exc.code}: "
                            f"{hinweis.get(exc.code, meldung or 'Fehler')}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise MailingFehler(f"Mailing-Tool nicht erreichbar ({type(exc).__name__})") from None
    except ValueError:
        raise MailingFehler("Mailing-Tool hat keine gültige Antwort geliefert") from None


def _stand_speichern(db_path, ergebnis: Ergebnis, extra: dict | None = None) -> None:
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            db.einstellungen_setzen(conn, {"mailing_letzter_stand": json.dumps(asdict(ergebnis)),
                                           **(extra or {})}, "Abgleich")
    finally:
        conn.close()


def abgleichen(db_path, backup_dir, zugang: Zugang | None = None, benutzer: str = "Abgleich",
               liste_erzwingen: bool = False) -> Ergebnis:
    """Ein Abgleich. Wirft MailingFehler; der Stand wird in jedem Fall gespeichert."""
    zugang = zugang or zugang_aus_env()
    ergebnis = Ergebnis(zeitpunkt=db.jetzt())
    if not zugang.konfiguriert:
        raise MailingFehler("Mailing-Tool nicht eingerichtet (MAILING_SYNC_TOKEN in deploy/.env fehlt).")

    conn = db.connect(db_path)
    try:
        cfg = einstellungen_lesen(conn)
        sperren = [{"email": r["email"], "reason": r["grund"]}
                   for r in conn.execute("SELECT email, grund FROM suppression_list ORDER BY email")]
        pruefen = [r["email"] for r in queries.segment_kontakte(conn, "alle_aktiven")]
        empfaenger = [{"email": r["email"], "firstName": r["vorname"] or None,
                       "lastName": r["nachname"] or None, "company": r["firma"] or None}
                      for r in queries.segment_kontakte(conn, cfg.segment, cfg.tage)]
        liste_hash = hashlib.sha256(json.dumps([cfg.liste, empfaenger], ensure_ascii=False)
                                    .encode()).hexdigest()
        alter_hash = db.einstellung(conn, "mailing_liste_hash", "")
        zuletzt = db.einstellung(conn, "mailing_liste_gesendet_am", "")
    finally:
        conn.close()

    faellig = liste_erzwingen or liste_hash != alter_hash
    if not faellig and zuletzt:
        try:
            faellig = datetime.now() - datetime.fromisoformat(zuletzt) > LISTE_SPAETESTENS_NACH
        except ValueError:
            faellig = True
    nutzlast = {"suppress": sperren, "check": pruefen}
    if faellig:
        nutzlast["list"] = {"name": cfg.liste, "contacts": empfaenger}

    try:
        antwort = _senden(zugang, nutzlast)
    except MailingFehler as exc:
        ergebnis.fehler = str(exc)
        _stand_speichern(db_path, ergebnis)
        raise

    ergebnis.sperren_uebergeben = len(sperren)
    ergebnis.sperren_dort_neu = int(antwort.get("suppressionsAdded") or 0)
    ergebnis.sendungen_abgebrochen = int(antwort.get("jobsSkipped") or 0)
    liste = antwort.get("list") or None
    if faellig and isinstance(liste, dict):
        ergebnis.liste_gesendet = True
        ergebnis.liste_mitglieder = int(liste.get("members") or 0)
        ergebnis.liste_neu = int(liste.get("created") or 0)
        ergebnis.liste_entfernt = int(liste.get("removed") or 0)

    # Rückmeldungen: nur Adressen, nach denen wir gefragt haben, nur bekannte Gründe
    gefragt = set(pruefen)
    rueck = [r for r in (antwort.get("suppressions") or [])
             if isinstance(r, dict) and r.get("email") in gefragt and r.get("grund") in GRUENDE]
    ergebnis.rueckmeldungen = len(rueck)
    if rueck:
        pfad = db.backup(db_path, backup_dir)
        ergebnis.backup = str(pfad) if pfad else ""
        conn = db.connect(db_path)
        try:
            with db.transaction(conn):
                for r in rueck:
                    if imports.sperren(conn, r["email"], r["grund"]):
                        ergebnis.hier_neu_gesperrt += 1
                imports._log(conn, "mailing", "Mailing-Tool", 0, ergebnis.hier_neu_gesperrt, 0,
                             {k: v for k, v in asdict(ergebnis).items() if k not in ("backup", "fehler")},
                             benutzer)
        finally:
            conn.close()

    extra = {}
    if ergebnis.liste_gesendet:
        extra = {"mailing_liste_hash": liste_hash,
                 "mailing_liste_gesendet_am": datetime.now().isoformat(timespec="seconds")}
    _stand_speichern(db_path, ergebnis, extra)
    return ergebnis
