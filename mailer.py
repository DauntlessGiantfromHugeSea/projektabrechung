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
import downloads
from report import Report, render_html, render_text, subject

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download_block_html(url: str) -> str:
    if not url:
        return ""
    return (
        f'<div style="margin:18px 0 4px"><a href="{url}" '
        f'style="display:inline-block;background:{config.BRAND_COLOR};'
        'color:#123018;font-weight:bold;text-decoration:none;padding:11px 20px;'
        'border-radius:999px">Bericht als Excel herunterladen</a></div>'
        '<div style="color:#64748b;font-size:12px;margin-top:6px">'
        'Der Link führt direkt zum Download dieser Datei.</div>')


def _brand_html(inner: str, download_url: str = "") -> str:
    """Report-HTML in ein gebrandetes Mail-Layout (Logo + Farbe) huellen.
    Inline-Styles, damit es in Mail-Clients funktioniert."""
    inner = inner + _download_block_html(download_url)
    return (
        '<!doctype html><html><body style="margin:0;background:#f5f7f9;'
        'font-family:Arial,Helvetica,sans-serif;color:#1e293b">'
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f5f7f9;padding:24px 0"><tr><td align="center">'
        '<table width="640" cellpadding="0" cellspacing="0" '
        'style="background:#fff;border-radius:14px;overflow:hidden;'
        'border:1px solid #e6eaef;max-width:640px">'
        f'<tr><td style="background:{config.BRAND_COLOR};padding:16px 24px">'
        f'<img src="{config.LOGO_URL}" alt="FBE" height="32" '
        'style="vertical-align:middle;display:inline-block"></td></tr>'
        f'<tr><td style="padding:22px 24px">{inner}</td></tr>'
        '<tr><td style="padding:14px 24px;background:#f0f5ec;color:#64748b;'
        'font-size:12px">Automatischer Bericht · FBE Projektabrechnung</td></tr>'
        '</table></td></tr></table></body></html>')


def _save_to_disk(label: str, text: str, html: str) -> str:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(config.TIMEZONE).strftime("%Y%m%d-%H%M%S")
    safe = (label or "bericht").replace("/", "_").replace(" ", "_")[:60]
    base = config.REPORT_DIR / f"{stamp}_{safe}"
    base.with_suffix(".txt").write_text(text, encoding="utf-8")
    base.with_suffix(".html").write_text(html, encoding="utf-8")
    return str(base)


def send(subject_line: str, text: str, html: str,
         recipients: list[str], label: str = "", download_url: str = "") -> dict:
    """Bericht an konkrete Empfaenger zustellen (Datei + ggf. Mail).

    Wird IMMER als Datei gespeichert. Gemailt wird nur, wenn ein SMTP-Server
    konfiguriert UND mindestens ein Empfaenger angegeben ist. Ein optionaler
    download_url wird als Button/Link in die Mail eingebettet (statt Anhang).
    """
    if download_url:
        text = f"{text}\nDownload (Excel): {download_url}\n"
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
    msg.add_alternative(_brand_html(html, download_url), subtype="html")

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


def send_report(subject_line: str, text: str, html: str, recipients: list[str],
                xlsx_bytes: bytes | None, filename: str, base_url: str = "",
                label: str = "") -> dict:
    """Wie send(), legt aber zusaetzlich die Excel-Datei als tokenisierten
    Download ab und haengt den Link (statt Anhang) in die Mail."""
    url = ""
    if xlsx_bytes:
        token = downloads.register(xlsx_bytes, filename, _XLSX_MIME)
        url = downloads.link(base_url, token)
    return send(subject_line, text, html, recipients, label=label,
                download_url=url)


def deliver(rep: Report) -> dict:
    """Komfort-Wrapper: einen (einfachen) Report an die Standard-Empfaenger
    aus der Env senden. Wird vom Dashboard-Button und der /report/run-API
    genutzt."""
    return send(subject(rep), render_text(rep), render_html(rep),
                config.REPORT_RECIPIENTS, label=(rep.project or "alle"))
