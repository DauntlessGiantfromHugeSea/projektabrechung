# Offene Hinweise (Needs Validation) – FBE Intranet + E-Mail-Verteiler (projektabrechung)

Diese Punkte sind **keine bestätigten Schwachstellen** und haben deshalb keine Schwere. Ihnen fehlt ein Fakt, der nur am Betrieb oder mit einer Fixture geklärt werden kann.

## Intranet-Admin-Aktionen von jeder same-site Origin (*.rss-fb.com) fälschbar: kein CSRF-Token, keine Origin-/Sec-Fetch-Site-Prüfung, kein frame-ancestors – SameSite=Lax ist die einzige Kontrolle

- Fingerprint: `intranet:csrf:samesite-lax-only-no-token-origin-or-frame-ancestors`
- Stand: gehärtet – Origin/Sec-Fetch-Site-Prüfung für alle schreibenden Anfragen, X-Frame-Options/CSP frame-ancestors

**Beschreibung.** Alle zustandsändernden Intranet-Routen (u. a. Benutzer anlegen/Rolle ändern, Impersonation, Einstellungen, Löschungen) vertrauen ausschließlich dem ambienten Session-Cookie. Das Cookie ist host-only, Secure, HttpOnly, SameSite=Lax; Lax verhindert nur cross-SITE-POSTs und cross-site Frames, nicht Anfragen von einer same-site Origin (beliebige *.rss-fb.com-Hosts wie mailing.rss-fb.com oder ticket.*). Eine Seite auf einer solchen Origin kann ein Formular an https://intern.rss-fb.com/users/create (role=admin, email=<Angreifer>) automatisch absenden; der Browser hängt das Cookie des eingeloggten Admins an, der Server legt eine Admin-Einladung an und mailt den Einladungslink an die angegebene Adresse (sofern Mailversand konfiguriert; sonst erscheint der Link nur im Flash des Opfers). Ebenso ändert POST /users/{u}/edit Rolle/E-Mail beliebiger Konten. Da die Intranet-Antworten weder X-Frame-Options noch CSP frame-ancestors tragen, können same-site Origins das Intranet mit Cookie einbetten (Clickjacking). Serverseitige Annahme ist lokal reproduziert (TestClient, fastapi 0.115.6/starlette 0.41.3: POST mit Origin https://mailing.rss-fb.com und Sec-Fetch-Site: same-site → 303 /users, Konto role=admin angelegt bzw. E-Mail geändert; ohne Cookie → 303 /login). Ob eine niedriger vertraute same-site Origin existiert und wie die eingesetzten Browser (schemeful same-site, HSTS) sich verhalten, ist nicht im Repository sichtbar.

**Vermutete Ursache.** Die CSRF-Abwehr ist vollständig an SameSite=Lax delegiert (app.py:69), dessen Grenze die registrierbare Domain rss-fb.com ist, die mit anderen, unabhängig betriebenen Apps geteilt wird. Es gibt keine anfragebezogene Bindung (CSRF-Token oder strikte Origin-/Sec-Fetch-Site=same-origin-Prüfung) in app.py/web.py, und der Intranet-Block in deploy/caddy-intern.snippet:34-43 setzt kein X-Frame-Options/CSP frame-ancestors.

**Trace**

1. `web.py:4059` (entrypoint) – Formular-POST von einer same-site Nachbarseite; der Browser hängt das SameSite=Lax-Session-Cookie an, weil der Initiator same-site ist.
2. `app.py:64` (propagation) – Signiertes Cookie wird zu request.session dekodiert; same_site='lax' (Zeile 69); keine Origin-/Token-Prüfung im Middleware-Stack.
3. `web.py:2279` (propagation) – Prüft nur Session-Benutzer und Rolle 'admin'; die Herkunft der Anfrage wird nie berücksichtigt.
4. `web.py:4067` (sink) – Legt ein vom Angreifer gewähltes Konto mit role=admin an und mailt das Einladungstoken an die im Request angegebene Adresse (Zeile 4079).

**Belege**

