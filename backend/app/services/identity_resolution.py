from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from enum import Enum
from typing import Any

import structlog
from app.core.logging import log_audit

logger = structlog.get_logger()


# --- Data Classes ---

class MatchConfidence(Enum):
    """Confidence levels for identity matches."""
    EXACT = "exact"           # 1.0 - exact match on all key fields
    HIGH = "high"             # 0.8-0.99 - strong match
    MEDIUM = "medium"         # 0.5-0.79 - moderate match
    LOW = "low"               # 0.3-0.49 - weak match
    AMBIGUOUS = "ambiguous"   # < 0.3 - multiple candidates


@dataclass
class IdentityCandidate:
    """A candidate faculty member for identity matching."""
    user_id: str
    faculty_id: str
    full_name: str
    email: str
    department: str | None = None
    designation: str | None = None
    institution: str = ""
    is_active: bool = True
    
    # Extracted data from certificate
    extracted_name: str = ""
    extracted_department: str = ""
    extracted_designation: str = ""
    extracted_institution: str = ""
    
    # Match scores
    name_similarity: float = 0.0
    institution_match: bool = False
    department_match: bool = False
    designation_match: bool = False
    public_data_match: bool = False
    prior_association_match: bool = False
    
    overall_confidence: float = 0.0
    confidence_level: MatchConfidence = MatchConfidence.AMBIGUOUS
    
    # Evidence
    match_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityMatchResult:
    """Result of identity resolution."""
    query_name: str
    query_department: str | None = None
    query_designation: str | None = None
    query_institution: str | None = None
    
    candidates: list[IdentityCandidate] = field(default_factory=list)
    best_match: IdentityCandidate | None = None
    requires_human_review: bool = False
    review_reason: str | None = None
    total_candidates: int = 0
    
    # Processing metadata
    processing_time_ms: float = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# --- Name Matching Utilities ---

def normalize_name(name: str) -> str:
    """Normalize name for comparison."""
    if not name:
        return ""
    # Remove extra whitespace, convert to lowercase
    normalized = re.sub(r'\s+', ' ', name.strip().lower())
    # Remove common titles
    normalized = re.sub(r'\b(dr|prof|professor|mr|ms|mrs|miss)\.?\b', '', normalized)
    # Remove punctuation except hyphens and apostrophes in names
    normalized = re.sub(r'[^\w\s\-\']', '', normalized)
    return normalized.strip()


def calculate_name_similarity(name1: str, name2: str) -> float:
    """Calculate similarity between two names using multiple algorithms."""
    if not name1 or not name2:
        return 0.0
    
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    
    if n1 == n2:
        return 1.0
    
    # SequenceMatcher ratio (similar to Levenshtein)
    seq_ratio = SequenceMatcher(None, n1, n2).ratio()
    
    # Token-based matching (for reordered names)
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if tokens1 and tokens2:
        token_overlap = len(tokens1 & tokens2) / len(tokens1 | tokens2)
    else:
        token_overlap = 0.0
    
    # Initials matching
    initials1 = ''.join(w[0] for w in n1.split() if w)
    initials2 = ''.join(w[0] for w in n2.split() if w)
    initials_match = 1.0 if initials1 == initials2 and initials1 else 0.0
    
    # Weighted combination
    return max(seq_ratio, token_overlap * 0.8, initials_match * 0.6)


def generate_name_variants(name: str) -> set[str]:
    """Generate common name variants for fuzzy matching."""
    normalized = normalize_name(name)
    variants = {normalized}
    
    if not normalized:
        return variants
    
    parts = normalized.split()
    if len(parts) >= 2:
        # First Last
        variants.add(' '.join(parts))
        # Last, First
        variants.add(f"{parts[-1]}, {' '.join(parts[:-1])}")
        # F. Last
        variants.add(f"{parts[0][0]}. {parts[-1]}")
        # First L.
        variants.add(f"{parts[0]} {parts[-1][0]}.")
        # Last F.
        variants.add(f"{parts[-1]} {parts[0][0]}.")
        
        # Handle hyphenated names
        for part in parts:
            if '-' in part:
                subparts = part.split('-')
                variants.update(subparts)
    
    return variants


