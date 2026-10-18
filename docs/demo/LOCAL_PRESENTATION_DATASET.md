# FPP Presentation Dataset

**DB:** local `faculty_portal_staging` · **Prefix:** `demo-` / `DEMO-` · **Builder:** `fpp-demo\demo_seed.py` + `demo_flows.py` (idempotent; refuse non-staging).
**Users:** 5 faculty (Computing A/B, Electronics C/D, Mechanical E) + 3 HODs (one per dept) + preserved `admin@faculty.edu` + preserved Mohan faculty.
**Departments (real reference rows):** Staging Computing (A) / Electronics (B) / Mechanical (C). No duplicate departments created.

| Scenario | Record | Uploader | State | Visible to | Demo beat |
|---|---|---|---|---|---|
| 1 assoc pending | DEMO-ASSOC-001 | Fac A | COMPLETE/VERIFIED + 2 PENDING reqs | Fac A/B/C, HOD-A only | auto-accept, no self-req, explicit send, B accepts live |
| 2 multidept | DEMO-MULTIDEPT-001 | Fac A (+C,E linked, accepted) | COMPLETE/VERIFIED | HOD-A/B/C, all faculty | fan-out, read-only HOD |
| 3 grant-ready | DEMO-GRANT-READY-001 | Fac B | COMPLETE/VERIFIED, no pendings/blocks | SA (+faculty/HOD read) | **live Grant moment (pristine)** |
| 4 granted | DEMO-GRANTED-001 | Fac D | GRANTED (+grant date, audit) | all roles | listing, audit, double-grant 409 |
| 5 conflict | DEMO-CONFLICT-001 | Fac E | COMPLETE/VERIFIED + OPEN HIGH conflict | SA/faculty/HOD | grant refused 422, UI explains block |
| 6 rejected | DEMO-REJECT-001 | Fac C | NEEDS_REVIEW, REJECTED history kept | parties + SA | rejection persisted, grant 422 |
| 7 review | DEMO-REVIEW-001 | Fac A | PENDING/VERIFICATION_REQUIRED, all metadata null | faculty/SA (HODs excluded) | safe failure, no fabrication |
| 8 fresh upload | DEMO-UPLOAD-001 + `demo-live.pdf` | Fac A | COMPLETE/VERIFIED (backup proof) | — | live re-upload during show |

**Negative cases:** HOD-B/C exclude ASSOC; all HODs exclude pre-stage REVIEW; faculty/HOD/anon grants refused (covered in automated suites).
**Titles** set via the real uploader-review endpoint (REVIEW stays null-titled by design).
**Not in dataset:** legacy `stg-*` fixtures (removed after backup), pre-existing test residue (164 rows removed, manifest in prep log), `master_ip_record` ×3 (uncertain ownership — preserved, reported).