- `app.py:69` – same_site='lax' ist die einzige anfrageübergreifende Kontrolle am Session-Cookie (kein Domain-Attribut → host-only).
- `web.py:2279` – _need_admin und Geschwister (web.py:2268-2316) prüfen nur Session-Werte; weder web.py noch app.py enthalten CSRF-Token-, Origin-, Referer- oder Sec-Fetch-Site-Prüfungen (grep).
- `web.py:4079` – Einladungslink des gefälschten Admin-Kontos wird an die request-gelieferte E-Mail gesendet.
- `web.py:4098` – POST /users/{username}/edit ändert Rolle/E-Mail eines beliebigen Kontos unter demselben Gate (lokal mit same-site Origin akzeptiert).
- `web.py:4165` – POST /users/{username}/impersonate ist ebenfalls nur session-gated.
- `deploy/caddy-intern.snippet:34` – Intranet-handle-Block (34-43) setzt weder X-Frame-Options noch CSP noch HSTS; X-Frame-Options DENY nur für /verteiler/* (Zeile 26).
- `deploy/DEPLOY.md:179` – Derselbe Caddy bedient weitere Seiten (ticket, mailing, …) – same-site Nachbarn existieren laut Doku.
- `deploy/docker-compose.yml:24` – MAILING_URL https://mailing.rss-fb.com – Nachbar-App auf derselben registrierbaren Domain.

**Blocker**

- Ob eine same-site Origin (mailing.rss-fb.com, ticket.*, weitere *.rss-fb.com-Hosts) angreiferbeeinflusstes HTML/JS ausliefert (z. B. Newsletter-Webansichten, hochgeladene Dateien, XSS), ist nicht im Repository sichtbar und entscheidet die Ausnutzbarkeit.
- Ob rss-fb.com HSTS mit includeSubDomains sendet bzw. preloaded ist und welche Browser die Admins nutzen (schemeful same-site in Chromium >= 89 aktiv, in Firefox/Safari standardmäßig nicht), entscheidet die Variante eines Netzwerkangreifers über eine http://-Subdomain.
- Die Browser-Cookie-Anhängung (same-site vs. cross-site, Frames) ist mit TestClient nicht beobachtbar; ein lokaler Browserlauf war in der vorgegebenen Sandbox nicht verfügbar (laut Hunter bricht Chromium dort mit SIGTRAP ab).

**Klärung**

- *local*: In einer Umgebung, in der ein Browser gegen Loopback laufen kann: intern.rss-fb.test und mailing.rss-fb.test (Kontrolle evil.example) per --host-resolver-rules auf 127.0.0.1 abbilden; App mit Dummy-Daten starten (SESSION_HTTPS_ONLY=false, SCHEDULER_ENABLED=false, TWOFA_REQUIRED=false), als Dummy-Admin einloggen; Fixture-Seite auf mailing.rss-fb.test sendet automatisch <form method=post action=http://intern.rss-fb.test:PORT/users/create> (username=csrf-probe, role=admin, email leer), eine zweite Seite bettet /users per iframe ein. Erwartet bei Verwundbarkeit: csrf-probe in users.json, iframe-GET /users liefert 200 mit Inhalt; Kontrolle von evil.example muss 303 /login ergeben. Regressionstest nach Fix: derselbe POST mit Origin/Sec-Fetch-Site einer Nachbar-Origin liefert 403 und kein Konto.
- *deployment*: Eigentümer prüft ohne Probing: alle DNS-Namen unter rss-fb.com auflisten und feststellen, ob einer davon nutzer-/fremdgeliefertes HTML hostet oder bekannte XSS hat (Mailing-Tool-Webansichten, Ticket-Anhänge); `curl -sI https://intern.rss-fb.com/login` auf Strict-Transport-Security (includeSubDomains), X-Frame-Options und CSP prüfen; eingesetzte Browser der Admins bestätigen. Unabhängig davon empfohlener Fix: Middleware, die für POST/PUT/PATCH/DELETE Sec-Fetch-Site in {same-origin, none} bzw. Origin == https://intern.rss-fb.com verlangt (oder Synchronizer-Token), plus `header X-Frame-Options DENY` / `Content-Security-Policy frame-ancestors 'none'` im Intranet-handle-Block.

## Microsoft-Login prüft weder Heim-Tenant noch Benutzertyp (Gast); jede akzeptierte Identität wird als aktives Konto angelegt

- Fingerprint: `intranet:msauth.exchange:tenant-and-guest-not-enforced-jit-provisioning`
- Stand: gehärtet – Tenant-ID wird gegen MS_TENANT_ID (GUID) geprüft; Gäste nur über MS_ALLOWED_DOMAINS steuerbar

**Beschreibung.** Defekt auf Seite der Anwendung (Relying Party): msauth.exchange() übernimmt aus Graph /oidc/userinfo nur E-Mail/Name und prüft weder Tenant (tid/iss) noch userType; users.upsert_oauth() legt jede unbekannte Identität als Konto mit Rolle 'user', Status 'active' an, und ms_callback() meldet sie sofort an. Standardwerte: MS_TENANT_ID='organizations' (config.py:160, Compose-Default deploy/docker-compose.yml:62) = Multi-Tenant-Authority; MS_ALLOWED_DOMAINS leer (config.py:164). Die Doku nennt MS_TENANT_ID nur als Variable (docs.py:429), ohne Hinweis auf eine Tenant-GUID; der Docstring msauth.py:8-9 behauptet fälschlich, die Tenant-Angabe in der URL beschränke die Anmeldung auf den eigenen Tenant (gilt nicht für 'organizations'). Der Admin-Massenimport (msauth.list_tenant_users, msauth.py:128-132) schließt Gäste, deaktivierte Konten und #EXT#-Adressen aus, der interaktive Login nicht -> zwei Zugänge zum selben Kontenspeicher mit unterschiedlichen Regeln. Lokal reproduziert (Sandbox, gestubbte Token-/Userinfo-Antwort, kein Netz): Mit Defaults erzeugt der Callback die Konten 'partner@extern.example' und 'gast_extern.example#ext#@fbe-dummy.onmicrosoft.com' (role=user, status=active, auth=microsoft), Sitzung gesetzt, Redirect /start; mit gepinnter Tenant-GUID identisches RP-Verhalten (Prüfung liegt dann allein bei Entra); MS_ALLOWED_DOMAINS=fb-eng.example blockiert beide (Redirect /login, keine Konten). Ob fremde Tenants bzw. Gäste tatsächlich einen Code für diese App erhalten, entscheidet die nicht sichtbare Entra-App-Registrierung (signInAudience, 'Zuweisung erforderlich') und deploy/.env. Folge bei offener Konfiguration: ein Außenstehender erhält Zugang zu allen nur per _need_login geschützten Bereichen (z. B. interne Dokumentbereiche /bereich/{slug}, web.py:3474-3484). Fix: MS_TENANT_ID als Tenant-GUID erzwingen (config.ms_enabled() False bzw. Start-Fehler bei 'common'/'organizations'/'consumers' oder Nicht-GUID); in exchange() die tid aus dem direkt vom Token-Endpunkt erhaltenen id_token gegen MS_TENANT_ID prüfen; userType per Graph /me?$select=userType,accountEnabled (Scope User.Read ergänzen) prüfen und != 'Member' sowie '#ext#' ablehnen wie list_tenant_users; JIT-Anlage abschalten oder an dieselben Filter binden (Abgleich per oid statt E-Mail). Regressionstest: Stub mit tid != MS_TENANT_ID bzw. userType='Guest' -> Redirect /login, users.json unverändert; config.ms_enabled() ist False bei MS_TENANT_ID='organizations'.

**Vermutete Ursache.** Die Tenant-Beschränkung ist vollständig an Konfiguration (Authority-URL, Entra-App-Registrierung) delegiert, deren Default 'organizations' multi-tenant ist; msauth.exchange() prüft weder tid noch userType, bevor users.upsert_oauth() die Identität automatisch als aktives Konto anlegt – anders als der Gäste ausschließende Importpfad list_tenant_users().

**Trace**

1. `web.py:2391` (entrypoint) – Anonymes GET /auth/microsoft/login setzt ms_state in der Session und leitet zu msauth.login_url() mit Authority aus MS_TENANT_ID weiter (web.py:2391-2397).
2. `config.py:160` (propagation) – Default 'organizations' (beliebiger Entra-Arbeits-/Schul-Tenant); Compose übergibt denselben Default (deploy/docker-compose.yml:62); ms_enabled() (config.py:167-168) akzeptiert jeden nicht-leeren Wert.
3. `web.py:2409` (propagation) – Nach erfolgreicher state-Prüfung (web.py:2405) wird msauth.exchange(code) aufgerufen; nur None/error führt zurück zu /login.
4. `msauth.py:73` (propagation) – Identität = email/preferred_username/upn aus Graph /oidc/userinfo; tid und userType werden weder angefordert noch geprüft, id_token wird ignoriert; Domain-Check (msauth.py:78-81) nur bei gesetztem MS_ALLOWED_DOMAINS (Default leer, config.py:164).
5. `users.py:303` (propagation) – Unbekannte Identität -> neues Konto username=email, role 'user', status 'active', auth 'microsoft' (users.py:311-323).
6. `web.py:2417` (sink) – _finalize_login schreibt user/role in die signierte Session (web.py:2353-2366); alle _need_login-Routen (z. B. /bereich/{slug} web.py:3474-3484, /meine-zeiten web.py:3699) sind erreichbar.

**Belege**

- `config.py:160` – MS_TENANT_ID = os.getenv('MS_TENANT_ID', 'organizations') – Multi-Tenant-Authority als Default; Kommentar config.py:163 ('leer = alle im Tenant') setzt einen gepinnten Tenant voraus.
- `msauth.py:8` – Docstring behauptet, der Tenant in der Authorize-/Token-URL stelle sicher, dass sich nur Konten des eigenen Tenants anmelden – trifft für den Default 'organizations' nicht zu und schützt auch bei GUID nicht vor B2B-Gästen.
- `msauth.py:73` – exchange() wertet nur email/preferred_username/upn und name aus; keine tid-, iss- oder userType-Prüfung.
- `msauth.py:128` – list_tenant_users() verwirft userType=='Guest', accountEnabled==False und '#ext#'-Adressen – der interaktive Login hat keinen entsprechenden Filter.
- `users.py:316` – JIT-Anlage: 'role': 'user', 'status': 'active' für jede vom Callback gelieferte unbekannte E-Mail.
- `docs.py:429` – Betriebsdoku nennt MS_TENANT_ID nur als Variable, ohne Vorgabe einer Tenant-GUID; README.md/deploy/DEPLOY.md erwähnen Tenant/MS_ALLOWED_DOMAINS gar nicht.
- `web.py:3476` – Dokumentbereiche sind nur per _need_login geschützt; ein JIT-angelegtes Fremdkonto kann interne Dokumente listen.
- `agents/v3-pa-12/artifacts/v3_mslogin_tenant_check.txt:1` – Sandbox-Lauf (kein Netz, Stub für Token/Userinfo): Defaults -> Konten 'partner@extern.example' und '...#ext#@fbe-dummy.onmicrosoft.com' angelegt (user/active), Redirect /start; MS_TENANT_ID=GUID -> RP-Verhalten identisch; MS_ALLOWED_DOMAINS=fb-eng.example -> Redirect /login, keine Konten.

**Blocker**

- Tatsächliche Werte von MS_TENANT_ID und MS_ALLOWED_DOMAINS in /root/projektabrechung/deploy/.env sind nicht im Repository.
- Unterstützte Kontotypen (signInAudience) der Entra-App-Registrierung und die Einstellung 'Zuweisung erforderlich' der Unternehmensanwendung sind nicht sichtbar; sie entscheiden, ob Benutzer fremder Tenants bzw. Gäste des Heim-Tenants für diesen Client überhaupt einen Code erhalten (bei Single-Tenant-App lehnt Entra fremde Tenants am /organizations-Endpunkt ab).
- Ob der Heim-Tenant B2B-Gastkonten enthält, ist nicht sichtbar.

**Klärung**

- *local*: Artefakt v3_mslogin_tenant_check.txt: sandbox.sh <scratch> sh run.sh mit gestubbtem msauth.urllib.request.urlopen (Token + Userinfo) ruft web.ms_callback direkt auf. Nach dem Fix muss derselbe Lauf (a) mit MS_TENANT_ID='organizations' config.ms_enabled()==False bzw. Redirect /login liefern, (b) mit gepinnter GUID und id_token-tid != MS_TENANT_ID sowie (c) mit userType='Guest' oder '#ext#'-UPN jeweils Redirect /login liefern und users.json unverändert lassen.
- *deployment*: Vom Betreiber, nicht-destruktiv: (1) grep -E '^MS_(TENANT_ID|ALLOWED_DOMAINS)=' /root/projektabrechung/deploy/.env lesen; (2) im Entra Admin Center bei der Intranet-App 'Unterstützte Kontotypen' (nur dieses Verzeichnis?) und in der Unternehmensanwendung 'Zuweisung erforderlich' prüfen; (3) in Entra Benutzer filtern nach Benutzertyp 'Gast'; (4) /data/users.json nach Konten mit auth=='microsoft' durchsehen, deren E-Mail-Domain keine Firmendomain ist, '#ext#' enthält oder nicht in der Import-Mitgliederliste vorkommt.

## Microsoft-Login bindet per veränderlichem E-Mail-/Benutzernamen-Claim an beliebiges vorhandenes Konto und überspringt die lokale 2FA (auch lokale Admin- und unbestätigte Einladungskonten)

- Fingerprint: `intranet:users.upsert_oauth:email-claim-links-any-existing-account`
- Stand: gehärtet – Konto wird beim ersten Login an Microsoft-oid gebunden, danach nur noch per oid

**Beschreibung.** Der Callback /auth/microsoft/callback ordnet die Microsoft-Identität einem Intranet-Konto ausschließlich per Stringvergleich zu: msauth.exchange liefert nur den kleingeschriebenen Claim email (sonst preferred_username/upn) aus /oidc/userinfo, ohne oid/tid. users.upsert_oauth gibt jedes Konto zurück, dessen vom Admin gepflegtes Freitextfeld 'email' gleich diesem Claim ist (by_email), sonst ein Konto mit Benutzername == Claim – ohne Prüfung von auth-Typ, status, Rolle oder twofa_enabled. _finalize_login schreibt danach Benutzername, Rolle und Rechte-Flags in die Session, ohne den TOTP-Schritt, den /login für dasselbe Konto erzwingt; unbestätigte Einladungen (status 'invited'), die verify_login ablehnt, werden ebenfalls angemeldet. Lokal reproduziert (Sandbox, gestubbter Token-/Userinfo-Abruf, Dummy-users.json): userinfo {email: chef@fb-eng.example, tid: fremd} ergibt Session user=admin, role=admin, pending_user=null, Redirect /start, obwohl das lokale Admin-Konto Passwort + twofa_enabled hat; identisch mit MS_ALLOWED_DOMAINS=fb-eng.example. userinfo mit der E-Mail eines eingeladenen, nicht eingelösten buchhaltung-Kontos ergibt role=buchhaltung, fix_times=true. Ob eine andere Person als der Postfachinhaber einen solchen userinfo-Claim erhalten kann (fremder Tenant über die Standard-Authority 'organizations', unbestätigte/admin-gesetzte mail-Attribute, Mitarbeiter mit änderbarem mail-Attribut), ist IdP-/Deployment-Konfiguration und offline nicht beobachtbar; davon hängt die tatsächliche Kontoübernahme ab. Fix: (1) in msauth.exchange tid/oid aus dem id_token derselben Token-Antwort (oder Graph /me?$select=id,userPrincipalName,mail,userType) lesen und tid == konfigurierte Tenant-GUID sowie userType == 'Member' verlangen; MS_TENANT_ID-Default 'organizations' durch Pflicht-GUID ersetzen; (2) Konten über unveränderliches ms_oid(+ms_tid) binden; ohne gespeicherte oid nur an aktive, per Microsoft angelegte Konten (auth == 'microsoft', ohne password/totp_secret) verknüpfen, nie an lokale Konten, Einladungen oder per users[email]-Fallback; sonst ablehnen mit Hinweis 'Admin muss verknüpfen'; (3) für Konten mit twofa_enabled lokale TOTP beibehalten oder amr 'mfa' aus dem id_token verlangen. Regressionstest: lokaler Admin {email: chef@x, password, twofa_enabled} + gestubbte Identität {oid o1, tid T, email chef@x} -> keine Admin-Session; Einladungskonto gleicher E-Mail -> nicht gebunden; Konto mit ms_oid o1 -> gebunden auch bei geändertem E-Mail-Claim.

**Vermutete Ursache.** users.upsert_oauth (users.py:303-323) verknüpft die externe Identität per veränderlichem email/preferred_username-Claim mit dem Freitextfeld 'email' bzw. dem Benutzernamen eines beliebigen vorhandenen Kontos, ohne unveränderliche oid/tid-Bindung und ohne Beschränkung auf per Microsoft angelegte, aktive Konten; msauth.exchange (msauth.py:73-81) prüft weder tid noch userType; web.py:2416-2417 finalisiert die Anmeldung ohne die lokale TOTP des Kontos.

**Trace**

1. `web.py:2401` (entrypoint) – Anonymer GET /auth/microsoft/callback (Route web.py:2400) mit code+state; die state-Prüfung web.py:2405 bindet nur an die vom Aufrufer selbst gestartete Browser-Session und besteht für einen eigenen Flow.
2. `msauth.py:73` (propagation) – Identitätsstring = userinfo-Claim email, sonst preferred_username, sonst upn, kleingeschrieben; oid/tid werden verworfen. MS_ALLOWED_DOMAINS (msauth.py:78-81) prüft nur den Domainteil desselben Claims.
3. `web.py:2416` (propagation) – users.upsert_oauth(info['email'], info['name']) wählt das Konto aus.
4. `users.py:306` (propagation) – by_email (users.py:293-300) liefert jedes Konto, dessen Feld 'email' dem Claim entspricht; Rückgabe ohne Prüfung von auth, status, Rolle oder twofa_enabled.
5. `users.py:323` (propagation) – Fallback: existiert bereits users[email] (lokales Konto mit E-Mail-förmigem Benutzernamen), wird dieses unverändert zurückgegeben.
6. `web.py:2357` (sink) – Session erhält Benutzername, Rolle (z. B. admin/buchhaltung) und Rechte-Flags des gewählten Kontos; Aufruf aus web.py:2417 ohne den TOTP-Schritt, den /login für dasselbe Konto erzwingt (web.py:2380-2386).

**Belege**

- `users.py:306` – existing = by_email(email); if existing: return existing – keine Prüfung von existing.get('auth') == 'microsoft', status oder Rolle.
- `users.py:323` – return users[uname] mit uname = email: gibt ein vorhandenes lokales Konto zurück, dessen Benutzername dem Claim entspricht.
- `users.py:108` – Kontrast: verify_login lehnt status != 'active' ab; der Microsoft-Pfad akzeptiert dagegen auch status 'invited' (lokal bestätigt: role=buchhaltung).
- `web.py:2417` – _finalize_login(request, user)  # Microsoft-MFA genügt -> keine eigene 2FA: twofa_enabled/totp_secret des gebundenen Kontos werden ignoriert, kein amr/acr geprüft.
- `web.py:2380` – Kontrast: /login leitet bei twofa_enabled und totp_secret auf /login/2fa (pending_user) um.
- `msauth.py:73` – email-Claim vor preferred_username/upn bevorzugt; Microsoft dokumentiert beide als veränderlich und nicht zur Autorisierung geeignet; kein oid/tid verwendet.
- `msauth.py:8` – Docstring behauptet, der Tenant in der Authorize-/Token-URL beschränke auf eigene Konten – gilt nicht für den Default MS_TENANT_ID='organizations'.
- `users.py:192` – set_profile speichert 'email' als Freitext für jedes Konto inkl. lokaler Admins; bootstrap_admin (users.py:91) und create_invite (users.py:157) führen ebenfalls ein 'email'-Feld.
- `config.py:160` – MS_TENANT_ID-Default 'organizations' (Multi-Tenant-Authority), ebenso deploy/docker-compose.yml:62; erweitert, wer einen beliebigen email-Claim vorlegen kann.
- `agents/v3-pa-11/artifacts/v3_mslogin_recheck.txt:1` – Unabhängige Sandbox-Nachprüfung: Fall A (email-Claim = E-Mail des lokalen TOTP-Admins, fremder tid) -> 303 /start, role=admin, pending_user=null, auch mit MS_ALLOWED_DOMAINS=fb-eng.example; Fall C (Einladungskonto) -> role=buchhaltung, fix_times=true; Kontrolle verify_login('kasse') -> None.

**Blocker**

- Unterstützte Kontotypen (signInAudience) der Entra-App-Registrierung des Intranets und das produktive MS_TENANT_ID/MS_ALLOWED_DOMAINS in deploy/.env stehen nicht im Repository; sie entscheiden, ob eine Identität aus einem vom Angreifer verwalteten Tenant den Callback erreicht.
- Ob Graph /oidc/userinfo für Benutzer fremder Tenants (oder für Benutzer mit admin-gesetztem, unbestätigtem mail-Attribut) einen beliebigen email-Claim liefert, ist offline nicht beobachtbar (Microsofts Mitigation für unbestätigte E-Mail-Claims ist für Tokens dokumentiert, nicht für userinfo).
- Welche lokalen Konten (Passwort/TOTP, Einladungen) in der produktiven users.json ein 'email'-Feld oder einen E-Mail-förmigen Benutzernamen tragen, der einem Postfach eines anderen Menschen/Tenants entsprechen kann, ist nicht sichtbar.

**Klärung**

- *local*: Nach dem Fix v3_harness.py (Artefakt v3_mslogin_recheck.txt; Stub für fastapi und msauth.urllib.request.urlopen, Dummy-users.json) erneut im Sandbox ausführen: Fall A (email-Claim = E-Mail des lokalen TOTP-Admins, fremder tid) und Fall C (Einladungskonto) müssen auf /login ohne session['role'] enden; eine Identität mit bereits gespeichertem ms_oid muss trotz geändertem email-Claim gebunden werden. Als Regressionstest tests/test_msauth_binding.py mit demselben urlopen-Stub anlegen.
- *deployment*: Vom Betreiber zu beobachten, ohne Probing: im Entra Admin Center bei der Intranet-App 'Unterstützte Kontotypen' prüfen (nur 'Nur Konten in diesem Organisationsverzeichnis' ist sicher) und in deploy/.env MS_TENANT_ID (Tenant-GUID statt 'organizations') und MS_ALLOWED_DOMAINS kontrollieren; in users.json alle Konten mit password oder totp_secret bzw. status 'invited' auflisten, die ein nicht leeres 'email' oder einen E-Mail-förmigen Benutzernamen haben; falls die App mandantenübergreifend ist, in einem eigenen Test-Tenant prüfen, ob /oidc/userinfo für einen Benutzer mit gesetztem, nicht verifiziertem mail-Attribut diese Adresse als email-Claim liefert.

## Verteiler-Dateiimport: winzige XLSX/CSV wird zu Gigabytes Speicher (Spaltenbreite × Zeilen-Verstärkung)

- Fingerprint: `verteiler/verteiler_core/fileio.py:_tabelle_aus_zeilen:column-width-row-amplification`
- Stand: gehärtet – max. 500 Spalten / 5 Mio. Zellen, leere Randspalten werden abgeschnitten

**Beschreibung.** Der Datei-Parser des E-Mail-Verteilers begrenzt Dateigröße (50 MB), Zeilenzahl (500.000) und deklarierte entpackte XLSX-Größe (300 MB), aber weder die Spaltenzahl noch die Zahl materialisierter Zellen (Zeilen × Spalten). lese_xlsx füllt jede Zeile bis zum höchsten Zellindex auf (bis 16.384, Spalte XFD), und _tabelle_aus_zeilen erzeugt pro Datenzeile ein dict mit len(kopf) Einträgen; bei CSV bestimmt die Kopfzeilenbreite die dict-Größe. Lokal unabhängig reproduziert (Sandbox, Original-fileio.py, SHA-256 c4be317c…): XLSX mit je einer Zelle in Spalte XFD – 50/100/200 Datenzeilen (1027/1275/1816 Byte) → tracemalloc-Spitze 29,3/56,9/112,2 MB, CPU 1,0/2,0/4,5 s, d. h. ca. 0,56 MB und ca. 22 ms pro Zeile bei ca. 2,7 komprimierten Byte pro Zeile; CSV mit 20.000-Spalten-Kopf und 10/20/40 Zeilen ‚x‘ → 6,1/10,2/18,6 MB. Linear in den Zeilen, aber mit Faktor bis 16.384 (XLSX) bzw. Kopfbreite (CSV); bis 500.000 Zeilen werden akzeptiert, sodass eine Datei von wenigen zehn KB bereits mehrere GB und Minuten CPU erfordert. Der Parse läuft synchron im einzigen, von allen Verteiler-Sitzungen geteilten Streamlit-Prozess (Dockerfile-CMD), der Container hat in docker-compose kein Speicherlimit. Erreichbar ist der Upload nur für Intranet-Admins (Caddy forward_auth + auth.pruefen); die einzige niedriger vertrauenswürdige Quelle ist ein Externer, dessen präparierte Kontaktliste/Reach-Export ein Admin importiert. Kein persistenter Effekt: der fehlgeschlagene Parse wird nicht gecacht (st.cache_data speichert nur Erfolge), nach OOM-Kill startet der Container per restart: unless-stopped neu. Gegenprobe: ein Fix mit Spalten-/Zellgrenze weist beide Eingaben mit DateiFehler ab (Spitze ≤0,5 MB), normale Dateien werden unverändert gelesen, alle 43 bestehenden Verteiler-Tests bestehen.

**Vermutete Ursache.** fileio.lese_xlsx übernimmt den Spaltenindex aus dem frei wählbaren r-Attribut bis 16383 (fileio.py:212, 229-230) – auch für leere Zellen – und füllt jede Zeile auf max(Index)+1 auf (fileio.py:232-233); _tabelle_aus_zeilen baut pro Datenzeile ein dict mit len(kopf) Schlüsseln (fileio.py:109-110). Es gibt keine Grenze für Spalten oder Zellen insgesamt, nur für Bytes, Zeilen und deklarierte entpackte Größe (fileio.py:15-17, 35, 107, 183, 236).

**Trace**

1. `verteiler/app.py:116` (entrypoint) – st.file_uploader (type csv/txt/xlsx) nimmt die Datei eines angemeldeten Intranet-Admins entgegen (Kontakte-Import app.py:220, Reach-Report app.py:337, Sperrliste app.py:440); Dateiinhalt kann von einem Externen stammen. Uploadgrenze 50 MB (.streamlit/config.toml:7 maxUploadSize = 50; Dockerfile-CMD überschreibt sie nicht).
2. `verteiler/app.py:95` (propagation) – lese_datei läuft synchron im gemeinsamen Streamlit-Serverprozess; nur erfolgreiche Ergebnisse werden gecacht (max_entries=4).
3. `verteiler/verteiler_core/fileio.py:212` (propagation) – Spaltenindex aus dem frei wählbaren r-Attribut, z. B. XFD → 16383.
4. `verteiler/verteiler_core/fileio.py:233` (propagation) – Zeilenliste wird für eine einzelne Zelle auf max(Index)+1 = 16384 Einträge aufgefüllt und für alle Zeilen in roh gehalten; die Kopfzeile bekommt so 16384 Spalten.
5. `verteiler/verteiler_core/fileio.py:110` (sink) – Pro Datenzeile ein dict mit len(kopf) Einträgen (hier 16384), bis zu 500.000 Zeilen (fileio.py:107) – Speicher/CPU ∝ Zeilen × Spalten ohne Obergrenze.

**Belege**

- `verteiler/verteiler_core/fileio.py:15` – Nur MAX_DATEI_BYTES, MAX_XLSX_ENTPACKT und MAX_ZEILEN (Zeilen 15-17); keine Spalten- oder Zellgrenze.
- `verteiler/verteiler_core/fileio.py:229` – Jeder Index 0..16383 wird übernommen, auch für leere Zellen (text == "").
- `verteiler/verteiler_core/fileio.py:109` – Zeilen werden auf Kopfbreite aufgefüllt und in dicts mit len(kopf) Schlüsseln umgewandelt.
- `deploy/docker-compose.yml:93` – Dienst verteiler ohne mem_limit/deploy.resources; restart: unless-stopped.
- `verteiler/Dockerfile:31` – Ein einziger Streamlit-Serverprozess bedient alle Verteiler-Sitzungen.
- `verteiler/app.py:93` – st.cache_data(max_entries=4) – hält erfolgreiche Parse-Ergebnisse im Prozess.
- `agents/v3-pa-05/artifacts/out.txt:1` – Unabhängige Sandbox-Messung (Original vs. Fix): XLSX 50/100/200 XFD-Zeilen → 29,3/56,9/112,2 MB, 1,0/2,0/4,5 s CPU; CSV 20.000 Spalten × 10/20/40 Zeilen → 6,1/10,2/18,6 MB; mit Fix jeweils DateiFehler bei ≤0,5 MB, Normaldateien unverändert.
- `agents/v3-pa-05/artifacts/h.py:1` – Messharness (erzeugt minimale XLSX/CSV im Speicher, misst mit tracemalloc/process_time).
- `agents/v3-pa-05/artifacts/fix.diff:1` – Vorgeschlagener Fix für fileio.py: MAX_SPALTEN=500, MAX_ZELLEN=5.000.000, leere Zellen bestimmen keine Breite, Kopf rechts getrimmt, Datenzeilen auf Kopfbreite gekürzt.
- `agents/v3-pa-05/artifacts/tests_fix.txt:1` – Alle 43 bestehenden Verteiler-Tests bestehen mit dem Fix (Ran 43 tests … OK).

**Blocker**

- Geteilte Auswirkung hängt von Betriebsfakten außerhalb des Repos ab: effektives Speicher-cgroup-Limit des Containers verteiler, Host-RAM/Swap/Overcommit und damit, ob nur der Verteiler-Prozess (OOM-Kill, Auto-Neustart) oder auch mitlaufende Dienste (Intranet-App 127.0.0.1:8080, Caddy, Mailing-Tool) durch Speicherdruck/Swapping beeinträchtigt werden.
- Der Upload ist nur Intranet-Admins zugänglich; ob Admins von Externen gelieferte Kontaktlisten/Exporte importieren (einziger Pfad für einen niedriger vertrauenswürdigen Akteur), ist ein im Quelltext nicht sichtbarer Betriebsfakt.

**Klärung**

- *local*: Erledigt (nicht destruktiv, nicht bis OOM): python3 -I h.py in der Sandbox (prlimit AS 4 GiB, ohne Netz) gegen unveränderte fileio.py – XLSX mit je einer inlineStr-Zelle in Spalte XFD für 50/100/200 Datenzeilen und CSV mit 20.000-Spalten-Kopf und 10/20/40 Zeilen; beobachtet ca. 0,56 MB und ca. 22 ms pro XLSX-Zeile, lineares Wachstum mit Kopfbreite bei CSV (out.txt). Regressionstest für verteiler/tests/test_verteiler.py (TestDateien): (1) XLSX mit Kopfzelle A1 und Datenzelle XFD2 → assertRaises(DateiFehler) bzw. höchstens MAX_SPALTEN Spalten; (2) CSV mit ';'.join(['a']*20000)+'\nx\n' → assertRaises(DateiFehler); (3) XLSX mit formatierten leeren Zellen (<c r="Z1" s="1"/>) rechts neben echten Daten → kopfzeilen bleibt auf die befüllten Spalten beschränkt; (4) bestehende test_xlsx/CSV-Tests unverändert grün. Mit fix.diff bestehen alle 43 vorhandenen Tests (tests_fix.txt).
- *deployment*: Owner prüft nicht destruktiv: `docker inspect verteiler --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}'` (0 = unbegrenzt), `free -h` und `cat /proc/sys/vm/overcommit_memory` auf dem Host sowie, welche weiteren Dienste dort laufen; außerdem, ob im Verteiler Dateien aus externen Quellen (Partnerlisten, Messe-Exporte) importiert werden. Unabhängig davon beheben: in fileio.py Spalten (z. B. 500) und Zellen gesamt (Zeilen × Spalten, z. B. 5 Mio.) vor dem Auffüllen begrenzen, leere/nur formatierte XLSX-Zellen nicht zur Zeilenbreite zählen, Datenzeilen auf Kopfbreite kürzen (fix.diff); zusätzlich mem_limit (z. B. 1g) für den Dienst verteiler in deploy/docker-compose.yml setzen.

## Intranet-Templates geben gespeicherte Nutzerdaten und Query-Parameter ohne HTML-Escaping aus (Stored/Reflected XSS)

- Fingerprint: `web.py:jinja2-template-no-autoescape-xss`
- Stand: gehärtet – Jinja2-Autoescape für alle Templates

**Beschreibung.** Alle Intranet-Seiten werden mit jinja2.Template(...) ohne Autoescape gerendert. Lokal reproduziert (Original-Handler, FastAPI-Stubs, Sandbox): (1) Stored: Ein Konto mit Rolle 'user' speichert ueber POST /meine-zeiten/save (meine_save) Projekt und Taetigkeitsbeschreibung mit Markup; GET /log als Admin (log_page) liefert beide als rohe Elemente aus (<td><b id="probe-p">, <summary><span class="desctext"><b id="probe-d">). (2) Reflected: GET /?project=... (dashboard, Admin/Buchhaltung) und GET /tickets?q=... (tickets_list, Ticket-Leser) brechen mit '"><b id="probe-q">' aus dem value-Attribut aus. Korrektur gegenueber Hunter: /log reflektiert 'employee'/'project' nur ueber |urlencode (nicht ausnutzbar), wohl aber start/end roh im href (Quelltext, web.py:853-854). Weder App (app.py) noch Caddy-Block (deploy/caddy-intern.snippet) setzen eine Content-Security-Policy; das Session-Cookie ist SameSite=lax, wird also bei Top-Level-GET-Navigation von fremden Seiten mitgesendet, sodass die reflektierten GET-Varianten per Link gegen eingeloggte Admins nutzbar waeren. Mit Skriptausfuehrung im Admin-Kontext waeren alle Admin-Aktionen derselben Origin (z. B. Benutzer/Rollen aendern) moeglich – nicht ueber den Markup-Nachweis hinaus getestet. Fix: ein gemeinsames jinja2.Environment(autoescape=True) statt Template(...); beabsichtigtes HTML ist bereits mit |safe markiert (Icons, ms_logo, report_html, Doku-Bloecke), lokale Gegenprobe zeigt Escaping der Marker bei weiter gerenderten SVG-Icons.

**Vermutete Ursache.** web.py erzeugt alle Seitenvorlagen mit jinja2.Template(...) (web.py:1343 _base_tpl, web.py:2018 _tpls, web.py:2058 _VCARD_PUB). Template() nutzt eine Standard-Environment mit autoescape=False; Interpolationen wie {{ s.project }}, {{ s.description }}, {{ q }}, {{ project }} verwenden kein |e. Nutzer- und Request-Werte werden daher als rohes Markup in Text- und Attributkontexte eingefuegt.

**Trace**

1. `web.py:3793` (entrypoint) – Jedes angemeldete Konto (_need_login, Rolle 'user' genuegt) uebergibt project und description; project wird nur gestrippt und in manual.add_entry gespeichert, description ueber activities.set_description (web.py:3849-3850). Weitere Quellen: POST /account/name (web.py:3974, users.set_name ohne Validierung), POST /tickets/new (web.py:3083), GET-Parameter project in dashboard (web.py:2643) und q in tickets_list (web.py:3061).
2. `web.py:2202` (propagation) – Gespeichertes project und description (via report.collect_intervals/activities.mapping) werden unveraendert in den Template-Kontext uebernommen.
3. `web.py:2018` (propagation) – Vorlagen werden mit jinja2.Template(s) kompiliert – autoescape aus.
4. `web.py:2751` (propagation) – Admin/Buchhaltung/'Zeiten korrigieren' (_need_timekeeper) rendert _tpls['log'] mit sessions=[_session_view(iv) ...] aller Mitarbeitenden.
5. `web.py:896` (sink) – {{ s.project }} roh in <td>; Beschreibung {{ s.description }} roh in <summary><span class=desctext> (web.py:900). Weitere Senken: {{ project }} in value-Attribut (web.py:783, 808), {{ q }} (web.py:1551), {{ u.name or u.username }} (web.py:1126), {{ t.title }} (web.py:1563), {{ t.description }} (web.py:1645).

**Belege**

- `web.py:26` – from jinja2 import Template; keine jinja2.Environment(autoescape=...) im Modul.
- `web.py:540` – Einzige Interpolation mit explizitem |e; beabsichtigtes HTML ist sonst mit |safe markiert (z. B. web.py:466, 562, 803, 1036-1046), was eine Umstellung auf autoescape=True weitgehend verlustfrei macht.
- `web.py:783` – GET-Parameter project roh im value-Attribut der Dashboard-Seite (auch web.py:808 hidden input).
- `web.py:1551` – GET-Parameter q roh im value-Attribut der Ticketliste.
- `app.py:69` – SessionMiddleware mit same_site='lax': Cookie wird bei Top-Level-GET von fremden Seiten mitgesendet; keine CSP-Middleware in app.py.
- `deploy/caddy-intern.snippet:42` – Intranet-handle: reverse_proxy 127.0.0.1:8080 ohne header-Direktive / Content-Security-Policy (Sicherheitsheader nur im Verteiler-handle, Zeilen 25-29).
- `agents/v3-pa-01/artifacts/xss_log_check.txt:5` – Lokal (Sandbox, Original-Handler meine_save -> log_page als Admin): <td><b id="probe-p">x</b></td> – Projekt-Marker roh ausgegeben.
- `agents/v3-pa-01/artifacts/xss_log_check.txt:8` – Python html.parser erkennt die Marker als Start-Tags: ('b','probe-p','tbody/tr/td') und ('b','probe-d','details/summary/span').
- `agents/v3-pa-01/artifacts/xss_log_check.txt:12` – tickets_list(q='"><b id="probe-q">z</b>') bricht aus value-Attribut aus.
- `agents/v3-pa-01/artifacts/xss_log_check.txt:14` – dashboard(project=...) bricht aus value-Attribut aus (zusaetzlich roh in <h2> Zeile 15 und hidden input Zeile 21).
- `agents/v3-pa-01/artifacts/xss_log_check.txt:22` – Gegenprobe: gleicher _LOG/_BASE-Quelltext mit jinja2.Environment(autoescape=True) gibt die Marker escaped aus; Icons (|safe) bleiben SVG (Zeile 24).

**Blocker**

- Kein Browser-Renderer in der Sandbox verfuegbar (kein chromium/firefox/playwright installiert, Installation untersagt): Skriptausfuehrung im Admin-Browser-Kontext ist nicht lokal beobachtet; belegt ist die serverseitige Ausgabe des Markups als Element (stdlib-HTML-Parser).
- Deployte Antwort-Header von https://intern.rss-fb.com (eine evtl. ausserhalb des Repos gesetzte Content-Security-Policy) wurden nicht beobachtet; Repo (app.py, deploy/caddy-intern.snippet) setzt keine.

**Klärung**

- *local*: In einer Testumgebung mit Browser (z. B. Playwright/Chromium, nur localhost): App mit auf ein Temp-Verzeichnis umgebogenen Datenpfaden (LOG_FILE, USERS_FILE, MANUAL_FILE, ACTIVITIES_FILE usw., SCHEDULER_ENABLED=false) starten, Dummy-Konto 'ma1' (Rolle user, timemoto_name gesetzt) und Dummy-Admin anlegen. Als ma1 POST /meine-zeiten/save mit project=<b id=probe-p>x</b> und description=<img src=x onerror="document.title='probe'">; als Admin /log oeffnen und pruefen, dass document.querySelector('#probe-p') existiert bzw. document.title=='probe' (harmloser Marker, keine Netzwerkzugriffe). Ebenso /tickets?q=%22%3E%3Cb%20id%3Dprobe-q%3E und /?project=%22%3E%3Cb%20id%3Dprobe-q%3E. Fix: in web.py ein gemeinsames _env = jinja2.Environment(autoescape=True) anlegen, _base_tpl = _env.from_string(_BASE), _tpls = {n: _env.from_string(s) ...}, _VCARD_PUB = _env.from_string(...), Globals einmal auf _env.globals setzen; Seiten mit beabsichtigtem HTML (Icons, ms_logo, report_html, Doku-Bloecke, login_heading) sind bereits mit |safe markiert – alle Seiten einmal rendern und auf doppelt escapte Ausgabe pruefen. Zusaetzlich CSP setzen (z. B. in Caddy: header Content-Security-Policy "default-src 'self'; img-src 'self' data: https://fb-eng.de; object-src 'none'; base-uri 'none'; frame-ancestors 'none'", nach Pruefung inline-Skripte/-Styles anpassen). Regressionstest: Unit-Test, der fuer jede Vorlage in web._tpls und web._base_tpl assert tpl.environment.autoescape is True prueft, plus Test wie im Harness: meine_save mit project='<b id="probe">' speichern, log_page als Admin rendern, assert '<b id="probe">' not in body and '&lt;b id=' in body; analog tickets_list(q='"><x>') und dashboard(project='"><x>') -> '"><x>' not in body.
- *deployment*: Owner prueft nicht-destruktiv per Browser-Devtools oder curl -sI https://intern.rss-fb.com/login, ob ein Content-Security-Policy-Header geliefert wird; optional (eigenes Testkonto) eine Buchung mit Beschreibung <b>probe</b> anlegen, /log als Admin ansehen (fett = verwundbar), Buchung danach loeschen.

## Passwort-Reset-Link in der Mail übernimmt den Host aus dem Host-Header der anonymen Anfrage (request.base_url) statt PUBLIC_BASE_URL

- Fingerprint: `web.reset_request:reset-link-host-from-request.base_url`
- Stand: gehärtet – alle Links aus PUBLIC_BASE_URL statt Host-Header

**Beschreibung.** Der anonyme Endpunkt POST /reset (web.reset_request) baut den gemailten Reset-Link aus request.base_url, also aus dem Host-Header (und über --proxy-headers aus X-Forwarded-Proto) der anonymen Anfrage. Lokal mit echtem uvicorn 0.34.0 und den Deploy-Flags (--proxy-headers --forwarded-allow-ips='*') reproduziert: Host 'attacker.invalid' + X-Forwarded-Proto 'https' ergibt in der gespeicherten Mail den Link 'https://attacker.invalid/reset/<token>', obwohl PUBLIC_BASE_URL='https://intern.example.test' gesetzt ist; X-Forwarded-Host wird ignoriert. Kommt eine solche Anfrage am App-Port an, erhält das Opfer (identifiziert per Benutzername oder E-Mail) eine echte Mail, deren Link beim Klick den 60-Minuten-Reset-Token an den fremden Host übermittelt; damit lässt sich das Passwort setzen (Login verlangt danach weiterhin TOTP, bei Konten ohne eingerichtete 2FA ist laut Begleitprüfung Selbst-Einrichtung möglich). Über den im Repository dokumentierten Host-Caddy-Block (Site-Adresse intern.rss-fb.com, Caddy-Host-Matcher) erreicht nur Host intern.rss-fb.com (ggf. mit Port-Suffix) die App; der Token ginge dann an denselben Server. Gleiches Muster bei Einladungslinks (web.py:4019, 4078, 4146) und Download-Links (web.py:2702, 3012, 4328), dort aber nur durch angemeldete Admins auslösbar.

**Vermutete Ursache.** web.reset_request (web.py:2582) verwendet f"{request.base_url}reset/{token}"; Starlette leitet base_url aus dem Host-Header ab, uvicorns ProxyHeadersMiddleware setzt nur Schema und Client-Adresse. app.py registriert keine TrustedHostMiddleware und keine Host-Allowlist, obwohl config.PUBLIC_BASE_URL als vertrauenswürdige Basis existiert und für Ticket-, Scheduler- und Visitenkarten-Links bereits genutzt wird.

**Trace**

1. `web.py:2579` (entrypoint) – Anonymer Handler; Host-Header und X-Forwarded-Proto sind bis zum Ingress clientgesteuert, identifier wählt das Opferkonto (Benutzername oder E-Mail).
2. `web.py:2582` (propagation) – link = f"{request.base_url}reset/{token}" übernimmt Schema und Host der Anfrage.
3. `web.py:2596` (sink) – Link wird als Text und als href an die hinterlegte Adresse des Kontos gemailt (lokal: als Datei in REPORT_DIR gespeichert).

**Belege**

- `web.py:2582` – Reset-Link aus request.base_url gebaut.
- `config.py:224` – PUBLIC_BASE_URL existiert (Default https://intern.rss-fb.com) und ist die vorgesehene Quelle für Links in Mails (vgl. scheduler.py:41, web.py:3045).
- `app.py:64` – Einzige Middleware ist SessionMiddleware; keine TrustedHostMiddleware/Host-Prüfung.
- `Dockerfile:16` – uvicorn --proxy-headers --forwarded-allow-ips='*': X-Forwarded-Proto von jedem Client übernommen, Host bleibt unverändert der Client-Host-Header.
- `deploy/caddy-intern.snippet:6` – Dokumentierter Host-Caddy-Block ist auf intern.rss-fb.com host-gematcht und leitet per reverse_proxy (Zeile 42) mit unverändertem Host an 127.0.0.1:8080; fremde Hosts erreichen die App über diesen Block nicht.
- `deploy/docker-compose.yml:33` – App zusätzlich per expose im geteilten Docker-Netz fbe-tools_default erreichbar; Konfiguration von fbe-caddy und weiterer Container dort nicht im Repository (laut DEPLOY.md bekommt fbe-caddy keinen Verkehr).

**Blocker**

- Die Reflexion ist lokal belegt (agents/v3-pa-14/artifacts/v3pa14_observed.json: Host 'attacker.invalid' + X-Forwarded-Proto 'https' -> Mail-Link 'https://attacker.invalid/reset/<token>' über echtes uvicorn mit Deploy-Flags; Harness agents/v3-pa-14/artifacts/v3pa14_run_check.py). Ob ein externer Angreifer einen fremden Host-Header bis zur App bringt, hängt allein von der Live-Konfiguration /etc/caddy/Caddyfile (weitere Site-Blöcke, Catch-all ':80'/':443'/IP-/Wildcard-Blöcke mit reverse_proxy 127.0.0.1:8080, z. B. ein README-artiger Webhook-Block) und von Diensten im Netz fbe-tools_default ab; beides ist nicht im Repository. Über den dokumentierten Block ist nur intern.rss-fb.com (ggf. mit Port) möglich, was den Token nicht an einen fremden Host leitet.

**Klärung**

- *local*: Regressionstest nach Fix: Harness v3pa14_run_check.py (uvicorn mit proxy_headers=True, forwarded_allow_ips='*', Dummy-Konto dummy.user/dummy@example.test, PUBLIC_BASE_URL=https://intern.example.test) erneut ausführen und prüfen, dass der Link in REPORT_DIR/*.txt für Host 'attacker.invalid' mit 'https://intern.example.test/reset/' beginnt. Fix: in web.py:2582 link = f"{config.PUBLIC_BASE_URL}/reset/{token}"; analog web.py:4019, 4078, 4146 (Einladung) und base_url=config.PUBLIC_BASE_URL in web.py:2702, 3012, 4328; optional zusätzlich TrustedHostMiddleware(allowed_hosts=[Host aus PUBLIC_BASE_URL, 'localhost', '127.0.0.1', 'projektabrechnung']) in app.py.
- *deployment*: Nur lesend durch den Betreiber auf dem Server: `caddy adapt --config /etc/caddy/Caddyfile | grep -n -e '"host"' -e '127.0.0.1:8080'` bzw. Caddyfile sichten, ob außer intern.rss-fb.com ein Block (':80', ':443', '*', IP-Adresse, http://, zusätzliche Domain mit fremdem Inhaber) an 127.0.0.1:8080 weiterleitet; `docker network inspect fbe-tools_default` auf weitere Container prüfen und bestätigen, dass fbe-caddy keinen Block auf projektabrechnung:8080 ohne Host-Matcher hat. Existiert ein solcher Pfad, ist der Host-Header clientgesteuert und der Befund bestätigt; ein reiner Test mit `curl -s -o /dev/null -w '%{http_code}' -H 'Host: attacker.invalid' https://<server-ip>/health -k` (kein /reset) zeigt, ob fremde Hosts überhaupt bis zur App durchgereicht werden.
