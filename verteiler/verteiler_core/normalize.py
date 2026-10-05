"""
Normalisierung und Prüfung von Eingabewerten (E-Mail, Namen, Datum, Zahlen)
sowie die automatische Zuordnung von Spalten und Statuswerten.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

# Unsichtbare Zeichen, die beim Kopieren aus Excel/Outlook gern mitkommen.
_UNSICHTBAR = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)

# Bewusst strenger als RFC 5322: nur Zeichen, die in echten Adressen
# vorkommen und die Reach sicher akzeptiert. Exotische, aber formal gültige
# Adressen (z. B. mit "!" oder Anführungszeichen) gelten als ungültig.
_LOCAL_RE = re.compile(r"^[a-z0-9_%+'&-]+(\.[a-z0-9_%+'&-]+)*$")
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TLD_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")

_NAME_MAX = 200


def normalize_email(roh: object) -> str:
    """Kleinschreiben, trimmen, typischen Ballast entfernen.

    Beispiele: " Max.Muster@Firma.DE " -> "max.muster@firma.de",
    "Max Muster <max@firma.de>" -> "max@firma.de", "mailto:max@firma.de".
    """
    if roh is None:
        return ""
    s = str(roh).translate(_UNSICHTBAR).replace("\xa0", " ").strip()
    m = re.search(r"<([^<>]*)>\s*$", s)
    if m:
        s = m.group(1)
    s = s.strip().strip("\"'").strip()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    return s.strip().lower()


def email_fehler(email: str) -> str | None:
    """Prüft die Syntax einer bereits normalisierten Adresse.

    Gibt None zurück, wenn gültig, sonst einen kurzen Grund.
    """
    if not email:
        return "leer"
    if len(email) > 254:
        return "zu lang"
    if any(ch.isspace() for ch in email):
        return "enthält Leerzeichen"
    if email.count("@") != 1:
        return "kein oder mehrere @"
    local, domain = email.split("@")
    if not local or len(local) > 64:
        return "Teil vor @ leer oder zu lang"
    if not _LOCAL_RE.match(local):
        return "ungültige Zeichen vor @"
    if not domain or "." not in domain:
        return "Domain ohne Punkt"
    labels = domain.split(".")
    if any(not _LABEL_RE.match(lab) for lab in labels):
        return "ungültige Domain"
    if not _TLD_RE.match(labels[-1]):
        return "ungültige Top-Level-Domain"
    return None


def ist_gueltige_email(email: str) -> bool:
    return email_fehler(email) is None


def clean_text(roh: object, max_len: int = _NAME_MAX) -> str:
    """Text trimmen, Steuerzeichen entfernen, Leerraum zusammenfassen."""
    if roh is None:
        return ""
    s = str(roh).translate(_UNSICHTBAR).replace("\xa0", " ")
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch in " \t")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


_DATUM_FORMATE = (
    "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d", "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
)


def normalize_datum(roh: object) -> tuple[str, bool]:
    """Datum in ISO-Form (JJJJ-MM-TT) bringen.

    Rückgabe (wert, erkannt). Nicht erkannte Werte werden unverändert
    (bereinigt) zurückgegeben, damit keine Information verloren geht.
    Excel-Seriennummern (z. B. 45123) werden ebenfalls erkannt.
    """
    s = clean_text(roh, 40)
    if not s:
        return "", True
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        n = float(s)
        if 20000 <= n <= 80000:  # ca. 1954 bis 2119
            return (date(1899, 12, 30) + timedelta(days=int(n))).isoformat(), True
    for fmt in _DATUM_FORMATE:
        try:
            return datetime.strptime(s, fmt).date().isoformat(), True
        except ValueError:
            continue
    return s, False


_WAHR = {"ja", "yes", "true", "wahr", "x", "y", "j"}
_FALSCH = {"", "nein", "no", "false", "falsch", "-", "n", "0"}


def parse_anzahl(roh: object) -> tuple[int, bool]:
    """Öffnungen/Klicks als Zahl. Akzeptiert Zahlen und Ja/Nein.

    Rückgabe (wert, erkannt).
    """
    s = clean_text(roh, 40).lower()
    if s in _FALSCH:
        return 0, True
    if s in _WAHR:
        return 1, True
    s2 = s.replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d+([.,]0+)?", s2):
        return int(re.split(r"[.,]", s2)[0]), True
    if re.fullmatch(r"\d{1,3}([.]\d{3})+", s2):  # 1.234
        return int(s2.replace(".", "")), True
    return 0, False


def _schluessel(text: str) -> str:
    """Spaltennamen/Statuswerte vergleichbar machen."""
    s = clean_text(text, 200).lower()
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    return re.sub(r"[^a-z0-9]", "", s)


SPALTEN_SYNONYME: dict[str, tuple[str, ...]] = {
    "email": ("email", "emailadresse", "mail", "mailadresse", "emailaddress",
              "e_mail"),
    "vorname": ("vorname", "firstname", "first", "givenname"),
    "nachname": ("nachname", "lastname", "last", "surname", "familienname", "name"),
    "firma": ("firma", "unternehmen", "company", "organisation", "organization",
              "firmenname"),
    "quelle": ("quelle", "source", "herkunft"),
    "einwilligung_art": ("einwilligungart", "einwilligung", "consent", "consenttype",
                         "optin", "optinart", "einwilligungsart"),
    "einwilligung_datum": ("einwilligungdatum", "einwilligungsdatum", "consentdate",
                           "optindatum", "optindate", "datumeinwilligung", "subscribedat",
                           "subscriptiondate", "abonniertam", "angemeldetam", "optinat"),
    "abo_status": ("subscriptionstatus", "abostatus", "abonnementstatus", "newsletterstatus",
                   "subscription", "abonnement", "status"),
    "geoeffnet": ("geoeffnet", "oeffnungen", "opens", "opened", "open", "geoeffnetanzahl"),
    "geklickt": ("geklickt", "klicks", "clicks", "clicked", "click"),
    "status": ("status", "zustellstatus", "deliverystatus", "state"),
    "grund": ("grund", "reason", "sperrgrund"),
    "datum": ("datum", "date", "gesperrtam", "abgemeldetam"),
}


def spalte_erkennen(feld: str, kopfzeilen: list[str]) -> str | None:
    """Findet zu einem Feld die passende Spalte der Datei (oder None)."""
    synonyme = [_schluessel(s) for s in SPALTEN_SYNONYME.get(feld, (feld,))]
    keys = {k: _schluessel(k) for k in kopfzeilen}
    for syn in synonyme:  # Reihenfolge = Priorität
        for kopf, key in keys.items():
            if key == syn:
                return kopf
    return None


# Reach-Statuswerte -> internes Ziel. "beschwerde" ist kein Zustellstatus,
# sondern wird als "zugestellt" + Sperre (Grund beschwerde) verarbeitet.
REPORT_ZIELE = ("zugestellt", "unzustellbar", "soft_bounce", "nicht_zugestellt",
                "abgemeldet", "beschwerde")

_REPORT_STATUS: dict[str, str] = {
    # zugestellt
    "zugestellt": "zugestellt", "delivered": "zugestellt", "versendet": "zugestellt",
    "gesendet": "zugestellt", "sent": "zugestellt", "geoeffnet": "zugestellt",
    "opened": "zugestellt", "geklickt": "zugestellt", "clicked": "zugestellt",
    "erfolgreich": "zugestellt",
    # harter Bounce
    "unzustellbar": "unzustellbar", "hardbounce": "unzustellbar",
    "harterbounce": "unzustellbar", "bounced": "unzustellbar", "bounce": "unzustellbar",
    "undeliverable": "unzustellbar", "abgewiesen": "unzustellbar",
    # weicher Bounce
    "softbounce": "soft_bounce", "weicherbounce": "soft_bounce",
    "softbounced": "soft_bounce",
    # nicht zugestellt (nicht versendet / ausstehend)
    "nichtzugestellt": "nicht_zugestellt", "notdelivered": "nicht_zugestellt",
    "nichtgesendet": "nicht_zugestellt", "notsent": "nicht_zugestellt",
    "ausstehend": "nicht_zugestellt", "pending": "nicht_zugestellt",
    # abgemeldet
    "abgemeldet": "abgemeldet", "unsubscribed": "abgemeldet",
    "abbestellt": "abgemeldet", "austragung": "abgemeldet",
    # Beschwerde
    "beschwerde": "beschwerde", "spam": "beschwerde", "complaint": "beschwerde",
    "alsspammarkiert": "beschwerde", "spambeschwerde": "beschwerde",
}


def status_schluessel(roh: object) -> str:
    """Vergleichsschlüssel eines Statuswerts ("Soft-Bounce" -> "softbounce")."""
    return _schluessel(str(roh or ""))


def report_status_erkennen(roh: object) -> str | None:
    """Ordnet einen Reach-Statuswert automatisch zu (None = unbekannt)."""
    return _REPORT_STATUS.get(status_schluessel(roh))


# Abo-Status einer Kontaktliste (z. B. Reach-Export "Subscription Status").
# "ok" = darf angeschrieben werden, sonst Sperrgrund; leer = keine Angabe.
_ABO_STATUS: dict[str, str] = {
    "subscribed": "ok", "abonniert": "ok", "angemeldet": "ok", "aktiv": "ok", "active": "ok",
    "unsubscribed": "abgemeldet", "abgemeldet": "abgemeldet", "abbestellt": "abgemeldet",
    "optout": "abgemeldet", "ausgetragen": "abgemeldet",
    "bounced": "bounce_hart", "cleaned": "bounce_hart", "unzustellbar": "bounce_hart",
    "complained": "beschwerde", "spam": "beschwerde", "beschwerde": "beschwerde",
}


def abo_status_erkennen(roh: object) -> str | None:
    """'ok', ein Sperrgrund, '' (leer) oder None (unbekannter Wert, z. B. 'pending')."""
    key = _schluessel(str(roh or ""))
    if not key:
        return ""
    return _ABO_STATUS.get(key)


_SPERRGRUND: dict[str, str] = {
    "bouncehart": "bounce_hart", "hardbounce": "bounce_hart", "harterbounce": "bounce_hart",
    "unzustellbar": "bounce_hart", "bounce": "bounce_hart", "bounced": "bounce_hart",
    "abgemeldet": "abgemeldet", "unsubscribed": "abgemeldet", "abbestellt": "abgemeldet",
    "beschwerde": "beschwerde", "spam": "beschwerde", "complaint": "beschwerde",
    "manuell": "manuell", "manual": "manuell", "gesperrt": "manuell",
}


def sperrgrund_erkennen(roh: object) -> str | None:
    return _SPERRGRUND.get(_schluessel(str(roh or "")))


_FORMEL_START = ("=", "+", "-", "@", "\t", "\r")


def csv_sicher(wert: str) -> str:
    """Schutz vor CSV-/Formel-Injection beim Öffnen in Excel.

    Werte, die mit = + - @ beginnen, bekommen ein führendes Apostroph.
    Wird nur auf Freitextfelder (Namen) angewendet; E-Mail-Adressen sind durch
    die Syntaxprüfung bereits ungefährlich.
    """
    if wert and wert.startswith(_FORMEL_START):
        return "'" + wert
    return wert
