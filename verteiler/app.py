"""
E-Mail-Verteiler – Oberfläche (Streamlit).

Start:  streamlit run app.py      (oder start.bat unter Windows)
"""

from __future__ import annotations

import hashlib
import os
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from verteiler_core import db, imports, queries
from verteiler_core.fileio import DateiFehler, lese_datei
from verteiler_core.normalize import REPORT_ZIELE, spalte_erkennen

BASIS = Path(__file__).resolve().parent
DB_PFAD = Path(os.environ.get("VERTEILER_DB", BASIS / "verteiler.db"))
BACKUP_DIR = Path(os.environ.get("VERTEILER_BACKUPS", BASIS / "backups"))

st.set_page_config(page_title="E-Mail-Verteiler", layout="wide")

NICHT = "– nicht vorhanden –"
STATUS_TEXT = {"aktiv": "Aktiv", "bounce_hart": "Bounce (hart)", "bounce_weich": "Bounce (weich)",
               "abgemeldet": "Abgemeldet", "gesperrt": "Gesperrt"}
GRUND_TEXT = {"bounce_hart": "Harter Bounce", "abgemeldet": "Abgemeldet",
              "beschwerde": "Beschwerde / Spam", "manuell": "Manuell gesperrt"}
ZIEL_TEXT = {"zugestellt": "Zugestellt", "unzustellbar": "Unzustellbar → Sperrliste",
             "soft_bounce": "Soft-Bounce (Zähler)", "nicht_zugestellt": "Nicht zugestellt (neutral)",
             "abgemeldet": "Abgemeldet → Sperrliste", "beschwerde": "Beschwerde → Sperrliste"}
UEBERSPRINGEN = "(Zeilen überspringen)"


# ------------------------------------------------------------------ Hilfen

def verbindung():
    return closing(db.connect(DB_PFAD))


def md(text: str) -> str:
    """Freitext für Markdown-Ausgaben entschärfen (keine Links/Formatierung aus Daten)."""
    return "".join("\\" + ch if ch in "\\`*_{}[]()<>#+-.!|~" else ch for ch in str(text))


