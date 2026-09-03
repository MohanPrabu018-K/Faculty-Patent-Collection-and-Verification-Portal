from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from app.core.logging import log_audit

logger = structlog.get_logger()


# --- Data Classes ---

class ConflictType(Enum):
    """Types of conflicts per blueprint C1-C8."""
    C1_DUPLICATE_UPLOAD = "C1_DUPLICATE_UPLOAD"                    # Duplicate upload of same IP by another faculty
    C2_SAME_NAME_FACULTY = "C2_SAME_NAME_FACULTY"                  # Same-name faculty in multiple departments
    C3_INSTITUTION_MISMATCH = "C3_INSTITUTION_MISMATCH"            # Institution mismatch (internal vs external)
    C4_MISSING_FACULTY_NAME = "C4_MISSING_FACULTY_NAME"            # Missing faculty name on certificate
    C5_VERIFICATION_MISMATCH = "C5_VERIFICATION_MISMATCH"          # Verification mismatch (AI vs official source)
    C6_AI_UNCERTAINTY = "C6_AI_UNCERTAINTY"                        # AI uncertainty / low confidence
    C7_CONTRIBUTOR_ORDER_AMBIGUITY = "C7_CONTRIBUTOR_ORDER_AMBIGUITY"  # Contributor-order ambiguity
    C8_PATENT_DESIGN_MISCLASSIFICATION = "C8_PATENT_DESIGN_MISCLASSIFICATION"  # Patent vs Design misclassification


class ConflictStatus(Enum):
    """Status of a conflict case."""
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


class ConflictResolutionAction(Enum):
    """Actions for resolving conflicts."""
    ASSIGN_TO_FACULTY = "assign_to_faculty"              # Assign to specific faculty
    MARK_EXTERNAL = "mark_external"                      # Mark as external contributor
    REQUEST_CLARIFICATION = "request_clarification"      # Request human clarification
    USE_EXISTING_RECORD = "use_existing_record"          # Link to existing IP record
    MANUAL_ASSIGNMENT = "manual_assignment"              # Admin manually assigns
    OVERRIDE_CLASSIFICATION = "override_classification"  # Override AI classification
    ACCEPT_AI_RESULT = "accept_ai_result"                # Accept AI result with review
    MERGE_RECORDS = "merge_records"                      # Merge duplicate records
    DISMISS = "dismiss"                                  # Dismiss as false positive


