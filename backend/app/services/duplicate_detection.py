from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from app.core.logging import log_audit

logger = structlog.get_logger()


def normalize_identifier(identifier: str) -> str:
    """Normalize identifier for comparison."""
    if not identifier:
        return ""
    # Remove spaces, hyphens, convert to uppercase
    normalized = re.sub(r'[\s\-]', '', identifier.upper())
    return normalized


# --- Data Classes ---

class DuplicateDetectionMethod(Enum):
    """Methods for detecting duplicates."""
    EXACT_IDENTIFIER = "exact_identifier"      # Same patent/design number
    FINGERPRINT = "fingerprint"                # Same file content
    SIMILARITY = "similarity"                  # Similar content/metadata
    COMPOSITE = "composite"                    # Multiple methods combined


class DuplicateResolutionAction(Enum):
    """Actions for resolving duplicates."""
    KEEP_FIRST = "keep_first"                  # Keep the first record
    KEEP_SECOND = "keep_second"                # Keep the second record
    MERGE = "merge"                            # Merge both records
    DISMISS = "dismiss"                        # Not a duplicate


class DuplicateStatus(Enum):
    """Status of duplicate case."""
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass
class DuplicateCandidate:
    """A candidate duplicate record."""
    record_id: str
    ip_type: str
    patent_number: str | None = None
    application_number: str | None = None
    design_number: str | None = None
    serial_number: str | None = None
    title: str | None = None
    applicant: str | None = None
    inventors: list[str] = field(default_factory=list)
    filing_date: str | None = None
    fingerprint: str | None = None
    uploader_id: str | None = None
    uploader_name: str | None = None
    created_at: str | None = None
    
    # Match scores
    identifier_match: bool = False
    fingerprint_match: bool = False
    title_similarity: float = 0.0
    applicant_similarity: float = 0.0
    inventor_similarity: float = 0.0
    
    overall_confidence: float = 0.0
    detection_method: DuplicateDetectionMethod = DuplicateDetectionMethod.SIMILARITY
    
    # Evidence
    match_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DuplicateCase:
    """A duplicate detection case."""
    id: str
    record_id_1: str
    record_id_2: str
    
    # Detection details
    detection_method: DuplicateDetectionMethod
    confidence: float
    detected_by: str | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    # Match details
    match_details: dict[str, Any] = field(default_factory=dict)
    
    # Resolution
    status: DuplicateStatus = DuplicateStatus.OPEN
    resolution_action: DuplicateResolutionAction | None = None
    kept_record_id: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_notes: str | None = None
    
    # Processing metadata
    processing_time_ms: float = 0


# --- Fingerprinting ---

def calculate_file_fingerprint(file_data: bytes) -> str:
    """Calculate SHA-256 fingerprint of file content."""
    return hashlib.sha256(file_data).hexdigest()


def calculate_content_fingerprint(
    text: str,
    identifiers: dict[str, str]
) -> str:
    """Calculate fingerprint based on extracted content."""
    # Combine identifiers and normalized text
    content_parts = []
    for key in sorted(identifiers.keys()):
        if identifiers[key]:
            content_parts.append(f"{key}:{identifiers[key]}")
    
    if text:
        # Normalize text: lowercase, remove extra whitespace
        normalized = ' '.join(text.lower().split())
        content_parts.append(f"text:{normalized[:500]}")  # Limit text length
    
    content = '|'.join(content_parts)
    return hashlib.sha256(content.encode()).hexdigest()


# --- Similarity Functions ---

