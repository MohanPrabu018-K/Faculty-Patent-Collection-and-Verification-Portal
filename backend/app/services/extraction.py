from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


# --- Date Normalization ---

def normalize_date(raw: str) -> date | None:
    """Normalize a date string to a Python date object.
    
    Handles various formats:
    - YYYY-MM-DD
    - MM/DD/YYYY
    - DD-MM-YYYY
    - YYYY/MM/DD
    - Month DD, YYYY
    - DD Month YYYY
    """
    if not raw:
        return None
    
    raw = raw.strip()
    
    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y %m %d",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    
    # If no format matched, return None (will be handled as UNKNOWN)
    logger.warning("date_normalization_failed", raw=raw)
    return None


def normalize_year(raw: str) -> int | None:
    """Extract and normalize a year from a string."""
    if not raw:
        return None
    
    matches = re.findall(r"(\d{4})", raw)
    if matches:
        try:
            year = int(matches[0])
            if 1900 <= year <= 2100:
                return year
        except ValueError:
            pass
    return None


# --- Identifier Normalization ---

def normalize_patent_number(raw: str) -> str | None:
    """Normalize a patent number.
    
    Strips whitespace, converts to uppercase, validates format.
    Accepts various formats: US numbers, European, etc.
    """
    if not raw:
        return None
    
    # Remove common prefixes/suffixes and normalize
    normalized = raw.strip().upper()
    
    # Remove "US" prefix if present but keep the structure
    # e.g., "US 6789012" -> "US6789012" or just "6789012"
    
    # Basic cleanup
    normalized = re.sub(r'[^A-Z0-9\-]', '', normalized)
    
    if len(normalized) >= 4:
        return normalized
    return None


def normalize_design_number(raw: str) -> str | None:
    """Normalize a design registration number."""
    if not raw:
        return None
    
    normalized = raw.strip().upper()
    normalized = re.sub(r'[^A-Z0-9\-]', '', normalized)
    
    if len(normalized) >= 3:
        return normalized
    return None


def normalize_application_number(raw: str) -> str | None:
    """Normalize a patent application number."""
    if not raw:
        return None
    
    normalized = raw.strip().upper()
    normalized = re.sub(r'[^A-Z0-9/-]', '', normalized)
    
    if len(normalized) >= 3:
        return normalized
    return None


# --- Contributor Normalization ---

def normalize_contributor_name(raw: str) -> str:
    """Normalize a contributor/faculty name."""
    if not raw:
        return "UNKNOWN"
    
    # Basic normalization: strip, title case
    name = raw.strip()
    # Don't aggressively title case as names may have specific capitalization
    return name


def normalize_designation(raw: str) -> str | None:
    """Normalize a faculty designation."""
    if not raw:
        return None
    
    # Common designations - map variations
    designation_map = {
        "assoc. prof.": "Associate Professor",
        "assistant prof.": "Assistant Professor",
        "prof.": "Professor",
        "lecturer": "Lecturer",
        "dr.": "Dr.",
        "professor": "Professor",
        "associate professor": "Associate Professor",
        "assistant professor": "Assistant Professor",
    }
    
    raw_lower = raw.strip().lower()
    if raw_lower in designation_map:
        return designation_map[raw_lower]
    
    # Return as-is if not in map
    return raw.strip()


def normalize_department(raw: str) -> str | None:
    """Normalize a department name."""
    if not raw:
        return None
    
    # Common department normalizations
    dept_map = {
        "computer science": "Computer Science",
        "cs": "Computer Science",
        "electrical engineering": "Electrical Engineering",
        "ee": "Electrical Engineering",
        "mechanical engineering": "Mechanical Engineering",
        "mfg": "Mechanical Engineering",
    }
    
    raw_lower = raw.strip().lower()
    if raw_lower in dept_map:
        return dept_map[raw_lower]
    
    return raw.strip()


# --- Evidence Tracking ---

