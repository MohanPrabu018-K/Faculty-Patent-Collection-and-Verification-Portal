"""Regression tests for applicant semantics on design certificates.

Applicant must only ever come from an explicit proprietor statement
("in the name of ..."). Contributor/inventor names must never be silently
converted into an applicant, and joint proprietors must persist as a clean
human-readable string (never a Postgres array literal like '{"A","B"}').
"""

from app.services.canonical import normalize_canonical_data
from app.services.extraction import StructuredExtractionService


def _cert_text(with_proprietors: bool) -> str:
    names = (
        "in the name of 1.Dr. Ada Example 2.Dr. Bob Sample."
        if with_proprietors
        else "by 1.Dr. Ada Example 2.Dr. Bob Sample."
    )
    return (
        "ORIGINAL\n"
        "Serial No. : 123456\n"
        "Design No. : 999991-001\n"
        "Date : 22/10/2024\n"
        "Certified that the design of which a copy is annexed hereto has been\n"
        "registered as of the number and date given above in class 24-01 in\n"
        "respect of the application of such design to TEST WIDGET "
        f"{names}\n"
        "In pursuance of and subject to the provisions of the Designs Act,\n"
        "2000 and the Designs Rules, 2001.\n"
    )


def test_explicit_proprietors_become_clean_applicant_string():
    service = StructuredExtractionService()
    result = service.extract_from_text(_cert_text(with_proprietors=True), "DESIGN_REGISTRATION")
    canonical = normalize_canonical_data(result["normalized_fields"])
    applicant = canonical.get("applicant")
    assert isinstance(applicant, str), applicant
    assert "Ada Example" in applicant and "Bob Sample" in applicant
    assert '{"' not in applicant, applicant
    # Contributors stay separate and intact.
    assert canonical.get("design_number") == "999991-001"


def test_no_proprietor_statement_means_no_applicant():
    service = StructuredExtractionService()
    result = service.extract_from_text(_cert_text(with_proprietors=False), "DESIGN_REGISTRATION")
    canonical = normalize_canonical_data(result["normalized_fields"])
    assert canonical.get("applicant") in (None, ""), canonical.get("applicant")
    # Inventor/contributor names are preserved where they belong.
    inventors = canonical.get("inventors") or []
    assert any("Ada Example" in name for name in inventors), inventors


def test_canonical_joins_applicant_name_list():
    canonical = normalize_canonical_data(
        {
            "applicant": [{"value": ["Dr. Ada Example", "Dr. Bob Sample"], "source": "ocr_text", "confidence": 0.85}],
            "ip_type": "DESIGN_REGISTRATION",
        }
    )
    assert canonical.get("applicant") == "Dr. Ada Example, Dr. Bob Sample"
