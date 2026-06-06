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


def _save_to_disk(label: str, text: str, html: str) -> str:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(config.TIMEZONE).strftime("%Y%m%d-%H%M%S")
    safe = (label or "bericht").replace("/", "_").replace(" ", "_")[:60]
    base = config.REPORT_DIR / f"{stamp}_{safe}"
    base.with_suffix(".txt").write_text(text, encoding="utf-8")
    base.with_suffix(".html").write_text(html, encoding="utf-8")
    return str(base)


def send(subject_line: str, text: str, html: str,
         recipients: list[str], label: str = "") -> dict:
    """Bericht an konkrete Empfaenger zustellen (Datei + ggf. Mail).

    Wird IMMER als Datei gespeichert. Gemailt wird nur, wenn ein SMTP-Server
    konfiguriert UND mindestens ein Empfaenger angegeben ist.
    """
    saved_path = _save_to_disk(label or subject_line, text, html)
    print("=" * 70, flush=True)
    print(f"[report] {subject_line}", flush=True)
    print(f"[report] gespeichert unter: {saved_path}", flush=True)

    if not config.SMTP_HOST or not recipients:
        reason = "no_smtp_host" if not config.SMTP_HOST else "no_recipients"
        print(f"[report] kein Mailversand ({reason}) -> nur Datei.", flush=True)
        return {"mailed": False, "reason": reason,
                "saved_path": saved_path, "recipients": recipients}

    msg = EmailMessage()
    msg["Subject"] = subject_line
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(recipients)
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
                "recipients": recipients}
    except Exception as exc:  # Versand-Fehler nicht eskalieren lassen
        print(f"[report] FEHLER beim Mailversand: {exc}", flush=True)
        return {"mailed": False, "reason": f"smtp_error: {exc}",
                "saved_path": saved_path, "recipients": recipients}


def _login_and_send(server: smtplib.SMTP, msg: EmailMessage) -> None:
    if config.SMTP_USER:
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    server.send_message(msg)


def deliver(rep: Report) -> dict:
    """Komfort-Wrapper: einen (einfachen) Report an die Standard-Empfaenger
    aus der Env senden. Wird vom Dashboard-Button und der /report/run-API
    genutzt."""
    return send(subject(rep), render_text(rep), render_html(rep),
                config.REPORT_RECIPIENTS, label=(rep.project or "alle"))
