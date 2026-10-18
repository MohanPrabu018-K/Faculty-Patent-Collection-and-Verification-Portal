# -*- coding: utf-8 -*-
"""Public API smoke probe for run_full_validation.ps1 (Phase 10).

No credentials required: health/readiness plus intentionally-failing calls
(unauthenticated grant/settings, bad login, unknown forgot-password).
Forgot-password returns 200 or 503 depending on email configuration; both
are acceptable contract states and are reported, not asserted.
Exit 1 on any hard failure. Never prints secrets (no auth material used).
"""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8099"
fails = []


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, (r.read().decode() or "")[:80]
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001 - transport diagnostics
        return "ERR:" + str(e)[:60], ""


def check(name, got, want):
    ok = got == want if not isinstance(want, tuple) else got in want
    print("smoke %s: got=%s want=%s %s" % (name, got, want, "OK" if ok else "FAIL"))
    if not ok:
        fails.append(name)


check("healthz", call("GET", "/healthz")[0], 200)
check("readyz", call("GET", "/readyz")[0], 200)
check("grant-anon", call("POST", "/api/v1/admin/ip-records/x/grant", {"confirm": True})[0], (400, 401, 403))
check("settings-anon", call("GET", "/api/v1/admin/settings")[0], 401)
check("bad-login", call("POST", "/api/v1/auth/login",
                        {"email": "nobody@example.com", "password": "wrong-password-1"})[0], 401)
code, _ = call("POST", "/api/v1/auth/forgot-password", {"email": "nobody@example.com"})
print("smoke forgot-unknown: got=%s (200 generic or 503 EMAIL_UNAVAILABLE both valid)" % code)
if code not in (200, 503):
    fails.append("forgot-unknown")

if fails:
    print("SMOKE FAILURES: %s" % fails)
    sys.exit(1)
print("smoke: OK")
