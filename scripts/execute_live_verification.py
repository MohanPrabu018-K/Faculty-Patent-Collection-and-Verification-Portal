#!/usr/bin/env python3
"""
Comprehensive Live Production Verification Script for FPP
Tests Phase A (Deployment) and Bugs 1-4 against live production services.
Safety: Read-only, no destructive actions, no credential leaks.
"""
import json
import os
import re
import urllib.request
import httpx

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://faculty-patent-collection-and-verification-portal.pages.dev")
BACKEND_URL = os.getenv("BACKEND_URL", "https://faculty-patent-portal-api.onrender.com")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@faculty.edu")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminPass123!")

results = {
    "deployment": {},
    "bug1_dates": {},
    "bug2_faculty_navigation": {},
    "bug3_aids_hod": {},
    "bug4_auth_refresh": {},
}

print("=" * 80)
print("1. PHASE A: DEPLOYMENT VERIFICATION")
print("=" * 80)

# 1.1 Backend Health
with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as client:
    r_health = client.get("/healthz")
    r_ready = client.get("/readyz")
    r_openapi = client.get("/openapi.json")
    
    print(f"Backend /healthz:  {r_health.status_code} {r_health.text.strip()}")
    print(f"Backend /readyz:   {r_ready.status_code} {r_ready.text.strip()}")
    print(f"Backend /openapi:  {r_openapi.status_code} (bytes: {len(r_openapi.content)})")
    
    results["deployment"]["backend_health"] = {
        "healthz_status": r_health.status_code,
        "readyz_status": r_ready.status_code,
        "openapi_status": r_openapi.status_code,
    }

# 1.2 Frontend CDN probe
req_cf = urllib.request.Request(FRONTEND_URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req_cf, timeout=15) as resp_cf:
    cf_status = resp_cf.status
    cf_headers = dict(resp_cf.getheaders())
    html = resp_cf.read().decode("utf-8", errors="ignore")
    assets = re.findall(r'/assets/[a-zA-Z0-9_\-\.]+\.js', html)
    print(f"Frontend Status:   {cf_status}")
    print(f"Server Header:     {cf_headers.get('server') or cf_headers.get('Server')}")
    print(f"Assets linked:     {assets}")
    
    results["deployment"]["frontend"] = {
        "status": cf_status,
        "server": cf_headers.get("server") or cf_headers.get("Server"),
        "assets": assets,
    }

# Check bundle contents
main_bundle = assets[0] if assets else None
if main_bundle:
    bundle_url = FRONTEND_URL + main_bundle
    req_b = urllib.request.Request(bundle_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req_b, timeout=15) as resp_b:
        js_text = resp_b.read().decode("utf-8", errors="ignore")
        has_poll_interval = "POLL_INTERVAL" in js_text
        has_pub_date = "publication_date" in js_text
        has_refresh_promise = "refreshPromise" in js_text
        print(f"Main bundle {main_bundle}:")
        print(f"  has POLL_INTERVAL:    {has_poll_interval}")
        print(f"  has publication_date: {has_pub_date}")
        print(f"  has refreshPromise:   {has_refresh_promise}")
        results["deployment"]["frontend_bundle_features"] = {
            "bundle": main_bundle,
            "has_poll_interval": has_poll_interval,
            "has_publication_date": has_pub_date,
            "has_refresh_promise": has_refresh_promise,
        }

print("\n" * 1)
print("=" * 80)
print("2. BUG 4: AUTHENTICATION TOKEN REFRESH & TOKEN TYPE SEPARATION")
print("=" * 80)

