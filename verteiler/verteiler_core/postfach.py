"""
Kontakte aus einem Microsoft-365-Postfach übernehmen.

Jede Mail, die im eingestellten Postfach ankommt (meist weitergeleitet oder in
CC gesetzt), wird ausgewertet. Alle E-Mail-Adressen aus Absender, Empfänger
(An), CC und dem Mailtext werden als Kontakt übernommen. Es gelten dieselben
Regeln wie beim Listen-Import: Syntaxprüfung, Sperrliste wird beachtet,
Dubletten werden zusammengeführt.

Nicht übernommen werden:
- Adressen der eigenen Domains (Kolleg:innen), Standard: Domain des Postfachs
- das Postfach selbst
- Systemadressen (noreply, mailer-daemon, postmaster, bounce …)

Verbindung: Im Backend (Seite „Postfach“) klickt ein Admin auf „Mit Microsoft
verbinden“ und meldet sich mit seinem Microsoft-Konto an. Genutzt wird die
App-Registrierung des Intranets (MS_CLIENT_ID/MS_CLIENT_SECRET/MS_TENANT_ID aus
deploy/.env) mit der eigenen Umleitungs-URI https://intern.rss-fb.com/verteiler/.
Der Login des Intranets bleibt unverändert. Angefragt wird nur Leserecht
(Mail.Read, Mail.Read.Shared für freigegebene Postfächer). Das Tool
verschiebt, löscht oder sendet keine Mails.

Das Refresh-Token liegt in einer eigenen Datei (Rechte 0600, Standard
/data/postfach_token.json) und damit NICHT in der Datenbank und nicht in den
Backups. Es wird nie angezeigt oder protokolliert.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, imports, zertifikat
from .normalize import clean_text, email_fehler, normalize_email

LOG = logging.getLogger("verteiler.postfach")

MAX_MAILS_PRO_LAUF = 200
MAX_ADRESSEN_PRO_MAIL = 1000
TIMEOUT_SEKUNDEN = 30
STATE_GUELTIG = timedelta(minutes=15)
SCOPES = "offline_access openid email User.Read Mail.Read Mail.Read.Shared"
STANDARD_REDIRECT = "https://intern.rss-fb.com/verteiler/"


class PostfachFehler(RuntimeError):
    """Fehler beim Verbinden/Abruf (Meldung ohne Geheimnisse, für Nutzer gedacht)."""


def _int(wert: str | None, standard: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(str(wert).strip())))
    except (TypeError, ValueError):
        return standard


# ------------------------------------------------------------ Konfiguration

@dataclass
class MsApp:
    """Die bestehende Microsoft-App-Registrierung des Intranets."""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    tenant_id: str = ""
    redirect_uri: str = STANDARD_REDIRECT
    login_url: str = "https://login.microsoftonline.com"
    graph_url: str = "https://graph.microsoft.com/v1.0"

    @property
    def konfiguriert(self) -> bool:
        return all((self.client_id, self.client_secret, self.tenant_id, self.redirect_uri))


def app_aus_env(env: dict | None = None) -> MsApp:
    env = os.environ if env is None else env
    return MsApp(
        client_id=env.get("MS_CLIENT_ID", "").strip(),
        client_secret=env.get("MS_CLIENT_SECRET", "").strip(),
        tenant_id=env.get("MS_TENANT_ID", "").strip(),
        redirect_uri=(env.get("VERTEILER_MS_REDIRECT_URI") or STANDARD_REDIRECT).strip(),
    )


MODI = ("zertifikat", "login")


@dataclass
class Einstellungen:
    postfach: str = ""
    intern_domains: tuple[str, ...] = ()
    aktiv: bool = False
    tage_zurueck: int = 7
    modus: str = "zertifikat"          # "zertifikat" (App-only) oder "login" (delegiert)
    zert_tenant_id: str = ""
    zert_client_id: str = ""

    @property
    def bereit(self) -> bool:
        return bool(self.aktiv and self.postfach)


def _domains(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(d.strip().lower().lstrip("@") for d in re.split(r"[,;\s]+", text or "")
                               if d.strip()))


def einstellungen_lesen(conn) -> Einstellungen:
    postfach = normalize_email(db.einstellung(conn, "postfach_adresse", ""))
    if email_fehler(postfach):
        postfach = ""
    intern = _domains(db.einstellung(conn, "postfach_intern_domains", ""))
    if not intern and postfach:
        intern = (postfach.split("@")[1],)
    modus = db.einstellung(conn, "postfach_modus", "zertifikat")
    return Einstellungen(
        postfach=postfach, intern_domains=intern,
        aktiv=db.einstellung(conn, "postfach_aktiv", "0") == "1",
        tage_zurueck=_int(os.environ.get("VERTEILER_MAIL_TAGE_ZURUECK"), 7, 0, 365),
        modus=modus if modus in MODI else "zertifikat",
        zert_tenant_id=db.einstellung(conn, "zert_tenant_id", ""),
        zert_client_id=db.einstellung(conn, "zert_client_id", ""),
    )


def zert_zugang(cfg: Einstellungen) -> "zertifikat.AppZugang":
    return zertifikat.AppZugang(tenant_id=cfg.zert_tenant_id, client_id=cfg.zert_client_id)


def zertifikat_einstellungen_speichern(db_path, modus: str, tenant_id: str, client_id: str,
                                       benutzer: str = "") -> None:
    if modus not in MODI:
        raise PostfachFehler("Unbekannte Anmeldeart.")
    tenant_id, client_id = (tenant_id or "").strip(), (client_id or "").strip()
    for wert, name in ((tenant_id, "Verzeichnis-ID"), (client_id, "Anwendungs-ID")):
        if wert and not zertifikat._GUID.match(wert):
            raise PostfachFehler(f"{name} muss eine GUID sein (z. B. 1a2b3c4d-…).")
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            db.einstellungen_setzen(conn, {"postfach_modus": modus, "zert_tenant_id": tenant_id.lower(),
                                           "zert_client_id": client_id.lower()}, benutzer)
    finally:
        conn.close()


def einstellungen_speichern(db_path, postfach: str, intern_domains: str, aktiv: bool,
                            benutzer: str = "") -> None:
    adresse = normalize_email(postfach)
    if adresse and email_fehler(adresse):
        raise PostfachFehler("Die Postfach-Adresse ist ungültig.")
    domains = _domains(intern_domains)
    for d in domains:
        if email_fehler("x@" + d):
            raise PostfachFehler(f"Ungültige Domain: {d}")
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            db.einstellungen_setzen(conn, {"postfach_adresse": adresse,
                                           "postfach_intern_domains": ", ".join(domains),
                                           "postfach_aktiv": "1" if (aktiv and adresse) else "0"}, benutzer)
    finally:
        conn.close()


# ------------------------------------------------------------ Token-Datei

def token_pfad() -> Path:
    if os.environ.get("VERTEILER_TOKEN_DATEI"):
        return Path(os.environ["VERTEILER_TOKEN_DATEI"])
    return Path(os.environ.get("VERTEILER_DB", "verteiler.db")).resolve().parent / "postfach_token.json"


class TokenSpeicher:
    def __init__(self, pfad: Path | str | None = None):
        self.pfad = Path(pfad) if pfad else token_pfad()

    def laden(self) -> dict | None:
        try:
            daten = json.loads(self.pfad.read_text(encoding="utf-8"))
            return daten if isinstance(daten, dict) and daten.get("refresh_token") else None
        except (OSError, ValueError):
            return None

    def speichern(self, daten: dict) -> None:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.pfad.with_name(self.pfad.name + f".{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.pfad)

    def loeschen(self) -> None:
        try:
            self.pfad.unlink()
        except FileNotFoundError:
            pass

    def status(self) -> dict:
        """Nur unkritische Angaben für die Anzeige (nie das Token)."""
        d = self.laden() or {}
        return {k: d.get(k, "") for k in ("konto", "verbunden_am", "verbunden_von", "fehler")}


# ------------------------------------------------------------ OAuth (Verbinden)

def _token_anfrage(app: MsApp, felder: dict) -> dict:
    daten = urllib.parse.urlencode({"client_id": app.client_id, "client_secret": app.client_secret,
                                    "scope": SCOPES, **felder}).encode()
    url = f"{app.login_url}/{urllib.parse.quote(app.tenant_id, safe='')}/oauth2/v2.0/token"
    req = urllib.request.Request(url, data=daten, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEKUNDEN) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with exc:
            code = ""
            try:
                code = str(json.loads(exc.read().decode("utf-8", "replace")).get("error", ""))
            except Exception:
                pass
        code = re.sub(r"[^A-Za-z0-9_.-]", "", code)[:60]
        if code == "invalid_grant":
            raise PostfachFehler("Die Verbindung zu Microsoft ist abgelaufen oder wurde widerrufen – "
                                 "bitte unter „Postfach“ neu verbinden.") from None
        raise PostfachFehler(f"Microsoft-Anmeldung fehlgeschlagen (HTTP {exc.code} {code})".strip()) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PostfachFehler(f"Microsoft nicht erreichbar ({type(exc).__name__})") from None


def verbinden_url(db_path, app: MsApp, benutzer: str) -> str:
    """Startet „Mit Microsoft verbinden“: Einmal-State speichern, Login-URL liefern."""
    if not app.konfiguriert:
        raise PostfachFehler("Microsoft-Anmeldung ist nicht eingerichtet (MS_CLIENT_ID/MS_CLIENT_SECRET/"
                             "MS_TENANT_ID fehlen in deploy/.env).")
    grenze = (datetime.now() - STATE_GUELTIG).isoformat(sep=" ", timespec="seconds")
    noch_frisch = (datetime.now() - STATE_GUELTIG / 2).isoformat(sep=" ", timespec="seconds")
    wer = clean_text(benutzer, 200)
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            conn.execute("DELETE FROM oauth_state WHERE erstellt_am < ?", (grenze,))
            # Beim Neuladen der Seite denselben (noch frischen) State weiterverwenden
            row = conn.execute("SELECT state FROM oauth_state WHERE benutzer = ? AND erstellt_am >= ? "
                               "ORDER BY erstellt_am DESC LIMIT 1", (wer, noch_frisch)).fetchone()
            state = row[0] if row else "vt" + secrets.token_urlsafe(32)
            if not row:
                conn.execute("INSERT INTO oauth_state (state, benutzer, erstellt_am) VALUES (?, ?, ?)",
                             (state, wer, db.jetzt()))
    finally:
        conn.close()
    return (f"{app.login_url}/{urllib.parse.quote(app.tenant_id, safe='')}/oauth2/v2.0/authorize?"
            + urllib.parse.urlencode({
                "client_id": app.client_id, "response_type": "code", "redirect_uri": app.redirect_uri,
                "response_mode": "query", "scope": SCOPES, "state": state, "prompt": "select_account",
            }))


def verbindung_abschliessen(db_path, app: MsApp, speicher: TokenSpeicher, code: str, state: str,
                            benutzer: str) -> str:
    """Rücksprung von Microsoft: State prüfen (einmalig, 15 Min., gleicher Nutzer), Code einlösen."""
    state = str(state or "")[:200]
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            row = conn.execute("SELECT benutzer, erstellt_am FROM oauth_state WHERE state = ?",
                               (state,)).fetchone()
            conn.execute("DELETE FROM oauth_state WHERE state = ?", (state,))
    finally:
        conn.close()
    if row is None or not state.startswith("vt"):
        raise PostfachFehler("Ungültiger oder bereits benutzter Verbindungsversuch – bitte neu starten.")
    if datetime.now() - datetime.fromisoformat(row["erstellt_am"]) > STATE_GUELTIG:
        raise PostfachFehler("Der Verbindungsversuch ist abgelaufen – bitte neu starten.")
    if row["benutzer"] and row["benutzer"] != clean_text(benutzer, 200):
        raise PostfachFehler("Der Verbindungsversuch gehört zu einem anderen Benutzer.")
    if not code:
        raise PostfachFehler("Microsoft hat keinen Code geliefert.")

    tok = _token_anfrage(app, {"grant_type": "authorization_code", "code": code[:4000],
                               "redirect_uri": app.redirect_uri})
    if not tok.get("refresh_token") or not tok.get("access_token"):
        raise PostfachFehler("Microsoft hat keinen dauerhaften Zugang erteilt (offline_access fehlt).")
    konto = ""
    try:
        req = urllib.request.Request(f"{app.graph_url}/me?$select=mail,userPrincipalName",
                                     headers={"Authorization": f"Bearer {tok['access_token']}"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEKUNDEN) as antwort:
            me = json.loads(antwort.read().decode("utf-8"))
        konto = normalize_email(me.get("mail") or me.get("userPrincipalName") or "")
    except (urllib.error.URLError, OSError, ValueError):
        pass
    speicher.speichern({"refresh_token": tok["refresh_token"], "konto": konto,
                        "verbunden_am": db.jetzt(), "verbunden_von": clean_text(benutzer, 200), "fehler": ""})

    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            if not db.einstellung(conn, "postfach_adresse", "") and konto and not email_fehler(konto):
                db.einstellungen_setzen(conn, {"postfach_adresse": konto}, benutzer)
            imports._log(conn, "postfach_verbunden", "", 0, 0, 0, {"konto": konto}, benutzer)
    finally:
        conn.close()
    return konto


def trennen(db_path, speicher: TokenSpeicher, benutzer: str = "") -> None:
    speicher.loeschen()
    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            db.einstellungen_setzen(conn, {"postfach_aktiv": "0"}, benutzer)
            imports._log(conn, "postfach_getrennt", "", 0, 0, 0, {}, benutzer)
    finally:
        conn.close()


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

class ZertifikatQuelle:
    """Zugriffstoken per Zertifikat (App-only)."""

    def __init__(self, zugang: "zertifikat.AppZugang"):
        self.zugang = zugang

    def hole(self) -> tuple[str, int]:
        try:
            return zertifikat.app_token(self.zugang)
        except zertifikat.ZertifikatFehler as exc:
            raise PostfachFehler(str(exc)) from None


class Graph:
    """Minimaler Graph-Client. Token per Zertifikat oder per Refresh-Token des verbundenen Kontos."""

    def __init__(self, app: MsApp, speicher: TokenSpeicher | None = None, quelle: ZertifikatQuelle | None = None):
        self.app = app
        self.speicher = speicher
        self.quelle = quelle
        self._token = ""
        self._token_bis = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._token_bis:
            return self._token
        if self.quelle is not None:
            self._token, gueltig = self.quelle.hole()
            self._token_bis = time.time() + gueltig - 120
            return self._token
        gespeichert = self.speicher.laden() if self.speicher else None
        if not gespeichert:
            raise PostfachFehler("Kein Postfach verbunden – unter „Postfach“ mit Microsoft verbinden.")
        try:
            tok = _token_anfrage(self.app, {"grant_type": "refresh_token",
                                            "refresh_token": gespeichert["refresh_token"]})
        except PostfachFehler as exc:
            self.speicher.speichern({**gespeichert, "fehler": str(exc)[:200]})
            raise
        if not tok.get("access_token"):
            raise PostfachFehler("Microsoft hat kein Zugriffstoken geliefert.")
        # Microsoft tauscht Refresh-Tokens aus – immer das neueste aufheben.
        self.speicher.speichern({**gespeichert, "refresh_token": tok.get("refresh_token") or
                                 gespeichert["refresh_token"], "fehler": ""})
        self._token = tok["access_token"]
        self._token_bis = time.time() + int(tok.get("expires_in", 3600)) - 120
        return self._token

    def _get(self, url: str) -> dict:
        for versuch in range(3):
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self.token()}", "Accept": "application/json",
                "Prefer": 'outlook.body-content-type="text"'})
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
                        fehler = json.loads(exc.read().decode("utf-8", "replace")).get("error")
                        code = fehler.get("code", "") if isinstance(fehler, dict) else str(fehler or "")
                    except Exception:
                        pass
                code = re.sub(r"[^A-Za-z0-9_.-]", "", code)[:60]
                if exc.code in (403, 404):
                    raise PostfachFehler(
                        f"Kein Zugriff auf das Postfach (HTTP {exc.code} {code}). Bei Zertifikat: Wurde der "
                        "Exchange-Befehl für dieses Postfach ausgeführt (kann bis zu 1 Stunde dauern)? "
                        "Bei Microsoft-Login: Hat das verbundene Konto Vollzugriff?") from None
                raise PostfachFehler(f"Microsoft antwortet mit HTTP {exc.code} {code}".strip()) from None
            except (urllib.error.URLError, OSError, ValueError) as exc:
                raise PostfachFehler(f"Microsoft nicht erreichbar ({type(exc).__name__})") from None
        raise PostfachFehler("Microsoft antwortet nicht")

    def nachrichten(self, postfach: str, seit: datetime, maximal: int = MAX_MAILS_PRO_LAUF) -> list[dict]:
        """Mails im Posteingang ab `seit`, älteste zuerst."""
        parameter = urllib.parse.urlencode({
            "$select": "id,internetMessageId,subject,receivedDateTime,from,toRecipients,ccRecipients,body",
            "$filter": f"receivedDateTime ge {seit.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
            "$orderby": "receivedDateTime asc",
            "$top": "50",
        })
        url = (f"{self.app.graph_url}/users/{urllib.parse.quote(postfach, safe='@')}"
               f"/mailFolders/inbox/messages?{parameter}")
        ergebnis: list[dict] = []
        while url and len(ergebnis) < maximal:
            seite = self._get(url)
            ergebnis.extend(seite.get("value") or [])
            url = seite.get("@odata.nextLink") or ""
            if url and not url.startswith(self.app.graph_url + "/"):
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


def graph_fuer(cfg: Einstellungen, app: MsApp, speicher: TokenSpeicher,
               zugang: "zertifikat.AppZugang | None" = None) -> Graph:
    """Graph-Client passend zur eingestellten Anmeldeart."""
    if cfg.modus == "zertifikat":
        zugang = zugang or zert_zugang(cfg)
        if not zugang.konfiguriert:
            raise PostfachFehler("Zertifikats-Anmeldung unvollständig: " + ", ".join(zugang.fehlend()) + ".")
        return Graph(MsApp(graph_url=zugang.graph_url), quelle=ZertifikatQuelle(zugang))
    if not speicher.laden():
        raise PostfachFehler("Kein Postfach verbunden – unter „Postfach“ mit Microsoft verbinden.")
    return Graph(app, speicher)


def verbindung_testen(db_path, app: MsApp | None = None, speicher: TokenSpeicher | None = None,
                      zugang: "zertifikat.AppZugang | None" = None) -> str:
    """Anmelden und den Posteingang des eingestellten Postfachs öffnen (liest keine Mails)."""
    conn = db.connect(db_path)
    try:
        cfg = einstellungen_lesen(conn)
    finally:
        conn.close()
    if not cfg.postfach:
        raise PostfachFehler("Bitte zuerst die Postfach-Adresse eintragen.")
    graph = graph_fuer(cfg, app or app_aus_env(), speicher or TokenSpeicher(), zugang)
    ordner = graph._get(f"{graph.app.graph_url}/users/{urllib.parse.quote(cfg.postfach, safe='@')}"
                        "/mailFolders/inbox?$select=totalItemCount")
    return (f"Verbindung klappt: Posteingang von {cfg.postfach} ist lesbar "
            f"({int(ordner.get('totalItemCount') or 0)} Mails).")


def abrufen(db_path, backup_dir, app: MsApp | None = None, speicher: TokenSpeicher | None = None,
            benutzer: str = "Postfach", graph: Graph | None = None,
            nur_wenn_aktiv: bool = False, zugang: "zertifikat.AppZugang | None" = None) -> Ergebnis:
    """Neue Mails holen und die Adressen übernehmen. Jede Mail in eigener Transaktion."""
    app = app or app_aus_env()
    speicher = speicher or TokenSpeicher()
    conn = db.connect(db_path)
    try:
        cfg = einstellungen_lesen(conn)
        bekannt_ids = {r[0] for r in conn.execute("SELECT message_id FROM mail_eingang")}
        letzte = conn.execute("SELECT MAX(empfangen_am) FROM mail_eingang").fetchone()[0]
    finally:
        conn.close()
    if not cfg.postfach:
        raise PostfachFehler("Bitte zuerst die Postfach-Adresse eintragen.")
    if nur_wenn_aktiv and not cfg.aktiv:
        return Ergebnis()
    if graph is None:
        graph = graph_fuer(cfg, app, speicher, zugang)

    letzte_dt = _iso(letzte) if letzte else None
    seit = (letzte_dt - timedelta(days=2) if letzte_dt
            else datetime.now(timezone.utc) - timedelta(days=cfg.tage_zurueck))
    neue = [m for m in graph.nachrichten(cfg.postfach, seit)
            if _mail_id(m) and _mail_id(m) not in bekannt_ids]
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