class ConflictPriority(Enum):
    """Priority levels for conflicts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ConflictEvidence:
    """Evidence for a conflict."""
    source: str
    data: dict[str, Any]
    confidence: float
    description: str = ""


@dataclass
class ConflictCase:
    """A conflict case with resolution workflow."""
    id: str
    conflict_type: ConflictType
    priority: ConflictPriority
    
    # Related entities
    ip_record_id: str | None = None
    record_id_1: str | None = None  # For duplicate conflicts
    record_id_2: str | None = None
    faculty_id: str | None = None
    contributor_ids: list[str] = field(default_factory=list)
    
    # Conflict details
    description: str = ""
    evidence: list[ConflictEvidence] = field(default_factory=list)
    
    # Status
    status: ConflictStatus = ConflictStatus.OPEN
    priority: ConflictPriority = ConflictPriority.MEDIUM
    
    # Resolution
    resolution_action: ConflictResolutionAction | None = None
    resolution_notes: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    
    # Assignment
    assigned_to: str | None = None
    assigned_at: datetime | None = None
    
    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    # History
    history: list[dict[str, Any]] = field(default_factory=list)


# --- Conflict Detection Service ---

class ConflictDetectionService:
    """Service for detecting conflicts from various sources."""
    
    def __init__(self):
        self.logger = logger.bind(service="conflict_detection")
    
    async def detect_conflicts(
        self,
        ip_record: dict[str, Any],
        extracted_data: dict[str, Any],
        verification_result: dict[str, Any] | None = None,
        identity_matches: list[dict[str, Any]] | None = None,
        duplicate_candidates: list[dict[str, Any]] | None = None,
        classification_result: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect all conflicts for a new/updated IP record."""
        conflicts = []
        
        # C1: Duplicate upload
        if duplicate_candidates:
            for candidate in duplicate_candidates:
                if candidate.get("confidence", 0) > 0.7:
                    conflicts.append(await self._create_c1_conflict(
                        ip_record, candidate
                    ))
        
        # C2: Same-name faculty ambiguity
        if identity_matches:
            high_confidence = [m for m in identity_matches if m.get("confidence", 0) >= 0.5]
            if len(high_confidence) > 1:
                conflicts.append(await self._create_c2_conflict(
                    ip_record, high_confidence
                ))
            elif high_confidence and high_confidence[0].get("confidence", 0) < 0.7:
                conflicts.append(await self._create_c2_conflict(
                    ip_record, high_confidence
                ))
        
        # C3: Institution mismatch
        extracted_inst = extracted_data.get("institution")
        if extracted_inst and ip_record.get("institution"):
            if not self._institutions_match(extracted_inst, ip_record["institution"]):
                conflicts.append(await self._create_c3_conflict(
                    ip_record, extracted_inst, ip_record["institution"]
                ))
        
        # C4: Missing faculty name
        if not extracted_data.get("contributor_name") and not extracted_data.get("inventors"):
            conflicts.append(await self._create_c4_conflict(ip_record, extracted_data))
        
        # C5: Verification mismatch
        if verification_result and verification_result.get("status") == "MISMATCH":
            conflicts.append(await self._create_c5_conflict(ip_record, verification_result))
        
        # C6: AI uncertainty
        if classification_result and classification_result.get("confidence", 1.0) < 0.7:
            conflicts.append(await self._create_c6_conflict(ip_record, classification_result))
        
        # C7: Contributor order ambiguity
        inventors = extracted_data.get("inventors", [])
        if len(inventors) > 1 and not self._has_clear_order(inventors):
            conflicts.append(await self._create_c7_conflict(ip_record, inventors))
        
        # C8: Patent vs Design misclassification
        if classification_result and classification_result.get("ip_type") != ip_record.get("ip_type"):
            conflicts.append(await self._create_c8_conflict(ip_record, classification_result))
        
        return conflicts
    
    def _institutions_match(self, inst1: str, inst2: str) -> bool:
        """Check if two institution names match."""
        if not inst1 or not inst2:
            return True  # Can't determine, assume match
        inst1_norm = inst1.lower().strip()
        inst2_norm = inst2.lower().strip()
        return inst1_norm == inst2_norm or inst1_norm in inst2_norm or inst2_norm in inst1_norm
    
    def _has_clear_order(self, inventors: list[str]) -> bool:
        """Check if inventor list has clear order indicators."""
        # Check for numbered order, "first author", "corresponding author", etc.
        for i, inventor in enumerate(inventors):
            lower = inventor.lower()
            if any(keyword in lower for keyword in ["first", "corresponding", "lead", "primary", "senior"]):
                return True
            if lower.startswith(f"{i+1}.") or lower.startswith(f"{i+1})"):
                return True
        return False
    
    async def _create_c1_conflict(self, ip_record: dict, candidate: dict) -> dict:
        return {
            "conflict_type": ConflictType.C1_DUPLICATE_UPLOAD,
            "priority": ConflictPriority.HIGH,
            "description": f"Duplicate IP detected: {candidate.get('identifier')} already uploaded by another faculty",
            "evidence": [{"source": "duplicate_detection", "data": candidate, "confidence": candidate.get("confidence", 0)}],
            "ip_record_id": ip_record.get("id"),
            "record_id_1": ip_record.get("id"),
            "record_id_2": candidate.get("record_id"),
        }
    
    async def _create_c2_conflict(self, ip_record: dict, matches: list[dict]) -> dict:
        return {
            "conflict_type": ConflictType.C2_SAME_NAME_FACULTY,
            "priority": ConflictPriority.HIGH,
            "description": f"Multiple faculty members match extracted name: {', '.join([m.get('name', '') for m in matches[:3]])}",
            "evidence": [{"source": "identity_resolution", "data": matches, "confidence": max(m.get("confidence", 0) for m in matches)}],
            "ip_record_id": ip_record.get("id"),
            "faculty_id": matches[0].get("faculty_id") if matches else None,
        }
    
    async def _create_c3_conflict(self, ip_record: dict, extracted: str, recorded: str) -> dict:
        return {
            "conflict_type": ConflictType.C3_INSTITUTION_MISMATCH,
            "priority": ConflictPriority.MEDIUM,
            "description": f"Institution mismatch: certificate shows '{extracted}', database has '{recorded}'",
            "evidence": [{"source": "extraction", "data": {"extracted": extracted, "recorded": recorded}, "confidence": 0.8}],
            "ip_record_id": ip_record.get("id"),
        }
    
    async def _create_c4_conflict(self, ip_record: dict, extracted: dict) -> dict:
        return {
            "conflict_type": ConflictType.C4_MISSING_FACULTY_NAME,
            "priority": ConflictPriority.HIGH,
            "description": "No faculty name found on certificate - requires manual identification",
            "evidence": [{"source": "extraction", "data": extracted, "confidence": 0.9}],
            "ip_record_id": ip_record.get("id"),
        }
    
    async def _create_c5_conflict(self, ip_record: dict, verification: dict) -> dict:
        return {
            "conflict_type": ConflictType.C5_VERIFICATION_MISMATCH,
            "priority": ConflictPriority.HIGH,
            "description": f"Verification mismatch: {verification.get('details', 'AI extraction differs from official source')}",
            "evidence": [{"source": "verification", "data": verification, "confidence": 0.9}],
            "ip_record_id": ip_record.get("id"),
        }
    
    async def _create_c6_conflict(self, ip_record: dict, classification: dict) -> dict:
        return {
            "conflict_type": ConflictType.C6_AI_UNCERTAINTY,
            "priority": ConflictPriority.MEDIUM,
            "description": f"AI classification uncertainty: {classification.get('ip_type', 'unknown')} with confidence {classification.get('confidence', 0):.2f}",
            "evidence": [{"source": "classification", "data": classification, "confidence": classification.get("confidence", 0)}],
            "ip_record_id": ip_record.get("id"),
        }
    
    async def _create_c7_conflict(self, ip_record: dict, inventors: list) -> dict:
        return {
            "conflict_type": ConflictType.C7_CONTRIBUTOR_ORDER_AMBIGUITY,
            "priority": ConflictPriority.MEDIUM,
            "description": f"Contributor order ambiguous for {len(inventors)} inventors: {', '.join(inventors[:3])}",
            "evidence": [{"source": "extraction", "data": {"inventors": inventors}, "confidence": 0.7}],
            "ip_record_id": ip_record.get("id"),
            "contributor_ids": inventors,
        }
    
    async def _create_c8_conflict(self, ip_record: dict, classification: dict) -> dict:
        return {
            "conflict_type": ConflictType.C8_PATENT_DESIGN_MISCLASSIFICATION,
            "priority": ConflictPriority.HIGH,
            "description": f"Classification mismatch: AI says {classification.get('ip_type')}, record has {ip_record.get('ip_type')}",
            "evidence": [{"source": "classification", "data": {"ai_type": classification.get("ip_type"), "record_type": ip_record.get("ip_type"), "confidence": classification.get("confidence")}, "confidence": 0.9}],
            "ip_record_id": ip_record.get("id"),
        }


