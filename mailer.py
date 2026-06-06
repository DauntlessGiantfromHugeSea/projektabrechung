"""
Versand des Berichts.

Zwei Modi:
1. SMTP konfiguriert (SMTP_HOST + REPORT_RECIPIENTS) -> echte Mail.
2. Sonst -> Bericht wird nur als Datei in REPORT_DIR abgelegt und geloggt.
   So funktioniert die Wochenmechanik schon jetzt vollstaendig, und der
   Mailversand laesst sich spaeter durch reines Setzen der Env-Vars aktivieren.

Der Bericht wird IMMER zusaetzlich als Datei gespeichert (Audit/Nachschau).
"""

from __future__ import annotations

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

import config
from report import Report, render_html, render_text, subject


def _save_to_disk(rep: Report, text: str, html: str) -> str:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(config.TIMEZONE).strftime("%Y%m%d-%H%M%S")
    proj = (rep.project or "alle").replace("/", "_").replace(" ", "_")
    base = config.REPORT_DIR / f"{stamp}_{proj}"
    base.with_suffix(".txt").write_text(text, encoding="utf-8")
    base.with_suffix(".html").write_text(html, encoding="utf-8")
    return str(base)


def deliver(rep: Report) -> dict:
    """Bericht zustellen. Liefert ein Status-Dict zurueck (fuer API/Logs)."""
    text = render_text(rep)
    html = render_html(rep)

    saved_path = _save_to_disk(rep, text, html)
    print("=" * 70, flush=True)
    print(f"[report] {subject(rep)}", flush=True)
    print(text, flush=True)
    print(f"[report] gespeichert unter: {saved_path}", flush=True)

    if not config.mail_configured():
        print("[report] SMTP nicht konfiguriert -> keine Mail versendet "
              "(nur Datei). Setze SMTP_HOST + REPORT_RECIPIENTS zum Aktivieren.",
              flush=True)
        return {"mailed": False, "reason": "smtp_not_configured",
                "saved_path": saved_path, "recipients": config.REPORT_RECIPIENTS}

    msg = EmailMessage()
    msg["Subject"] = subject(rep)
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(config.REPORT_RECIPIENTS)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    try:
        if config.SMTP_SSL:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                                  context=ctx, timeout=30) as s:
                _login_and_send(s, msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT,
                              timeout=30) as s:
                if config.SMTP_STARTTLS:
                    s.starttls(context=ssl.create_default_context())
                _login_and_send(s, msg)
        print(f"[report] Mail an {msg['To']} versendet.", flush=True)
        return {"mailed": True, "saved_path": saved_path,
                "recipients": config.REPORT_RECIPIENTS}
    except Exception as exc:  # Versand-Fehler nicht eskalieren lassen
        print(f"[report] FEHLER beim Mailversand: {exc}", flush=True)
        return {"mailed": False, "reason": f"smtp_error: {exc}",
                "saved_path": saved_path, "recipients": config.REPORT_RECIPIENTS}


def _login_and_send(server: smtplib.SMTP, msg: EmailMessage) -> None:
    if config.SMTP_USER:
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    server.send_message(msg)