class EvidenceTracker:
    """Tracks evidence for extracted fields with pointers to sources."""
    
    def __init__(self):
        self.evidence: dict[str, list[dict[str, Any]]] = {}
    
    def add(self, field: str, value: Any, source: str, confidence: float, qr_data: str | None = None):
        """Add evidence for a field."""
        if field not in self.evidence:
            self.evidence[field] = []
        
        self.evidence[field].append({
            "value": value,
            "source": source,
            "confidence": confidence,
            "qr_data": qr_data,
        })
    
    def get(self, field: str) -> list[dict[str, Any]] | None:
        """Get evidence for a field."""
        return self.evidence.get(field)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {k: [{"value": v["value"], "source": v["source"], "confidence": v["confidence"]} 
                  for v in vs] for k, vs in self.evidence.items()}


# --- Main Extraction Service ---

class StructuredExtractionService:
    """Service for structured extraction and normalization of IP document data."""
    
    def __init__(self):
        self.evidence_tracker = EvidenceTracker()
    
    def extract_from_text(
        self, 
        text: str, 
        ip_type: str,
        qr_data: str | None = None
    ) -> dict[str, Any]:
        """Extract and normalize structured fields from OCR text.
        
        Returns dict with normalized fields, confidence, and evidence.
        """
        self.evidence_tracker = EvidenceTracker()
        
        result: dict[str, Any] = {
            "ip_type": ip_type,
            "normalized_fields": {},
            "confidence": 0.0,
            "evidence": {},
            "status": "partial",
            "requires_review": False,
        }
        
        if ip_type == "PATENT":
            self._extract_patent_fields(text, qr_data)
        elif ip_type == "DESIGN_REGISTRATION":
            self._extract_design_fields(text, qr_data)
        else:
            self._extract_generic_fields(text)
        
        result["normalized_fields"] = self.evidence_tracker.to_dict()
        result["confidence"] = self._calculate_confidence()
        result["requires_review"] = self._check_review_required(ip_type, result["confidence"])
        result["status"] = "complete" if not result["requires_review"] else "awaiting_review"
        
        return result
    
    def _extract_patent_fields(self, text: str, qr_data: str | None):
        """Extract patent-specific fields from text."""
        
        # Patent Number - try QR first, then text
        if qr_data:
            pn = normalize_patent_number(qr_data)
            if pn:
                self.evidence_tracker.add("patent_number", pn, "qr_code", 0.9, qr_data)
        
        # If not from QR, try text extraction
        if "patent_number" not in self.evidence_tracker.to_dict():
            # Look for "Patent No." or "Patent Number" patterns
            patterns = [
                r'patent\s+no\.?[:\s]+(.+?)(?:\n|$)',
                r'patent\s+number[:\s]+(.+?)(?:\n|$)',
                r'no\.?\s*[Pp]atent[:\s]+(.+?)(?:\n|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    raw = match.group(1).strip()
                    pn = normalize_patent_number(raw)
                    if pn:
                        self.evidence_tracker.add("patent_number", pn, "ocr_text", 0.6, qr_data)
                    break
        
        # Title
        title_match = re.search(r'title[:\s]+(.+?)(?:\n{2,}|$)', text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()[:200]
            self.evidence_tracker.add("title", title, "ocr_text", 0.5)
        
        # Filing Date
        for pattern in [r'filing[:\s]+date[:\s]+(.+?)(?:\n|$)', r'application[:\s]+date[:\s]+(.+?)(?:\n|$)']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
                normalized = normalize_date(raw)
                if normalized:
                    self.evidence_tracker.add("filing_date", normalized, "ocr_text", 0.5, qr_data)
                else:
                    # Try just extracting the year
                    year = normalize_year(raw)
                    if year:
                        self.evidence_tracker.add("filing_date", year, "ocr_text", 0.3, qr_data)
        
        # Grant Date
        grant_match = re.search(r'grant[:\s]+date[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
        if grant_match:
            raw = grant_match.group(1).strip()
            normalized = normalize_date(raw)
            if normalized:
                self.evidence_tracker.add("grant_date", normalized, "ocr_text", 0.5, qr_data)
        
        # Inventors
        inventor_match = re.search(r'inventor[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
        if inventor_match:
            inventors = [inp.strip() for inp in inventor_match.group(1).split(",") if inp.strip()]
            if inventors:
                self.evidence_tracker.add("inventors", inventors, "ocr_text", 0.4, qr_data)
        
        # Applicant/Patentee
        applicant_match = re.search(r'(?:applicant|patentee)[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
        if applicant_match:
            applicant = applicant_match.group(1).strip()[:200]
            self.evidence_tracker.add("applicant", applicant, "ocr_text", 0.4, qr_data)
    
    def _extract_design_fields(self, text: str, qr_data: str | None):
        """Extract design registration-specific fields from text."""
        
        # Design Number
        if qr_data:
            dn = normalize_design_number(qr_data)
            if dn:
                self.evidence_tracker.add("design_number", dn, "qr_code", 0.9, qr_data)
        
        if "design_number" not in self.evidence_tracker.to_dict():
            # Support split OCR labels like "Design No." on one line and the value on the next.
            match = re.search(r'design\s*(?:number|no\.?)\s*[:\-\s]*([A-Z0-9][A-Z0-9\-/]*)', text, re.IGNORECASE | re.DOTALL)
            if match:
                raw = match.group(1).strip()
                dn = normalize_design_number(raw)
                if dn:
                    self.evidence_tracker.add("design_number", dn, "ocr_text", 0.6, qr_data)
        
        # Serial Number
        serial_match = re.search(r'serial[:\s]+no\.?[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
        if serial_match:
            raw = serial_match.group(1).strip()
            sn = normalize_design_number(raw) or raw.strip()
            self.evidence_tracker.add("serial_number", sn, "ocr_text", 0.5, qr_data)
        
        # Title
        title_match = re.search(r'title[:\s]+(.+?)(?:\n{2,}|$)', text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()[:200]
            self.evidence_tracker.add("title", title, "ocr_text", 0.5)
        
        # Design Date
        for pattern in [r'design[:\s]+date[:\s]+(.+?)(?:\n|$)', r'registration[:\s]+date[:\s]+(.+?)(?:\n|$)', r'\bdate\b\s*[:\-\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}|[0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
                normalized = normalize_date(raw)
                if normalized:
                    self.evidence_tracker.add("registration_date", normalized, "ocr_text", 0.5, qr_data)
                    break
    
    def _extract_generic_fields(self, text: str):
        """Extract generic fields for UNKNOWN_OTHER type."""
        # Just look for any prominent text that could be identifiers
        # Look for patterns that look like numbers/letters combinations
        identifiers = re.findall(r'[A-Z0-9]{4,}(?:[-][A-Z0-9]{2,})?', text)
        if identifiers:
            self.evidence_tracker.add("identifier_candidates", identifiers[:5], "ocr_text", 0.3)
    
    def _calculate_confidence(self) -> float:
        """Calculate overall confidence score based on evidence."""
        evidence = self.evidence_tracker.evidence
        
        if not evidence:
            return 0.1
        
        # Weight different evidence sources
        total_weight = 0
        weighted_sum = 0
        
        for field, entries in evidence.items():
            for entry in entries:
                conf = entry.get("confidence", 0)
                # QR evidence weighted higher
                source = entry.get("source", "")
                if "qr" in source.lower():
                    total_weight += 3
                elif "ocr" in source.lower():
                    total_weight += 2
                else:
                    total_weight += 1
                weighted_sum += conf * (3 if "qr" in source.lower() else 2 if "ocr" in source.lower() else 1)
        
        if total_weight == 0:
            return 0.1
        
        return round(min(weighted_sum / total_weight, 1.0), 2)
    
    def _check_review_required(self, ip_type: str, confidence: float) -> bool:
        """Determine if human review is required based on confidence and IP type."""
        # Low confidence always requires review
        if confidence < 0.5:
            return True
        
        # Certain IP types need higher confidence
        if ip_type == "PATENT" and confidence < 0.7:
            return True
        if ip_type == "DESIGN_REGISTRATION" and confidence < 0.6:
            return True
        
        # If we have core identifiers (patent number or design number), may not need review
        evidence = self.evidence_tracker.evidence
        has_core_id = any(
            "patent_number" in field or "design_number" in field
            for field in evidence.keys()
        )
        
        if has_core_id and confidence >= 0.5:
            return False
        
        return True


# Create default service instance
extraction_service = StructuredExtractionService()