def prozent(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def zahl(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@st.cache_data(max_entries=4, show_spinner="Datei wird gelesen …")
def _lies(name: str, daten: bytes):
    return lese_datei(name, daten)


def meldung_zeigen():
    # Fester Platzhalter: Die Seitenstruktur bleibt gleich, ob eine Meldung kommt
    # oder nicht – sonst klappen geöffnete Bereiche beim nächsten Neuladen zu.
    platz = st.container()
    m = st.session_state.pop("meldung", None)
    if m:
        platz.success(m)


def nach_import(text: str, schluessel: str):
    st.session_state["meldung"] = text
    st.session_state[schluessel] = st.session_state.get(schluessel, 0) + 1  # Upload leeren
    st.rerun()


def datei_hochladen(titel: str, schluessel: str):
    """Upload + Lesen. Gibt (dateiname, tabelle, kennung) oder None zurück."""
    n = st.session_state.get(schluessel, 0)
    datei = st.file_uploader(titel, type=["csv", "txt", "xlsx"], key=f"{schluessel}_{n}")
    if datei is None:
        return None
    daten = datei.getvalue()
    try:
        tabelle = _lies(datei.name, daten)
    except DateiFehler as exc:
        st.error(str(exc))
        return None
    for h in tabelle.hinweise:
        st.warning(h)
    trenn = {";": "Semikolon", ",": "Komma"}.get(tabelle.trennzeichen, "–")
    st.caption(f"{zahl(len(tabelle.zeilen))} Datenzeilen · Kodierung: {tabelle.kodierung} · "
               f"Trennzeichen: {trenn}")
    with st.expander("Erste Zeilen der Datei ansehen"):
        st.dataframe(pd.DataFrame(tabelle.zeilen[:15], columns=tabelle.kopfzeilen), hide_index=True)
    kennung = hashlib.sha256(daten).hexdigest()[:12]
    return datei.name, tabelle, kennung


def spalten_zuordnen(felder: dict[str, str], kopf: list[str], pflicht: set[str], praefix: str):
    st.markdown("**Spalten zuordnen**")
    optionen = [NICHT] + kopf
    zuordnung: dict[str, str | None] = {}
    spalten = st.columns(3)
    for i, (feld, label) in enumerate(felder.items()):
        auto = spalte_erkennen(feld, kopf)
        wahl = spalten[i % 3].selectbox(label + (" *" if feld in pflicht else ""), optionen,
                                        index=optionen.index(auto) if auto else 0,
                                        key=f"{praefix}_{feld}")
        zuordnung[feld] = None if wahl == NICHT else wahl
    belegt = [v for v in zuordnung.values() if v]
    if len(belegt) != len(set(belegt)):
        st.warning("Eine Spalte ist mehreren Feldern zugeordnet – bitte prüfen.")
    fehlend = [felder[f] for f in pflicht if not zuordnung.get(f)]
    if fehlend:
        st.error("Pflichtfeld fehlt: " + ", ".join(fehlend))
        return None
    return zuordnung


def liste_zeigen(titel: str, daten: list, spalten: list[str] | None = None):
    if not daten:
        return
    with st.expander(f"{titel} ({zahl(len(daten))})"):
        if isinstance(daten[0], dict):
            df = pd.DataFrame(daten)
        else:
            df = pd.DataFrame({spalten[0] if spalten else "E-Mail": daten})
        st.dataframe(df.head(1000), hide_index=True)


# ============================================================ Dashboard

def seite_dashboard():
    st.header("Dashboard")
    with verbindung() as c:
        status = queries.status_zahlen(c)
        sperre = queries.sperrlisten_zahlen(c)
        kennz = queries.kampagnen_kennzahlen(c)
        versandfaehig = len(queries.segment_kontakte(c, "alle_aktiven"))

    st.subheader("Kontakte je Status")
    sp = st.columns(len(status) + 1)
    sp[0].metric("Versandfähig", zahl(versandfaehig))
    for i, (s, n) in enumerate(status.items(), start=1):
        sp[i].metric(STATUS_TEXT[s], zahl(n))
    st.caption("Sperrliste: " + " · ".join(f"{GRUND_TEXT[g]}: {zahl(n)}" for g, n in sperre.items())
               + f" · gesamt {zahl(sum(sperre.values()))}")

    st.subheader("Kampagnen")
    if not kennz:
        st.info("Noch keine Kampagne importiert. Starte mit „Kampagnen-Report importieren“.")
        return
    for k in kennz:
        if k["warnung"]:
            st.error(f"Bounce-Rate {prozent(k['bounce_rate'])} bei „{md(k['name'])}“ "
                     f"({k['gesendet_am']}) liegt über 2 %. Vor dem nächsten Versand nur das "
                     "exportierte Segment verwenden – die Bounces sind bereits gesperrt.")
    df = pd.DataFrame([{
        "Versand": k["gesendet_am"], "Kampagne": k["name"], "Betreff": k["betreff"],
        "Empfänger": k["empfaenger"], "Versendet": k["versendet"], "Zugestellt": k["zugestellt"],
        "Bounce hart": k["bounce_hart"], "Bounce weich": k["bounce_weich"],
        "Abgemeldet": k["abgemeldet"],
        "Bounce-Rate": prozent(k["bounce_rate"]),
        "Öffnungsrate": prozent(k["oeffnungsrate"]),
        "Öffnungsrate (zugestellt)": prozent(k["oeffnungsrate_zugestellt"]),
        "Klickrate": prozent(k["klickrate"]),
        "Warnung": "über 2 %" if k["warnung"] else "",
    } for k in kennz])
    st.dataframe(df, hide_index=True)
    st.caption("Bounce-Rate = (harte + weiche Bounces) / versendete Mails. "
               "Öffnungsrate = Empfänger mit mindestens einer Öffnung / versendet bzw. / zugestellt.")


# =================================================== Kontakte importieren

def seite_kontakte_import():
    st.header("Kontaktliste importieren")
    st.write("Bestehende Liste (CSV oder XLSX) einlesen. Adressen der Sperrliste werden "
             "übersprungen, Dubletten zusammengeführt. Vor dem Schreiben siehst du eine Vorschau.")
    meldung_zeigen()
    hoch = datei_hochladen("Datei wählen", "up_kontakte")
    if not hoch:
        return
    name, tabelle, kennung = hoch
    zuordnung = spalten_zuordnen(
        {"email": "E-Mail", "vorname": "Vorname", "nachname": "Nachname", "firma": "Firma",
         "quelle": "Quelle", "einwilligung_art": "Einwilligung (Art)",
         "einwilligung_datum": "Einwilligung (Datum)"},
        tabelle.kopfzeilen, {"email"}, f"k_{kennung}")
    if zuordnung is None:
        return

    st.markdown("**Standardwerte für leere Felder**")
    a, b, m = st.columns(3)
    quelle = a.text_input("Quelle für leere Zeilen", placeholder="z. B. Altliste, Webinar-Anmeldung, Messe",
                          key=f"k_{kennung}_quelle_std")
    einw = b.text_input("Einwilligung (Art) für leere Zeilen", placeholder="z. B. Double-Opt-In",
                        key=f"k_{kennung}_einw_std")
    modus = m.radio("Bei Dubletten", ["ergaenzen", "ueberschreiben"], key=f"k_{kennung}_modus",
                    format_func={"ergaenzen": "nur leere Felder ergänzen",
                                 "ueberschreiben": "vorhandene Werte überschreiben"}.get)
    standard = {"quelle": quelle, "einwilligung_art": einw}

    try:
        with verbindung() as c:
            plan = imports.analysiere_kontakte(c, tabelle.zeilen, zuordnung, standard, modus)
    except imports.ImportFehler as exc:
        st.error(str(exc))
        return
    z = plan.zahlen()
    st.subheader("Vorschau")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Neu", zahl(z["neu"]))
    s2.metric("Dublette", zahl(z["dublette"]),
              help=f"{z['dublette_in_datei']} doppelt in der Datei, "
                   f"{z['dublette_bestand_aktualisiert']} bestehende Kontakte werden ergänzt, "
                   f"{z['dublette_bestand_unveraendert']} bleiben unverändert")
    s3.metric("Ungültig", zahl(z["ungueltig"]))
    s4.metric("Gesperrt (übersprungen)", zahl(z["gesperrt"]))
    st.caption(f"Davon bestehende Kontakte, die ergänzt werden: {zahl(z['dublette_bestand_aktualisiert'])}")
    if z["datum_unklar"]:
        st.warning(f"{z['datum_unklar']} Einwilligungsdaten nicht als Datum erkannt – sie werden als "
                   "Text übernommen.")
    liste_zeigen("Neue Kontakte", plan.neu)
    liste_zeigen("Bestehende Kontakte, die ergänzt werden",
                 [{"email": e, **{f"neu: {f}": v for f, v in aend.items()}}
                  for _i, e, aend in plan.aktualisieren])
    liste_zeigen("Ungültige Adressen", plan.ungueltig)
    liste_zeigen("Gesperrte Adressen (werden nicht importiert)", plan.gesperrt)
    liste_zeigen("Dubletten innerhalb der Datei", plan.dubletten_in_datei)
    liste_zeigen("Nicht erkannte Einwilligungsdaten", plan.datum_unklar)

    schreiben = z["neu"] + z["dublette_bestand_aktualisiert"]
    if st.button(f"Import ausführen ({zahl(schreiben)} Kontakte schreiben)", type="primary",
                 disabled=schreiben == 0, key=f"k_{kennung}_los"):
        try:
            e = imports.importiere_kontakte(DB_PFAD, BACKUP_DIR, name, tabelle.zeilen, zuordnung,
                                            standard, modus)
        except imports.ImportFehler as exc:
            st.error(str(exc))
            return
        nach_import(f"Import abgeschlossen: {e['neu']} neu, {e['dublette_bestand_aktualisiert']} "
                    f"aktualisiert, {e['ungueltig']} ungültig, {e['gesperrt']} gesperrt übersprungen. "
                    f"Backup: {Path(e['backup']).name if e['backup'] else '–'}", "up_kontakte")


# =============================================== Kampagnen-Report importieren

def seite_report_import():
    st.header("Kampagnen-Report aus Reach importieren")
    st.write("In Reach bei der Kampagne die Registerkarte **Empfänger** als CSV exportieren "
             "(Spalten E-Mail, Vorname, Nachname, Geöffnet, Geklickt, Status) und hier hochladen.")
    meldung_zeigen()

    with verbindung() as c:
        vorhandene = queries.kampagnen(c)
    art = st.radio("Kampagne", ["neu", "bestehend"], horizontal=True,
                   format_func={"neu": "Neue Kampagne anlegen",
                                "bestehend": "Bestehende Kampagne (Report erneut importieren)"}.get)
    kampagne: dict
    if art == "neu":
        n = st.session_state.get("up_report", 0)  # nach einem Import leeren
        a, b, d = st.columns([2, 3, 1])
        name_k = a.text_input("Name der Kampagne *", placeholder="z. B. Newsletter Oktober 2026",
                              key=f"r_name_{n}")
        betreff = b.text_input("Betreff", key=f"r_betreff_{n}")
        gesendet = d.date_input("Versanddatum *", value=date.today(), format="DD.MM.YYYY",
                                key=f"r_datum_{n}")
        kampagne = {"name": name_k, "betreff": betreff, "gesendet_am": gesendet.isoformat()}
        kdatum, kid = gesendet.isoformat(), None
        doppelt = [k for k in vorhandene if k["name"].strip().lower() == name_k.strip().lower()
                   and k["gesendet_am"] == kdatum]
        if doppelt:
            st.warning("Eine Kampagne mit diesem Namen und Datum gibt es schon – wähle "
                       "„Bestehende Kampagne“, sonst wird sie doppelt angelegt.")
    else:
        if not vorhandene:
            st.info("Noch keine Kampagne vorhanden.")
            return
        nach_id = {k["id"]: k for k in vorhandene}
        kid = st.selectbox("Kampagne", list(nach_id),
                           format_func=lambda i: f"{nach_id[i]['gesendet_am']} – {nach_id[i]['name']}")
        kampagne = {"id": kid}
        kdatum = nach_id[kid]["gesendet_am"]

    hoch = datei_hochladen("Reach-Report (CSV)", "up_report")
    if not hoch:
        return
    name, tabelle, kennung = hoch
    zuordnung = spalten_zuordnen(
        {"email": "E-Mail", "vorname": "Vorname", "nachname": "Nachname",
         "geoeffnet": "Geöffnet", "geklickt": "Geklickt", "status": "Status"},
        tabelle.kopfzeilen, {"email", "status"}, f"r_{kennung}")
    if zuordnung is None:
        return

    st.markdown("**Statuswerte zuordnen**")
    st.caption("Automatisch erkannt, bitte prüfen. Unbekannte Werte werden übersprungen, "
               "bis du sie zuordnest.")
    werte = imports.report_statuswerte(tabelle.zeilen, zuordnung["status"])
    optionen = [UEBERSPRINGEN, *REPORT_ZIELE]
    status_zuordnung: dict[str, str | None] = {}
    spalten = st.columns(3)
    for i, (key, (beispiel, anzahl, auto)) in enumerate(sorted(werte.items(), key=lambda x: -x[1][1])):
        wahl = spalten[i % 3].selectbox(
            f"„{md(beispiel) if beispiel else '(leer)'}“ – {zahl(anzahl)}×", optionen,
            index=optionen.index(auto) if auto else 0, key=f"r_{kennung}_st_{key}",
            format_func=lambda o: ZIEL_TEXT.get(o, o))
        status_zuordnung[key] = None if wahl == UEBERSPRINGEN else wahl

    anlegen = st.checkbox("Adressen, die noch nicht in der Datenbank sind, als Kontakt anlegen",
                          value=True, key=f"r_{kennung}_anlegen",
                          help="Empfohlen beim ersten Import: so landet der komplette Reach-Bestand "
                               "inkl. Bounces in der Datenbank.")
    try:
        with verbindung() as c:
            plan = imports.analysiere_report(c, tabelle.zeilen, zuordnung, status_zuordnung,
                                             kdatum, kid, anlegen)
    except imports.ImportFehler as exc:
        st.error(str(exc))
        return
    z = plan.zahlen()
    st.subheader("Vorschau")
    s = st.columns(6)
    s[0].metric("Empfänger", zahl(z["verarbeitet"]))
    s[1].metric("Zugestellt", zahl(z.get("status_zugestellt", 0) + z.get("status_abgemeldet", 0)
                                   + z.get("status_beschwerde", 0)))
    s[2].metric("Unzustellbar", zahl(z.get("status_unzustellbar", 0)))
    s[3].metric("Soft-Bounce", zahl(z.get("status_soft_bounce", 0)))
    s[4].metric("Abgemeldet", zahl(z.get("status_abgemeldet", 0)))
    s[5].metric("Nicht zugestellt", zahl(z.get("status_nicht_zugestellt", 0)))
    t = st.columns(5)
    t[0].metric("Neu auf Sperrliste", zahl(z["neu_gesperrt"]))
    t[1].metric("3. Soft-Bounce → gesperrt", zahl(z["soft_bounce_3x"]))
    t[2].metric("Neue Kontakte", zahl(z["neue_kontakte"]))
    t[3].metric("Ungültig", zahl(z["ungueltig"]))
    t[4].metric("Status unbekannt", zahl(z["status_unbekannt"]))
    versendet = z["verarbeitet"] - z.get("status_nicht_zugestellt", 0)
    if versendet:
        rate = (z.get("status_unzustellbar", 0) + z.get("status_soft_bounce", 0)) / versendet
        (st.error if rate > 0.02 else st.info)(f"Bounce-Rate dieses Reports: {prozent(rate)}")
    if z["zahl_unklar"]:
        st.warning(f"{z['zahl_unklar']} Werte in Geöffnet/Geklickt waren keine Zahl und wurden als 0 gezählt.")
    if z["unbekannt_uebersprungen"]:
        st.info(f"{z['unbekannt_uebersprungen']} Adressen sind nicht in der Datenbank und werden übersprungen.")
    for grund, emails in plan.neue_sperren.items():
        liste_zeigen(f"Neu auf die Sperrliste – {GRUND_TEXT[grund]}", emails)
    liste_zeigen("Erreichen den 3. Soft-Bounce in Folge (→ Sperrliste)", plan.soft_bounce_grenze)
    liste_zeigen("Neue Kontakte", plan.neue_kontakte)
    liste_zeigen("Ungültige Adressen", plan.ungueltig)
    liste_zeigen("Zeilen mit unbekanntem Status", plan.status_unbekannt)

    bereit = z["verarbeitet"] > 0 and (art == "bestehend" or kampagne.get("name", "").strip())
    if art == "neu" and not kampagne.get("name", "").strip():
        st.info("Bitte oben einen Namen für die Kampagne eintragen.")
    if st.button(f"Report importieren ({zahl(z['verarbeitet'])} Empfänger)", type="primary",
                 disabled=not bereit, key=f"r_{kennung}_los"):
        try:
            e = imports.importiere_report(DB_PFAD, BACKUP_DIR, name, tabelle.zeilen, zuordnung,
                                          status_zuordnung, kampagne, anlegen)
        except imports.ImportFehler as exc:
            st.error(str(exc))
            return
        nach_import(f"Report importiert: {e['verarbeitet']} Empfänger, {e['neu_gesperrt']} neu gesperrt, "
                    f"{e['soft_bounce_3x']} nach 3 Soft-Bounces gesperrt, {e['neue_kontakte']} neue "
                    f"Kontakte. Backup: {Path(e['backup']).name if e['backup'] else '–'}", "up_report")


# =================================================== Sperrliste importieren

def seite_sperrliste_import():
    st.header("Sperrliste importieren")
    st.write("Nur Adressen sperren, z. B. eine Liste Abgemeldeter oder Unzustellbarer. "
             "Gesperrte Adressen werden nie wieder exportiert oder aktiviert.")
    meldung_zeigen()

    with st.expander("Einzelne Adresse sperren"):
        with st.form("einzeln_sperren", clear_on_submit=True):
            a, b = st.columns([3, 2])
            adr = a.text_input("E-Mail-Adresse")
            grund = b.selectbox("Grund", list(GRUND_TEXT), index=3, format_func=GRUND_TEXT.get)
            if st.form_submit_button("Sperren"):
                try:
                    neu = queries.adresse_sperren(DB_PFAD, adr, grund)
                    st.success("Gesperrt." if neu else "Adresse stand bereits auf der Sperrliste.")
                except imports.ImportFehler as exc:
                    st.error(str(exc))

    hoch = datei_hochladen("Datei wählen", "up_sperre")
    if not hoch:
        return
    name, tabelle, kennung = hoch
    zuordnung = spalten_zuordnen({"email": "E-Mail", "grund": "Grund (optional)",
                                  "datum": "Datum (optional)"},
                                 tabelle.kopfzeilen, {"email"}, f"s_{kennung}")
    if zuordnung is None:
        return
    standard = st.selectbox("Grund für alle Zeilen (bzw. wenn die Grund-Spalte leer ist)",
                            list(GRUND_TEXT), format_func=GRUND_TEXT.get, key=f"s_{kennung}_standardgrund")
    try:
        with verbindung() as c:
            plan = imports.analysiere_sperrliste(c, tabelle.zeilen, zuordnung, standard)
    except imports.ImportFehler as exc:
        st.error(str(exc))
        return
    z = plan.zahlen()
    st.subheader("Vorschau")
    s = st.columns(4)
    s[0].metric("Neu gesperrt", zahl(z["neu_gesperrt"]))
    s[1].metric("Bereits gesperrt", zahl(z["bereits_gesperrt"]))
    s[2].metric("Ungültig", zahl(z["ungueltig"]))
    s[3].metric("Davon bestehende Kontakte", zahl(z["betrifft_bestehende_kontakte"]))
    if z["grund_nicht_erkannt"]:
        st.warning(f"{z['grund_nicht_erkannt']} Gründe nicht erkannt – dafür gilt „{GRUND_TEXT[standard]}“.")
    liste_zeigen("Neu auf die Sperrliste", [{"email": e, "grund": g, "datum": d}
                                            for e, (g, d) in plan.neu.items()])
    liste_zeigen("Ungültige Adressen", plan.ungueltig)
    if st.button(f"Sperrliste importieren ({zahl(z['neu_gesperrt'])} Adressen sperren)", type="primary",
                 disabled=z["neu_gesperrt"] == 0, key=f"s_{kennung}_los"):
        try:
            e = imports.importiere_sperrliste(DB_PFAD, BACKUP_DIR, name, tabelle.zeilen, zuordnung, standard)
        except imports.ImportFehler as exc:
            st.error(str(exc))
            return
        nach_import(f"{e['neu_gesperrt']} Adressen gesperrt ({e['betrifft_bestehende_kontakte']} davon "
                    f"bestehende Kontakte). Backup: {Path(e['backup']).name if e['backup'] else '–'}",
                    "up_sperre")


# ============================================================ Export

def seite_export():
    st.header("Export für Reach")
    st.write("Erzeugt eine CSV mit E-Mail, Vorname, Nachname zum Hochladen in Reach. "
             "Adressen der Sperrliste sind **nie** enthalten.")
    a, b, d = st.columns([3, 1, 1])
    segment = a.radio("Segment", list(queries.SEGMENTE), format_func=queries.SEGMENTE.get)
    tage = 90
    if segment == "engagierte":
        tage = b.number_input("Zeitraum (Tage)", 1, 3650, 90, key="tage_eng")
    elif segment == "inaktive":
        tage = b.number_input("Zeitraum (Tage)", 1, 3650, 180, key="tage_ina")
    trenn = d.selectbox("Trennzeichen", [",", ";"],
                        format_func={",": "Komma (,)", ";": "Semikolon (;)"}.get)
    with verbindung() as c:
        zeilen = queries.segment_kontakte(c, segment, int(tage))
        gesperrt = sum(queries.sperrlisten_zahlen(c).values())
    st.metric("Adressen im Export", zahl(len(zeilen)))
    st.caption(f"{zahl(gesperrt)} Adressen stehen auf der Sperrliste und sind ausgeschlossen.")
    if segment == "engagierte":
        st.caption("Engagiert = in einer Kampagne, die in den letzten Tagen versendet wurde, "
                   "mindestens einmal geöffnet oder geklickt.")
    elif segment == "inaktive":
        st.caption("Inaktiv = hat schon vor dem Zeitraum Mails erhalten, im Zeitraum aber nichts "
                   "geöffnet oder geklickt – für eine Reaktivierungsmail.")
    if zeilen:
        st.dataframe(pd.DataFrame([dict(z) for z in zeilen[:50]]), hide_index=True)
        st.download_button("CSV herunterladen", data=queries.export_csv(zeilen, trenn),
                           file_name=f"reach_{segment}_{date.today():%Y-%m-%d}.csv",
                           mime="text/csv", type="primary")


# ===================================================== Kontakte bearbeiten

def seite_kontakte():
    st.header("Kontakte suchen und bearbeiten")
    meldung_zeigen()
    a, b = st.columns([3, 1])
    such = a.text_input("Suche (E-Mail, Name, Firma)")
    status = b.selectbox("Status", [None, *db.KONTAKT_STATUS],
                         format_func=lambda s: "alle" if s is None else STATUS_TEXT[s])
    with verbindung() as c:
        treffer = queries.kontakte_suchen(c, such, status)
    st.caption(f"{zahl(len(treffer))} Treffer" + (" (max. 500 angezeigt)" if len(treffer) >= 500 else ""))
    if treffer:
        st.dataframe(pd.DataFrame([{"E-Mail": t["email"], "Vorname": t["vorname"],
                                    "Nachname": t["nachname"], "Firma": t["firma"],
                                    "Status": STATUS_TEXT[t["status"]], "Quelle": t["quelle"],
                                    "Einwilligung": t["einwilligung_art"]} for t in treffer]),
                     hide_index=True, height=260)
        auswahl = st.selectbox("Kontakt öffnen", [t["id"] for t in treffer],
                               format_func={t["id"]: t["email"] for t in treffer}.get)
        kontakt_detail(auswahl)

    with st.expander("Neuen Kontakt manuell anlegen"):
        with st.form("neu_anlegen", clear_on_submit=True):
            x = st.columns(3)
            daten = {"email": x[0].text_input("E-Mail *"), "vorname": x[1].text_input("Vorname"),
                     "nachname": x[2].text_input("Nachname"), "firma": x[0].text_input("Firma"),
                     "quelle": x[1].text_input("Quelle"),
                     "einwilligung_art": x[2].text_input("Einwilligung (Art)"),
                     "einwilligung_datum": x[0].text_input("Einwilligung (Datum)", placeholder="TT.MM.JJJJ")}
            if st.form_submit_button("Anlegen"):
                try:
                    queries.kontakt_anlegen(DB_PFAD, daten)
                    st.success("Kontakt angelegt.")
                except imports.ImportFehler as exc:
                    st.error(str(exc))


def kontakt_detail(kid: int):
    with verbindung() as c:
        k = queries.kontakt(c, kid)
        if k is None:
            return
        sperre = queries.kontakt_sperre(c, k["email"])
        historie = queries.kontakt_historie(c, kid)
    st.markdown(f"### `{k['email']}`")
    st.write(f"Status: **{STATUS_TEXT[k['status']]}**"
             + (f" · Soft-Bounces in Folge: {k['soft_bounce_folge']}" if k["soft_bounce_folge"] else "")
             + (f" · Sperrliste: {GRUND_TEXT[sperre['grund']]} seit {sperre['datum']}" if sperre else "")
             + f" · angelegt {k['erstellt_am']} · geändert {k['geaendert_am']}")

    v = f"{kid}_{k['geaendert_am']}"  # neue Felder nach jeder Änderung
    with st.form(f"bearbeiten_{kid}"):
        x = st.columns(3)
        daten = {"vorname": x[0].text_input("Vorname", k["vorname"], key=f"vn_{v}"),
                 "nachname": x[1].text_input("Nachname", k["nachname"], key=f"nn_{v}"),
                 "firma": x[2].text_input("Firma", k["firma"], key=f"fi_{v}"),
                 "quelle": x[0].text_input("Quelle", k["quelle"], key=f"qu_{v}"),
                 "einwilligung_art": x[1].text_input("Einwilligung (Art)", k["einwilligung_art"],
                                                     placeholder="z. B. Double-Opt-In, Messe-Visitenkarte",
                                                     key=f"ea_{v}"),
                 "einwilligung_datum": x[2].text_input("Einwilligung (Datum)", k["einwilligung_datum"],
                                                       placeholder="TT.MM.JJJJ", key=f"ed_{v}")}
        if st.form_submit_button("Speichern"):
            try:
                queries.kontakt_aktualisieren(DB_PFAD, kid, daten)
                st.session_state["meldung"] = "Gespeichert."
                st.rerun()
            except imports.ImportFehler as exc:
                st.error(str(exc))

    if historie:
        st.markdown("**Kampagnen**")
        st.dataframe(pd.DataFrame([{"Versand": h["gesendet_am"], "Kampagne": h["name"],
                                    "Zustellung": h["zustellstatus"], "Geöffnet": h["geoeffnet"],
                                    "Geklickt": h["geklickt"]} for h in historie]), hide_index=True)

    if not sperre:
        with st.expander("Kontakt manuell sperren"):
            with st.form(f"sperren_{kid}"):
                grund = st.selectbox("Grund", ["manuell", "abgemeldet", "beschwerde"],
                                     format_func=GRUND_TEXT.get)
                ok = st.checkbox("Ja, diese Adresse dauerhaft sperren")
                if st.form_submit_button("Sperren"):
                    if not ok:
                        st.error("Bitte zuerst das Häkchen zur Bestätigung setzen.")
                    else:
                        queries.kontakt_sperren(DB_PFAD, kid, grund)
                        st.session_state["meldung"] = f"{k['email']} wurde gesperrt."
                        st.rerun()

    with st.expander("Kontakt vollständig löschen (DSGVO)"):
        st.warning("Löscht Stammdaten und Kampagnenhistorie unwiderruflich. Ältere Backups im "
                   "Ordner backups/ enthalten den Kontakt weiterhin.")
        with st.form(f"dsgvo_{kid}"):
            behalten = st.checkbox("Adresse auf der Sperrliste behalten (empfohlen – verhindert, dass "
                                   "sie über eine alte Liste wieder hereinkommt; gespeichert bleibt nur "
                                   "die E-Mail-Adresse)", value=True)
            best = st.text_input("Zur Bestätigung die E-Mail-Adresse eintippen")
            if st.form_submit_button("Endgültig löschen", type="primary"):
                try:
                    queries.kontakt_dsgvo_loeschen(DB_PFAD, kid, best, behalten)
                    st.session_state["meldung"] = "Kontakt gelöscht."
                    st.rerun()
                except imports.ImportFehler as exc:
                    st.error(str(exc))


# ===================================================== Sperrliste & Protokoll

def seite_protokoll():
    st.header("Sperrliste, Kampagnen & Protokoll")
    such = st.text_input("Sperrliste durchsuchen")
    with verbindung() as c:
        sperre = queries.sperrliste_suchen(c, such)
        log = queries.import_protokoll(c)
        kamp = queries.kampagnen(c)
    st.subheader("Sperrliste")
    st.dataframe(pd.DataFrame([{"E-Mail": s["email"], "Grund": GRUND_TEXT[s["grund"]], "Datum": s["datum"]}
                               for s in sperre]), hide_index=True)
    st.subheader("Kampagnen")
    st.dataframe(pd.DataFrame([dict(k) for k in kamp]), hide_index=True)
    st.subheader("Import-Protokoll")
    st.dataframe(pd.DataFrame([dict(r) for r in log]), hide_index=True)
    backups = sorted(BACKUP_DIR.glob("verteiler_*.db")) if BACKUP_DIR.exists() else []
    st.caption(f"Backups: {len(backups)} im Ordner {BACKUP_DIR}"
               + (f" · neuestes: {backups[-1].name}" if backups else ""))


SEITEN = {
    "Dashboard": seite_dashboard,
    "Kontaktliste importieren": seite_kontakte_import,
    "Kampagnen-Report importieren": seite_report_import,
    "Sperrliste importieren": seite_sperrliste_import,
    "Export für Reach": seite_export,
    "Kontakte suchen / bearbeiten": seite_kontakte,
    "Sperrliste & Protokoll": seite_protokoll,
}

with st.sidebar:
    st.title("E-Mail-Verteiler")
    seite = st.radio("Bereich", list(SEITEN), label_visibility="collapsed")
    st.caption(f"Datenbank: {DB_PFAD.name}")

db.connect(DB_PFAD).close()  # Schema anlegen, falls neu
SEITEN[seite]()
