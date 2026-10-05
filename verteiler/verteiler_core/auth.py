"""
Anmeldung im Server-Betrieb über das FBE Intranet.

Auf dem Server läuft der Verteiler unter https://intern.rss-fb.com/verteiler/.
Der Caddy-Dienst des Servers prüft jede Anfrage per forward_auth gegen das
Intranet. Zusätzlich
prüft die App selbst bei jedem Seitenaufbau noch einmal: Sie schickt das
Cookie des Browsers an den Intranet-Endpunkt /auth/verteiler. Nur wenn dieser
mit 204 antwortet (angemeldeter, aktiver Administrator inkl. 2FA), werden
Daten angezeigt. So bleibt der Verteiler auch dann geschützt, wenn jemand
den Container im Docker-Netz direkt anspricht.

Lokal (Windows, start.bat) ist VERTEILER_AUTH_URL nicht gesetzt; dort schützt
die Bindung an localhost. Im Docker-Image ist VERTEILER_MODUS=server gesetzt:
Fehlt dann die Auth-URL, verweigert die App den Zugriff (fail closed).
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

TIMEOUT_SEKUNDEN = 5


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # 3xx nicht folgen -> wird als "nicht angemeldet" gewertet


_OPENER = urllib.request.build_opener(_KeineWeiterleitung)


@dataclass
class Ergebnis:
    erlaubt: bool
    benutzer: str = ""
    grund: str = ""          # "", "nicht_angemeldet", "kein_recht", "fehler", "nicht_konfiguriert"


def server_modus() -> bool:
    return os.environ.get("VERTEILER_MODUS", "").strip().lower() == "server"


def auth_url() -> str:
    return os.environ.get("VERTEILER_AUTH_URL", "").strip()


def pruefen(cookie_header: str, url: str | None = None) -> Ergebnis:
    """Fragt das Intranet, ob das Cookie zu einem berechtigten Nutzer gehört."""
    url = auth_url() if url is None else url
    if not url:
        if server_modus():
            return Ergebnis(False, grund="nicht_konfiguriert")
        return Ergebnis(True, benutzer="")  # lokaler Betrieb
    if not cookie_header:
        return Ergebnis(False, grund="nicht_angemeldet")
    anfrage = urllib.request.Request(url, headers={"Cookie": cookie_header, "Accept": "*/*"})
    try:
        with _OPENER.open(anfrage, timeout=TIMEOUT_SEKUNDEN) as antwort:
            status = antwort.status
            benutzer = antwort.headers.get("X-Verteiler-User", "")
    except urllib.error.HTTPError as exc:
        status, benutzer = exc.code, ""
        exc.close()
    except (urllib.error.URLError, OSError, ValueError):
        return Ergebnis(False, grund="fehler")
    if status == 204:
        return Ergebnis(True, benutzer=urllib.parse.unquote(benutzer))
    if status == 403:
        return Ergebnis(False, grund="kein_recht")
    return Ergebnis(False, grund="nicht_angemeldet")
