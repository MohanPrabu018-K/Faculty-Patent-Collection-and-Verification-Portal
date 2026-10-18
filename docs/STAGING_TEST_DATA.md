# Staging test data & source-grounded mapping

This document defines the synthetic staging dataset produced by
`scripts/staging/provision_staging.py` and records how it maps back to the
source PDFs **without inventing identifiers**.

## 1. Accounts

All emails use the documentation-reserved `example.com` domain (RFC 2606; never
a real mailbox) and all IDs are prefixed
`STG-`; they cannot collide with a real institution identity. Passwords are
generated locally and written only to `scripts/staging/staging_accounts.local.json`
and `frontend/tests-staging/.staging-fixtures.json` (both gitignored).

### Base matrix — 14 accounts

| # | key | role | department | faculty_id | purpose |
| --- | --- | --- | --- | --- | --- |
| 1 | `faculty01` | faculty | A | `STG-FAC-01` | uploader / record owner |
| 2 | `faculty02` | faculty | A | `STG-FAC-02` | internal co-contributor |
| 3 | `faculty03` | faculty | A | `STG-FAC-03` | internal co-contributor |
| 4 | `faculty04` | faculty | A | `STG-FAC-04` | association recipient (positive) |
| 5 | `faculty05` | faculty | B | `STG-FAC-05` | uploader (dept B) |
| 6 | `faculty06` | faculty | B | `STG-FAC-06` | internal co-contributor |
| 7 | `faculty07` | faculty | B | `STG-FAC-07` | association recipient (SA-denial) |
| 8 | `faculty08` | faculty | C | `STG-FAC-08` | uploader (dept C) |
| 9 | `faculty09` | faculty | C | `STG-FAC-09` | internal co-contributor |
| 10 | `faculty10` | faculty | C | `STG-FAC-10` | non-recipient (IDOR denial) |
| 11 | `hodA` | hod_admin | A | `STG-HOD-01` | HOD dept A (read-only) |
| 12 | `hodB` | hod_admin | B | `STG-HOD-02` | HOD dept B (scoping) |
| 13 | `hodC` | hod_admin | C | `STG-HOD-03` | HOD dept C (scoping) |
| 14 | `superAdmin` | super_admin | — | — | grant + duplicates/conflicts resolution |

### Additional negative-test account (15th)

| key | role | department | faculty_id | purpose |
| --- | --- | --- | --- | --- |
| `facultyDeactivated` | faculty | A | `STG-FAC-DEACTIVATED` | login/action deactivation denial |

### Identity provenance

`identity_source = "SYNTHETIC_PLACEHOLDER"`. **No real faculty ID is invented.**
If the institution supplies approved IDs, replace the `faculty_id` values and
set `identity_source = "INSTITUTION_APPROVED"` before provisioning. The
provisioner records the source in the fixtures file so QA results state which
identities were used.

## 2. Scenario records

All record ids start with `stg-rec-`. Every record is synthetic; none is copied
from a real filing.

| id | uploader | dept | type | state | used by |
| --- | --- | --- | --- | --- | --- |
| `stg-rec-a1` | faculty01 | A | PATENT | FACULTY_ASSOCIATION_PENDING | A (auto-assoc + idempotency), B, F |
| `stg-rec-a2` | faculty01 | A | DESIGN | FACULTY_ASSOCIATION_PENDING | duplicate pair, B |
| `stg-rec-b1` | faculty05 | B | PATENT | FACULTY_ASSOCIATION_PENDING | HOD scoping, E |
| `stg-rec-b1b` | faculty05 | B | PATENT | FACULTY_ASSOCIATION_PENDING | duplicate pair 2 |
| `stg-rec-c1` | faculty08 | C | PATENT | FACULTY_ASSOCIATION_PENDING | conflict case, D |
| `stg-rec-ext-only` | faculty01 | A | PATENT | FACULTY_ASSOCIATION_PENDING | C (externals excluded) |
| `stg-rec-grantable` | faculty01 | A | PATENT | FACULTY_ASSOCIATION_COMPLETE, VERIFIED | E (grant success) |
| `stg-rec-needverify` | faculty01 | A | PATENT | VERIFICATION_REQUIRED | E (grant ineligible) |
| `stg-rec-hod-a` | faculty01 | A | PATENT | FACULTY_ASSOCIATION_COMPLETE, VERIFIED | D (HOD sees dept A) |
| `stg-rec-hod-b` | faculty05 | B | PATENT | FACULTY_ASSOCIATION_COMPLETE, VERIFIED | D (HOD must NOT see dept B) |

Supporting fixtures:

* `stg-dup-01` (open duplicate: a1 ↔ a2), `stg-dup-02` (open duplicate: b1 ↔ b1b)
* `stg-conf-01` (open conflict on c1)
* `stg-assoc-pending-01` (faculty01 → faculty04 on a1; recipient-only + IDOR)
* `stg-assoc-pending-02` (faculty05 → faculty07 on b1; SA-denial)

## 3. Source-grounded mapping (the 7 PDFs)

The 7 source PDFs are **input material only**. They are used to shape realistic
synthetic records; they are never uploaded to production, and no identifier is
transcribed into a fixture unless it is explicitly present in the document.

Inventory (read-only inspection):

| file | document type | applicant / inventors (as printed) | official identifier in doc? |
| --- | --- | --- | --- |
| design certificate 1–4 | DESIGN_REGISTRATION | R P Sarathy Institute of Technology | not present as a verifiable full number |
| patent certificate | PATENT | R P Sarathy Institute of Technology | not present as a verifiable full number |
| journal app-publication | PUBLICATION_DOCUMENT | applicant R P Sarathy Institute of Technology; inventor Dr. N. Devakirubai | n/a |
| multi-entry journal design-publication page | PUBLICATION_DOCUMENT | external contributors (Vels, Saveetha, SKSVMACET, MRIIRS, Greehopper Machineries & Contractors Pvt. Ltd — Sijo Joseph) | n/a |

**Institution:** R P Sarathy Institute of Technology (Salem, TN).

### Mapping rules applied

1. **No invented IDs.** None of the documents contains a faculty ID; therefore
   every `faculty_id` in the fixtures is an explicit `STG-` synthetic
   placeholder, never a plausible-looking real ID.
2. **A journal page is not one record.** The multi-entry journal
   design-publication page lists several unrelated entries/contributors; it is
   treated as N separate design-registration entries (mapped conceptually to
   `stg-rec-a1`/`a2`/`c1`), never as a single record.
3. **Recurring contributor.** `Dr. N. Devakirubai` recurs across documents and
   is represented in fixtures as an **EXTERNAL** contributor (`stg-con-a1-03`,
   `stg-con-ext-02`) because no staging user account was created from the source
   name — externals must never receive association requests (rule C).
4. **External institutions stay external.** Vels / Saveetha / SKSVMACET / MRIIRS
   / Greehopper Machineries contributors are external, not internal reviewers.
5. **Prefer synthetic records.** Where a document lacks a machine-readable
   official identifier, the staging record uses a synthetic `STG-…` number so
   the workflow (grant identifier gate) is testable without fabricating a real
   registration number.

The full inventory (names, page counts) lives in the Phase 1 preflight report;
addresses are intentionally not reproduced anywhere in repo files.
