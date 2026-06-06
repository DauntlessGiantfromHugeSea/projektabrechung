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

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage

import audit
import config
import downloads
from report import Report, render_html, render_text, subject

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download_block_html(url: str) -> str:
    if not url:
        return ""
    return (
        '<table cellpadding="0" cellspacing="0" style="margin:22px 0 6px">'
        f'<tr><td style="border-radius:999px;background:{config.BRAND_COLOR}">'
        f'<a href="{url}" style="display:inline-block;color:#123018;'
        'font-weight:bold;text-decoration:none;padding:13px 26px;'
        'border-radius:999px;font-size:15px">⬇  Bericht als Excel herunterladen'
        '</a></td></tr></table>'
        '<div style="color:#8a98a6;font-size:12px;margin-top:4px">'
        'Der Link führt direkt zum Download dieser Datei.</div>')


def _brand_html(inner: str, download_url: str = "") -> str:
    """Report-HTML in ein gebrandetes Mail-Layout huellen (weisses Logo auf
    gruenem Header, runde Karte). Inline-Styles fuer Mail-Client-Kompatibilitaet."""
    inner = inner + _download_block_html(download_url)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head>'
        '<body style="margin:0;padding:0;background:#eef2f4;'
        '-webkit-font-smoothing:antialiased;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'color:#1e293b">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#eef2f4;padding:28px 12px"><tr><td align="center">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;border-radius:18px;overflow:hidden;'
        'max-width:600px;box-shadow:0 8px 28px rgba(40,80,40,.10)">'
        # Header mit Verlauf von Markenfarbe -> dunkler, weisses Logo
        f'<tr><td style="background:{config.BRAND_COLOR};'
        f'background-image:linear-gradient(135deg,{config.BRAND_COLOR},'
        f'{config.BRAND_COLOR_DARK});padding:26px 30px" align="left">'
        f'<img src="{config.EMAIL_LOGO_URL}" alt="FBE" height="38" '
        'style="display:block;border:0;outline:none"></td></tr>'
        # Inhalt
        f'<tr><td style="padding:26px 30px 30px">{inner}</td></tr>'
        # Footer
        '<tr><td style="padding:18px 30px;background:#f4f8f0;color:#7d8a96;'
        'font-size:12px;line-height:1.5;border-top:1px solid #e6eaef">'
        'Diese E-Mail wurde automatisch von der <b>FBE Projektabrechnung</b> '
        'erstellt.</td></tr>'
        '</table>'
        '<div style="color:#aab4be;font-size:11px;margin-top:14px">'
        'FB Engineering · Projektzeiten</div>'
        '</td></tr></table></body></html>')


def _save_to_disk(label: str, text: str, html: str) -> str:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(config.TIMEZONE).strftime("%Y%m%d-%H%M%S")
    safe = (label or "bericht").replace("/", "_").replace(" ", "_")[:60]
    base = config.REPORT_DIR / f"{stamp}_{safe}"
    base.with_suffix(".txt").write_text(text, encoding="utf-8")
    base.with_suffix(".html").write_text(html, encoding="utf-8")
    return str(base)


def _log_send(actor: str, subject_line: str, result: dict) -> None:
    rec = ", ".join(result.get("recipients") or [])
    if result.get("mailed"):
        audit.log(actor, "Mail gesendet", f"{subject_line} → {rec}")
    elif result.get("reason") != "no_recipients":
        audit.log(actor, "Mail fehlgeschlagen",
                  f"{subject_line} → {rec} ({result.get('reason')})")