# --- Institution Matching ---

INSTITUTION_ALIASES = {
    "iit": ["indian institute of technology", "iit"],
    "iisc": ["indian institute of science", "iisc"],
    "nit": ["national institute of technology", "nit"],
    "iiser": ["indian institute of science education and research", "iiser"],
    "iim": ["indian institute of management", "iim"],
    "aiims": ["all india institute of medical sciences", "aiims"],
    "university": ["univ", "university"],
    "college": ["coll", "college"],
    "institute": ["inst", "institute"],
}


def normalize_institution(name: str) -> str:
    """Normalize institution name for comparison."""
    if not name:
        return ""
    name = name.lower().strip()
    # Replace aliases
    for alias, expansions in INSTITUTION_ALIASES.items():
        for exp in expansions:
            name = name.replace(exp, alias)
    # Remove common words
    name = re.sub(r'\b(dept|department|school|faculty|center|centre)\b', '', name)
    name = re.sub(r'[^\w\s]', '', name)
    return ' '.join(name.split())


def match_institution(query: str, target: str) -> tuple[bool, float]:
    """Match institution names with confidence."""
    if not query or not target:
        return False, 0.0
    
    q_norm = normalize_institution(query)
    t_norm = normalize_institution(target)
    
    if q_norm == t_norm:
        return True, 1.0
    
    # Check if one contains the other
    if q_norm in t_norm or t_norm in q_norm:
        return True, 0.8
    
    # Token overlap
    q_tokens = set(q_norm.split())
    t_tokens = set(t_norm.split())
    if q_tokens and t_tokens:
        overlap = len(q_tokens & t_tokens) / len(q_tokens | t_tokens)
        return overlap > 0.5, overlap
    
    return False, 0.0


# --- Identity Resolution Service ---

