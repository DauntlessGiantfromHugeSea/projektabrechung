"""
Beispieldaten für Tests und zum Ausprobieren der Oberfläche.

Alle Adressen nutzen die reservierten Test-Domains example.com/.net/.org –
es sind keine echten Personen.

Direkt ausgeführt (python tests/beispieldaten.py) schreibt das Skript die
Dateien nach verteiler/beispieldaten/.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verteiler_core.fileio import schreibe_csv  # noqa: E402

VORNAMEN = ["Anna", "Ben", "Clara", "David", "Emma", "Felix", "Greta", "Hannes", "Ida", "Jonas",
            "Klara", "Lukas", "Mia", "Noah", "Olga", "Paul", "Rosa", "Simon", "Tara", "Ümit"]
NACHNAMEN = ["Abel", "Becker", "Cramer", "Dörr", "Eckert", "Fuchs", "Groß", "Hahn", "Imhof", "Jäger",
             "Kühn", "Lang", "Maier", "Neumann", "Otto", "Peters", "Quandt", "Rösch", "Schulz", "Thiel"]

# Bestand, der vor dem Testimport schon in der DB ist (10 Kontakte).
BESTAND = [{"E-Mail": f"bestand{i:02d}@example.org", "Vorname": VORNAMEN[i - 1],
            "Nachname": NACHNAMEN[i - 1], "Firma": "", "Quelle": "Altliste"} for i in range(1, 11)]

# Bereits gesperrte Adressen (20), z. B. aus der letzten Kampagne.
GESPERRT = [f"gesperrt{i:02d}@example.net" for i in range(1, 21)]

UNGUELTIG = [
    "kein-at-zeichen.example.com", "a@b", "doppel@@example.com", "max muster@example.com",
    "max@example", "max..muster@example.com", ".max@example.com", "max@-example.com",
    "max@example.c", "", "@example.com", "max@", "max@exa mple.com", "max@example..com",
    "mäx@example.com", "max(at)example.com", "max@example.com;moritz@example.com",
    "max@example_.com", "max@example.123", "max,muster@example.com",
]


def kontaktliste() -> list[dict[str, str]]:
    """80 Zeilen: je 20 neu, Dublette, ungültig, gesperrt (gemischt)."""
    zeilen: list[tuple[str, dict[str, str]]] = []
    for i in range(1, 21):  # 20 neue Adressen
        zeilen.append(("neu", {"E-Mail": f"neu{i:02d}@example.com", "Vorname": VORNAMEN[i - 1],
                               "Nachname": NACHNAMEN[i - 1], "Firma": f"Firma {i}",
                               "Einwilligung": "Webinar-Anmeldung", "Einwilligungsdatum": "15.03.2026"}))
    for i in range(1, 11):  # 10 Dubletten zum Bestand (andere Schreibweise, Firma ergänzt)
        zeilen.append(("dublette", {"E-Mail": f"  Bestand{i:02d}@EXAMPLE.org ", "Vorname": "",
                                    "Nachname": NACHNAMEN[i - 1], "Firma": f"Bestandsfirma {i}",
                                    "Einwilligung": "", "Einwilligungsdatum": ""}))
    for i in range(1, 11):  # 10 Dubletten innerhalb der Datei
        zeilen.append(("dublette", {"E-Mail": f"NEU{i:02d}@Example.com", "Vorname": "",
                                    "Nachname": "", "Firma": "", "Einwilligung": "",
                                    "Einwilligungsdatum": ""}))
    for adr in UNGUELTIG:
        zeilen.append(("ungueltig", {"E-Mail": adr, "Vorname": "X", "Nachname": "Y", "Firma": "",
                                     "Einwilligung": "", "Einwilligungsdatum": ""}))
    for i, adr in enumerate(GESPERRT, start=1):
        zeilen.append(("gesperrt", {"E-Mail": f" {adr.upper()} ", "Vorname": "Gesperrt",
                                    "Nachname": str(i), "Firma": "", "Einwilligung": "",
                                    "Einwilligungsdatum": ""}))
    # Reihenfolge so mischen, dass "neu" vor seiner Datei-Dublette steht.
    rnd = random.Random(42)
    neu = [z for z in zeilen if z[0] == "neu"]
    rest = [z for z in zeilen if z[0] != "neu"]
    rnd.shuffle(rest)
    gemischt = neu[:5] + rest[:10] + neu[5:] + rest[10:]
    return [z[1] for z in gemischt]


def als_csv(zeilen: list[dict[str, str]], trennzeichen: str = ";") -> bytes:
    kopf = list(zeilen[0].keys())
    return schreibe_csv(kopf, [[z[k] for k in kopf] for z in zeilen], trennzeichen)


def reach_report(eintraege: list[tuple[str, str, str, int, int, str]]) -> bytes:
    """eintraege: (email, vorname, nachname, geöffnet, geklickt, status)"""
    return schreibe_csv(["E-Mail", "Vorname", "Nachname", "Geöffnet", "Geklickt", "Status"],
                        [[e, v, n, str(o), str(k), s] for e, v, n, o, k, s in eintraege], ",")


def beispiel_report() -> bytes:
    """Ein Reach-Report mit allen Statusarten (für die Oberfläche)."""
    eintraege = []
    for i in range(1, 21):
        status = ("Zugestellt" if i <= 12 else "Unzustellbar" if i <= 15 else
                  "Soft-Bounce" if i <= 17 else "Abgemeldet" if i <= 19 else "Nicht zugestellt")
        auf = 2 if (i <= 8 and status == "Zugestellt") else 0
        klick = 1 if i <= 3 else 0
        eintraege.append((f"neu{i:02d}@example.com", VORNAMEN[i - 1], NACHNAMEN[i - 1], auf, klick, status))
    return reach_report(eintraege)


def main() -> None:
    ziel = Path(__file__).resolve().parents[1] / "beispieldaten"
    ziel.mkdir(exist_ok=True)
    (ziel / "1_bestand.csv").write_bytes(als_csv(BESTAND))
    (ziel / "2_sperrliste.csv").write_bytes(
        schreibe_csv(["E-Mail", "Grund"], [[a, "Unzustellbar"] for a in GESPERRT], ";"))
    (ziel / "3_kontaktliste_80_zeilen.csv").write_bytes(als_csv(kontaktliste()))
    (ziel / "4_reach_report.csv").write_bytes(beispiel_report())
    print(f"Beispieldateien geschrieben nach {ziel}")


if __name__ == "__main__":
    main()