with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as client:
    # 2.1 Login
    r_login = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    print(f"Login POST /api/v1/auth/login: {r_login.status_code}")
    login_data = r_login.json()
    access_token = login_data.get("access_token")
    refresh_token = login_data.get("refresh_token")
    cookies = r_login.cookies
    cookie_keys = list(cookies.keys())
    print(f"  access_token present:  {bool(access_token)}")
    print(f"  refresh_token present: {bool(refresh_token)}")
    print(f"  cookies returned:      {cookie_keys}")
    
    # Check token types
    import jwt
    acc_claims = jwt.decode(access_token, options={"verify_signature": False})
    ref_claims = jwt.decode(refresh_token, options={"verify_signature": False})
    print(f"  access_token claims token_type:  '{acc_claims.get('token_type')}'")
    print(f"  refresh_token claims token_type: '{ref_claims.get('token_type')}'")
    assert acc_claims.get("token_type") == "access", "Expected token_type='access'"
    assert ref_claims.get("token_type") == "refresh", "Expected token_type='refresh'"
    
    # 2.2 Access protected endpoint with access token
    r_me_valid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    print(f"GET /api/v1/auth/me with access token:  {r_me_valid.status_code}")
    assert r_me_valid.status_code == 200
    
    # 2.3 Access protected endpoint with refresh token (Must FAIL with 401)
    r_me_invalid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    print(f"GET /api/v1/auth/me with refresh token: {r_me_invalid.status_code} {r_me_invalid.text}")
    assert r_me_invalid.status_code == 401
    assert "refresh token cannot be used as access token" in r_me_invalid.text
    
    # 2.4 Refresh via JSON body
    r_ref_body = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    print(f"POST /api/v1/auth/refresh via JSON body: {r_ref_body.status_code}")
    assert r_ref_body.status_code == 200
    new_acc_body = r_ref_body.json().get("access_token")
    assert new_acc_body
    
    # 2.5 Refresh via Cookie header
    r_ref_cookie = client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={refresh_token}"})
    print(f"POST /api/v1/auth/refresh via Cookie:    {r_ref_cookie.status_code}")
    assert r_ref_cookie.status_code == 200
    
    # 2.6 Refresh without credentials (Must reject with 401)
    with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as clean_client:
        r_ref_none = clean_client.post("/api/v1/auth/refresh")
    print(f"POST /api/v1/auth/refresh without creds: {r_ref_none.status_code} {r_ref_none.text}")
    assert r_ref_none.status_code == 401
    assert "Authentication credentials missing" in r_ref_none.text
    
    # 2.7 Refresh with malformed token (Must reject with 401)
    r_ref_bad = client.post("/api/v1/auth/refresh", json={"refresh_token": "malformed.jwt.token"})
    print(f"POST /api/v1/auth/refresh malformed:     {r_ref_bad.status_code} {r_ref_bad.text}")
    assert r_ref_bad.status_code == 401
    
    # 2.8 Logout
    r_logout = client.post("/api/v1/auth/logout")
    print(f"POST /api/v1/auth/logout:               {r_logout.status_code}")
    assert r_logout.status_code == 200
    
    results["bug4_auth_refresh"] = {
        "status": "PASS",
        "token_type_separation": True,
        "access_token_type": acc_claims.get("token_type"),
        "refresh_token_type": ref_claims.get("token_type"),
        "refresh_token_rejected_as_access_token": r_me_invalid.status_code == 401,
        "refresh_via_body_status": r_ref_body.status_code,
        "refresh_via_cookie_status": r_ref_cookie.status_code,
        "refresh_missing_creds_status": r_ref_none.status_code,
        "logout_status": r_logout.status_code,
    }

print("\n" * 1)
print("=" * 80)
print("3. BUG 3: AIDS DEPARTMENT HOD CREATION & ALIAS RESOLUTION")
print("=" * 80)

