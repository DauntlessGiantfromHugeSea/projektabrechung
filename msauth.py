"""
Microsoft-Login über Entra ID (Azure AD), OpenID Connect.

Authorization-Code-Flow ohne externe Abhängigkeiten (urllib):
1. login_url(): Weiterleitung zu Microsoft.
2. exchange(): Code gegen Token tauschen, dann Userinfo (E-Mail, Name) holen.

Der Tenant in der Authorize-/Token-URL stellt sicher, dass sich nur Konten
aus eurem Tenant anmelden können.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import config

_AUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_TOKEN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_USERINFO = "https://graph.microsoft.com/oidc/userinfo"
_SCOPE = "openid profile email"


def login_url(state: str) -> str:
    params = {
        "client_id": config.MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.ms_redirect_uri(),
        "response_mode": "query",
        "scope": _SCOPE,
        "state": state,
    }
    return (_AUTH.format(tenant=config.MS_TENANT_ID) + "?"
            + urllib.parse.urlencode(params))


def exchange(code: str) -> dict | None:
    """Code gegen Token tauschen und Userinfo (email, name) zurueckgeben."""
    data = urllib.parse.urlencode({
        "client_id": config.MS_CLIENT_ID,
        "client_secret": config.MS_CLIENT_SECRET,
        "code": code,
        "redirect_uri": config.ms_redirect_uri(),
        "grant_type": "authorization_code",
        "scope": _SCOPE,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            _TOKEN.format(tenant=config.MS_TENANT_ID), data=data,
            headers={"content-type": "application/x-www-form-urlencoded"},
            method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
        access = tok.get("access_token")
        if not access:
            print(f"[ms-login] kein access_token: {tok}", flush=True)
            return None
        ui_req = urllib.request.Request(
            _USERINFO, headers={"Authorization": f"Bearer {access}"})
        with urllib.request.urlopen(ui_req, timeout=20) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        print(f"[ms-login] HTTP {e.code}: {body}", flush=True)
        return None
    except Exception as exc:
        print(f"[ms-login] Fehler: {exc}", flush=True)
        return None

    email = (info.get("email") or info.get("preferred_username")
             or info.get("upn") or "").strip().lower()
    name = (info.get("name") or "").strip()
    if not email:
        return None
    if config.MS_ALLOWED_DOMAINS:
        dom = email.split("@")[-1]
        if dom not in [d.lower() for d in config.MS_ALLOWED_DOMAINS]:
            return {"error": "domain_not_allowed", "email": email}
    return {"email": email, "name": name or email}
