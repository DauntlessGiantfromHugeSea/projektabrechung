"""
Kontakte aus einem Microsoft-365-Postfach übernehmen.

Das Tool bekommt ein eigenes Postfach (z. B. verteiler@fb-eng.de). Jede Mail,
die dort ankommt – meist weitergeleitet –, wird ausgewertet. Alle
E-Mail-Adressen aus Absender, Empfänger (An), CC und dem Mailtext werden als
Kontakt übernommen. Es gelten dieselben Regeln wie beim Listen-Import:
Syntaxprüfung, Sperrliste wird beachtet, Dubletten werden zusammengeführt.

Nicht übernommen werden:
- Adressen der eigenen Domains (Kolleg:innen), Standard: Domain des Postfachs
- das Postfach selbst
- Systemadressen (noreply, mailer-daemon, postmaster, bounce …)

Zugriff über Microsoft Graph mit einer eigenen App-Registrierung
(Client-Credentials). Das Tool braucht nur Leserecht ("Mail.Read"), das per
Exchange-RBAC auf genau dieses eine Postfach beschränkt wird – siehe
deploy/DEPLOY.md. Es verschiebt oder löscht keine Mails. Welche Mails schon
ausgewertet wurden, merkt es sich in der Tabelle mail_eingang.

Start im Dauerbetrieb (eigener Container):  python -m verteiler_core.postfach
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import db, imports
from .normalize import clean_text, email_fehler, normalize_email

LOG = logging.getLogger("verteiler.postfach")

MAX_MAILS_PRO_LAUF = 200
MAX_ADRESSEN_PRO_MAIL = 1000
TIMEOUT_SEKUNDEN = 30


class PostfachFehler(RuntimeError):
    """Fehler beim Abruf (Meldung ohne Geheimnisse, für Nutzer gedacht)."""


@dataclass
class Einstellungen:
    postfach: str = ""
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    intern_domains: tuple[str, ...] = ()
    intervall_min: int = 10
    tage_zurueck: int = 7
    graph_url: str = "https://graph.microsoft.com/v1.0"
    login_url: str = "https://login.microsoftonline.com"

    @property
    def konfiguriert(self) -> bool:
        return all((self.postfach, self.tenant_id, self.client_id, self.client_secret))


def _int(wert: str | None, standard: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(str(wert).strip())))
    except (TypeError, ValueError):
        return standard


def einstellungen_aus_env(env: dict | None = None) -> Einstellungen:
    env = os.environ if env is None else env
    postfach = normalize_email(env.get("VERTEILER_MAIL_POSTFACH", ""))
    if postfach and email_fehler(postfach):
        postfach = ""
    domains = env.get("VERTEILER_MAIL_INTERN_DOMAINS", "").strip()
    if domains:
        intern = tuple(d.strip().lower().lstrip("@") for d in domains.split(",") if d.strip())
    else:
        intern = (postfach.split("@")[1],) if postfach else ()
    return Einstellungen(
        postfach=postfach,
        tenant_id=env.get("VERTEILER_MAIL_TENANT_ID", "").strip(),
        client_id=env.get("VERTEILER_MAIL_CLIENT_ID", "").strip(),
        client_secret=env.get("VERTEILER_MAIL_CLIENT_SECRET", "").strip(),
        intern_domains=intern,
        intervall_min=_int(env.get("VERTEILER_MAIL_INTERVALL_MIN"), 10, 1, 1440),
        tage_zurueck=_int(env.get("VERTEILER_MAIL_TAGE_ZURUECK"), 7, 0, 365),
    )


# ------------------------------------------------------------ Adressen finden

_EMAIL_IM_TEXT = re.compile(
    r"(?<![A-Za-z0-9._%+'&-])[A-Za-z0-9._%+'&-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")
_NAME_UND_ADRESSE = re.compile(
    r"(?:^|[\s:;,])[\"']?([^\s<>\"'@:;,][^<>\"@\r\n:;]{0,78}?)[\"']?\s*<\s*(?:mailto:)?"
    r"([^<>\s@]{1,64}@[^<>\s]{1,253})\s*>")
_MAILTO = re.compile(r"mailto:([^\"'?>\s]+)", re.IGNORECASE)
_SYSTEM_LOCAL = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|noreply|mailer-daemon|postmaster|bounces?|abuse"
    r"|unsubscribe|notifications?)([+._-].*)?$")
_TITEL = re.compile(r"^(dr|prof|dipl|ing|mag|herr|frau|mr|mrs|ms)\.?(-[a-z]+\.?)?$", re.IGNORECASE)


def name_teilen(name: str) -> tuple[str, str]:
    """'Max Muster' / 'Muster, Max' / 'Dr. Max Muster (Firma)' -> (Vorname, Nachname)."""
    n = clean_text(name, 120).strip(" '\"")
    if not n or "@" in n:
        return "", ""
    n = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if "," in n:
        nach, vor = (t.strip() for t in n.split(",", 1))
        return (vor, nach) if vor and nach else ("", "")
    teile = [t for t in n.split(" ") if not _TITEL.match(t)]
    if len(teile) < 2:
        return "", ""  # einzelnes Wort (z. B. "Vertrieb") ist kein sicherer Name
    return " ".join(teile[:-1]), teile[-1]


def ignorieren_grund(email: str, cfg: Einstellungen) -> str | None:
    if email == cfg.postfach:
        return "postfach"
    local, domain = email.split("@", 1)
    if any(domain == d or domain.endswith("." + d) for d in cfg.intern_domains):
        return "intern"
    if _SYSTEM_LOCAL.match(local):
        return "system"
    return None


def _text_der_mail(nachricht: dict) -> str:
    body = nachricht.get("body") or {}
    inhalt = str(body.get("content") or "")[:2_000_000]  # sehr lange Mails begrenzen
    if str(body.get("contentType", "")).lower() == "html":
        mailtos = " ".join(urllib.parse.unquote(m) for m in _MAILTO.findall(inhalt))
        inhalt = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", inhalt)
        inhalt = re.sub(r"(?s)<[^>]+>", " ", inhalt)
        inhalt = html.unescape(inhalt) + " " + mailtos
    return inhalt


def adressen_aus_mail(nachricht: dict, cfg: Einstellungen) -> tuple[dict[str, tuple[str, str]], dict[str, int]]:
    """Alle Adressen einer Graph-Nachricht.

    Rückgabe: ({email: (vorname, nachname)}, {"intern": n, "system": n, ...}).
    """
    gefunden: dict[str, tuple[str, str]] = {}
    ignoriert: dict[str, int] = {}

    def aufnehmen(roh: str, name: str = "") -> None:
        email = normalize_email(roh)
        if email_fehler(email):
            return
        grund = ignorieren_grund(email, cfg)
        if grund:
            ignoriert[grund] = ignoriert.get(grund, 0) + 1
            return
        vor, nach = name_teilen(name)
        if email not in gefunden:
            if len(gefunden) >= MAX_ADRESSEN_PRO_MAIL:
                ignoriert["limit"] = ignoriert.get("limit", 0) + 1
                return
            gefunden[email] = (vor, nach)
        elif not any(gefunden[email]) and (vor or nach):
            gefunden[email] = (vor, nach)

    def kopf(eintrag: dict | None) -> None:
        adr = (eintrag or {}).get("emailAddress") or {}
        if adr.get("address"):
            aufnehmen(adr["address"], adr.get("name") or "")

    kopf(nachricht.get("from"))
    for feld in ("toRecipients", "ccRecipients"):
        for eintrag in nachricht.get(feld) or []:
            kopf(eintrag)

    text = _text_der_mail(nachricht)
    for name, adr in _NAME_UND_ADRESSE.findall(text):   # z. B. "Von: Max Muster <max@firma.de>"
        aufnehmen(adr, name)
    for adr in _EMAIL_IM_TEXT.findall(text):
        aufnehmen(adr)
    return gefunden, ignoriert


# ------------------------------------------------------------ Microsoft Graph

class Graph:
    """Minimaler Graph-Client (nur Standardbibliothek)."""

    def __init__(self, cfg: Einstellungen):
        self.cfg = cfg
        self._token = ""
        self._token_bis = 0.0

    def _anfrage(self, req: urllib.request.Request) -> dict:
        for versuch in range(3):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_SEKUNDEN) as antwort:
                    return json.loads(antwort.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                with exc:
                    if exc.code in (429, 503, 504) and versuch < 2:
                        time.sleep(_int(exc.headers.get("Retry-After"), 5, 1, 30))
                        continue
                    code = ""
                    try:
                        daten = json.loads(exc.read().decode("utf-8", "replace"))
                        fehler = daten.get("error")
                        code = fehler.get("code", "") if isinstance(fehler, dict) else str(fehler or "")
                    except Exception:
                        pass
                code = re.sub(r"[^A-Za-z0-9_.-]", "", code)[:60]
                raise PostfachFehler(f"Microsoft antwortet mit HTTP {exc.code} {code}".strip()) from None
            except (urllib.error.URLError, OSError, ValueError) as exc:
                raise PostfachFehler(f"Microsoft nicht erreichbar ({type(exc).__name__})") from None
        raise PostfachFehler("Microsoft antwortet nicht")

    def token(self) -> str:
        if self._token and time.time() < self._token_bis:
            return self._token
        daten = urllib.parse.urlencode({
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode()
        url = f"{self.cfg.login_url}/{urllib.parse.quote(self.cfg.tenant_id, safe='')}/oauth2/v2.0/token"
        antwort = self._anfrage(urllib.request.Request(url, data=daten, method="POST"))
        if "access_token" not in antwort:
            raise PostfachFehler("Anmeldung bei Microsoft fehlgeschlagen (kein Token)")
        self._token = antwort["access_token"]
        self._token_bis = time.time() + int(antwort.get("expires_in", 3600)) - 120
        return self._token

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token()}",
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        })
        return self._anfrage(req)

    def nachrichten(self, seit: datetime, maximal: int = MAX_MAILS_PRO_LAUF) -> list[dict]:
        """Mails im Posteingang ab `seit`, älteste zuerst."""
        parameter = urllib.parse.urlencode({
            "$select": "id,internetMessageId,subject,receivedDateTime,from,toRecipients,ccRecipients,body",
            "$filter": f"receivedDateTime ge {seit.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
            "$orderby": "receivedDateTime asc",
            "$top": "50",
        })
        url = (f"{self.cfg.graph_url}/users/{urllib.parse.quote(self.cfg.postfach, safe='@')}"
               f"/mailFolders/inbox/messages?{parameter}")
        ergebnis: list[dict] = []
        while url and len(ergebnis) < maximal:
            seite = self._get(url)
            ergebnis.extend(seite.get("value") or [])
            url = seite.get("@odata.nextLink") or ""
            if url and not url.startswith(self.cfg.graph_url + "/"):
                raise PostfachFehler("Unerwartete Weiterleitungsadresse von Microsoft")
        return ergebnis[:maximal]


# ------------------------------------------------------------ Abruf

@dataclass
class Ergebnis:
    mails: int = 0
    gefunden: int = 0
    neu: int = 0
    bekannt: int = 0
    gesperrt: int = 0
    ignoriert: int = 0
    backup: str = ""

    def text(self) -> str:
        if not self.mails:
            return "Keine neuen Mails."
        return (f"{self.mails} neue Mail(s) ausgewertet: {self.gefunden} Adressen gefunden, "
                f"{self.neu} neue Kontakte, {self.bekannt} schon vorhanden, "
                f"{self.gesperrt} auf der Sperrliste, {self.ignoriert} ignoriert (intern/System).")


def _mail_id(nachricht: dict) -> str:
    return clean_text(nachricht.get("internetMessageId") or nachricht.get("id") or "", 500)


def _iso(roh: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(roh).replace("Z", "+00:00"))
    except ValueError:
        return None


def abrufen(db_path, backup_dir, cfg: Einstellungen, benutzer: str = "Postfach",
            graph: Graph | None = None) -> Ergebnis:
    """Neue Mails holen und die Adressen übernehmen. Jede Mail in eigener Transaktion."""
    if not cfg.konfiguriert:
        raise PostfachFehler("Postfach ist nicht eingerichtet (VERTEILER_MAIL_* fehlen).")
    graph = graph or Graph(cfg)

    conn = db.connect(db_path)
    try:
        bekannt_ids = {r[0] for r in conn.execute("SELECT message_id FROM mail_eingang")}
        letzte = conn.execute("SELECT MAX(empfangen_am) FROM mail_eingang").fetchone()[0]
    finally:
        conn.close()
    letzte_dt = _iso(letzte) if letzte else None
    seit = (letzte_dt - timedelta(days=2) if letzte_dt
            else datetime.now(timezone.utc) - timedelta(days=cfg.tage_zurueck))

    neue = [m for m in graph.nachrichten(seit) if _mail_id(m) and _mail_id(m) not in bekannt_ids]
    ergebnis = Ergebnis()
    if not neue:
        return ergebnis
    pfad = db.backup(db_path, backup_dir)
    ergebnis.backup = str(pfad) if pfad else ""

    conn = db.connect(db_path)
    try:
        for m in neue:
            adressen, ignoriert = adressen_aus_mail(m, cfg)
            betreff = clean_text(m.get("subject") or "(ohne Betreff)", 200)
            zeilen = [{"email": e, "vorname": v, "nachname": n} for e, (v, n) in adressen.items()]
            with db.transaction(conn):
                cur = conn.execute(
                    "INSERT OR IGNORE INTO mail_eingang (message_id, empfangen_am, betreff, verarbeitet_am) "
                    "VALUES (?, ?, ?, ?)",
                    (_mail_id(m), clean_text(m.get("receivedDateTime"), 40), betreff, db.jetzt()))
                if cur.rowcount == 0:
                    continue  # parallel schon verarbeitet
                plan = imports.analysiere_kontakte(
                    conn, zeilen, {"email": "email", "vorname": "vorname", "nachname": "nachname"},
                    {"quelle": f"Postfach: {betreff[:100]}"}, "ergaenzen")
                imports.kontakte_schreiben(conn, plan)
                z = plan.zahlen()
                bekannt = z["dublette_bestand_aktualisiert"] + z["dublette_bestand_unveraendert"]
                n_ign = sum(ignoriert.values())
                conn.execute(
                    "UPDATE mail_eingang SET gefunden = ?, neu = ?, bekannt = ?, gesperrt = ?, ignoriert = ? "
                    "WHERE message_id = ?",
                    (len(zeilen), z["neu"], bekannt, z["gesperrt"], n_ign, _mail_id(m)))
                imports._log(conn, "postfach", f"Mail: {betreff}", z["neu"],
                             z["dublette_bestand_aktualisiert"], z["gesperrt"] + n_ign,
                             {**z, "ignoriert": ignoriert}, benutzer)
            ergebnis.mails += 1
            ergebnis.gefunden += len(zeilen)
            ergebnis.neu += z["neu"]
            ergebnis.bekannt += bekannt
            ergebnis.gesperrt += z["gesperrt"]
            ergebnis.ignoriert += n_ign
    finally:
        conn.close()
    return ergebnis


def letzte_mails(conn, limit: int = 100) -> list:
    return conn.execute("SELECT empfangen_am, betreff, gefunden, neu, bekannt, gesperrt, ignoriert, "
                        "verarbeitet_am FROM mail_eingang ORDER BY empfangen_am DESC LIMIT ?",
                        (int(limit),)).fetchall()


# ------------------------------------------------------------ Dauerbetrieb

def dauerbetrieb() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    db_path = os.environ.get("VERTEILER_DB", "verteiler.db")
    backup_dir = os.environ.get("VERTEILER_BACKUPS", "backups")
    cfg = einstellungen_aus_env()
    if not cfg.konfiguriert:
        LOG.warning("Postfach nicht eingerichtet (VERTEILER_MAIL_* in deploy/.env) – Abruf ruht.")
        while True:
            time.sleep(3600)
    LOG.info("Postfach-Abruf aktiv: %s, alle %s Minuten, intern: %s",
             cfg.postfach, cfg.intervall_min, ", ".join(cfg.intern_domains) or "-")
    graph = Graph(cfg)
    while True:
        try:
            LOG.info(abrufen(db_path, backup_dir, cfg, graph=graph).text())
        except PostfachFehler as exc:
            LOG.error("Abruf fehlgeschlagen: %s", exc)
        except Exception as exc:  # nie abstürzen, beim nächsten Intervall erneut
            LOG.error("Unerwarteter Fehler beim Abruf: %s", type(exc).__name__)
        time.sleep(cfg.intervall_min * 60)


if __name__ == "__main__":
    dauerbetrieb()
