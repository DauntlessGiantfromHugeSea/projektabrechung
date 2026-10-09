"""Regressionstests zum Sicherheits-Audit 2026-10 (Intranet).

Aufruf (aus dem Repo-Wurzelverzeichnis, mit installierten requirements + httpx):
    python -m unittest tests.test_sicherheit
Läuft komplett lokal mit Wegwerf-Datenverzeichnis; es wird keine Mail verschickt.
"""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

_DATEN = tempfile.mkdtemp()
os.environ.update(DATA_DIR=_DATEN, MAX_UPLOAD_MB="1", SHARED_SECRET="x" * 32,
                  TIMEMOTO_WEBHOOK="1",
                  SESSION_SECRET="s" * 40, PUBLIC_BASE_URL="http://testserver",
                  SCHEDULER_ENABLED="0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import app as A  # noqa: E402
import config  # noqa: E402
import mailer  # noqa: E402
import users  # noqa: E402

GLEICHE_SEITE = {"Sec-Fetch-Site": "same-origin"}


class Sicherheit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(A.app)
        u = users._load()
        u["alice"] = {"username": "alice", "status": "active", "email": "alice@example.test",
                      "password": users.hash_password("pw-alice-12345")}
        users._save(u)

    def test_health_ohne_details(self):
        self.assertEqual(self.c.get("/health").json(), {"status": "ok"})

    def test_sicherheitsheader(self):
        h = self.c.get("/health").headers
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", h["content-security-policy"])
        self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_fremde_seite_wird_abgelehnt(self):
        r = self.c.post("/login", data={"username": "alice", "password": "x"},
                        headers={"Sec-Fetch-Site": "same-site"}, follow_redirects=False)
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/login", data={"username": "alice", "password": "x"},
                        headers={"Origin": "https://evil.example"}, follow_redirects=False)
        self.assertEqual(r.status_code, 403)

    def test_body_limit(self):
        r = self.c.post("/bereich/x/upload", headers=GLEICHE_SEITE,
                        files={"file": ("a.bin", b"x" * (2 * 1024 * 1024))})
        self.assertEqual(r.status_code, 413)

    def test_webhook_braucht_secret(self):
        r = self.c.post(config.WEBHOOK_PATH, content=b"{}")
        self.assertEqual(r.status_code, 401)
        r = self.c.post(config.WEBHOOK_PATH, content=b"x" * (65 * 1024),
                        headers={"Authorization": "Bearer " + "x" * 32})
        self.assertEqual(r.status_code, 413)

    def test_webhook_standardmaessig_aus(self):
        import subprocess
        code = ("import os, sys; sys.path.insert(0, '.'); "
                "os.environ.pop('TIMEMOTO_WEBHOOK', None); "
                "from fastapi.testclient import TestClient; import app; "
                "print(TestClient(app.app).post('/timemoto', content=b'{}').status_code)")
        env = {k: v for k, v in os.environ.items() if k != "TIMEMOTO_WEBHOOK"}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           cwd=str(Path(__file__).resolve().parent.parent), env=env, timeout=120)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "404", r.stderr[-500:])

    def test_reset_gedrosselt(self):
        gesendet = []
        alt = mailer.send
        mailer.send = lambda *a, **k: gesendet.append(a)
        try:
            for _ in range(3):
                r = self.c.post("/reset", data={"identifier": "alice"}, headers=GLEICHE_SEITE,
                                follow_redirects=False)
                self.assertEqual(r.status_code, 303)
        finally:
            mailer.send = alt
        self.assertEqual(len(gesendet), 1)

    def test_login_gleich_teuer_fuer_unbekannte(self):
        n = [0]
        orig = hashlib.pbkdf2_hmac

        def zaehl(*a, **k):
            n[0] += 1
            return orig(*a, **k)
        users.hashlib.pbkdf2_hmac = zaehl
        try:
            self.assertIsNone(users.verify_login("gibt-es-nicht", "x"))
            self.assertIsNone(users.verify_login("alice", "falsch"))
        finally:
            users.hashlib.pbkdf2_hmac = orig
        self.assertEqual(n[0], 2)


if __name__ == "__main__":
    unittest.main()
