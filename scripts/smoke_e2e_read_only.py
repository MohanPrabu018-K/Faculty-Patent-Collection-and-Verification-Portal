import json
import os
import sys
import httpx

API_BASE = "https://faculty-patent-portal-api.onrender.com"

def run_smoke_test():
    print("=" * 70)
    print("  FPP PRODUCTION READ-ONLY SMOKE TEST SUITE")
    print("=" * 70)
    
    # Load credentials safely from environment or local admin_cred.json if present
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not (admin_email and admin_password) and os.path.exists("admin_cred.json"):
        try:
            with open("admin_cred.json", "r", encoding="utf-8") as f:
                admin_cred = json.load(f)
                admin_email = admin_email or admin_cred.get("email")
                admin_password = admin_password or admin_cred.get("password")
        except Exception:
            pass
    
    admin_email = admin_email or "admin@faculty.edu"
    admin_password = admin_password or "TestPassAdmin123!"

    # Authorized test accounts
    accounts = {
        "Super Admin": {"email": admin_email, "password": admin_password},
        "HOD": {"email": os.getenv("HOD_EMAIL", "mv-hod@faculty.edu"), "password": os.getenv("HOD_PASSWORD", "TestPass123!")},
        "Faculty": {"email": os.getenv("FACULTY_EMAIL", "faculty2@faculty.edu"), "password": os.getenv("FACULTY_PASSWORD", "TestPass456!")}
    }
    
    tokens = {}
    
    with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
        # -------------------------------------------------------------
        # 1. Unauthenticated Security Gates (Section 5)
        # -------------------------------------------------------------
        print("\n--- 1. Unauthenticated Security Gate Probes ---")
        for ep in ["/api/v1/admin/dashboard", "/api/v1/hod/dashboard", "/api/v1/faculty/my-records"]:
            r = client.get(ep)
            print(f"GET {ep} (Anonymous) -> Status: {r.status_code} (Expected: 401)")
            assert r.status_code == 401, f"Expected 401 for anonymous {ep}, got {r.status_code}"
        print("Unauthenticated gates: ALL PASS")

        # -------------------------------------------------------------
        # 2. Authentication Smoke Tests (Section 4)
        # -------------------------------------------------------------
        print("\n--- 2. Authentication Smoke Tests ---")
        for role_name, cred in accounts.items():
            r = client.post("/api/v1/auth/login", json={"email": cred["email"], "password": cred["password"]})
            print(f"Login [{role_name}] -> Status: {r.status_code} (Expected: 200)")
            assert r.status_code == 200, f"Login failed for {role_name}: {r.status_code}"
            data = r.json()
            token = data.get("access_token")
            assert token, f"No access token returned for {role_name}"
            tokens[role_name] = token
            
            # Verify /auth/me
            r_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert r_me.status_code == 200, f"/auth/me failed for {role_name}"
            me_data = r_me.json()
            user_role = me_data.get("role")
            print(f"  /auth/me -> Role: {user_role}, Status: {r_me.status_code}")
        
        # -------------------------------------------------------------
        # 3. Role-Based Access Smoke Tests (Section 5)
        # -------------------------------------------------------------
        print("\n--- 3. Role-Based Access Smoke Tests ---")
        admin_tok = tokens["Super Admin"]
        hod_tok = tokens["HOD"]
        fac_tok = tokens["Faculty"]
        
        # Super Admin accesses admin endpoints
        r_ad_dash = client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {admin_tok}"})
        print(f"Super Admin -> GET /api/v1/admin/dashboard: Status {r_ad_dash.status_code}")
        assert r_ad_dash.status_code == 200, "Super Admin dashboard access failed"
        
        r_ad_recs = client.get("/api/v1/admin/ip-records?per_page=50", headers={"Authorization": f"Bearer {admin_tok}"})
        print(f"Super Admin -> GET /api/v1/admin/ip-records: Status {r_ad_recs.status_code}")
        assert r_ad_recs.status_code == 200, "Super Admin records access failed"
        admin_records_payload = r_ad_recs.json()
        
        # HOD accesses HOD endpoints
        r_hod_dash = client.get("/api/v1/hod/dashboard", headers={"Authorization": f"Bearer {hod_tok}"})
        print(f"HOD -> GET /api/v1/hod/dashboard: Status {r_hod_dash.status_code}")
        assert r_hod_dash.status_code == 200, "HOD dashboard access failed"
        
        r_hod_docs = client.get("/api/v1/hod/documents", headers={"Authorization": f"Bearer {hod_tok}"})
        print(f"HOD -> GET /api/v1/hod/documents: Status {r_hod_docs.status_code}")
        assert r_hod_docs.status_code == 200, "HOD documents access failed"
        
        # HOD negative gate to Admin endpoint
        r_hod_neg = client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {hod_tok}"})
        print(f"HOD -> GET /api/v1/admin/dashboard: Status {r_hod_neg.status_code} (Expected: 403)")
        assert r_hod_neg.status_code == 403, f"Expected 403 for HOD admin access, got {r_hod_neg.status_code}"
        
        # Faculty accesses Faculty endpoints
        r_fac_dash = client.get("/api/v1/faculty/dashboard", headers={"Authorization": f"Bearer {fac_tok}"})
        print(f"Faculty -> GET /api/v1/faculty/dashboard: Status {r_fac_dash.status_code}")
        assert r_fac_dash.status_code == 200, "Faculty dashboard access failed"
        
        r_fac_recs = client.get("/api/v1/faculty/my-records", headers={"Authorization": f"Bearer {fac_tok}"})
        print(f"Faculty -> GET /api/v1/faculty/my-records: Status {r_fac_recs.status_code}")
        assert r_fac_recs.status_code == 200, "Faculty records access failed"
        
        # Faculty negative gate to Admin and HOD endpoints
        r_fac_neg_ad = client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {fac_tok}"})
        print(f"Faculty -> GET /api/v1/admin/dashboard: Status {r_fac_neg_ad.status_code} (Expected: 403)")
        assert r_fac_neg_ad.status_code == 403, f"Expected 403 for Faculty admin access, got {r_fac_neg_ad.status_code}"
        
        r_fac_neg_hod = client.get("/api/v1/hod/dashboard", headers={"Authorization": f"Bearer {fac_tok}"})
        print(f"Faculty -> GET /api/v1/hod/dashboard: Status {r_fac_neg_hod.status_code} (Expected: 403)")
        assert r_fac_neg_hod.status_code == 403, f"Expected 403 for Faculty HOD access, got {r_fac_neg_hod.status_code}"
        
        print("Role-Based Access: ALL PASS")
        
        # -------------------------------------------------------------
        # 4. Existing Data & Dashboard Check (Section 6)
        # -------------------------------------------------------------
        print("\n--- 4. Existing Data & Dashboard Verification ---")
        total_records = admin_records_payload.get("total")
        records_list = admin_records_payload.get("records", [])
        print(f"Total existing records reported by API: {total_records}")
        print(f"Records returned in single batch: {len(records_list)}")
        assert total_records is not None and total_records >= 0, f"Expected non-negative record count, found {total_records}"
        assert len(records_list) >= 0, f"Expected records list, found {len(records_list)}"
        
        # Inspect date fields and timezone immunity
        print("\nChecking sample record date formatting (ISO Calendar Date YYYY-MM-DD):")
        for rec in records_list[:4]:
            rec_id = rec.get("id")
            title = (rec.get("title") or "Untitled")[:35]
            grant_date = rec.get("grant_date")
            filing_date = rec.get("filing_date")
            status = rec.get("verification_status")
            state = rec.get("workflow_state")
            print(f"  [{rec_id[:8]}] State: {state} | Verif: {status} | Grant: {grant_date} | Filing: {filing_date}")
            if grant_date:
                # Must be YYYY-MM-DD or None
                assert len(grant_date) == 10 and grant_date.count("-") == 2, f"Invalid grant_date format: {grant_date}"
        
        # Pagination check
        r_page = client.get("/api/v1/admin/ip-records?page=1&per_page=5", headers={"Authorization": f"Bearer {admin_tok}"})
        assert r_page.status_code == 200
        p_data = r_page.json()
        print(f"\nPagination test: page=1, per_page=5 -> total={p_data.get('total')}, returned={len(p_data.get('records', []))}")
        assert len(p_data.get("records", [])) <= 5, "Pagination per_page failed"
        assert p_data.get("total") is not None, "Pagination total count missing"
        
        # Search & filter check
        r_search = client.get("/api/v1/admin/ip-records?q=MACHINE", headers={"Authorization": f"Bearer {admin_tok}"})
        assert r_search.status_code == 200
        s_data = r_search.json()
        print(f"Search filter test: q='MACHINE' -> total={s_data.get('total')}, returned={len(s_data.get('records', []))}")
        assert s_data.get("total") > 0, "Search returned 0 results for MACHINE"
        
        # Dashboard stats check
        dash_stats = r_ad_dash.json()
        print(f"Admin Dashboard Statistics loaded successfully: keys={list(dash_stats.keys())}")
        print("Existing Data & Dashboard: ALL PASS")

        # -------------------------------------------------------------
        # 5. Logout Check (Section 4.6)
        # -------------------------------------------------------------
        print("\n--- 5. Logout Smoke Check ---")
        r_logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {fac_tok}"})
        print(f"Logout POST /api/v1/auth/logout -> Status: {r_logout.status_code} (Expected: 200)")
        assert r_logout.status_code == 200, f"Logout failed: {r_logout.status_code}"
        print("Logout: PASS")

        print("\n" + "=" * 70)
        print("  ALL READ-ONLY SMOKE TESTS COMPLETED SUCCESSFULLY (100% PASS)")
        print("=" * 70)

if __name__ == "__main__":
    run_smoke_test()