# --- Conflict Resolution Service ---

class ConflictResolutionService:
    """Service for managing and resolving conflict cases."""
    
    def __init__(self):
        self.logger = logger.bind(service="conflict_resolution")
        self._cases: dict[str, dict] = {}  # In-memory for testing
    
    async def create_conflict_case(self, conflict_data: dict) -> dict:
        """Create a new conflict case."""
        conflict_id = f"conflict-{conflict_data.get('conflict_type', 'unknown').value}-{int(time.time())}"
        
        case = {
            "id": conflict_id,
            "conflict_type": conflict_data["conflict_type"],
            "priority": conflict_data.get("priority", "medium"),
            "description": conflict_data.get("description", ""),
            "evidence": conflict_data.get("evidence", []),
            "ip_record_id": conflict_data.get("ip_record_id"),
            "record_id_1": conflict_data.get("record_id_1"),
            "record_id_2": conflict_data.get("record_id_2"),
            "faculty_id": conflict_data.get("faculty_id"),
            "contributor_ids": conflict_data.get("contributor_ids", []),
            "status": "open",
            "priority": conflict_data.get("priority", "medium"),
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "history": [{"action": "created", "timestamp": datetime.now(UTC).isoformat()}],
        }
        
        self._cases[conflict_id] = case
        
        # Log audit
        log_audit(
            actor="system",
            action="CONFLICT_CREATED",
            target_type="conflict_case",
            target_id=conflict_id,
            status="open",
            extra={
                "conflict_type": conflict_data.get("conflict_type"),
                "priority": conflict_data.get("priority"),
                "ip_record_id": conflict_data.get("ip_record_id"),
            },
        )
        
        return case
    
    async def resolve_conflict(
        self,
        conflict_id: str,
        action: str,
        resolved_by: str,
        notes: str | None = None,
    ) -> dict:
        """Resolve a conflict case."""
        case = self._get_case(conflict_id)
        if not case:
            raise ValueError(f"Conflict {conflict_id} not found")
        
        if case["status"] != "open":
            raise ValueError(f"Conflict already {case['status']}")
        
        case["status"] = "resolved"
        case["resolution_action"] = action
        case["resolution_notes"] = notes
        case["resolved_by"] = resolved_by
        case["resolved_at"] = datetime.now(UTC).isoformat()
        case["updated_at"] = datetime.now(UTC).isoformat()
        
        # Log audit
        log_audit(
            actor=resolved_by,
            action="CONFLICT_RESOLVED",
            target_type="conflict_case",
            target_id=conflict_id,
            status="resolved",
            before={"status": "open"},
            after={"status": "resolved", "action": action},
            extra={"notes": notes},
        )
        
        return case
    
    async def dismiss_conflict(
        self,
        conflict_id: str,
        dismissed_by: str,
        notes: str | None = None,
    ) -> dict:
        """Dismiss a conflict as false positive."""
        case = self._get_case(conflict_id)
        if not case:
            raise ValueError(f"Conflict {conflict_id} not found")
        
        case["status"] = "dismissed"
        case["resolved_by"] = dismissed_by
        case["resolved_at"] = datetime.now(UTC).isoformat()
        case["updated_at"] = datetime.now(UTC).isoformat()
        case["resolution_notes"] = notes
        
        log_audit(
            actor=dismissed_by,
            action="CONFLICT_DISMISSED",
            target_type="conflict_case",
            target_id=conflict_id,
            status="dismissed",
            extra={"notes": notes},
        )
        
        return case
    
    async def assign_conflict(
        self,
        conflict_id: str,
        assigned_to: str,
        assigned_by: str,
    ) -> dict:
        """Assign conflict to a resolver."""
        case = self._get_case(conflict_id)
        if not case:
            raise ValueError(f"Conflict {conflict_id} not found")
        
        case["assigned_to"] = assigned_to
        case["assigned_at"] = datetime.now(UTC).isoformat()
        case["updated_at"] = datetime.now(UTC).isoformat()
        
        log_audit(
            actor=assigned_by,
            action="CONFLICT_ASSIGNED",
            target_type="conflict_case",
            target_id=conflict_id,
            status="assigned",
            extra={"assigned_to": assigned_to},
        )
        
        return case
    
    def _get_case(self, conflict_id: str) -> dict:
        case = globals().get("_conflict_cases", {}).get(conflict_id)
        if not case:
            raise ValueError(f"Conflict {conflict_id} not found")
        return case
    
    def get_conflict(self, conflict_id: str) -> dict | None:
        """Get a conflict case by ID."""
        return globals().get("_conflict_cases", {}).get(conflict_id)
    
    def list_conflicts(
        self,
        status: str | None = None,
        conflict_type: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
    ) -> list[dict]:
        """List conflicts with filters."""
        cases = list(globals().get("_conflict_cases", {}).values())
        
        if status:
            cases = [c for c in cases if c["status"] == status]
        if conflict_type:
            cases = [c for c in cases if c["conflict_type"].value == conflict_type]
        if priority:
            cases = [c for c in cases if c["priority"] == priority]
        if assigned_to:
            cases = [c for c in cases if c.get("assigned_to") == assigned_to]
        
        return sorted(cases, key=lambda c: c["created_at"], reverse=True)


