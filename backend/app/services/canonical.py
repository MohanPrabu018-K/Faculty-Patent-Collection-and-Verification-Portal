"""Canonical data normalization utilities.

This module provides the single canonical normalization point for the FPP pipeline.
It converts evidence-wrapped extraction output into clean scalar canonical values
while preserving evidence/provenance separately.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def unwrap_evidence(value: Any) -> Any:
    """Extract canonical scalar/list value from evidence wrapper structures.

    Handles:
    - Scalar values (passed through)
    - Lists of evidence wrappers: [{"value": X, "source": Y, "confidence": Z}, ...]
      -> Returns list of scalar values [X, ...]
    - Single evidence wrapper dict: {"value": X, "source": Y, "confidence": Z}
      -> Returns scalar X
    - Lists of scalars (passed through)
    - None (returns None)
    - Malformed/legacy structures (best effort)

    Args:
        value: Raw extracted value which may be evidence-wrapped

    Returns:
        Canonical unwrapped value (scalar, list of scalars, or None)
    """
    if value is None:
        return None

    # Already a scalar (str, int, float, bool, date, datetime) - pass through
    if isinstance(value, (str, int, float, bool, date, datetime)):
        return value

    # List of items - process each element
    if isinstance(value, list):
        if not value:
            return []
        unwrapped = []
        for item in value:
            unwrapped_item = unwrap_evidence(item)
            if unwrapped_item is not None:
                unwrapped.append(unwrapped_item)
        
        # Special case: if we have a single item that is a list, 
        # and the original was an evidence wrapper for a list field,
        # unwrap the extra layer
        if len(unwrapped) == 1 and isinstance(unwrapped[0], list):
            # This handles the case where evidence wrapper's "value" is a list
            # e.g., [{"value": ["a", "b", "c"], ...}] -> ["a", "b", "c"]
            return unwrapped[0]
        
        return unwrapped

    # Dict - could be evidence wrapper or structured object
    if isinstance(value, dict):
        # Check if this looks like an evidence wrapper
        if "value" in value and len(value) <= 4:  # evidence wrapper typically has value, source, confidence, qr_data
            return value.get("value")
        # Otherwise it's a structured object (e.g., contributor) - return as-is
        return value

    # Unknown type - return as-is
    return value


def normalize_canonical_data(evidence_fields: dict[str, Any]) -> dict[str, Any]:
    """Convert evidence-wrapped fields dict to canonical data dict.

    This is the SINGLE canonical normalization point. It must be called
    exactly once after OCRExtractionAgent completes.

    Args:
        evidence_fields: The `normalized_fields` from StructuredExtractionService
                         (evidence-wrapped structure)

    Returns:
        Canonical data dict with scalar/list/structured values
    """
    canonical = {}

    # Fields that should be scalar (take first value)
    scalar_fields = {
        "patent_number", "design_number", "application_number",
        "publication_number", "serial_number", "title",
        "applicant", "patentee", "qr_data", "ip_type",
        "filing_date", "grant_date", "registration_date",
        "certificate_date", "published_date", "confidence"
    }

    # Fields that should be lists of structured objects
    structured_list_fields = {
        "contributors"
    }

# Fields that should be lists of simple values
    simple_list_fields = {
        "inventors"
    }

    for field_name, field_value in evidence_fields.items():
        unwrapped = unwrap_evidence(field_value)
        
        if field_name in scalar_fields:
            # For scalar fields, take the first value if it's a list.
            # Exception: applicant/patentee may legitimately hold several
            # joint proprietor names; joining keeps every name instead of
            # silently keeping only the first (and a raw list must never
            # reach a String column, where the driver would persist it as
            # a Postgres array literal like '{"A","B"}').
            if isinstance(unwrapped, list):
                if field_name in ("applicant", "patentee"):
                    canonical[field_name] = (
                        ", ".join(str(v) for v in unwrapped)
                        if unwrapped
                        else None
                    )
                else:
                    canonical[field_name] = unwrapped[0] if unwrapped else None
            else:
                canonical[field_name] = unwrapped
        elif field_name in structured_list_fields:
            # For structured list fields (contributors), the unwrapped value
            # should already be a list of dicts. But evidence wrapper may
            # wrap it in an extra list layer.
            if isinstance(unwrapped, list):
                if unwrapped and isinstance(unwrapped[0], list):
                    # Double-wrapped: [[contributor1, contributor2, ...]]
                    canonical[field_name] = unwrapped[0]
                else:
                    # Single-wrapped: [contributor1, contributor2, ...]
                    canonical[field_name] = unwrapped
            else:
                canonical[field_name] = []
        elif field_name in simple_list_fields:
            # For simple list fields (inventors), ensure it's a flat list
            if isinstance(unwrapped, list):
                if unwrapped and isinstance(unwrapped[0], list):
                    canonical[field_name] = unwrapped[0]
                else:
                    canonical[field_name] = unwrapped
            elif unwrapped is not None:
                canonical[field_name] = [unwrapped]
            else:
                canonical[field_name] = []
        else:
            # Default: use unwrapped as-is
            canonical[field_name] = unwrapped

    return canonical


# Canonical field schema definition for validation/documentation
CANONICAL_FIELDS = {
    # Scalar identifiers
    "patent_number": str,
    "design_number": str,
    "application_number": str,
    "publication_number": str,
    "serial_number": str,
    
    # Scalar metadata
    "title": str,
    "filing_date": (date, str),
    "grant_date": (date, str),
    "registration_date": (date, str),
    "certificate_date": (date, str),
    "published_date": (date, str),
    "applicant": str,
    "patentee": str,
    
    # List fields
    "inventors": list,
    "contributors": list,
    
    # Derived/computed
    "ip_type": str,
    "qr_data": str,
    "confidence": float,
}


def validate_canonical_data(canonical: dict[str, Any]) -> list[str]:
    """Validate canonical data structure. Returns list of validation errors."""
    errors = []
    
    # Check required fields exist (at least one identifier)
    has_identifier = any(
        canonical.get(f) for f in 
        ["patent_number", "design_number", "application_number", "publication_number", "serial_number"]
    )
    if not has_identifier:
        errors.append("No identifier found in canonical data")
    
    # Validate types
    for field, expected_type in CANONICAL_FIELDS.items():
        value = canonical.get(field)
        if value is not None:
            if isinstance(expected_type, tuple):
                if not isinstance(value, expected_type):
                    errors.append(f"Field '{field}' has wrong type: expected {expected_type}, got {type(value)}")
            elif not isinstance(value, expected_type):
                errors.append(f"Field '{field}' has wrong type: expected {expected_type}, got {type(value)}")
    
    # Validate contributors structure
    contributors = canonical.get("contributors", [])
    if contributors:
        for i, c in enumerate(contributors):
            if not isinstance(c, dict):
                errors.append(f"Contributor {i} is not a dict")
            elif "name" not in c:
                errors.append(f"Contributor {i} missing 'name' field")
    
    return errors