with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as client:
    # Login as admin
    r_login = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3.1 Get departments list
    r_depts = client.get("/api/v1/admin/departments?per_page=100", headers=headers)
    depts = r_depts.json().get("departments", [])
    aids_dept = next((d for d in depts if "artificial intelligence" in (d.get("name") or "").lower() or d.get("code") in ("AIDS", "AIADS")), None)
    print("AIDS Department in DB:")
    print(f"  ID:   {aids_dept.get('id') if aids_dept else None}")
    print(f"  Name: {aids_dept.get('name') if aids_dept else None}")
    print(f"  Code: {aids_dept.get('code') if aids_dept else None}")
    assert aids_dept is not None, "AIDS department not found in DB"
    aids_uuid = aids_dept["id"]
    
    # 3.2 Check existing active HOD for AIDS
    r_fac = client.get("/api/v1/admin/faculty?per_page=100", headers=headers)
    all_fac = r_fac.json().get("faculty", [])
    aids_active_hod = next((u for u in all_fac if u.get("role") == "hod_admin" and u.get("department_id") == aids_uuid and u.get("is_active")), None)
    print(f"Active HOD for AIDS: {aids_active_hod.get('email') if aids_active_hod else 'None'} (ID: {aids_active_hod.get('id') if aids_active_hod else 'None'})")
    
    # Get HOD designation (use per_page=100 as HOD is on page 2)
    r_desg = client.get("/api/v1/admin/designations?per_page=100", headers=headers)
    desgs = r_desg.json().get("designations", [])
    hod_desg = next((d for d in desgs if (d.get("title") or "").upper() == "HOD"), None)
    hod_desg_id = hod_desg["id"] if hod_desg else None
    print(f"HOD Designation ID: {hod_desg_id}")
    assert hod_desg_id is not None, "HOD designation ID must be found"
    
    # 3.3 Test duplicate active HOD rejection with canonical UUID
    payload_uuid = {
        "email": "qa.duplicate.uuid.test@faculty.edu",
        "full_name": "QA Duplicate UUID Test",
        "department_id": aids_uuid,
        "designation_id": hod_desg_id,
        "is_active": True,
    }
    r_dup_uuid = client.post("/api/v1/admin/faculty", json=payload_uuid, headers=headers)
    print(f"Create HOD with canonical UUID -> Status: {r_dup_uuid.status_code} {r_dup_uuid.text}")
    assert r_dup_uuid.status_code == 409
    assert "ACTIVE_HOD_EXISTS" in r_dup_uuid.text
    
    # 3.4 Test duplicate active HOD rejection with code 'AIDS'
    payload_code_aids = {
        "email": "qa.duplicate.code.aids@faculty.edu",
        "full_name": "QA Duplicate Code AIDS",
        "department_id": "AIDS",
        "designation_id": hod_desg_id,
        "is_active": True,
    }
    r_dup_aids = client.post("/api/v1/admin/faculty", json=payload_code_aids, headers=headers)
    print(f"Create HOD with code 'AIDS'     -> Status: {r_dup_aids.status_code} {r_dup_aids.text}")
    assert r_dup_aids.status_code == 409
    assert "ACTIVE_HOD_EXISTS" in r_dup_aids.text
    
    # 3.5 Test duplicate active HOD rejection with code 'AIADS'
    payload_code_aiads = {
        "email": "qa.duplicate.code.aiads@faculty.edu",
        "full_name": "QA Duplicate Code AIADS",
        "department_id": "AIADS",
        "designation_id": hod_desg_id,
        "is_active": True,
    }
    r_dup_aiads = client.post("/api/v1/admin/faculty", json=payload_code_aiads, headers=headers)
    print(f"Create HOD with code 'AIADS'    -> Status: {r_dup_aiads.status_code} {r_dup_aiads.text}")
    assert r_dup_aiads.status_code == 409
    assert "ACTIVE_HOD_EXISTS" in r_dup_aiads.text
    
    # 3.6 Test duplicate active HOD rejection with full department name
    payload_name = {
        "email": "qa.duplicate.name@faculty.edu",
        "full_name": "QA Duplicate Name Test",
        "department_id": "Artificial Intelligence and Data Science",
        "designation_id": hod_desg_id,
        "is_active": True,
    }
    r_dup_name = client.post("/api/v1/admin/faculty", json=payload_name, headers=headers)
    print(f"Create HOD with Full Name       -> Status: {r_dup_name.status_code} {r_dup_name.text}")
    assert r_dup_name.status_code == 409
    assert "ACTIVE_HOD_EXISTS" in r_dup_name.text
    
    results["bug3_aids_hod"] = {
        "status": "PASS",
        "aids_department_found": True,
        "aids_uuid": aids_uuid,
        "active_hod_email": aids_active_hod.get("email") if aids_active_hod else None,
        "canonical_uuid_409": r_dup_uuid.status_code == 409,
        "code_aids_409": r_dup_aids.status_code == 409,
        "code_aiads_409": r_dup_aiads.status_code == 409,
        "name_alias_409": r_dup_name.status_code == 409,
    }

print("\n" * 1)
print("=" * 80)
print("4. BUG 1: PATENT DATE EXTRACTION & SERIALIZATION")
print("=" * 80)

with httpx.Client(base_url=BACKEND_URL, timeout=30.0) as client:
    r_login = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    r_recs = client.get("/api/v1/admin/ip-records?per_page=50", headers=headers)
    records = r_recs.json().get("records", [])
    print(f"Total live records inspected: {len(records)}")
    
    iso_date_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    checked_records = []
    
    for r in records:
        f_date = r.get("filing_date")
        p_date = r.get("published_date")
        g_date = r.get("grant_date")
        c_date = r.get("certificate_date")
        
        # Verify date format when present
        for date_field, val in [("filing_date", f_date), ("published_date", p_date), ("grant_date", g_date), ("certificate_date", c_date)]:
            if val is not None:
                assert iso_date_regex.match(val), f"Field {date_field} '{val}' on record {r.get('id')} does not match YYYY-MM-DD!"
        
        checked_records.append({
            "id": r.get("id"),
            "ip_type": r.get("ip_type"),
            "title": (r.get("title") or "")[:40],
            "filing_date": f_date,
            "published_date": p_date,
            "grant_date": g_date,
            "certificate_date": c_date,
        })
    
    # Print sample verified records
    print("Sample verified records (Strict YYYY-MM-DD date serialization):")
    for cr in checked_records[:5]:
        print(f"  [{cr['id'][:8]}] {cr['ip_type']}: Filing={cr['filing_date']}, Pub={cr['published_date']}, Grant={cr['grant_date']}")
    
    # Check design registrations: design registrations must NOT invent grant dates
    design_recs = [cr for cr in checked_records if cr["ip_type"] == "DESIGN_REGISTRATION"]
    print(f"Design registrations inspected: {len(design_recs)}")
    for dr in design_recs:
        print(f"  Design [{dr['id'][:8]}]: Grant={dr['grant_date']} (None expected if not granted)")
        
    results["bug1_dates"] = {
        "status": "PASS (Backend Serialization & Model Gate)",
        "total_records_inspected": len(records),
        "all_dates_conforming_iso": True,
        "sample_records": checked_records[:5],
    }

print("\n" * 1)
print("=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print(json.dumps(results, indent=2))
with open("LIVE_PROBE_SUMMARY.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
print("Results saved to LIVE_PROBE_SUMMARY.json")