def send(subject_line: str, text: str, html: str, recipients: list[str],
         label: str = "", download_url: str = "", actor: str = "System") -> dict:
    """Bericht an konkrete Empfaenger zustellen (Datei + ggf. Mail).

    Wird IMMER als Datei gespeichert. Gemailt wird nur, wenn ein SMTP-Server
    konfiguriert UND mindestens ein Empfaenger angegeben ist. Ein optionaler
    download_url wird als Button/Link in die Mail eingebettet (statt Anhang).
    """
    if download_url:
        text = f"{text}\nDownload (Excel): {download_url}\n"
    saved_path = _save_to_disk(label or subject_line, text, html)
    branded = _brand_html(html, download_url)
    print("=" * 70, flush=True)
    print(f"[report] {subject_line}", flush=True)
    print(f"[report] gespeichert unter: {saved_path}", flush=True)

    has_transport = bool(config.BREVO_API_KEY or config.SMTP_HOST)
    if not recipients or not has_transport:
        reason = "no_recipients" if not recipients else "no_transport"
        print(f"[report] kein Mailversand ({reason}) -> nur Datei.", flush=True)
        result = {"mailed": False, "reason": reason,
                  "saved_path": saved_path, "recipients": recipients}
    else:
        try:
            if config.BREVO_API_KEY:
                _send_via_brevo_api(subject_line, text, branded, recipients)
                via = "Brevo-API"
            else:
                via = _send_via_smtp(subject_line, text, branded, recipients)
            print(f"[report] Mail an {', '.join(recipients)} versendet ({via}).",
                  flush=True)
            result = {"mailed": True, "saved_path": saved_path,
                      "recipients": recipients}
        except Exception as exc:  # Versand-Fehler nicht eskalieren lassen
            print(f"[report] FEHLER beim Mailversand: {exc}", flush=True)
            result = {"mailed": False, "reason": f"smtp_error: {exc}",
                      "saved_path": saved_path, "recipients": recipients}
    _log_send(actor, subject_line, result)
    return result


def _send_via_brevo_api(subject_line: str, text: str, html: str,
                        recipients: list[str]) -> None:
    """Versand ueber die Brevo Transactional-Email-API (HTTPS, Port 443)."""
    payload = {
        "sender": {"email": config.SMTP_FROM or "noreply@rss-fb.com"},
        "to": [{"email": r} for r in recipients],
        "subject": subject_line,
        "htmlContent": html,
        "textContent": text,
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": config.BREVO_API_KEY,
                 "content-type": "application/json",
                 "accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if not (200 <= resp.status < 300):
                raise RuntimeError(f"HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"Brevo-API {e.code}: {body}") from None


def _send_via_smtp(subject_line: str, text: str, html: str,
                   recipients: list[str]) -> str:
    msg = EmailMessage()
    msg["Subject"] = subject_line
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if config.SMTP_SSL:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                              context=ssl.create_default_context(),
                              timeout=30) as s:
            _login_and_send(s, msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            if config.SMTP_STARTTLS:
                s.starttls(context=ssl.create_default_context())
            _login_and_send(s, msg)
    return f"SMTP:{config.SMTP_PORT}"


def _login_and_send(server: smtplib.SMTP, msg: EmailMessage) -> None:
    if config.SMTP_USER:
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    server.send_message(msg)


def send_report(subject_line: str, text: str, html: str, recipients: list[str],
                xlsx_bytes: bytes | None, filename: str, base_url: str = "",
                label: str = "", actor: str = "System") -> dict:
    """Wie send(), legt aber zusaetzlich die Excel-Datei als tokenisierten
    Download ab und haengt den Link (statt Anhang) in die Mail."""
    url = ""
    if xlsx_bytes:
        token = downloads.register(xlsx_bytes, filename, _XLSX_MIME)
        url = downloads.link(base_url, token)
    return send(subject_line, text, html, recipients, label=label,
                download_url=url, actor=actor)


def deliver(rep: Report) -> dict:
    """Komfort-Wrapper: einen (einfachen) Report an die Standard-Empfaenger
    aus der Env senden. Wird vom Dashboard-Button und der /report/run-API
    genutzt."""
    return send(subject(rep), render_text(rep), render_html(rep),
                config.REPORT_RECIPIENTS, label=(rep.project or "alle"))
