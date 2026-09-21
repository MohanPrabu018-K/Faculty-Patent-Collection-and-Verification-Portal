"""Regression tests for production defects F1 (external user_id leak) and
F2 (patent-journal extraction starved by OCR context truncation / missing
INID journal patterns).

All fixtures are synthetic. No real certificate values are used.
"""

from types import SimpleNamespace

from app.agents.ocr_extraction_agent import OCR_TEXT_CONTEXT_CHARS
from app.services.canonical import normalize_canonical_data
from app.services.extraction import StructuredExtractionService
from app.workers.orchestrator_task import (
    _IDENTITY_INTERNAL_THRESHOLD,
    _master_identifier_present,
    _resolve_contributor_match,
)


def _synthetic_journal_text() -> str:
    """Long patent-application journal text with every key field placed
    AFTER character 500, in WIPO ST.16 numbered-field layout."""
    preamble = (
        "The Patent Office Journal No. 07/2026 Dated 13/02/2026 9911\n"
        "Office of the Controller General of Patents, Designs and Trade Marks\n"
        "Introductory notes on publication procedure and fee schedules follow. "
        * 12
    )
    assert len(preamble) > 500
    body = """
(12) PATENT APPLICATION PUBLICATION
(21) Application No.202612345678 A
(19) INDIA
(22) Date of filing of Application :15/03/2025
(43) Publication Date : 20/06/2025

(54) Title of the invention : SOLAR POWERED WATER PURIFICATION UNIT

(71)Name of Applicant :
   1)TEST APPLICANT UNIVERSITY
      Address of Applicant :Knowledge Park, Test City, India-000001.
(72)Name of Inventor :
   1)A. TESTER
      Address of Applicant :Professor, Test Applicant University.
   2)B. SAMPLE
      Address of Applicant :Assistant Professor, Test Applicant University.
(57) Abstract :
A solar powered unit for purifying water in remote areas.
"""
    return preamble + body


def test_journal_fields_extracted_after_char_500():
    text = _synthetic_journal_text()
    # Guard: every key field really sits past the old 500-char cutoff.
    for marker in ("202612345678", "SOLAR POWERED", "A. TESTER", "B. SAMPLE"):
        assert text.index(marker) > 500

    service = StructuredExtractionService()
    result = service.extract_from_text(text, "PATENT")
    canonical = normalize_canonical_data(result["normalized_fields"])

    assert canonical.get("application_number") == "202612345678"
    assert canonical.get("title") == "SOLAR POWERED WATER PURIFICATION UNIT"
    assert canonical.get("inventors") == ["A. TESTER", "B. SAMPLE"]
    assert canonical.get("applicant") == "TEST APPLICANT UNIVERSITY"
    assert str(canonical.get("filing_date")) == "2025-03-15"
    assert str(canonical.get("published_date")) == "2025-06-20"


def test_journal_inventor_section_absent_falls_back():
    service = StructuredExtractionService()
    result = service.extract_from_text(
        "Patent No: 7654321\nInventor: C. PLAIN, D. ORDINARY\n", "PATENT"
    )
    canonical = normalize_canonical_data(result["normalized_fields"])
    assert canonical.get("inventors") == ["C. PLAIN", "D. ORDINARY"]


def test_ocr_context_cap_preserves_full_document_text():
    assert OCR_TEXT_CONTEXT_CHARS >= 15000
    text = _synthetic_journal_text()
    # A typical full journal page (~4KB) must pass through whole.
    assert len(text) < OCR_TEXT_CONTEXT_CHARS
    assert text[:OCR_TEXT_CONTEXT_CHARS].index("B. SAMPLE") > 500
    # Even a 14KB document keeps its tail.
    long_text = "filler line for size padding. " * 450 + "TAIL MARKER 987"
    assert "TAIL MARKER 987" in long_text[:OCR_TEXT_CONTEXT_CHARS]


def test_external_contributor_match_returns_no_user():
    resolved = [
        {
            "contributor_name": "Dr. Suneel Kumar Asileti",
            "best_match": {
                "id": "some-user-id",
                "faculty_id": "FAC-X",
                "name": "Some Faculty",
                "confidence": 0.1655,
            },
            "candidates": [],
        }
    ]
    user_id, confidence, is_internal = _resolve_contributor_match(
        "Dr. Suneel Kumar Asileti", resolved
    )
    assert is_internal is False
    assert user_id is None
    assert confidence is None


