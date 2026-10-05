---
title: "E-Mail-Verteiler – Abo-Status und Postfach 2026-10-05"
date: 2026-10-05
tags: [projekt/fbe-intranet, verteiler, reach, microsoft-365, changelog, entwicklung]
aliases: ["Verteiler Postfach", "Verteiler Subscription Status"]
status: ausgeliefert
branch: main
url: https://intern.rss-fb.com/verteiler/
---

# E-Mail-Verteiler – Abo-Status und Postfach (05.10.2026)

> [!summary] Kurzfassung
> Zwei Erweiterungen für [[2026-10-02 E-Mail-Verteiler|den E-Mail-Verteiler]]:
> 1. **Abo-Status**: Die Spalte „Subscription Status“ (subscribed /
>    unsubscribed) aus dem Reach-Kontaktexport wird beim Import ausgewertet.
>    *unsubscribed* kommt direkt auf die Sperrliste.
> 2. **Postfach**: Das Tool liest ein eigenes Microsoft-365-Postfach und
>    übernimmt alle Adressen aus **Absender, An, CC und Mailtext** als
>    Kontakte. Weiterleiten oder in CC setzen genügt.

## Abo-Status

| Wert | Ergebnis |
|---|---|
| subscribed / leer | normaler Import |
| unsubscribed | Sperrliste (abgemeldet), bestehender Kontakt wird gesperrt |
| bounced / cleaned | Sperrliste (harter Bounce) |
| complained | Sperrliste (Beschwerde) |
| anderes (z. B. pending) | nicht importiert, in der Vorschau aufgelistet |

- „Subscribed At“ wird als Einwilligungsdatum erkannt.
- Doppelte Adresse in der Datei: „abgemeldet“ gewinnt.

## Postfach

- Eigener Container `verteiler-postfach`, Abruf alle 10 Minuten, im Verteiler
  unter **Postfach** auch per Knopf
- Übersprungen werden eigene Domains, das Postfach selbst, noreply/System-
  und gesperrte Adressen
- Bestehende Kontakte werden nur ergänzt. Neue bekommen die Quelle
  „Postfach: Betreff“
- **Nur Lesezugriff** über Microsoft Graph, per Exchange-RBAC auf genau dieses
  Postfach beschränkt. Mails werden nicht verschoben oder gelöscht.
  Gespeichert werden nur Betreff, Zeitpunkt und Zahlen.

> [!warning] Einwilligung
> Adressen aus Mails haben meist keine Newsletter-Einwilligung (§ 7 UWG).
> Vor dem Versand die Einwilligung klären und im Kontakt eintragen.

## Einrichtung

1. Freigegebenes Postfach anlegen, z. B. `verteiler@fb-eng.de`
2. Entra: App-Registrierung „FBE Verteiler Postfach“ mit Client-Geheimnis,
   **ohne** Graph-Berechtigung in der App
3. Exchange Online PowerShell: `New-ServicePrincipal`, `New-ManagementScope`
   (nur dieses Postfach), `New-ManagementRoleAssignment -Role "Application Mail.Read"`
4. `VERTEILER_MAIL_*` in `deploy/.env` eintragen →
   `git pull origin main && docker compose up --build -d`

Die genauen Befehle stehen in `deploy/DEPLOY.md` → „Postfach für den Verteiler“.

## Tests

- 36 automatische Tests grün, Microsoft Graph dabei simuliert: Token, Seiten,
  doppelte Mails, falsches Geheimnis, fremde Weiterleitungsadresse
- Oberfläche getestet: Reach-Export mit 5 Zeilen → 2 neu, 2 abgemeldet →
  Sperrliste, 1 „pending“ übersprungen

> [!note] Ablage
> Diese Notiz liegt auch im Repo unter `docs/2026-10-05 Verteiler – Abo-Status und Postfach.md`.