class IdentityResolutionService:
    """Service for resolving faculty identities from certificate data."""
    
    def __init__(self):
        self.logger = logger.bind(service="identity_resolution")
    
    async def resolve_identity(
        self,
        extracted_name: str,
        extracted_department: str | None = None,
        extracted_designation: str | None = None,
        extracted_institution: str | None = None,
        identifier: str | None = None,  # patent/design number
        public_data: dict[str, Any] | None = None,
        existing_associations: list[dict[str, Any]] | None = None,
        faculty_db: list[dict[str, Any]] | None = None,
    ) -> IdentityMatchResult:
        """Resolve faculty identity from extracted certificate data."""
        start_time = time.time()
        
        result = IdentityMatchResult(
            query_name=extracted_name,
            query_department=extracted_department,
            query_designation=extracted_designation,
            query_institution=extracted_institution,
        )
        
        # Load the REAL faculty master database when the caller did not pass an
        # explicit candidate list. Mock data is never used in production.
        if faculty_db is None:
            faculty_db = self._load_faculty_from_db()
        
        # Find matching candidates
        candidates = self._find_candidates(
            faculty_db=faculty_db,
            extracted_name=extracted_name,
            extracted_department=extracted_department,
            extracted_designation=extracted_designation,
            extracted_institution=extracted_institution,
            identifier=identifier,
            public_data=public_data,
            existing_associations=existing_associations,
        )
        
        result.candidates = candidates
        result.total_candidates = len(candidates)
        
        # Determine best match and if review required
        if candidates:
            result.best_match = candidates[0]
            result.requires_human_review = self._should_require_review(candidates)
            if result.requires_human_review:
                result.review_reason = self._get_review_reason(candidates)
        else:
            result.requires_human_review = True
            result.review_reason = "No matching faculty found"
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        
        # Log audit
        log_audit(
            actor="system",
            action="IDENTITY_RESOLUTION",
            target_type="identity_conflict",
            target_id=extracted_name,
            status="completed" if not result.requires_human_review else "requires_review",
            extra={
                "query_name": extracted_name,
                "candidates_count": result.total_candidates,
                "best_match_id": result.best_match.user_id if result.best_match else None,
                "confidence": result.best_match.overall_confidence if result.best_match else 0,
                "requires_review": result.requires_human_review,
            },
        )
        
        return result
    
    def _find_candidates(
        self,
        faculty_db: list[dict[str, Any]],
        extracted_name: str,
        extracted_department: str | None,
        extracted_designation: str | None,
        extracted_institution: str | None,
        identifier: str | None,
        public_data: dict[str, Any] | None,
        existing_associations: list[dict[str, Any]] | None,
    ) -> list[IdentityCandidate]:
        """Find and score candidate faculty members."""
        candidates = []
        
        for faculty in faculty_db:
            if not faculty.get("is_active", True):
                continue
            
            candidate = self._score_candidate(
                faculty=faculty,
                extracted_name=extracted_name,
                extracted_department=extracted_department,
                extracted_designation=extracted_designation,
                extracted_institution=extracted_institution,
                identifier=identifier,
                public_data=public_data,
                existing_associations=existing_associations,
            )
            
            if candidate.overall_confidence > 0.1:  # Minimum threshold
                candidates.append(candidate)
        
        # Sort by confidence descending
        candidates.sort(key=lambda c: c.overall_confidence, reverse=True)
        return candidates
    
    def _score_candidate(
        self,
        faculty: dict[str, Any],
        extracted_name: str,
        extracted_department: str | None,
        extracted_designation: str | None,
        extracted_institution: str | None,
        identifier: str | None,
        public_data: dict[str, Any] | None,
        existing_associations: list[dict[str, Any]] | None,
    ) -> IdentityCandidate:
        """Score a single faculty candidate."""
        candidate = IdentityCandidate(
            user_id=faculty.get("id", ""),
            faculty_id=faculty.get("faculty_id", ""),
            full_name=faculty.get("full_name", ""),
            email=faculty.get("email", ""),
            department=faculty.get("department", ""),
            designation=faculty.get("designation", ""),
            institution=faculty.get("institution", ""),
            is_active=faculty.get("is_active", True),
            extracted_name=extracted_name,
            extracted_department=extracted_department or "",
            extracted_designation=extracted_designation or "",
            extracted_institution=extracted_institution or "",
        )
        
        # Name similarity (primary factor)
        name_sim = calculate_name_similarity(faculty.get("full_name", ""), extracted_name)
        candidate.name_similarity = name_sim
        
        # Institution match
        inst_match, inst_conf = match_institution(extracted_institution or "", faculty.get("institution", ""))
        candidate.institution_match = inst_match
        
        # Department match
        dept_match = False
        if extracted_department and faculty.get("department"):
            dept_match, _ = match_institution(extracted_department, faculty["department"])
        candidate.department_match = dept_match
        
        # Designation match
        desig_match = False
        if extracted_designation and faculty.get("designation"):
            desig_norm = normalize_name(extracted_designation)
            fac_desig_norm = normalize_name(faculty["designation"])
            desig_match = desig_norm == fac_desig_norm or desig_norm in fac_desig_norm or fac_desig_norm in desig_norm
        candidate.designation_match = desig_match
        
        # Public data match (from patent office verification)
        pub_match = False
        if public_data:
            # Check if public data matches faculty info
            if public_data.get("applicant") and faculty.get("full_name"):
                pub_match = calculate_name_similarity(public_data.get("applicant", ""), faculty["full_name"]) > 0.7
        candidate.public_data_match = pub_match
        
        # Prior association match
        prior_match = False
        if existing_associations:
            for assoc in existing_associations:
                if assoc.get("faculty_id") == faculty.get("faculty_id") or assoc.get("user_id") == faculty.get("id"):
                    prior_match = True
                    break
        candidate.prior_association_match = prior_match
        
        # Calculate overall confidence
        candidate.overall_confidence = self._calculate_overall_confidence(candidate)
        candidate.confidence_level = self._get_confidence_level(candidate.overall_confidence)
        
        # Build evidence
        candidate.match_evidence = {
            "name_similarity": candidate.name_similarity,
            "institution_match": candidate.institution_match,
            "department_match": candidate.department_match,
            "designation_match": candidate.designation_match,
            "public_data_match": candidate.public_data_match,
            "prior_association_match": candidate.prior_association_match,
        }
        
        return candidate
    
    def _calculate_overall_confidence(self, candidate: IdentityCandidate) -> float:
        """Calculate overall confidence score for a candidate."""
        # Weights for different factors
        weights = {
            "name": 0.40,           # Primary factor
            "institution": 0.20,    # Strong indicator
            "department": 0.15,     # Moderate indicator
            "designation": 0.10,    # Weak indicator (can change)
            "public_data": 0.10,    # External verification
            "prior_assoc": 0.05,    # Historical data
        }
        
        scores = {
            "name": candidate.name_similarity,
            "institution": 1.0 if candidate.institution_match else 0.0,
            "department": 1.0 if candidate.department_match else 0.0,
            "designation": 1.0 if candidate.designation_match else 0.0,
            "public_data": 1.0 if candidate.public_data_match else 0.0,
            "prior_assoc": 1.0 if candidate.prior_association_match else 0.0,
        }
        
        # Calculate weighted score
        total = sum(weights[k] * scores[k] for k in weights)
        
        # Boost if exact name match
        if candidate.name_similarity >= 0.95:
            total = min(total + 0.1, 1.0)
        
        # Penalty for very low name similarity
        if candidate.name_similarity < 0.3:
            total *= 0.5
        
        return min(max(total, 0.0), 1.0)
    
    def _get_confidence_level(self, confidence: float) -> MatchConfidence:
        """Convert confidence score to level."""
        if confidence >= 0.95:
            return MatchConfidence.EXACT
        elif confidence >= 0.8:
            return MatchConfidence.HIGH
        elif confidence >= 0.5:
            return MatchConfidence.MEDIUM
        elif confidence >= 0.3:
            return MatchConfidence.LOW
        else:
            return MatchConfidence.AMBIGUOUS
    
    def _should_require_review(self, candidates: list[IdentityCandidate]) -> bool:
        """Determine if human review is required."""
        if not candidates:
            return True
        
        best = candidates[0]
        
        # Low confidence always requires review
        if best.overall_confidence < 0.5:
            return True
        
        # Ambiguous confidence requires review
        if best.confidence_level == MatchConfidence.AMBIGUOUS:
            return True
        
        # Multiple high-confidence candidates = ambiguity
        high_conf = [c for c in candidates if c.overall_confidence >= 0.7]
        if len(high_conf) > 1:
            # Check if they're very close
            if high_conf[0].overall_confidence - high_conf[1].overall_confidence < 0.15:
                return True
        
        # Multiple medium-confidence candidates that are close
        med_conf = [c for c in candidates if 0.5 <= c.overall_confidence < 0.7]
        if len(med_conf) > 1:
            if med_conf[0].overall_confidence - med_conf[1].overall_confidence < 0.15:
                return True
        
        return False
    
    def _get_review_reason(self, candidates: list[IdentityCandidate]) -> str:
        """Get human-readable reason for review requirement."""
        if not candidates:
            return "No matching faculty found in database"
        
        best = candidates[0]
        
        if best.overall_confidence < 0.3:
            return "Very low confidence match - no strong candidate found"
        
        if best.confidence_level == MatchConfidence.AMBIGUOUS:
            return "Ambiguous match - confidence below threshold"
        
        high_conf = [c for c in candidates if c.overall_confidence >= 0.7]
        if len(high_conf) > 1:
            if high_conf[0].overall_confidence - high_conf[1].overall_confidence < 0.15:
                return f"Multiple candidates with similar confidence: {high_conf[0].full_name} ({high_conf[0].overall_confidence:.2f}) vs {high_conf[1].full_name} ({high_conf[1].overall_confidence:.2f})"
        
        # Check medium confidence
        med_conf = [c for c in candidates if 0.5 <= c.overall_confidence < 0.7]
        if len(med_conf) > 1:
            if med_conf[0].overall_confidence - med_conf[1].overall_confidence < 0.15:
                return f"Multiple candidates with similar confidence: {med_conf[0].full_name} ({med_conf[0].overall_confidence:.2f}) vs {med_conf[1].full_name} ({med_conf[1].overall_confidence:.2f})"
        
        if best.overall_confidence < 0.5:
            return f"Low confidence match: {best.full_name} ({best.overall_confidence:.2f})"
        
        return "Review required per policy"
    
    def _load_faculty_from_db(self) -> list[dict[str, Any]]:
        """Load the real faculty master database from PostgreSQL.

        Never falls back to mock data. If the DB is unavailable, returns an empty
        list so identity resolution correctly flags "No matching faculty found".
        """
        try:
            from sqlalchemy import select
            from app.core.database import get_session
            from app.models.base import Department, Designation, User

            session = get_session()
            try:
                rows = session.execute(
                    select(
                        User.id,
                        User.faculty_id,
                        User.full_name,
                        User.email,
                        User.is_active,
                        Department.name.label("department"),
                        Designation.name.label("designation"),
                    )
                    .outerjoin(Department, User.department_id == Department.id)
                    .outerjoin(Designation, User.designation_id == Designation.id)
                    .where(User.role == "faculty")
                ).all()
            finally:
                session.close()

            return [
                {
                    "id": r.id,
                    "faculty_id": r.faculty_id or "",
                    "full_name": r.full_name or "",
                    "email": r.email or "",
                    "department": r.department or "",
                    "designation": r.designation or "",
                    "institution": "",
                    "is_active": bool(r.is_active),
                }
                for r in rows
            ]
        except Exception:
            self.logger.warning("faculty_db_load_failed")
            return []

    def _get_mock_faculty_db(self) -> list[dict[str, Any]]:
        """Test-only fixture. Production code paths never call this."""
        return [
            {
                "id": "fac-001",
                "faculty_id": "FAC001",
                "full_name": "Dr. John Smith",
                "email": "john.smith@institute.edu",
                "department": "Computer Science",
                "designation": "Professor",
                "institution": "Indian Institute of Technology Delhi",
                "is_active": True,
            },
        ]


# --- Global Service ---

_identity_resolution_service: IdentityResolutionService | None = None


def get_identity_resolution_service() -> IdentityResolutionService:
    """Get or create the global identity resolution service."""
    global _identity_resolution_service
    if _identity_resolution_service is None:
        _identity_resolution_service = IdentityResolutionService()
    return _identity_resolution_service


async def resolve_faculty_identity(
    extracted_name: str,
    extracted_department: str | None = None,
    extracted_designation: str | None = None,
    extracted_institution: str | None = None,
    identifier: str | None = None,
    public_data: dict[str, Any] | None = None,
    existing_associations: list[dict[str, Any]] | None = None,
    faculty_db: list[dict[str, Any]] | None = None,
) -> IdentityMatchResult:
    """High-level function for identity resolution."""
    service = get_identity_resolution_service()
    return await service.resolve_identity(
        extracted_name=extracted_name,
        extracted_department=extracted_department,
        extracted_designation=extracted_designation,
        extracted_institution=extracted_institution,
        identifier=identifier,
        public_data=public_data,
        existing_associations=existing_associations,
        faculty_db=faculty_db,
    )