def test_external_below_floor_returns_no_user():
    resolved = [
        {
            "contributor_name": "Dr. U. Sakthi",
            "best_match": {"id": "uid-1", "confidence": 0.2824},
            "candidates": [],
        }
    ]
    assert _resolve_contributor_match("Dr. U. Sakthi", resolved) == (
        None,
        None,
        False,
    )


def test_internal_exact_match_keeps_user():
    resolved = [
        {
            "contributor_name": "Dr. Ashwin. M",
            "best_match": {"id": "uid-ashwin", "confidence": 0.5},
            "candidates": [],
        }
    ]
    user_id, confidence, is_internal = _resolve_contributor_match(
        "Dr. Ashwin. M", resolved
    )
    assert is_internal is True
    assert user_id == "uid-ashwin"
    assert confidence == 0.5


def test_internal_high_confidence_match_keeps_user():
    resolved = [
        {
            "contributor_name": "Dr. N. Devakirubai",
            "best_match": {"id": "uid-deva", "confidence": 0.9},
            "candidates": [],
        }
    ]
    user_id, confidence, is_internal = _resolve_contributor_match(
        "dr. n. devakirubai", resolved
    )
    assert (user_id, confidence, is_internal) == ("uid-deva", 0.9, True)


def test_legacy_flat_entity_shape_still_matches():
    resolved = [{"name": "Dr. X", "id": "uid-x", "confidence": 0.6}]
    assert _resolve_contributor_match("Dr. X", resolved) == (
        "uid-x",
        0.6,
        True,
    )


def test_no_resolution_entity_returns_no_user():
    assert _resolve_contributor_match("Nobody Here", []) == (None, None, False)
    assert _resolve_contributor_match("Nobody Here", None) == (None, None, False)


def test_internal_threshold_separates_exact_from_noise():
    assert _IDENTITY_INTERNAL_THRESHOLD == 0.4


def test_title_with_whitespace_only_blank_line():
    """F2A: real OCR emits whitespace-only blank lines ("\\n \\n"); the title
    terminator must accept them instead of dropping the title."""
    text = (
        "The Patent Office Journal No. 07/2026 Dated 13/02/2026\n"
        "(12) PATENT APPLICATION PUBLICATION\n"
        "(21) Application No.202600000007\n"
        "(54) Title of the invention : SYNTHETIC TEST WIDGET\n"
        " \n"
        "(51) International classification :H04L0067120000\n"
    )
    service = StructuredExtractionService()
    result = service.extract_from_text(text, "PATENT")
    canonical = normalize_canonical_data(result["normalized_fields"])
    assert canonical.get("title") == "SYNTHETIC TEST WIDGET"


def test_title_with_clean_blank_line_still_works():
    text = "Patent Number: 7654321\nTitle: PLAIN OLD TITLE\n\nNext section here\n"
    service = StructuredExtractionService()
    result = service.extract_from_text(text, "PATENT")
    canonical = normalize_canonical_data(result["normalized_fields"])
    assert canonical.get("title") == "PLAIN OLD TITLE"


def test_patent_inventors_mirrored_as_canonical_contributors():
    """F2B: patent inventors must enter the canonical `contributors` contract
    so identity resolution and association stages can see them."""
    service = StructuredExtractionService()
    result = service.extract_from_text(_synthetic_journal_text(), "PATENT")
    canonical = normalize_canonical_data(result["normalized_fields"])
    assert canonical.get("inventors") == ["A. TESTER", "B. SAMPLE"]
    assert canonical.get("contributors") == [
        {"name": "A. TESTER"},
        {"name": "B. SAMPLE"},
    ]
    # And a canonical contributor entry flows through identity matching.
    user_id, confidence, is_internal = _resolve_contributor_match(
        "B. SAMPLE",
        [
            {
                "contributor_name": "B. SAMPLE",
                "best_match": {"id": "uid-sample", "confidence": 0.5},
                "candidates": [],
            }
        ],
    )
    assert (user_id, confidence, is_internal) == ("uid-sample", 0.5, True)


def test_master_identifier_present_with_application_only():
    """F2C: a pure patent application (no grant/design number yet) still
    carries a master-linking identifier via application_number."""
    assert (
        _master_identifier_present(
            SimpleNamespace(
                patent_number=None,
                design_number=None,
                application_number="202600000001",
            )
        )
        is True
    )
    assert (
        _master_identifier_present(
            SimpleNamespace(
                patent_number=None,
                design_number="410787-001",
                application_number=None,
            )
        )
        is True
    )
    assert (
        _master_identifier_present(
            SimpleNamespace(
                patent_number=None, design_number=None, application_number=None
            )
        )
        is False
    )
