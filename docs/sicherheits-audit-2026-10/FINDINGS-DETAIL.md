# Befund-Details – FBE Intranet + E-Mail-Verteiler (projektabrechung)

Enthält alle bestätigten Befunde der Schwere mittel oder höher mit Trace, lokaler Reproduktion und Fix.

## TimeMoto-Webhook setzt SHARED_SECRET nicht durch: anonyme Fälschung und Löschung abrechenbarer Zeitbuchungen

- Schwere: **hoch** – Fingerprint `app.py:receive:webhook-shared-secret-not-enforced`
- Stand: behoben – SHARED_SECRET Pflicht (sonst 503), Vergleich zeitkonstant, falsche Anfragen werden nicht gespeichert

**Beschreibung.** Der öffentliche Webhook (Standardpfad /timemoto, laut deploy/DEPLOY.md:96 unter https://intern.rss-fb.com/timemoto bei TimeMoto eingetragen; Host-Caddy leitet ihn ohne Gate an 127.0.0.1:8080 weiter) berechnet zwar, ob der konfigurierte SHARED_SECRET mitgeschickt wurde, lehnt Anfragen ohne/mit falschem Secret aber nie ab. Jede Anfrage wird mit secret_ok=false in events.jsonl geschrieben und von events.load_records/normalize, report.collect_intervals und allen Verbrauchern (Berichte, Exporte, Dashboard/Log/„Meine Zeiten“, geplante Berichtsmails, Erinnerungsmails) genauso verarbeitet wie ein echtes TimeMoto-Event. Ein anonymer Aufrufer, der den TimeMoto-Anzeigenamen eines Mitarbeiters kennt, kann beliebige Buchungen (Projekt, Dauer) für diesen Mitarbeiter anlegen; kennt er zusätzlich eine clockingPairId, kann er eine echte Buchung per isDeleted-Event löschen oder per späterem Event mit gleicher pair_id „korrigieren“ (zuletzt empfangenes Event gewinnt). Der gefälschte Projekttext landet außerdem unescaped im HTML der Erinnerungsmail, die der firmeneigene Mailversand an den zugeordneten Mitarbeiter schickt (eigene, nachgelagerte Escaping-Lücke in scheduler.run_reminders).

**Soll-Verhalten.** Ist SHARED_SECRET gesetzt, müssen Anfragen ohne passendes Secret (konstante Laufzeit beim Vergleich) mit 401/403 abgewiesen und nicht nach events.jsonl geschrieben werden; Verbraucher müssen bereits gespeicherte Records mit secret_ok == false ignorieren. Im Produktivbetrieb muss das Secret Pflicht sein (fail closed bei leerem SHARED_SECRET).

**Trace**

1. `deploy/caddy-intern.snippet:42` (entrypoint) – Alle Pfade außer /verteiler/* und (von außen) /report/* werden ohne Authentifizierung an 127.0.0.1:8080 weitergeleitet, also auch /timemoto.
2. `app.py:97` (propagation) – Webhook-Route auf config.WEBHOOK_PATH (Standard /timemoto, config.py:59; deploy/docker-compose.yml:39) für POST/GET/PUT ohne Dependency oder Auth.
3. `app.py:123` (propagation) – secret_ok = candidate == config.SHARED_SECRET wird berechnet, aber nie zur Ablehnung verwendet.
4. `app.py:146` (propagation) – Record mit vom Angreifer gewähltem body_json wird bedingungslos an LOG_FILE angehängt; app.py:150 liefert 200 {"status":"received"}.
5. `events.py:203` (propagation) – Alle JSONL-Zeilen werden geladen; normalize (events.py:259-308) extrahiert Mitarbeiter, Projekt, Zeit, pair_id und Löschkennzeichen aus body_json, ohne secret_ok zu prüfen.
6. `events.py:337` (propagation) – Ein einziges Event mit deleted=True in der Gruppe (Mitarbeiter, pair_id) verwirft die gesamte Buchung; sonst gewinnt je Richtung das zuletzt empfangene Event (events.py:344-345).
7. `report.py:31` (propagation) – Gefälschte/gelöschte Intervalle bilden die zentrale Datenquelle für Berichte, Exporte, Web-Ansichten und Scheduler.
8. `scheduler.py:80` (sink) – Gefälschte Buchung erzeugt eine Erinnerungsmail an den zugeordneten Mitarbeiter (Versand scheduler.py:87) mit unescaped eingesetztem Projekttext im HTML; dieselben Intervalle speisen die geplanten Kunden-/Buchhaltungsberichte (scheduler.py:30-44).

**Belege**

- `app.py:111` – secret_ok wird initialisiert und nur zugewiesen; keine Verzweigung vor dem Speichern.
- `app.py:131` – secret_ok wird nur als Feld im Record abgelegt; grep über alle *.py findet keine weitere Verwendung.
- `README.md:61` – Dokumentation: Secret wird nur als secret_ok protokolliert, Events werden nicht verworfen.
- `events.py:264` – normalize() nutzt record['body_json'] direkt; kein Authentifizierungsfeld wird ausgewertet.
- `deploy/caddy-intern.snippet:36` – Nur /report/* ist per remote_ip gesperrt; der Webhook-Pfad hat keine Ingress-Beschränkung.
- `deploy/DEPLOY.md:96` – Betriebsanleitung trägt https://intern.rss-fb.com/timemoto als Webhook-URL bei TimeMoto ein; der Endpunkt ist bestimmungsgemäß aus dem Internet erreichbar.
- `agents/v3-pa-04/artifacts/v3_webhook_output.txt:1` – Unabhängige lokale Prüfung (Sandbox): Anfragen ohne/mit falschem Secret liefern 200, werden mit secret_ok=false gespeichert, erscheinen als Intervalle; gefälschtes isDeleted-Event entfernt die legitime Buchung; Erinnerungsmail-HTML enthält rohes Tag aus projectName.
- `agents/v3-pa-04/artifacts/v3_harness.py:1` – Harness der unabhängigen Prüfung: nur fastapi-Hülle und web-Router gestubbt, mailer.send in-memory erfasst; app.receive, events, report, scheduler unverändert.

**Akteur (Dummy).** Anonymer HTTP-Client, der JSON an den öffentlichen Webhook-Pfad ohne (oder mit falschem) Secret sendet.

**Lokale Reproduktion.** ["In der OS-Sandbox (kein Netz, uid nobody, nur Scratch beschreibbar) SHARED_SECRET=dummy-shared-secret, SCHEDULER_ENABLED=false setzen und alle Datenpfade (LOG_FILE, USERS_FILE, ACTIVITIES_FILE, MANUAL_FILE usw.) in Scratch umlenken; Dummy-Benutzer tp mit timemoto_name 'Test Person' und E-Mail tp@example.invalid anlegen.", 'Da fastapi 0.115.6 gegen das installierte starlette 1.7.0 kein FastAPI() bauen kann, nur das fastapi-Modul und den web-Router stubben und app.receive mit echten starlette-Request-Objekten aufrufen.', 'Legitimes Paar L1 (2 h) mit korrektem x-webhook-secret senden, dann das gefälschte Paar F1 (5 h) ohne bzw. mit falschem Secret; report.collect_intervals() auslesen; danach das isDeleted-Event für L1 ohne Secret senden und erneut auslesen; abschließend scheduler.run_reminders() mit in-memory erfasstem mailer.send ausführen.']

**Beobachtet.** Alle Aufrufe ohne/mit falschem Secret lieferten 200 {"status":"received"}; gespeicherte secret_ok-Werte [true, true, false, false, false]. Intervalle nach Fälschung: Test Person 'P-<b>X</b>' 5.0 h und 'P-legit' 2.0 h. Nach dem unauthentifizierten Lösch-Event: nur noch 'P-<b>X</b>' 5.0 h (legitime Buchung verschwunden). run_reminders rief mailer.send an tp@example.invalid mit HTML auf, das das rohe Tag 'P-<b>X</b>' enthält.

**Voraussetzungen.** Keine: anonymer Internet-Aufrufer.; Host-Caddy-Block aus deploy/caddy-intern.snippet ist aktiv (laut CLAUDE.md/DEPLOY.md) und leitet /timemoto weiter; WEBHOOK_PATH ist der Standard /timemoto (deploy/docker-compose.yml:39). Die Erreichbarkeit aus dem Internet ist für die TimeMoto-Cloud funktional erforderlich.; Für gezielte Buchungen muss der TimeMoto-Anzeigename eines Mitarbeiters bekannt sein (oft „Vorname Nachname“); Löschen/Korrigieren einer bestehenden Buchung erfordert zusätzlich deren clockingPairId. Erinnerungsmail nur, wenn der Name einem Benutzer mit timemoto_name und E-Mail zugeordnet ist und Mailversand konfiguriert ist.; Unabhängig davon, ob SHARED_SECRET gesetzt oder leer ist: im gesetzten Fall wird es nicht durchgesetzt, im leeren Fall gibt es gar keine Prüfung.

**Fix.** Secret vor dem Persistieren durchsetzen (hmac.compare_digest, 401 bei Fehlschlag), Secret nicht mehr per Query-String akzeptieren (landet sonst in Logs), Methode auf POST beschränken, bei leerem SHARED_SECRET im Produktivbetrieb fail closed. Zusätzlich in events.load_records Records mit secret_ok == false verwerfen, damit bereits gespeicherte gefälschte Zeilen wirkungslos werden. Getrennt davon iv.project und name in scheduler.run_reminders HTML-escapen. Regressionstest: mit SHARED_SECRET=x muss POST ohne/mit falschem Secret 401 liefern und events.jsonl unverändert lassen; ein manuell eingefügter Record mit secret_ok=false darf in report.collect_intervals() nicht erscheinen; mit korrektem Secret weiterhin 200 und Intervall vorhanden.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`app.py`

```
import hmac
...
@app.post(config.WEBHOOK_PATH)
async def receive(request: Request):
    if not config.SHARED_SECRET:
        return JSONResponse({"status": "disabled"}, status_code=503)
    headers = request.headers
    auth = headers.get("authorization", "")
    candidate = (headers.get("x-webhook-secret") or headers.get("x-api-key")
                 or headers.get("x-timemoto-secret")
                 or auth.removeprefix("Bearer ").removeprefix("bearer ").strip() or "")
    if not hmac.compare_digest(candidate.encode(), config.SHARED_SECRET.encode()):
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    raw = await request.body()
    ...  # Record wie bisher speichern (secret_ok=True)
```

`events.py`

```
def load_records(log_file=None):
    ...
            rec = json.loads(line)
            if rec.get("secret_ok") is False:
                continue  # unauthentifizierte Webhook-Aufrufe nie verwenden
            records.append(rec)
```

`scheduler.py`

```
from html import escape
...
html = (f"<p>Hallo {escape(name)},</p><p>für deine Buchung am <b>{d}</b> "
        f"({escape(iv.project or '-')}, {dur}) fehlt noch die " ...)
```

## Ein winziger unauthentifizierter Webhook mit numerischem Out-of-Range-Zeitstempel legt Dashboard, Berichte, Log und Erinnerungen dauerhaft fuer alle Nutzer lahm

- Schwere: **hoch** – Fingerprint `events.py:_parse_time:unbounded-json-timestamp-poisons-shared-event-log`
- Stand: behoben – Zeitstempel-Bereich/Typ geprüft, defekte Einträge werden einzeln übersprungen

**Beschreibung.** Der TimeMoto-Webhook (app.py:97-150) speichert jeden empfangenen JSON-Body verbatim in das gemeinsame events.jsonl-Log; secret_ok wird berechnet, aber nicht durchgesetzt, der Response ist immer 200. events._parse_time gibt jede JSON-Zahl ungeprueft an datetime.fromtimestamp weiter (keine Bereichs-/NaN-Pruefung, kein except). normalize und collect_intervals/_punches re-parsen bei jedem Seitenaufruf und jedem Scheduler-Job die GESAMTE Datei ohne Isolierung einzelner Records. Ein einziger 38-Byte-POST mit uebergrosser Ganzzahl (oder NaN) vergiftet damit das Log: jeder spaetere Vollreparse wirft OSError('Value too large for defined data type'), sodass Dashboard, /log, /meine-zeiten und /report/preview 500 liefern und die stuendliche Erinnerung sowie die Berichtserzeugung fuer alle Nutzer brechen. Zusaetzlich scheitert der In-App-Loeschpfad (delete_interval) an derselben Zeile, weshalb keine Selbstheilung moeglich ist. Die nicht erzwungene Secret-Pruefung ist ein eigenes Finding; die Wurzel hier ist der ungepruefte Zahl-zu-fromtimestamp-Pfad plus fehlende Record-Isolierung.

**Soll-Verhalten.** Ein fehlerhafter oder ausserhalb des Bereichs liegender Zeitstempel in einem Record soll nur diesen Record ueberspringen (normalize liefert None), waehrend alle anderen Buchungen, Seiten und Jobs weiterlaufen -- genau wie der String-Parse-Zweig bereits bei unparsbaren Strings graceful None zurueckgibt.

**Trace**

1. `app.py:100` (entrypoint) – Webhook nimmt jeden Request-Body an (raw = await request.body()); secret_ok wird berechnet, aber nie erzwungen -- der Response ist bedingungslos 200 (app.py:150), ein unauthentifizierter POST wird akzeptiert.
2. `app.py:146` (propagation) – Der Record (inkl. body_json mit der uebergrossen Zahl) wird verbatim als JSON-Zeile an config.LOG_FILE (events.jsonl) angehaengt -- vor jeder Validierung, somit dauerhaft/neustartfest.
3. `report.py:20` (propagation) – collect_intervals()->_punches() ruft normalize(r) fuer JEDEN gespeicherten Record bei jedem Seitenaufruf/Scheduler-Job auf, ohne per-Record try/except.
4. `events.py:269` (propagation) – normalize ruft _parse_time(_find_first(body, _TIME_KEYS)) mit der Angreiferzahl ohne Exception-Behandlung auf.
5. `events.py:159` (sink) – datetime.fromtimestamp(ts, tz=utc) wirft OSError(Errno 75) bei der uebergrossen Ganzzahl (ValueError bei NaN); die Exception propagiert zu jedem Leser -> HTTP 500 und gebrochene Jobs, bis die Datei manuell editiert wird.

**Belege**

- `events.py:156` – isinstance(value,(int,float))-Zweig: ts = float(value); nachfolgend (Zeile 159) direkt datetime.fromtimestamp ohne Bereichs-/NaN-Pruefung. Lokal reproduziert: datetime.fromtimestamp(1e20/1000, tz=utc) -> OSError Errno 75.
- `events.py:269` – normalize ruft _parse_time ohne try/except auf; lokal reproduziert: normalize(poison) -> OSError Errno 75 (statt None).
- `report.py:31` – collect_intervals re-parst ALLE Records via pair_intervals(_punches()); kein Record isoliert. Lokal mit einer gueltigen + einer Poison-Zeile reproduziert: collect_intervals() -> OSError (gueltige Buchung geht mit verloren).
- `events.py:240` – delete_interval ruft normalize(rec) pro Zeile; lokal reproduziert: delete_interval(...) -> OSError Errno 75. Keine Selbstheilung, Wiederherstellung nur durch manuelles Editieren von events.jsonl.
- `app.py:146` – Poison-Body wird vor jeder Validierung persistiert; DoS ist damit neustartfest/dauerhaft.

**Akteur (Dummy).** Ein unauthentifizierter Client, der die TimeMoto-Webhook-URL erreicht, sendet einen kleinen JSON-Body und deaktiviert dauerhaft die Zeiterfassungs-UI und -Jobs des Intranets fuer alle.

**Lokale Reproduktion.** ['Den ersten Payload an den Webhook-Pfad (Default /timemoto) mit Content-Type application/json und ohne Secret-Header POSTen; HTTP 200 beobachten.', 'Eine Datenseite laden (Dashboard /, /log, /meine-zeiten, /report/preview) und beobachten, dass sie nun HTTP 500 liefert.', 'Beobachten, dass der stuendliche Erinnerungs-Job und die Berichtserzeugung denselben OSError werfen und das In-App-Loeschen den Record nicht entfernen kann.']

**Beobachtet.** Unabhaengig im OS-Sandbox nachgestellt (kein Netz, nobody, prlimit, timeout): Mit einer gueltigen Buchung plus der 38-Byte-Poison-Zeile in events.jsonl warf datetime.fromtimestamp(1e20/1000, tz=utc) OSError(Errno 75, 'Value too large for defined data type'); events.normalize(poison) warf denselben OSError statt None; report.collect_intervals() warf OSError (die gueltige Buchung ging mit verloren); events.delete_interval(...) warf ebenfalls OSError (keine Selbstheilung). Die NaN-Variante warf im selben Sink ValueError('Invalid value NaN'). Deckt sich mit dem 200->500-Nachweis des Hunters (GET /, /log, /meine-zeiten, /report/preview) und scheduler.run_reminders/web._all_projects.

**Voraussetzungen.** Unauthentifiziert: die Webhook-Route akzeptiert den Body ohne Durchsetzung von SHARED_SECRET (secret_ok berechnet, Response immer 200).; Der Webhook-Pfad muss fuer den Angreifer erreichbar sein; die Caddy-IP-Sperre schuetzt nur /report/*, nicht den Webhook.; Die Poison-Zeile verbleibt in events.jsonl; Wiederherstellung erfordert manuelles Dateieditieren, da der In-App-Loeschpfad dieselbe Zeile re-parst und ebenfalls scheitert.

**Fix.** Numerischen Zeitstempel vor der Konvertierung validieren und Parse-Fehler pro Record isolieren. In _parse_time nicht-endliche Floats ablehnen und den Epoch-Bereich begrenzen (math.isfinite plus vernuenftige 1970..2100-Schranke) sowie fromtimestamp in try/except kapseln und None zurueckgeben. Zusaetzlich normalize (bzw. die _punches-Comprehension) so haerten, dass Exceptions pro Record gefangen werden, damit eine fehlerhafte Zeile uebersprungen statt jeder Leser gebrochen wird; dieselbe Haertung in delete_interval, damit Poison-Records loeschbar bleiben. Hinweis: fuer den Fix ist zusaetzlich 'import math' in events.py noetig (timezone ist bereits importiert).

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`events.py`

```
if isinstance(value, (int, float)):
        ts = float(value)
        if not math.isfinite(ts):
            return None
        if ts > 1e12:
            ts /= 1000.0
        if not (0 <= ts <= 4102444800):  # 1970..2100
            return None
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
```

## 2FA-Einrichtung akzeptiert Sitzung nach reinem Passwortschritt und ersetzt bestehenden zweiten Faktor

- Schwere: **hoch** – Fingerprint `web.py:twofa_setup:pending_user-replaces-enrolled-totp`
- Stand: behoben – Einrichtung nur bei Erst-Einrichtung bzw. mit aktuellem Code; 2FA-Login nach 5 Fehlversuchen abgebrochen

**Beschreibung.** Nach korrektem Passwort setzt POST /login für Konten mit aktiver 2FA nur session['pending_user'] und leitet auf /login/2fa. GET/POST /2fa/setup akzeptieren pending_user jedoch ohne Prüfung, ob das Konto bereits twofa_enabled ist oder ob der Passwortschritt überhaupt eine Ersteinrichtung ausgelöst hat. Wer nur das Passwort kennt, kann so ein selbst erzeugtes TOTP-Geheimnis einschreiben; POST /2fa/setup ruft dann _finalize_login und erzeugt eine vollständige Sitzung mit der Rolle des Kontos. Der vorhandene zweite Faktor wird übersprungen und dauerhaft überschrieben (Eigentümer ist ausgesperrt). Unabhängig von TWOFA_REQUIRED (true und false lokal geprüft).

**Soll-Verhalten.** Ein Konto mit aktiver 2FA darf nur nach erfolgreicher Prüfung des bestehenden zweiten Faktors (/login/2fa) angemeldet werden. /2fa/setup mit pending_user darf nur für Konten ohne 2FA in einem explizit markierten Ersteinrichtungs-Zustand funktionieren; eine Neu-Einrichtung durch angemeldete Nutzer erfordert die Bestätigung des aktuellen Faktors.

**Trace**

1. `web.py:2370` (entrypoint) – Anonymer POST /login: Passwort korrekt, Konto hat twofa_enabled+totp_secret -> session['pending_user'] = username (web.py:2380-2382), Redirect /login/2fa
2. `web.py:2497` (propagation) – uname = pending_user or _user(request) ohne twofa_enabled-Prüfung; erzeugt und speichert enroll_secret in der Sitzung und zeigt es an
3. `web.py:2527` (propagation) – Prüft den Code nur gegen das neue enroll_secret, dann users.enroll_totp(uname, secret) -> bestehendes totp_secret überschrieben
4. `web.py:2531` (sink) – pending_user gesetzt -> _finalize_login(request, u): vollständige Sitzung (user, role, tk_*, fix_times) ohne Prüfung des bisherigen Faktors

**Belege**

- `web.py:2519` – twofa_setup_save: uname = request.session.get('pending_user') or _user(request) – keine Prüfung bestehender 2FA (identisch web.py:2497 im GET-Handler)
- `web.py:2380` – login_submit setzt für 2FA-Konten denselben pending_user-Schlüssel wie für die Ersteinrichtung (web.py:2385)
- `users.py:216` – enroll_totp ersetzt totp_secret bedingungslos und setzt twofa_enabled=True
- `web.py:2358` – _finalize_login schreibt die Rolle des Kontos in die Sitzung; Gates wie /users vertrauen ihr
- `web.py:2487` – Vergleich: twofa_verify prüft gegen das gespeicherte totp_secret – diese Kontrolle wird über /2fa/setup umgangen

**Akteur (Dummy).** Person mit dem Passwort, aber ohne Authenticator eines 2FA-geschützten lokalen Kontos

**Lokale Reproduktion.** ['Lokaler Regressionstest (Sandbox, kein Netz, Datenpfade im Scratch, gepinnte fastapi 0.115.6/starlette 0.41.3, SESSION_SECRET Dummy, SCHEDULER_ENABLED=false), ausgeführt mit TWOFA_REQUIRED=true und =false: Starlette-TestClient gegen app.app.', 'POST /login nur mit Passwort; Kontrolle GET /users; GET /2fa/setup und neues Geheimnis aus der Antwort lesen; POST /2fa/setup mit Code zu S2; GET /users; gespeichertes totp_secret prüfen; frischer Client: POST /login + POST /login/2fa mit Code zu S1.', 'Regressionstest nach Fix: Schritt GET/POST /2fa/setup muss für ein Konto mit aktiver 2FA bei reinem pending_user 303 /login liefern, totp_secret bleibt S1, GET /users bleibt 303 /login; Ersteinrichtung (Konto ohne 2FA, TWOFA_REQUIRED) und Einladung müssen weiter funktionieren.']

**Beobachtet.** Für beide TWOFA_REQUIRED-Werte identisch: POST /login -> 303 /login/2fa; Kontrolle GET /users -> 303 /login; GET /2fa/setup -> 200 mit neuem Geheimnis S2 != S1; POST /2fa/setup -> 303 /start; GET /users (nur admin) -> 200; gespeichertes totp_secret == S2; späterer Login des Eigentümers mit S1-Code -> 303 /login/2fa (abgelehnt). Artefakte: agents/v3-pa-09/artifacts/v_result_true.txt, agents/v3-pa-09/artifacts/v_result_false.txt, Harness agents/v3-pa-09/artifacts/v_check.py; deckt sich mit agents/pa-h3a/artifacts/evidence_2fa_setup.txt.

**Voraussetzungen.** Kenntnis des Passworts eines lokalen Kontos mit aktiver 2FA (genau das Szenario, gegen das 2FA schützen soll); kein zweiter Faktor nötig; Lokale Passwortanmeldung erreichbar (Standard; bei aktivem Microsoft-Login über /login?local=1 bzw. direkten POST /login). Unabhängig von TWOFA_REQUIRED.; Zielkonto ist ein lokales Konto mit Passwort (Microsoft-Konten haben kein Passwort)

**Fix.** Ersteinrichtungs-Zustand explizit trennen: pending_enroll nur in login_submit (TWOFA_REQUIRED-Zweig) und invite_submit setzen; /2fa/setup mit pending_user nur zulassen, wenn pending_enroll gesetzt ist und das Konto keine aktive 2FA hat. Für bereits angemeldete Nutzer Neu-Einrichtung nur nach Prüfung eines aktuellen Codes zum gespeicherten Geheimnis. Regressionstest wie oben ergänzen.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`web.py`

```
# Login (web.py:2380ff): Ersteinrichtung explizit markieren
    if user.get("twofa_enabled") and user.get("totp_secret"):
        request.session["pending_user"] = user["username"]
        request.session.pop("pending_enroll", None)
        return RedirectResponse("/login/2fa", status_code=303)
    if config.TWOFA_REQUIRED:
        request.session["pending_user"] = user["username"]
        request.session["pending_enroll"] = True
        return RedirectResponse("/2fa/setup", status_code=303)
# (analog invite_submit, web.py:4366ff: pending_enroll = True setzen)

def _setup_user(request: Request) -> str | None:
    """Wer darf /2fa/setup benutzen?"""
    pending = request.session.get("pending_user")
    if pending:
        u = users.get(pending)
        if (not u or not request.session.get("pending_enroll")
                or (u.get("twofa_enabled") and u.get("totp_secret"))):
            return None  # bestehende 2FA nur ueber /login/2fa
        return pending
    return _user(request)  # voll angemeldet (inkl. 2FA)

# twofa_setup_form / twofa_setup_save:
    uname = _setup_user(request)
    if not uname:
        return RedirectResponse("/login", status_code=303)
# twofa_setup_save zusaetzlich fuer angemeldete Nutzer mit aktiver 2FA:
# Formularfeld current_code gegen das gespeicherte totp_secret pruefen,
# bevor users.enroll_totp das Geheimnis ersetzt.
# _finalize_login: request.session.pop("pending_enroll", None)
```

## Webhook-Bodys wachsen unbegrenzt in events.jsonl und werden bei jeder Intranet-Ansicht vollständig neu geparst (22 Traversierungen pro Datensatz), synchron auf der Event-Loop

- Schwere: **mittel** – Fingerprint `events.jsonl:webhook-body-unbounded-append-and-full-reparse-per-view`
- Stand: behoben – Body-Limit 64 KiB (413), nur erlaubte Header, Rohbody nur bei JSON-Fehler

**Beschreibung.** Der TimeMoto-Webhook (app.py:97-148) puffert Request-Bodys beliebiger Größe (`await request.body()`), speichert jeden Body als body_raw-String plus geparste Kopie body_json plus alle Header (~2,15-fache Größe) per Append in /data/events.jsonl und druckt ihn zusätzlich eingerückt auf stdout (Docker-Logs ohne Rotation). Es gibt weder Body-Limit (App, uvicorn, Caddy-handle{}) noch Rotation/Retention der Datei. Jeder Lesepfad (Dashboard, /log, Berichte, Scheduler) lädt die gesamte Datei neu und normalisiert jeden Datensatz; normalize() ruft _find_first 22-mal auf, und jeder Aufruf materialisiert list(_iter_pairs(body)) über den gesamten Body. Das Dashboard (async def) führt 4 solcher Vollläufe synchron auf der gemeinsamen uvicorn-Event-Loop aus. Ein einzelner billiger Request erzeugt damit dauerhafte, linear mit den gespeicherten Bytes wachsende CPU-Kosten pro Ansicht für alle Intranet-Nutzer, bis ein Operator die Datei manuell bereinigt. Unabhängig von der separat erfassten Ursache „Webhook-Secret nicht durchgesetzt“: hier fehlen Größen-/Aggregatgrenzen und der Lesepfad parst alles bei jedem Request neu.

**Soll-Verhalten.** Webhook-Bodys oberhalb einer kleinen Grenze (TimeMoto-Stempelungen < 4 KiB) werden vor dem Puffern mit 413 abgewiesen; gespeicherte Events sind kompakt (nur geparster Body, Header-Allowlist) und die Datei wird rotiert/begrenzt; Lesepfade nutzen einen gecachten bzw. inkrementellen Parse, normalisieren jeden Body mit einer einzigen begrenzten Traversierung und laufen nicht auf der Event-Loop.

**Trace**

1. `app.py:100` (entrypoint) – `raw = await request.body()` puffert den gesamten Body ohne Größenprüfung; Route ist öffentlich über Caddy handle{} -> 127.0.0.1:8080 erreichbar.
2. `app.py:132` (propagation) – Record enthält body_raw (String), body_json (geparste Kopie, app.py:133) und alle Header (app.py:130); zusätzlich Pretty-Print auf stdout (app.py:139/141).
3. `app.py:146` (propagation) – Append in config.LOG_FILE (/data/events.jsonl, config.py:61); keine Rotation/Retention, einziges Umschreiben ist die manuelle events.delete_interval.
4. `events.py:215` (propagation) – Jeder Lesezugriff lädt und json-parst jede Zeile der gesamten Datei, ohne Cache.
5. `events.py:129` (propagation) – Materialisiert list(_iter_pairs(body)) über den gesamten Body; normalize() ruft dies 6 + 6 (_DELETED_FLAG_KEYS) + 10 (_DELETE_KEYS) = 22-mal pro Datensatz auf (events.py:268-300).
6. `report.py:20` (propagation) – collect_intervals/collect_open normalisieren bei jedem Aufruf alle Datensätze; build_report (report.py:186) und detail_sessions rufen collect_intervals jeweils neu auf.
7. `web.py:2643` (sink) – build_report, detail_sessions, _inspect_stats (web.py:2666) und _all_projects (web.py:2673) = 4 Vollläufe synchron auf der gemeinsamen Event-Loop; /log (web.py:2716) und Scheduler (scheduler.py:59) analog.

**Belege**

- `app.py:100` – Unbegrenztes Lesen des Request-Bodys vor jeder Prüfung.
- `deploy/caddy-intern.snippet:42` – reverse_proxy 127.0.0.1:8080 für alle Nicht-/report-Pfade ohne request_body max_size.
- `Dockerfile:16` – uvicorn ohne Body-/Concurrency-Limit (uvicorn kennt kein Body-Limit).
- `events.py:129` – Vollständige Materialisierung des Bodys pro _find_first-Aufruf.
- `events.py:290` – Schleifen pro Lösch-Key mit je einem eigenen _find_first-Aufruf (6 + 10 zusätzliche Traversierungen).
- `web.py:2666` – _inspect_stats parst bei jeder Dashboard-Ansicht das gesamte Log erneut.
- `agents/v3-pa-18/artifacts/v3pa18_evidence.txt:1` – Unabhängige begrenzte Sandbox-Messung mit den echten Modulen events/report/config: 130.146-Byte-Body -> +280.533 Byte Log; 520.146-Byte-Body -> +1.120.533 Byte (2,15x); je 22 _find_first-Aufrufe pro normalize(); normalize 0,053 s bzw. 0,274 s; ein collect_intervals-Lauf 0,0002 s (Baseline) -> 0,074 s -> 0,322 s (linear in gespeicherten Bytes).

**Akteur (Dummy).** Unauthentifizierter Internet-Client, der per POST an den Webhook-Pfad senden kann; betroffen sind alle angemeldeten Intranet-Nutzer (Dashboard/Log) und der Scheduler.

**Lokale Reproduktion.** ['In der Sandbox (kein Netz, nobody, Scratch-tmpfs) LOG_FILE=data/events.jsonl setzen und den Datensatz exakt wie app.receive (app.py:100-146) aufbauen und anhängen.', 'Dateiwachstum messen, _find_first-Aufrufe in einem events.normalize() zählen und einen report.collect_intervals()-Lauf timen; mit 5.000 und 20.000 Keys wiederholen, um Linearität zu prüfen.']

**Beobachtet.** 520.146-Byte-Body ließ events.jsonl um 1.120.533 Byte wachsen (2,15x); normalize() führte 22 vollständige Body-Traversierungen aus (0,274 s); ein collect_intervals()-Lauf stieg von 0,0002 s (Baseline) auf 0,322 s, ~linear zu 0,074 s bei 130 KB. Das Dashboard führt pro Ansicht ~4 solche Läufe synchron auf der Event-Loop aus (Quelle web.py:2643-2673); Dauer-Effekt bis zur manuellen Bereinigung.

**Voraussetzungen.** Webhook-Pfad wird vom Host-Caddy öffentlich an 127.0.0.1:8080 geroutet; kein quellsichtbares Body- oder Ratenlimit davor. Ein etwaiges Upstream-CDN/WAF-Limit liegt außerhalb des Repos und begrenzt nur die Einzelgröße, nicht das Aggregatwachstum.; Am billigsten, solange der Webhook unauthentifizierte Schreibzugriffe annimmt (separat erfasste Ursache: secret_ok wird nicht durchgesetzt, bzw. leeres SHARED_SECRET). Auch mit durchgesetztem Secret wird der Body vor jeder Prüfung vollständig gepuffert.; Die Wirkung bleibt in /data/events.jsonl bestehen, bis ein Operator die Datensätze manuell entfernt; Docker-stdout-Logs wachsen ohne Rotation mit.

**Fix.** Webhook-Body begrenzen (Caddy request_body max_size und App-seitig 413 oberhalb z. B. 64 KiB, Stream statt request.body()); kompakten Datensatz speichern (nur geparster Body, Header-Allowlist, keine Secret-Header); kein Pretty-Print ganzer Bodys auf stdout und Docker-Log-Rotation setzen; normalize() mit einer einzigen begrenzten Traversierung (Index einmal bauen); geparste Punches gecacht nach (st_size, st_mtime_ns) oder inkrementell lesen; Parse aus der Event-Loop nehmen (def-Handler bzw. run_in_threadpool); Rotation/Retention für events.jsonl.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`app.py`

```
MAX_WEBHOOK_BYTES = 64 * 1024

@app.api_route(config.WEBHOOK_PATH, methods=["POST", "GET", "PUT"])
async def receive(request: Request):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_WEBHOOK_BYTES:
        return JSONResponse({"error": "too large"}, status_code=413)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_WEBHOOK_BYTES:
            return JSONResponse({"error": "too large"}, status_code=413)
    raw = bytes(buf)
    # ... Secret-Pruefung (durchgesetzt) ...
    record = {"received_at": _now(), "method": request.method,
              "headers": {k: v for k, v in request.headers.items() if k in ("content-type", "user-agent")},
              "body_json": parsed,
              "body_raw": None if parsed is not None else raw.decode("utf-8", "replace")[:4096]}
    print(f"[{record['received_at']}] webhook {len(raw)} bytes", flush=True)
```

`events.py`

```
def _index(obj, limit=2000):
    out = {}
    for n, (k, v) in enumerate(_iter_pairs(obj)):
        if n >= limit:
            break
        out[str(k).lower()] = v  # gleiche Semantik wie bisher: letzter Treffer gewinnt
    return out

def _pick(idx, keys):
    for k in keys:
        v = idx.get(k)
        if v not in (None, "", []):
            return v
    return None

# normalize(): idx = _index(body) einmal, danach _pick(idx, _TIME_KEYS) usw.

_cache = {"key": None, "punches": []}
def load_punches():
    st = config.LOG_FILE.stat()
    key = (st.st_size, st.st_mtime_ns)
    if _cache["key"] != key:
        _cache["punches"] = [p for p in (normalize(r) for r in load_records()) if p]
        _cache["key"] = key
    return list(_cache["punches"])
```

`deploy/caddy-intern.snippet`

```
@webhook path /timemoto
	request_body @webhook {
		max_size 64KB
	}
```

`deploy/docker-compose.yml`

```
logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

## fastapi==0.115.6 bindet starlette <0.42, dessen FileResponse-Range-Merge quadratisch ist: unauthentifizierter Aufruf von /v/{slug}/foto blockiert den Event-Loop des gesamten Intranets

- Schwere: **mittel** – Fingerprint `requirements.txt:fastapi-0.115.6:starlette-0.41-FileResponse-range-merge-quadratic`
- Stand: behoben – fastapi 0.143.0 / starlette 1.7.0

**Beschreibung.** requirements.txt pinnt fastapi==0.115.6; dessen Metadaten verlangen starlette>=0.40.0,<0.42.0 (lokal in der installierten fastapi-0.115.6-Metadatei verifiziert: 'Requires-Dist: starlette<0.42.0,>=0.40.0'). Ein frischer Build loest innerhalb dieser Spanne starlette 0.41.3 auf. In dieser Version fuehrt FileResponse._parse_range_header fuer Multi-Range-Anfragen ein Merge mit verschachtelter Schleife (aeusser ueber die geparsten Ranges, inner ueber die wachsende Ergebnisliste) aus; bei disjunkten Ranges ist das O(n^2). Die Route GET /v/{slug}/foto (web.py:3676) liefert oeffentliche Visitenkarten-Fotos ohne Login per FileResponse aus (vcards.by_slug prueft nur valid_slug + enabled). Der Host-Caddy leitet jeden Pfad ausser /report/* an den einzelnen uvicorn-Prozess (Dockerfile:16, keine Worker) weiter und setzt kein Request-Header-Limit und kein Range-Stripping (deploy/caddy-intern.snippet). Eine anonyme Anfrage mit einem Range-Header aus einigen tausend disjunkten Byte-Ranges blockiert damit synchron den Event-Loop; ein kleiner Strom solcher Anfragen haelt das gesamte Intranet (Logins, Webhook-Aufnahme, Verteiler-Auth-Recheck via /auth/verteiler) unresponsiv. Derselbe Sink liegt hinter /download/{token} (web.py:2959), Ticket- und Dokument-Downloads (web.py:3315, 3531), die aber Token/Login erfordern. Der konkrete CVE-/Fix-Versions-Bezug (Angabe des Hunters: CVE-2025-62727, Fix starlette>=0.49.1) ist offline nicht gegenpruefbar; der Defekt ist jedoch unabhaengig vom CVE-Identifier direkt im Quellcode von starlette 0.41.3 belegt.

**Soll-Verhalten.** Eine einzelne unauthentifizierte Anfrage darf nicht superlinear in der angreifergesteuerten Header-Groesse CPU des Event-Loops verbrauchen. Range-Parsing muss begrenzt sein (gefixtes starlette) oder die Anzahl der Ranges limitiert werden.

**Trace**

1. `deploy/caddy-intern.snippet:42` (entrypoint) – Host-Caddy reverse_proxyt jede oeffentliche Anfrage inkl. /v/{slug}/foto mit ihrem Range-Header an 127.0.0.1:8080; im Snippet ist kein Request-Header-Limit und kein Range-Stripping konfiguriert (nur /report/* extern 403, Zeile 36-40).
2. `web.py:3676` (propagation) – Oeffentliche Route ohne Session-Pruefung; vcards.by_slug (vcards.py:93-101) gibt nur valid_slug-gepruefte, aktivierte Karten mit vorhandenem Foto zurueck.
3. `requirements.txt:1` (propagation) – Pin installiert starlette innerhalb >=0.40.0,<0.42.0 (installierte fastapi-Metadaten verifiziert; Dockerfile:6 pip install).
4. `web.py:3681` (sink) – starlette 0.41.3 FileResponse.__call__ ruft synchron _parse_range_header auf (responses.py:351); dessen Merge-Schleife (responses.py:472-489, aeusser ueber Ranges, inner ueber wachsendes result) ist bei disjunkten Ranges O(n^2) und blockiert den Event-Loop.

**Belege**

- `requirements.txt:1` – fastapi==0.115.6; installierte Metadaten 'Requires-Dist: starlette<0.42.0,>=0.40.0' (lokal gelesen).
- `Dockerfile:16` – Einzelner uvicorn-Prozess ohne --workers bedient alle Routen; Blockieren des Loops blockiert die gesamte App.
- `web.py:3681` – FileResponse auf der oeffentlichen Foto-Route; gleicher Sink (token-/login-geschuetzt) bei web.py:2959 (/download/{token}), 3315, 3531.
- `deploy/caddy-intern.snippet:40` – Nur /report/* wird am Proxy (extern) eingeschraenkt; /v/* passiert ungefiltert, kein Header-Groessenlimit gesetzt.

**Akteur (Dummy).** Anonymer Internet-Client, der einen oeffentlichen vCard-Slug kennt (z.B. von einer gedruckten Karte oder einem QR-Code).

**Lokale Reproduktion.** ['Nur lokal, in der OS-erzwungenen Sandbox (unshare net/mount/pid, ro-Root, nobody, prlimit, timeout 300 s): verifizierte Kopie von starlette 0.41.3 (dieselbe Version, die fastapi==0.115.6 aufloest) nach /tmp/sl in der tmpfs kopieren und per sys.path einbinden.', 'FileResponse._parse_range_header mit 500/1000/2000/4000 disjunkten Single-Byte-Ranges gegen eine 1-MB-Dummy-Datei in Scratch zeiten und das Zeitverhaeltnis pro Verdopplung messen.', 'Zusaetzlich (Hunter-Artefakt) eine Loopback-uvicorn-Fixture mit demselben gepinnten Stack starten, die web.py:3675-3682 nachbildet, und die Latenz eines parallelen GET /ping waehrend einer Multi-Range-Anfrage gegen den Idle-Wert messen.']

**Beobachtet.** Unabhaengig reproduziert (v3-pa-08, Sandbox, starlette 0.41.3): _parse_range_header t = 0,005 / 0,019 / 0,092 / 0,363 s fuer 500 / 1000 / 2000 / 4000 Ranges (~x4 pro Verdopplung => O(n^2)). Deckt sich mit dem Hunter-Lauf (0,019 / 0,085 / 0,335 / 1,491 s fuer 1000-8000 Ranges) und seiner Loopback-Fixture: ein GET mit 84.904-Byte-Range-Header wurde angenommen (206, 6,4 s), ein paralleles GET /ping dauerte 1,554 s statt 0,001 s idle; voller FileResponse-Aufruf mit 4000 Ranges => Status 206, max. Event-Loop-Luecke 0,330 s.

**Voraussetzungen.** Mindestens eine aktivierte Visitenkarte mit hochgeladenem Foto (oeffentlicher Slug, per Design auf Karten/QR gedruckt). Fuer n disjunkte Single-Byte-Ranges muss die Fotogroesse > 2*(n-1) Byte sein (z.B. >~16 KB fuer 8000 Ranges); reale Kartenfotos liegen deutlich darueber.; Caddy 2.6 leitet Request-Header weiter; Go net/http Default MaxHeaderBytes ~1 MiB, im Snippet nichts Kleineres gesetzt, sodass ein ~85-KB-Range-Header durchgeht. Caddy ist lokal nicht installiert; der 39-KB/4000-Range-Fall (schon ~0,36 s Blockade) liegt weit unter jedem plausiblen Limit.; Keine - anonymer Internet-Client, der einen oeffentlichen vCard-Slug kennt.

**Fix.** fastapi auf eine Version anheben, deren starlette-Spanne starlette mit begrenztem Range-Merging (lt. veroeffentlichter Advisory >=0.49.1, vom Entwickler via OSV gegenpruefen) zulaesst, und starlette explizit pinnen, damit der Build fehlschlaegt statt still eine alte Version aufzuloesen. Als Defense-in-Depth Range auf den oeffentlichen Foto-Routen entfernen/begrenzen (Foto als Plain-Response statt FileResponse ausliefern, oder Caddy 'request_header -Range' fuer /v/*) und einen Regressionstest ergaenzen, der einen 1000-Range-Header ablehnt oder in linearer Zeit abarbeitet.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`requirements.txt`

```
fastapi==<Release, das starlette>=0.49.1 erlaubt>
starlette>=0.49.1
uvicorn[standard]==0.34.0
...
```

`web.py`

```
@router.get("/v/{slug}/foto")
async def vcard_public_photo(slug: str):
    c = vcards.by_slug(slug)
    if not c or not c.get("photo") or not Path(c["photo"]).exists():
        return HTMLResponse("Nicht gefunden.", status_code=404, headers=_PUB_HEADERS)
    data = Path(c["photo"]).read_bytes()  # kleines Bild; kein Range-Handling
    return Response(data, media_type=mimetypes.guess_type(c["photo"])[0] or "application/octet-stream", headers=_PUB_HEADERS)
```

## Externe Absender können über das Verteiler-Postfach beliebige Adressen (und Namen) ohne Einwilligung in die automatisch zum Mailing-Tool synchronisierte Empfängerliste bringen

- Schwere: **mittel** – Fingerprint `verteiler/verteiler_core/postfach.py:abrufen:external-sender-addresses-synced-without-consent`
- Stand: behoben – Postfach-Kontakte ohne Einwilligung gehen in kein Segment

**Beschreibung.** Mit „Automatisch abrufen“ wertet verteiler-hintergrund jede Mail im Posteingang des Verteiler-Postfachs aus, unabhängig vom Absender (laut README bewusst auch „direkt geschickt“). Alle Adressen aus From/To/CC und bis zu 1000 Adressen aus dem Mailtext werden als Kontakte mit status='aktiv' und leerer Einwilligung angelegt; Namen der Form „Name <adr>“ füllen leere Namensfelder neuer und bestehender Kontakte. segment_kontakte('alle_aktiven') wählt nur nach Status und Sperrliste, nicht nach Einwilligung, und mailing.abgleichen (automatisch alle 10 Minuten bei mailing_aktiv=1) überträgt dieses Segment als Liste „Verteiler: Alle aktiven“ ohne Einwilligungsinformation an das Mailing-Tool. Ein nicht authentifizierter Außenstehender, der nur eine Mail an die Postfach-Adresse schickt, bestimmt damit Mitglieder und Anrede-Namen der Kampagnenliste. Die dokumentierte Regel „Einwilligung nachtragen, bevor sie einen Newsletter bekommen (§ 7 UWG)“ wird nirgends im Code durchgesetzt und ist nach dem automatischen Abgleich im Mailing-Tool auch nicht mehr prüfbar, weil die Liste keine Einwilligungsangabe trägt.

**Soll-Verhalten.** Aus Mails geerntete Adressen dürfen erst nach erfasster Einwilligung (bzw. expliziter Freigabe durch einen Admin) in ein versandfähiges Segment, den CSV-Export oder die Mailing-Tool-Liste gelangen; ein externer Absender darf die Versandliste nicht unmittelbar verändern.

**Trace**

1. `verteiler/verteiler_core/postfach.py:609` (entrypoint) – Alle Posteingangs-Mails ab dem Zeitfenster werden geholt; gefiltert wird nur nach bereits bekannter Message-ID, nicht nach Absender. Aufruf automatisch aus hintergrund.ein_durchlauf (hintergrund.py:36-39) bei postfach_aktiv=1.
2. `verteiler/verteiler_core/postfach.py:418` (propagation) – Adressen und Namen aus dem vom Absender kontrollierten Mailtext (plus From/To/CC), bis MAX_ADRESSEN_PRO_MAIL=1000; ignoriert werden nur Postfach, eigene Domains und Systemadressen (ignorieren_grund, Zeile 360).
3. `verteiler/verteiler_core/postfach.py:630` (propagation) – analysiere_kontakte im Modus 'ergaenzen': neue Kontakte werden geplant, leere Namen bestehender Kontakte gefüllt.
4. `verteiler/verteiler_core/imports.py:279` (propagation) – INSERT mit festem status 'aktiv' und leeren Einwilligungsfeldern.
5. `verteiler/verteiler_core/queries.py:58` (propagation) – Segmentbedingung nur status IN ('aktiv','bounce_weich') und nicht gesperrt – keine Einwilligungsbedingung.
6. `verteiler/verteiler_core/mailing.py:216` (propagation) – Segment wird als Listen-Nutzlast {name: 'Verteiler: Alle aktiven', contacts: [email, firstName, lastName, company]} ohne Einwilligungsangabe gebaut.
7. `verteiler/verteiler_core/mailing.py:219` (sink) – _senden überträgt die Liste per POST /api/integration/verteiler an das Mailing-Tool; automatisch alle 10 Minuten aus hintergrund.py:45-47 bei mailing_aktiv=1.

**Belege**

- `verteiler/verteiler_core/postfach.py:360` – ignorieren_grund schließt nur Postfach, eigene Domains und System-Localparts aus; externe Absender- und Textadressen werden übernommen.
- `verteiler/verteiler_core/postfach.py:50` – MAX_ADRESSEN_PRO_MAIL = 1000 (Zeile 49: MAX_MAILS_PRO_LAUF = 200) je Lauf, Standardintervall 10 Minuten.
- `verteiler/verteiler_core/queries.py:24` – VERSANDFAEHIG = ('aktiv', 'bounce_weich'); einwilligung_* wird in keiner Abfrage des Pakets gefiltert (nur in Formular/Normalisierung verwendet).
- `verteiler/verteiler_core/mailing.py:198` – Empfängerliste direkt aus segment_kontakte gebaut, ohne Einwilligungsfeld.
- `verteiler/README.md:133` – Postfach-Ernte ist bewusst für alle ankommenden Mails vorgesehen („weitergeleitet, in CC gesetzt oder direkt geschickt“) – die Absenderoffenheit ist Design, die Kontrolle muss daher vor dem Versandsegment liegen.
- `verteiler/README.md:153` – Dokumentierte Regel: „Einwilligung nachtragen, bevor sie einen Newsletter bekommen (§ 7 UWG)“ – im Code nicht durchgesetzt.
- `verteiler/app.py:787` – UI-Hinweis zur Einwilligung vor Newsletter-Versand – reiner Text.
- `agents/v3-pa-06/artifacts/postfach_verify.txt:1` – Unabhängige Sandbox-Reproduktion (Harness agents/v3-pa-06/artifacts/harness.py): 1 externe Mail -> 3 neue aktive Kontakte ohne Einwilligung, leerer Name eines Bestandskontakts mit Text aus der Mail gefüllt, alle 4 Adressen in segment alle_aktiven und in der erfassten Mailing-Tool-Liste „Verteiler: Alle aktiven“.

**Akteur (Dummy).** Externer, nicht authentifizierter E-Mail-Absender.

**Lokale Reproduktion.** ['In der OS-Sandbox (kein Netz, nobody, prlimit, DB in Sandbox-/tmp) Dummy-SQLite-DB mit postfach_adresse=verteiler@fbe.example, postfach_aktiv=1 und Bestandskontakt kunde@kunde.example (leere Namen, aktiv) anlegen.', 'postfach.abrufen(..., graph=FakeGraph, nur_wenn_aktiv=True) aufrufen; FakeGraph erbt von postfach.Graph und überschreibt nur token()/_get(), das die eine Dummy-Mail liefert.', "Kontakte und queries.segment_kontakte(conn, 'alle_aktiven') auslesen, mailing_aktiv=1 setzen und mailing.abgleichen mit Dummy-Zugang aufrufen, wobei mailing._senden durch einen Erfassungs-Stub ersetzt ist (kein Netz)."]

**Beobachtet.** abrufen: '1 neue Mail(s) ausgewertet: 4 Adressen gefunden, 3 neue Kontakte, 1 schon vorhanden, 0 auf der Sperrliste, 1 ignoriert'. angreifer@extern.example, dritte1@dritte.example (vorname 'Erika', nachname 'Beispiel') und dritte2@dritte.example haben status 'aktiv' und leere einwilligung_art; kunde@kunde.example hat jetzt vorname 'Test', nachname 'Name'. segment alle_aktiven und die an _senden übergebene Liste 'Verteiler: Alle aktiven' enthalten alle 4 Adressen inkl. firstName 'Test' für kunde@kunde.example.

**Voraussetzungen.** Keine: der Angreifer muss nur eine Mail an die konfigurierte Verteiler-Postfach-Adresse senden (Beispieladresse verteiler@fb-eng.de steht im README).; Postfach „Automatisch abrufen“ aktiv (postfach_aktiv=1, verbundenes Postfach) und Mailing-Abgleich aktiv (mailing_aktiv=1, MAILING_SYNC_TOKEN gesetzt) mit Segment alle_aktiven (Standard). Ohne Mailing-Abgleich landen die Adressen trotzdem im Segment/CSV-Export.; Der eigentliche Versand erfolgt erst, wenn Mitarbeitende eine Kampagne an die synchronisierte Liste schicken; eine etwaige Einwilligungsprüfung im Mailing-Tool (separates Repo) wurde nicht bewertet – die übertragene Nutzlast enthält jedoch keine Einwilligungsangabe.

**Fix.** Zwischen Postfach-Ernte und Versandsegment eine Einwilligungs-/Freigabestufe erzwingen: (1) segment_kontakte (und damit CSV-Export und mailing.abgleichen) schließt Kontakte aus Postfach-Quelle ohne erfasste Einwilligung aus – gezielt, damit Altbestände aus Datei-Importen nicht ungewollt herausfallen; langfristig besser eine explizite Spalte/Status „unbestätigt“, der erst mit Einwilligung bzw. Admin-Freigabe auf 'aktiv' wechselt (Achtung: status hat einen CHECK-Constraint, erfordert Migration). (2) Optional eine einstellbare Absender-Positivliste (eigene Domains/Weiterleitende), wenn direkt geschickte Fremdmails nicht gewollt sind – laut README sind sie derzeit vorgesehen. (3) Namen aus Fremdmails nicht in Bestandskontakte übernehmen. Regressionstest (tests/test_verteiler.py, unittest): FakeGraph-Mail eines externen Absenders mit Textadressen -> segment_kontakte(conn, 'alle_aktiven') und die von abgleichen an einen _senden-Stub übergebene Liste enthalten diese Adressen nicht; nach Eintragen von einwilligung_art über queries-Update erscheinen sie.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`verteiler/verteiler_core/queries.py`

```
bedingungen = [f"c.status IN ({', '.join(status_platzhalter)})", _NICHT_GESPERRT,
                   # Aus Mails geerntete Adressen erst nach erfasster Einwilligung versenden
                   "NOT (c.quelle LIKE 'Postfach:%' AND c.einwilligung_art = '')"]
```

`verteiler/verteiler_core/postfach.py`

```
plan = imports.analysiere_kontakte(
                    conn, zeilen, {"email": "email", "vorname": "vorname", "nachname": "nachname"},
                    {"quelle": f"Postfach: {betreff[:100]}"}, "ergaenzen")
                # Namen aus fremden Mails nicht in Bestandskontakte übernehmen
                plan.aktualisieren = []
```

## Meine Zeiten: Owner-Zuordnung über selbst änderbaren Anzeigenamen erlaubt Lesen und Ändern fremder Arbeitszeiten

- Schwere: **mittel** – Fingerprint `web.py:_my_timemoto/display-name-fallback-owner-scope`
- Stand: behoben – nur noch admin-gepflegter timemoto_name, exakter Vergleich

**Beschreibung.** Hat ein Konto keinen vom Admin gepflegten timemoto_name (Standard bei Microsoft-Login/-Import, users.py:315, und bei Einladung ohne TimeMoto-Namen, users.py:142), leitet _my_timemoto() (web.py:3430-3438) die Owner-Identität aus session['name'] ab. Diesen Anzeigenamen setzt jeder angemeldete Benutzer (Rolle 'user', ohne Zusatzrechte) frei über POST /account/name (web.py:3973-3979); es gibt keine Prüfung auf Eindeutigkeit oder Übereinstimmung mit einem TimeMoto-Mitarbeiter. Mit dem Namen eines Kollegen liefert /meine-zeiten (und /start, web.py:2432) dessen Buchungen der letzten 60 Tage inkl. Projekt, Zeiten, Tätigkeiten und laufender Buchungen. Die Schreibrouten /meine-zeiten/describe, /save und /delete prüfen nur Gleichheit mit diesem selbst gesetzten Namen; damit kann der Angreifer Tätigkeiten des Opfers überschreiben, Original-TimeMoto-Buchungen ausblenden und durch eigene Zeiten ersetzen (manual.hide + add_entry), manuelle Einträge des Opfers löschen und neue Stunden auf das Opfer buchen. Zusätzlich filtert die Leseansicht per Teilstring (report.py:158, web.py:3717): ein Anzeigename wie 'o' zeigt Buchungen aller Mitarbeiter, deren Name 'o' enthält. Diese Daten sind sonst nur für admin/buchhaltung/'Zeiten korrigieren' (_need_timekeeper, web.py:2298) zugänglich; die Änderungen fließen in Abrechnung, Berichte und Exporte. Das Audit-Log protokolliert den Angreifer-Benutzernamen (Erkennung möglich, keine Verhinderung).

**Soll-Verhalten.** Ein Benutzer ohne Recht 'Zeiten korrigieren' darf nur eigene Buchungen sehen und bearbeiten. Die Bindung Konto→TimeMoto-Mitarbeiter muss vom Admin (timemoto_name) bzw. über eine nicht selbst änderbare Identität erfolgen und in allen Lese- und Schreibpfaden exakt (case-insensitiv) verglichen werden.

**Trace**

1. `web.py:3974` (entrypoint) – POST /account/name: nur _need_login; beliebiger Name wird per users.set_name gespeichert (web.py:3978) und in request.session['name'] übernommen (web.py:3979).
2. `web.py:3438` (propagation) – Ohne timemoto_name wird session['name'] als effektiver TimeMoto-Name zurückgegeben.
3. `web.py:3709` (propagation) – filter_intervals(start, None, employee=tm) liefert Buchungen zum gewählten Namen; offene Buchungen per Teilstring (web.py:3717).
4. `report.py:158` (propagation) – Mitarbeiterfilter ist Teilstring-Vergleich (emp not in iv.employee.lower()).
5. `web.py:3750` (propagation) – Schreibpfade prüfen nur iv.employee.lower() == tm.lower() (web.py:3741, 3756) mit tm aus dem selbst gesetzten Namen.
6. `web.py:3838` (sink) – manual.add_entry(employee=tm) (web.py:3837) + manual.hide(iid): Original-TimeMoto-Buchung des Opfers wird ausgeblendet und ersetzt; ferner activities.set_description (web.py:3743) und manual.delete_entry (web.py:3865).

**Belege**

- `web.py:3438` – return (request.session.get('name') or _user(request) or '').strip(), False – Fallback auf den Anzeigenamen.
- `web.py:3979` – request.session['name'] = (name or username).strip() – Anzeigename frei durch den Benutzer setzbar.
- `users.py:176` – set_name speichert den Namen ohne Eindeutigkeits- oder Zuordnungsprüfung.
- `users.py:315` – upsert_oauth legt Microsoft-Konten mit timemoto_name '' an (import_microsoft nutzt denselben Pfad, users.py:335); create_invite ebenso standardmäßig '' (users.py:142).
- `report.py:158` – Teilstring-Filter für Mitarbeiter.
- `web.py:2432` – /start nutzt dieselbe Ableitung (timemoto_name or Anzeigename) und zeigt fremde Buchungen.
- `web.py:2298` – Vergleichskontrolle: /log und globale Korrekturen sind auf admin/buchhaltung/fix_times beschränkt (_need_timekeeper).
- `agents/v3-pa-03/artifacts/verify_owner.txt:1` – Unabhängige lokale Reproduktion (Sandbox, Dummy-Daten, TestClient gegen app.app mit gepinnter venv): Baseline leer/403, nach Namenswechsel Lesen, describe, save/replace und delete fremder Buchungen; Gegenprobe mit gefixtem _my_timemoto leer/403.

**Akteur (Dummy).** Angemeldeter Dummy-Benutzer 'attacker' (Rolle user, timemoto_name leer, keine Ticket-/Zeitkorrektur-Rechte); Opfer 'victim' mit timemoto_name 'Victim Vogel'.

**Lokale Reproduktion.** ['Sandbox (kein Netz, nobody, ro-Root, Scratch-tmpfs, Limits); Pakete aus Kopie der gepinnten Intranet-venv (/tmp/venv-intranet, starlette 0.41.3); Datenpfade per Env in Scratch, SCHEDULER_ENABLED=false, TWOFA_REQUIRED=false, SESSION_HTTPS_ONLY=false.', "Dummy-TimeMoto-Events 'Victim Vogel' (7 h, '90001 - Dummyprojekt') und 'Other Otto' (5 h) in events.jsonl; Benutzer victim (timemoto_name gesetzt) legt selbst einen manuellen Eintrag an; attacker per create_invite ohne timemoto_name.", "Als attacker: Baseline /meine-zeiten, /log, describe auf fremde iid; dann Anzeigenamen 'o' bzw. 'Victim Vogel' setzen, /meine-zeiten und /start abrufen, describe/save/delete ausführen, activities.json und manual.json prüfen, Opfersicht abrufen.", 'Gegenprobe: _my_timemoto in-process durch Variante ohne Anzeigenamen-Fallback ersetzen und dieselben Anfragen wiederholen.', 'Harness: verify_owner.py (via stdin), Ausgabe: verify_owner.txt.']

**Beobachtet.** Baseline: attacker sieht keine Buchungen, /log -> 303, describe auf wh:Victim Vogel:v1 -> 403. Name 'o': iids wh:Other Otto:o1, wh:Victim Vogel:v1 und man:<Opfer> sichtbar. Name 'Victim Vogel': Opferbuchungen inkl. Projekt sichtbar, auch auf /start. describe -> activities.json 'wh:Victim Vogel:v1' by 'attacker'. save -> manual.json hidden ['wh:Victim Vogel:v1'] plus Eintrag ('Victim Vogel','08:00','08:30', created_by 'attacker'). delete -> manueller Eintrag des Opfers entfernt. Opfer sieht danach nur noch 0:30 h statt 7 h + 1 h. Mit gefixtem _my_timemoto: /meine-zeiten leer, describe 403, save Redirect ohne Änderung, Opfer sieht eigene Daten weiterhin.

**Voraussetzungen.** Angreifer ist angemeldeter Intranet-Benutzer (beliebige Rolle, auch 'user' ohne Zusatzrechte).; Das Konto des Angreifers hat keinen admin-gepflegten timemoto_name (Standard bei Microsoft-Login/-Import und bei Einladung ohne TimeMoto-Namen).; Der TimeMoto-Name des Opfers ist bekannt oder erratbar (Vor-/Nachname eines Kollegen); für reines Lesen genügt ein Teilstring.

**Fix.** Owner-Scope ausschließlich aus dem admin-gepflegten timemoto_name ableiten (kein Fallback auf den selbst änderbaren Anzeigenamen in _my_timemoto und /start), alternativ den Fallback einmalig beim Anlegen durch den Admin bzw. aus dem verifizierten Microsoft-Profil in timemoto_name übernehmen und nicht über /account/name änderbar machen. Lesepfade (filter_intervals für meine_zeiten/home, offene Buchungen web.py:3717) exakt case-insensitiv vergleichen. Regressionstest: Benutzer ohne timemoto_name setzt Anzeigenamen auf fremden bzw. Teil-Namen -> /meine-zeiten und /start ohne fremde Buchungen; describe und delete auf fremde iid -> 403; save auf fremde wh:-iid -> keine Änderung an manual.json (Redirect mit Hinweis); Benutzer mit timemoto_name sieht weiterhin nur exakt seine Buchungen.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`web.py`

```
def _my_timemoto(request: Request) -> tuple[str, bool]:
    u = users.get(_user(request)) or {}
    tm = (u.get("timemoto_name") or "").strip()
    return (tm, True) if tm else ("", False)

# /start (home): emp, _ = _my_timemoto(request)
# meine_zeiten: offene Buchungen per (o.employee or "").strip().lower() == tm.lower()
```

`report.py`

```
def filter_intervals(start=None, end=None, project="", employee="",
                     include_no_project=False, employee_exact=False):
    ...
        if emp and ((iv.employee.strip().lower() != emp) if employee_exact
                    else (emp not in iv.employee.lower())):
            continue
# meine_zeiten/home: filter_intervals(..., employee=tm, employee_exact=True)
```

## Rolle und Identität werden nur aus dem signierten Session-Cookie gelesen – Herabstufen, Löschen, Passwortwechsel und Logout entziehen keine Rechte

- Schwere: **mittel** – Fingerprint `web.py:_need_gates:session-cookie-role-not-revalidated`
- Stand: behoben – Konto/Status/Session-Epoche werden bei jeder Anfrage geprüft; Logout/Passwortwechsel beenden alte Sitzungen; Cookie 12 h

**Beschreibung.** _finalize_login (web.py:2353-2366) kopiert Benutzername, Rolle und Rechte-Flags (tk_view, tk_edit, fix_times) in das clientseitige, nur signierte Starlette-Session-Cookie (app.py:64-70, Standard-max_age 14 Tage). _user/_role (web.py:2156-2161) und alle Gates (_need_login/_need_admin/_need_billing/_need_timekeeper/_need_tickets, web.py:2268-2319) lesen ausschließlich dieses Cookie; users.get() wird nicht aufgerufen. Folge: Ein herabgestufter Admin behält Admin-Zugriff, ein gelöschtes Konto bleibt angemeldet und kann z. B. über POST /users/create neue Admin-Konten anlegen (Persistenz über den Cookie-Ablauf hinaus), Passwortwechsel beendet andere Sitzungen nicht, und /logout (web.py:2540-2542) leert nur das Cookie im Browser – eine zuvor kopierte Cookie-Kopie bleibt gültig. /impersonate/stop (web.py:4198-4207) stellt die Admin-Rolle aus dem Cookie-Snapshot wieder her, ebenfalls ohne Neuprüfung. Einzige Route mit Neuprüfung ist /auth/verteiler (web.py:2548-2567).

**Soll-Verhalten.** Jede authentifizierte Anfrage prüft, dass das Konto noch existiert und aktiv ist, und verwendet die aktuelle Rolle/Flags aus der Benutzerverwaltung; Herabstufung, Löschung, Passwortwechsel und Logout machen bereits ausgestellte Sitzungen ungültig.

**Trace**

1. `web.py:4060` (entrypoint) – Authentifizierte Anfrage eines inzwischen herabgestuften/gelöschten Kontos mit vorher ausgestelltem Session-Cookie (gleiches Muster für GET /users, web.py:4007, und alle anderen _need_*-geschützten Routen)
2. `web.py:2156` (propagation) – liefert session['user'] bzw. session['role'] (web.py:2160) aus dem Cookie ohne Abgleich mit users.json
3. `web.py:2279` (sink) – Admin-Gate gibt None (Zugriff) allein auf Basis der Cookie-Rolle zurück; danach legt users.create_invite ein Admin-Konto an

**Belege**

- `web.py:2358` – _finalize_login schreibt session['role'] (sowie user/name/tk_view/tk_edit/fix_times) einmalig beim Login ins Cookie
- `app.py:65` – Starlette SessionMiddleware: signiertes Cookie ohne Server-Store, keine max_age-Angabe → Standard 14 Tage (starlette 0.41.3 sessions.py:21)
- `web.py:2540` – logout: nur request.session.clear(), keine serverseitige Invalidierung
- `web.py:4000` – account_submit: set_password ohne Invalidierung anderer Sitzungen
- `web.py:4205` – impersonate_stop stellt session['role'] aus dem Cookie-Snapshot wieder her, ohne users.get()
- `web.py:2558` – /auth/verteiler ist die einzige Route mit Neuprüfung (users.get + status + role) – zeigt das beabsichtigte Muster
- `agents/v3-pa-10/artifacts/result_v3.txt:2` – Unabhängige Sandbox-Reproduktion (fastapi 0.115.6/starlette 0.41.3, Dummy-Konten): Herabstufung → GET /users 200; nach Löschung POST /users/create role=admin → Admin angelegt; Logout-Replay → 200; mit Fix 303/abgelehnt

**Akteur (Dummy).** Herabgestufter oder gelöschter (ehemaliger) Admin bzw. Inhaber einer vor Logout kopierten Cookie-Kopie

**Lokale Reproduktion.** ['Im Sandbox-Wrapper (kein Netz, nobody, ro-Root) TestClient gegen app.app mit Datenpfaden in Scratch, SESSION_SECRET=dummy, TWOFA_REQUIRED=false starten (check_v3.py).', "dave meldet sich an; users.set_profile('dave', ..., role='user') (gleiche Funktion wie /users/{u}/edit); mit altem Cookie GET /users.", "users.delete_user('dave'); mit altem Cookie POST /users/create role=admin.", 'erin meldet sich an, Cookie kopieren, /logout, kopiertes Cookie für GET /account erneut senden.', 'Regression: web._user in-process durch die vorgeschlagene, re-validierende Fassung ersetzen und Schritte 2–3 wiederholen.']

**Beobachtet.** Ungepatcht: herabgestufter dave GET /users → 200; gelöschter dave POST /users/create role=admin → 303 und dummy-x mit Rolle admin gespeichert; nach Logout wiederverwendetes Cookie GET /account → 200. Mit re-validierendem _user: GET /users → 303 /start, POST /users/create → abgelehnt (kein Konto angelegt); Logout-Replay bleibt ohne Epoch-Erhöhung 200 (Epoch-Teil des Fixes nötig). Deckt sich mit Hunter-Artefakt agents/pa-h3a/artifacts/evidence_stale_session.txt (inkl. Passwortwechsel und /impersonate/stop).

**Voraussetzungen.** Angreifer besitzt ein vor der Rechteänderung ausgestelltes, gültiges Session-Cookie (eigene frühere Sitzung oder entwendete Kopie), höchstens bis zum Ablauf nach 14 Tagen bzw. bis zur Rotation von SESSION_SECRET; Dem Konto wurden Rechte entzogen (Rolle herabgestuft, Konto gelöscht, Passwort geändert) oder die Sitzung wurde per Logout beendet, nachdem das Cookie kopiert wurde

**Fix.** Zentrale Neuprüfung in _user(): bei jeder Anfrage users.get(session['user']) laden, nicht vorhandene oder nicht aktive Konten abmelden und Rolle/tk_view/tk_edit/fix_times frisch aus dem Datensatz setzen (statt nur 'role'). Zusätzlich ein session_epoch-Feld je Benutzer einführen, beim Login ins Cookie schreiben und bei Passwortwechsel, Rollenänderung, Löschung und Logout erhöhen; Abweichung → Sitzung verwerfen. /impersonate/stop muss die Admin-Rolle aus users.get(imp['user']) neu ableiten. SessionMiddleware mit kürzerem max_age (z. B. 8–12 h) konfigurieren. Sofortmaßnahme bis zum Fix: nach Rechteentzug SESSION_SECRET rotieren (meldet alle ab). Regressionstest: TestClient-Test, der Login → Herabstufen/Löschen/Passwortwechsel/Logout-Replay ausführt und für /users bzw. /users/create Redirect/Ablehnung sowie unveränderte users.json erwartet.

**Vorgeschlagene Code-Änderung (Audit-Vorschlag; umgesetzte Fassung siehe Commit)**

`web.py`

```
def _user(request):
    name = request.session.get("user")
    if not name:
        return None
    u = users.get(name)
    if (not u or u.get("status") != "active"
            or int(u.get("session_epoch", 0)) != int(request.session.get("epoch", 0))):
        request.session.clear()
        return None
    role = u.get("role", "user")
    request.session["role"] = role
    request.session["tk_view"] = bool(role == "admin" or u.get("can_view_tickets") or u.get("can_edit_tickets"))
    request.session["tk_edit"] = bool(role == "admin" or u.get("can_edit_tickets"))
    request.session["fix_times"] = bool(role in ("admin", "buchhaltung") or u.get("can_fix_times"))
    return name

# _finalize_login: zusaetzlich request.session["epoch"] = int(user.get("session_epoch", 0))
# users.set_password / set_profile (Rollenwechsel) / Logout: session_epoch des Kontos um 1 erhoehen
# /impersonate/stop: Rolle nicht aus imp-Snapshot, sondern aus users.get(imp["user"]) neu laden (nur wenn aktiv und admin)
```