def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts."""
    if not text1 or not text2:
        return 0.0
    
    # Use difflib for sequence matching
    from difflib import SequenceMatcher
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def calculate_inventor_similarity(inventors1: list[str], inventors2: list[str]) -> float:
    """Calculate similarity between inventor lists."""
    if not inventors1 or not inventors2:
        return 0.0
    
    # Normalize inventor names
    norm1 = {normalize_inventor_name(name) for name in inventors1}
    norm2 = {normalize_inventor_name(name) for name in inventors2}
    
    if not norm1 or not norm2:
        return 0.0
    
    intersection = norm1 & norm2
    union = norm1 | norm2
    
    return len(intersection) / len(union) if union else 0.0


def normalize_inventor_name(name: str) -> str:
    """Normalize inventor name for comparison."""
    if not name:
        return ""
    # Remove titles, normalize whitespace
    normalized = name.lower().strip()
    normalized = re.sub(r'\b(dr|prof|professor|mr|ms|mrs|miss)\.?\b', '', normalized)
    normalized = re.sub(r'[^\w\s\-\']', '', normalized)
    # Split into parts and sort for comparison
    parts = sorted(normalized.split())
    return ' '.join(parts)


# --- Duplicate Detection Service ---

class DuplicateDetectionService:
    """Service for detecting duplicate IP records."""
    
    def __init__(self):
        self.logger = logger.bind(service="duplicate_detection")
    
    async def check_for_duplicates(
        self,
        new_record: dict[str, Any],
        existing_records: list[dict[str, Any]],
        file_data: bytes | None = None,
    ) -> list[DuplicateCandidate]:
        """Check new record against existing records for duplicates."""
        candidates = []
        
        for existing in existing_records:
            candidate = self._compare_records(new_record, existing, file_data)
            if candidate and candidate.overall_confidence > 0.3:
                candidates.append(candidate)
        
        # Sort by confidence
        candidates.sort(key=lambda c: c.overall_confidence, reverse=True)
        return candidates
    
    def _compare_records(
        self,
        new_record: dict[str, Any],
        existing: dict[str, Any],
        file_data: bytes | None = None,
    ) -> DuplicateCandidate | None:
        """Compare two records for duplication."""
        # Check exact identifier match first (strongest signal)
        identifier_match = self._check_identifier_match(new_record, existing)
        
        # Check fingerprint match if file data available
        fingerprint_match = False
        if file_data and existing.get("fingerprint"):
            new_fp = calculate_file_fingerprint(file_data)
            fingerprint_match = new_fp == existing["fingerprint"]
        
        # If exact identifier or fingerprint match, high confidence
        if identifier_match or fingerprint_match:
            method = DuplicateDetectionMethod.EXACT_IDENTIFIER if identifier_match else DuplicateDetectionMethod.FINGERPRINT
            confidence = 1.0 if identifier_match else 0.99
        else:
            # Calculate similarity-based match
            method = DuplicateDetectionMethod.SIMILARITY
            confidence = self._calculate_similarity_confidence(new_record, existing)
        
        if confidence < 0.3:
            return None
        
        # Build candidate
        candidate = DuplicateCandidate(
            record_id=existing.get("id", ""),
            ip_type=existing.get("ip_type", ""),
            patent_number=existing.get("patent_number"),
            application_number=existing.get("application_number"),
            design_number=existing.get("design_number"),
            serial_number=existing.get("serial_number"),
            title=existing.get("title"),
            applicant=existing.get("applicant"),
            inventors=existing.get("inventors", []),
            filing_date=existing.get("filing_date"),
            fingerprint=existing.get("fingerprint"),
            uploader_id=existing.get("uploader_id"),
            uploader_name=existing.get("uploader_name"),
            created_at=existing.get("created_at"),
            identifier_match=identifier_match,
            fingerprint_match=fingerprint_match,
            title_similarity=calculate_text_similarity(
                new_record.get("title", ""), existing.get("title", "")
            ),
            applicant_similarity=calculate_text_similarity(
                new_record.get("applicant", ""), existing.get("applicant", "")
            ),
            inventor_similarity=calculate_inventor_similarity(
                new_record.get("inventors", []), existing.get("inventors", [])
            ),
            overall_confidence=confidence,
            detection_method=method,
            match_evidence={
                "identifier_match": identifier_match,
                "fingerprint_match": fingerprint_match,
                "title_similarity": calculate_text_similarity(
                    new_record.get("title", ""), existing.get("title", "")
                ),
                "applicant_similarity": calculate_text_similarity(
                    new_record.get("applicant", ""), existing.get("applicant", "")
                ),
                "inventor_similarity": calculate_inventor_similarity(
                    new_record.get("inventors", []), existing.get("inventors", [])
                ),
            },
        )
        
        return candidate
    
    def _check_identifier_match(self, new: dict[str, Any], existing: dict[str, Any]) -> bool:
        """Check if any strong identifier matches."""
        # Patent number
        if new.get("patent_number") and existing.get("patent_number"):
            if normalize_identifier(new["patent_number"]) == normalize_identifier(existing["patent_number"]):
                return True
        
        # Application number
        if new.get("application_number") and existing.get("application_number"):
            if normalize_identifier(new["application_number"]) == normalize_identifier(existing["application_number"]):
                return True
        
        # Design number
        if new.get("design_number") and existing.get("design_number"):
            if normalize_identifier(new["design_number"]) == normalize_identifier(existing["design_number"]):
                return True
        
        # Serial number
        if new.get("serial_number") and existing.get("serial_number"):
            if normalize_identifier(new["serial_number"]) == normalize_identifier(existing["serial_number"]):
                return True
        
        return False
    
    def _calculate_similarity_confidence(self, new: dict[str, Any], existing: dict[str, Any]) -> float:
        """Calculate confidence based on metadata similarity."""
        scores = []
        weights = []
        
        # Title similarity (high weight)
        title_sim = calculate_text_similarity(new.get("title", ""), existing.get("title", ""))
        if title_sim > 0:
            scores.append(title_sim)
            weights.append(0.4)
        
        # Applicant similarity
        app_sim = calculate_text_similarity(new.get("applicant", ""), existing.get("applicant", ""))
        if app_sim > 0:
            scores.append(app_sim)
            weights.append(0.25)
        
        # Inventor similarity
        inv_sim = calculate_inventor_similarity(
            new.get("inventors", []), existing.get("inventors", [])
        )
        if inv_sim > 0:
            scores.append(inv_sim)
            weights.append(0.25)
        
        # Filing date proximity (if both have dates)
        if new.get("filing_date") and existing.get("filing_date"):
            try:
                from datetime import datetime
                d1 = datetime.fromisoformat(new["filing_date"].replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(existing["filing_date"].replace("Z", "+00:00"))
                days_diff = abs((d1 - d2).days)
                if days_diff <= 30:
                    scores.append(1.0 - (days_diff / 30.0) * 0.5)
                    weights.append(0.1)
            except:
                pass
        
        if not scores:
            return 0.0
        
        # Weighted average
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        
        return sum(s * w for s, w in zip(scores, weights)) / total_weight


# --- Duplicate Case Management ---

class DuplicateCaseManager:
    """Manages duplicate cases and resolution workflow."""
    
    def __init__(self):
        self.logger = logger.bind(service="duplicate_case_manager")
    
    async def create_duplicate_case(
        self,
        record_id_1: str,
        record_id_2: str,
        detection_method: DuplicateDetectionMethod,
        confidence: float,
        match_details: dict[str, Any],
        detected_by: str | None = None,
    ) -> DuplicateCase:
        """Create a new duplicate case."""
        case = DuplicateCase(
            id=f"dup-{record_id_1}-{record_id_2}-{int(time.time())}",
            record_id_1=record_id_1,
            record_id_2=record_id_2,
            detection_method=detection_method,
            confidence=confidence,
            detected_by=detected_by,
            match_details=match_details,
        )
        
        # Log audit
        log_audit(
            actor=detected_by or "system",
            action="DUPLICATE_DETECTED",
            target_type="duplicate_case",
            target_id=case.id,
            status="open",
            extra={
                "record_id_1": record_id_1,
                "record_id_2": record_id_2,
                "method": detection_method.value,
                "confidence": confidence,
            },
        )
        
        return case
    
    async def resolve_duplicate_case(
        self,
        case: DuplicateCase,
        action: DuplicateResolutionAction,
        kept_record_id: str,
        resolved_by: str,
        notes: str | None = None,
    ) -> DuplicateCase:
        """Resolve a duplicate case."""
        case.status = DuplicateStatus.RESOLVED
        case.resolution_action = action
        case.kept_record_id = kept_record_id
        case.resolved_by = resolved_by
        case.resolved_at = datetime.now(UTC)
        case.resolution_notes = notes
        
        # Log audit
        log_audit(
            actor=resolved_by,
            action="DUPLICATE_RESOLVED",
            target_type="duplicate_case",
            target_id=case.id,
            status="resolved",
            before={"status": "open"},
            after={"status": "resolved", "action": action.value, "kept_record": kept_record_id},
            extra={"notes": notes},
        )
        
        return case
    
    async def dismiss_duplicate_case(
        self,
        case: DuplicateCase,
        dismissed_by: str,
        notes: str | None = None,
    ) -> DuplicateCase:
        """Dismiss a duplicate case (not a duplicate)."""
        case.status = DuplicateStatus.DISMISSED
        case.resolved_by = dismissed_by
        case.resolved_at = datetime.now(UTC)
        case.resolution_notes = notes
        
        # Log audit
        log_audit(
            actor=dismissed_by,
            action="DUPLICATE_DISMISSED",
            target_type="duplicate_case",
            target_id=case.id,
            status="dismissed",
            before={"status": "open"},
            after={"status": "dismissed"},
            extra={"notes": notes},
        )
        
        return case


# --- Global Services ---

_duplicate_detection_service: DuplicateDetectionService | None = None
_duplicate_case_manager: DuplicateCaseManager | None = None


def get_duplicate_detection_service() -> DuplicateDetectionService:
    """Get or create the global duplicate detection service."""
    global _duplicate_detection_service
    if _duplicate_detection_service is None:
        _duplicate_detection_service = DuplicateDetectionService()
    return _duplicate_detection_service


def get_duplicate_case_manager() -> DuplicateCaseManager:
    """Get or create the global duplicate case manager."""
    global _duplicate_case_manager
    if _duplicate_case_manager is None:
        _duplicate_case_manager = DuplicateCaseManager()
    return _duplicate_case_manager


async def check_duplicates(
    new_record: dict[str, Any],
    existing_records: list[dict[str, Any]],
    file_data: bytes | None = None,
) -> list[DuplicateCandidate]:
    """High-level function to check for duplicates."""
    service = get_duplicate_detection_service()
    return await service.check_for_duplicates(new_record, existing_records, file_data)


async def create_duplicate_case(
    record_id_1: str,
    record_id_2: str,
    detection_method: DuplicateDetectionMethod,
    confidence: float,
    match_details: dict[str, Any],
    detected_by: str | None = None,
) -> DuplicateCase:
    """Create a duplicate case."""
    manager = get_duplicate_case_manager()
    return await manager.create_duplicate_case(
        record_id_1, record_id_2, detection_method, confidence, match_details, detected_by
    )