# --- Global Services ---

_conflict_detection_service: ConflictDetectionService | None = None
_conflict_resolution_service: ConflictResolutionService | None = None
_conflict_cases: dict[str, dict] = {}


def get_conflict_detection_service() -> ConflictDetectionService:
    global _conflict_detection_service
    if _conflict_detection_service is None:
        _conflict_detection_service = ConflictDetectionService()
    return _conflict_detection_service


def get_conflict_resolution_service() -> ConflictResolutionService:
    global _conflict_resolution_service
    if _conflict_resolution_service is None:
        _conflict_resolution_service = ConflictResolutionService()
    return _conflict_resolution_service


async def detect_conflicts(
    ip_record: dict[str, Any],
    extracted_data: dict[str, Any],
    verification_result: dict[str, Any] | None = None,
    identity_matches: list[dict[str, Any]] | None = None,
    duplicate_candidates: list[dict[str, Any]] | None = None,
    classification_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """High-level function to detect conflicts."""
    service = get_conflict_detection_service()
    conflicts = await service.detect_conflicts(
        ip_record, extracted_data, verification_result, identity_matches,
        duplicate_candidates, None
    )
    
    # Create conflict cases
    resolution_service = get_conflict_resolution_service()
    created = []
    for conflict in conflicts:
        case = await resolution_service.create_conflict_case(conflict)
        created.append(case)
    
    return created


async def get_conflict_resolution_service_instance() -> ConflictResolutionService:
    return get_conflict_resolution_service()