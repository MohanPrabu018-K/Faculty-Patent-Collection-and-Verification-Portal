# FPP Skipped Backend Test Resolution Report

**Execution Date:** 2026-10-26  
**Auditor:** QA Automation Engineer & Backend Integration Specialist  
**Test Database:** Disposable local PostgreSQL 16 on `localhost:5432` (`test_fpp`)  
**Initial State:** 11 skipped tests across 3 test suites (`test_hardening.py`, `test_batch5_authz.py`, `test_regression_fixes.py`)  
**Final State:** 11 resolved and passing tests (**0 skipped**)  

---

## 1. Executive Summary & Root Cause Analysis

During the initial baseline automated test run, 11 backend tests were skipped. A thorough investigation into each test file revealed a common root cause:
- **Clean-Room Disposable Database Assumption:** The tests were authored under the assumption of a shared staging database pre-populated with faculty records and on-disk certificate files.
- When running in an isolated clean-room environment against `test_fpp`, `fac-a-001` and `fac-b-001` did not possess pre-existing records, and no file existed under `upload_settings.local_storage_root`.
- Consequently, `ref_record` returned `None`, and the dashboard queries returned empty record lists, triggering conditional `pytest.skip()` clauses.

Rather than weakening assertions or removing skip checks, we implemented isolated synthetic fixtures (department-scoped test records and an on-disk synthetic PDF certificate fixture), enabling all 11 tests to execute their full assertion logic deterministically.

---

## 2. Detailed Resolution Matrix (All 11 Tests)

| # | Test Suite | Test Function | Pre-Resolution Skip Reason | Synthetic Fixture / Resolution Applied | Post-Resolution Status |
| :-: | :--- | :--- | :--- | :--- | :---: |
| 1 | `test_hardening.py` | `test_archive_unarchive_and_filter` | `no dept-scoped record with file available` | Seeded synthetic patent `test-hardening-rec-001` with `synthetic_test_cert.pdf` on disk. | **PASSED** |
| 2 | `test_hardening.py` | `test_faculty_cannot_archive_record` | `no dept-scoped record with file available` | Reused synthetic record fixture; verified 403 response on faculty archive attempt. | **PASSED** |
| 3 | `test_hardening.py` | `test_admin_date_range_filters_effective` | `no dept-scoped record with file available` | Reused synthetic record fixture; verified admin date filter bounding. | **PASSED** |
| 4 | `test_hardening.py` | `test_admin_designation_and_is_archived_filters` | `no dept-scoped record with file available` | Reused synthetic record fixture; verified designation and archive query flags. | **PASSED** |
| 5 | `test_hardening.py` | `test_admin_contributor_count_and_institution_filters` | `no dept-scoped record with file available` | Reused synthetic record fixture; verified contributor aggregations. | **PASSED** |
| 6 | `test_hardening.py` | `test_file_download_owner_and_admin_ok` | `no dept-scoped record with file available` | Generated real PDF bytes at storage root; verified 200 download for owner & admin. | **PASSED** |
| 7 | `test_hardening.py` | `test_file_download_hod_scoping_and_idor` | `no dept-scoped record with file available` | Verified same-dept HOD allowed (200), cross-dept HOD denied (404/403). | **PASSED** |
| 8 | `test_hardening.py` | `test_file_download_unknown_file_id` | `no dept-scoped record with file available` | Reused synthetic record; verified 404 on nonexistent file ID. | **PASSED** |
| 9 | `test_batch5_authz.py`| `test_faculty_status_contract_fields_present` | `Faculty A has no records in the staging DB` | `fac-a-001` seeded with `test-hardening-rec-001`; verified status contract fields (`workflow_state`, `duplicate_status`, `conflict_status`). | **PASSED** |
| 10 | `test_batch5_authz.py`| `test_hod_cannot_read_other_department_record_status` | `Faculty B has no records in the staging DB` | `fac-b-001` seeded with `test-hardening-rec-002` (`dept-b`); verified HOD-A receives 404 (department isolation). | **PASSED** |
| 11 | `test_regression_fixes.py`| `test_status_qr_data_is_list` | `Faculty A has no records in the staging DB` | Linked to active synthetic record; verified `/api/v1/faculty/{rid}/status` returns `qr_data` as a JSON list. | **PASSED** |

---

## 3. Verification Commands & Outputs

```bash
# Running test_hardening.py
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_hardening.py -v
======================= 16 passed, 2 warnings in 7.14s ========================

# Running test_batch5_authz.py
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_batch5_authz.py -v
======================= 21 passed, 2 warnings in 3.09s ========================

# Running test_regression_fixes.py
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_regression_fixes.py -v
======================= 13 passed, 2 warnings in 2.37s ========================
```

Total tests across the 3 affected suites: **50 passed, 0 failed, 0 skipped**.
All 11 previously skipped scenarios are now fully verified.
