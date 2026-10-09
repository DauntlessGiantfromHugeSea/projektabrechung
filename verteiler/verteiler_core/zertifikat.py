"""
Anmeldung des Postfach-Abrufs bei Microsoft per Zertifikat.

Statt eines Benutzer-Logins oder eines Client-Geheimnisses meldet sich der
Verteiler als eigene App an (Client-Credentials) und beweist seine Identität
mit einem Zertifikat. Das Verfahren:

1. Im Backend erzeugt der Verteiler ein Schlüsselpaar mit selbstsigniertem
   Zertifikat. Der private Schlüssel verlässt den Server nie. Er liegt in
   /data/postfach_zertifikat.key (Rechte 0600), nicht in der Datenbank und
   nicht in den Backups.
2. Der öffentliche Teil (.cer) wird in Entra bei der App-Registrierung unter
   „Zertifikate & Geheimnisse“ hochgeladen.
3. Für jede Anmeldung signiert der Verteiler eine kurzlebige Bestätigung
   (JWT, RS256, 10 Minuten gültig) und tauscht sie bei Microsoft gegen ein
   Zugriffstoken.

Welche Postfächer die App lesen darf, legt Exchange fest. Die Befehle dafür
zeigt die Seite „Postfach“ mit den richtigen Werten an. Empfohlen ist
„Application Mail.Read“ per RBAC, beschränkt auf genau das Verteiler-Postfach.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

TIMEOUT_SEKUNDEN = 30
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class ZertifikatFehler(RuntimeError):
    """Meldung ohne Geheimnisse, für Nutzer gedacht."""


def _b64url(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).rstrip(b"=").decode()


def _ordner() -> Path:
    if os.environ.get("VERTEILER_ZERT_ORDNER"):
        return Path(os.environ["VERTEILER_ZERT_ORDNER"])
    return Path(os.environ.get("VERTEILER_DB", "verteiler.db")).resolve().parent


@dataclass
class Dateien:
    schluessel: Path
    zertifikat: Path

    @classmethod
    def standard(cls) -> "Dateien":
        o = _ordner()
        return cls(o / "postfach_zertifikat.key", o / "postfach_zertifikat.pem")

    def vorhanden(self) -> bool:
        return self.schluessel.exists() and self.zertifikat.exists()


@dataclass
class Info:
    fingerabdruck: str      # SHA-1, wie Entra ihn anzeigt ("Fingerabdruck")
    gueltig_ab: str
    gueltig_bis: str
    name: str

    @property
    def laeuft_bald_ab(self) -> bool:
        return datetime.fromisoformat(self.gueltig_bis) - datetime.now(timezone.utc) < timedelta(days=60)


def _laden_zert(dateien: Dateien) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(dateien.zertifikat.read_bytes())
    except (OSError, ValueError) as exc:
        raise ZertifikatFehler("Zertifikat nicht lesbar – bitte neu erzeugen.") from exc


def info(dateien: Dateien | None = None) -> Info | None:
    dateien = dateien or Dateien.standard()
    if not dateien.vorhanden():
        return None
    z = _laden_zert(dateien)
    return Info(
        fingerabdruck=z.fingerprint(hashes.SHA1()).hex().upper(),  # noqa: S303 – von Microsoft so verlangt
        gueltig_ab=z.not_valid_before_utc.isoformat(),
        gueltig_bis=z.not_valid_after_utc.isoformat(),
        name=z.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
    )


def erzeugen(dateien: Dateien | None = None, jahre: int = 2, ersetzen: bool = False) -> Info:
    """Neues Schlüsselpaar + selbstsigniertes Zertifikat anlegen."""
    dateien = dateien or Dateien.standard()
    if dateien.vorhanden() and not ersetzen:
        raise ZertifikatFehler("Es gibt bereits ein Zertifikat. Zum Ersetzen ausdrücklich „neu erzeugen“ wählen.")
    schluessel = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FBE Verteiler Postfach")])
    jetzt = datetime.now(timezone.utc)
    zert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(schluessel.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - timedelta(minutes=5))
            .not_valid_after(jetzt + timedelta(days=365 * max(1, min(3, jahre))))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(schluessel, hashes.SHA256()))
    dateien.schluessel.parent.mkdir(parents=True, exist_ok=True)
    _schreiben(dateien.schluessel, schluessel.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), 0o600)
    _schreiben(dateien.zertifikat, zert.public_bytes(serialization.Encoding.PEM), 0o644)
    return info(dateien)


def _schreiben(pfad: Path, daten: bytes, rechte: int) -> None:
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, rechte)
    with os.fdopen(fd, "wb") as f:
        f.write(daten)
    os.chmod(tmp, rechte)
    os.replace(tmp, pfad)


def oeffentlicher_teil(dateien: Dateien | None = None) -> bytes:
    """Nur das Zertifikat (öffentlich) zum Hochladen in Entra – nie den Schlüssel."""
    dateien = dateien or Dateien.standard()
    return _laden_zert(dateien).public_bytes(serialization.Encoding.PEM)


def loeschen(dateien: Dateien | None = None) -> None:
    dateien = dateien or Dateien.standard()
    for p in (dateien.schluessel, dateien.zertifikat):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ------------------------------------------------------------ Anmeldung

@dataclass
class AppZugang:
    tenant_id: str = ""
    client_id: str = ""
    dateien: Dateien | None = None
    login_url: str = "https://login.microsoftonline.com"
    graph_url: str = "https://graph.microsoft.com/v1.0"

    def __post_init__(self):
        self.dateien = self.dateien or Dateien.standard()

    def fehlend(self) -> list[str]:
        f = []
        if not _GUID.match(self.tenant_id or ""):
            f.append("Verzeichnis-ID (Mandant) als GUID")
        if not _GUID.match(self.client_id or ""):
            f.append("Anwendungs-ID (Client) als GUID")
        if not self.dateien.vorhanden():
            f.append("Zertifikat")
        return f

    @property
    def konfiguriert(self) -> bool:
        return not self.fehlend()


def client_assertion(zugang: AppZugang, jetzt: float | None = None) -> str:
    """Signierte Bestätigung (JWT) für den Token-Endpunkt, 10 Minuten gültig."""
    try:
        schluessel = serialization.load_pem_private_key(zugang.dateien.schluessel.read_bytes(), password=None)
    except (OSError, ValueError) as exc:
        raise ZertifikatFehler("Privater Schlüssel nicht lesbar – Zertifikat neu erzeugen.") from exc
    zert = _laden_zert(zugang.dateien)
    jetzt = int(jetzt or time.time())
    kopf = {"alg": "RS256", "typ": "JWT",
            "x5t": _b64url(zert.fingerprint(hashes.SHA1())),           # noqa: S303
            "x5t#S256": _b64url(zert.fingerprint(hashes.SHA256()))}
    inhalt = {"aud": f"{zugang.login_url}/{zugang.tenant_id}/oauth2/v2.0/token",
              "iss": zugang.client_id, "sub": zugang.client_id, "jti": str(uuid.uuid4()),
              "nbf": jetzt - 60, "iat": jetzt, "exp": jetzt + 600}
    signiert = (_b64url(json.dumps(kopf, separators=(",", ":")).encode()) + "."
                + _b64url(json.dumps(inhalt, separators=(",", ":")).encode()))
    signatur = schluessel.sign(signiert.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signiert + "." + _b64url(signatur)


def app_token(zugang: AppZugang) -> tuple[str, int]:
    """Zugriffstoken für Microsoft Graph (nur für diese App, keine Benutzerrechte)."""
    if not zugang.konfiguriert:
        raise ZertifikatFehler("Zertifikats-Anmeldung unvollständig: " + ", ".join(zugang.fehlend()) + ".")
    daten = urllib.parse.urlencode({
        "client_id": zugang.client_id,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": client_assertion(zugang),
    }).encode()
    req = urllib.request.Request(f"{zugang.login_url}/{zugang.tenant_id}/oauth2/v2.0/token", data=daten,
                                 method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEKUNDEN) as antwort:
            tok = json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with exc:
            code, beschreibung = "", ""
            try:
                d = json.loads(exc.read().decode("utf-8", "replace"))
                code = str(d.get("error", ""))
                beschreibung = str(d.get("error_description", ""))
            except Exception:
                pass
        code = re.sub(r"[^A-Za-z0-9_.-]", "", code)[:60]
        aadsts = re.search(r"AADSTS\d+", beschreibung)
        hinweis = {
            "AADSTS700027": "Zertifikat ist bei der App in Entra nicht (mehr) hinterlegt",
            "AADSTS700016": "Anwendungs-ID nicht gefunden – Client-ID und Mandant prüfen",
            "AADSTS90002": "Mandant nicht gefunden – Verzeichnis-ID prüfen",
            "AADSTS7000215": "ungültige Anmeldedaten",
        }.get(aadsts.group(0) if aadsts else "", "")
        raise ZertifikatFehler(
            f"Microsoft lehnt die Anmeldung ab (HTTP {exc.code} {code}"
            + (f", {aadsts.group(0)}" if aadsts else "") + ")" + (f": {hinweis}" if hinweis else "")) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ZertifikatFehler(f"Microsoft nicht erreichbar ({type(exc).__name__})") from None
    if not tok.get("access_token"):
        raise ZertifikatFehler("Microsoft hat kein Zugriffstoken geliefert.")
    return tok["access_token"], int(tok.get("expires_in", 3600))


def powershell_befehle(client_id: str, postfach: str) -> str:
    """Exchange-Befehle, die der App Lesezugriff auf GENAU dieses Postfach geben."""
    cid = client_id if _GUID.match(client_id or "") else "<Anwendungs-ID>"
    pf = postfach or "verteiler@fb-eng.de"
    return (
        "Connect-ExchangeOnline\n"
        f'New-ServicePrincipal -AppId {cid} -ObjectId <Objekt-ID der Unternehmensanwendung> '
        '-DisplayName "FBE Verteiler Postfach"\n'
        f"New-ManagementScope -Name \"Verteiler-Postfach\" -RecipientRestrictionFilter "
        f"\"PrimarySmtpAddress -eq '{pf}'\"\n"
        f'New-ManagementRoleAssignment -App {cid} -Role "Application Mail.Read" '
        '-CustomResourceScope "Verteiler-Postfach"\n'
        f"# Kontrolle: muss InScope = True zeigen\n"
        f"Test-ServicePrincipalAuthorization -Identity {cid} -Resource {pf}"
    )
