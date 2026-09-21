from __future__ import annotations

from enum import Enum
from typing import Any


class WorkflowState(str, Enum):
    """Canonical lifecycle states for an IP record / master record."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    OCR_COMPLETED = "OCR_COMPLETED"
    QR_DETECTED = "QR_DETECTED"
    IDENTIFIER_FOUND = "IDENTIFIER_FOUND"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    EXTERNAL_VERIFICATION_FAILURE = "EXTERNAL_VERIFICATION_FAILURE"
    DATA_CONFLICT = "DATA_CONFLICT"
    IDENTITY_REVIEW = "IDENTITY_REVIEW"
    CONTRIBUTOR_REVIEW = "CONTRIBUTOR_REVIEW"
    FACULTY_APPROVAL_PENDING = "FACULTY_APPROVAL_PENDING"
    DUPLICATE_REVIEW = "DUPLICATE_REVIEW"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    VERIFIED = "VERIFIED"
    GRANTED = "GRANTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


# Allowed transitions. A key maps to the set of states it may transition into.
_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.UPLOADED: {WorkflowState.PROCESSING, WorkflowState.FAILED, WorkflowState.REJECTED},
    WorkflowState.PROCESSING: {
        WorkflowState.OCR_COMPLETED,
        WorkflowState.QR_DETECTED,
        WorkflowState.IDENTIFIER_FOUND,
        WorkflowState.FAILED,
    },
    WorkflowState.OCR_COMPLETED: {WorkflowState.IDENTIFIER_FOUND, WorkflowState.NEEDS_REVIEW, WorkflowState.FAILED},
    WorkflowState.QR_DETECTED: {WorkflowState.IDENTIFIER_FOUND, WorkflowState.NEEDS_REVIEW},
    WorkflowState.IDENTIFIER_FOUND: {
        WorkflowState.VERIFICATION_PENDING,
        WorkflowState.DUPLICATE_REVIEW,
        WorkflowState.IDENTITY_REVIEW,
        WorkflowState.CONTRIBUTOR_REVIEW,
        WorkflowState.FACULTY_APPROVAL_PENDING,
        WorkflowState.DATA_CONFLICT,
    },
    WorkflowState.VERIFICATION_PENDING: {
        WorkflowState.VERIFIED,
        WorkflowState.VERIFICATION_REQUIRED,
        WorkflowState.EXTERNAL_VERIFICATION_FAILURE,
        WorkflowState.NEEDS_REVIEW,
        WorkflowState.DATA_CONFLICT,
        WorkflowState.FAILED,
    },
    WorkflowState.VERIFICATION_REQUIRED: {
        WorkflowState.VERIFIED,
        WorkflowState.NEEDS_REVIEW,
        WorkflowState.FACULTY_APPROVAL_PENDING,
        WorkflowState.REJECTED,
    },
    WorkflowState.EXTERNAL_VERIFICATION_FAILURE: {
        WorkflowState.VERIFICATION_PENDING,
        WorkflowState.NEEDS_REVIEW,
        WorkflowState.FAILED,
    },
    WorkflowState.DATA_CONFLICT: {WorkflowState.NEEDS_REVIEW, WorkflowState.VERIFICATION_PENDING},
    WorkflowState.IDENTITY_REVIEW: {WorkflowState.NEEDS_REVIEW, WorkflowState.IDENTIFIER_FOUND, WorkflowState.REJECTED},
    WorkflowState.CONTRIBUTOR_REVIEW: {WorkflowState.NEEDS_REVIEW, WorkflowState.IDENTIFIER_FOUND, WorkflowState.REJECTED},
    WorkflowState.FACULTY_APPROVAL_PENDING: {WorkflowState.VERIFIED, WorkflowState.NEEDS_REVIEW, WorkflowState.REJECTED},
    WorkflowState.DUPLICATE_REVIEW: {WorkflowState.IDENTIFIER_FOUND, WorkflowState.NEEDS_REVIEW, WorkflowState.REJECTED},
    WorkflowState.NEEDS_REVIEW: {
        WorkflowState.VERIFIED,
        WorkflowState.VERIFICATION_PENDING,
        WorkflowState.REJECTED,
        WorkflowState.IDENTIFIER_FOUND,
    },
    WorkflowState.VERIFIED: {WorkflowState.GRANTED},  # VERIFIED -> GRANTED is the grant action
    WorkflowState.GRANTED: set(),  # Terminal
    WorkflowState.REJECTED: set(),  # Terminal
    WorkflowState.FAILED: {WorkflowState.PROCESSING, WorkflowState.REJECTED},  # Retry allowed
}


def coerce_state(value: str | None) -> WorkflowState:
    """Coerce an arbitrary stored string into a valid WorkflowState."""
    if not value:
        return WorkflowState.UPLOADED
    try:
        return WorkflowState(value)
    except ValueError:
        # Fall back to a safe parenthetical review state for unknown legacy values.
        return WorkflowState.NEEDS_REVIEW


def can_transition(current: str | None, target: str | WorkflowState) -> bool:
    """Return True if moving from ``current`` to ``target`` is permitted."""
    current_state = coerce_state(current)
    target_state = target if isinstance(target, WorkflowState) else coerce_state(target)
    if current_state == target_state:
        return True
    return target_state in _TRANSITIONS.get(current_state, set())


def advance_state(current: str | None, target: str | WorkflowState) -> str:
    """Advance to ``target`` if permitted, otherwise return the current state.

    This is the single choke-point for all workflow-state mutation, so the state
    machine cannot be bypassed by arbitrary writes.
    """
    if can_transition(current, target):
        return target.value if isinstance(target, WorkflowState) else str(target)
    return coerce_state(current).value


def advance_through(current: str | None, target: str | WorkflowState) -> str:
    """Advance from ``current`` toward ``target`` following the shortest chain of
    permitted transitions.

    The document pipeline computes a single final ``target`` but never walks the
    record through the intermediate states, so a one-hop guarded transition such
    as ``UPLOADED -> DUPLICATE_REVIEW`` is rejected and the record stays put.
    This resolves a valid multi-step path and applies each hop in turn. If no
    path exists the record keeps its current state.
    """
    from collections import deque

    start = coerce_state(current)
    goal = target if isinstance(target, WorkflowState) else coerce_state(target)
    if start == goal:
        return goal.value

    prev: dict[WorkflowState, WorkflowState | None] = {start: None}
    queue: deque[WorkflowState] = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            break
        for nxt in _TRANSITIONS.get(node, set()):
            if nxt not in prev:
                prev[nxt] = node
                queue.append(nxt)

    if goal not in prev:
        return start.value

    chain: list[WorkflowState] = []
    node: WorkflowState | None = goal
    while node is not None:
        chain.append(node)
        node = prev[node]
    chain.reverse()

    state: str = start.value
    for step in chain[1:]:
        state = advance_state(state, step)
    return state


def derive_state_from_verification(verification_status: str | None) -> WorkflowState:
    """Map a verification status to the corresponding workflow state."""
    mapping = {
        "VERIFIED": WorkflowState.VERIFIED,
        "MISMATCH": WorkflowState.DATA_CONFLICT,
        "NOT_FOUND": WorkflowState.VERIFICATION_REQUIRED,
        "VERIFICATION_REQUIRED": WorkflowState.VERIFICATION_REQUIRED,
        "ERROR": WorkflowState.EXTERNAL_VERIFICATION_FAILURE,
    }
    return mapping.get(verification_status or "", WorkflowState.VERIFICATION_PENDING)


def describe_state(state: str | None) -> dict[str, Any]:
    """Human-readable summary of a workflow state."""
    s = coerce_state(state)
    return {
        "state": s.value,
        "terminal": s in (WorkflowState.VERIFIED, WorkflowState.GRANTED, WorkflowState.REJECTED),
        "requires_human_review": s in {
            WorkflowState.NEEDS_REVIEW,
            WorkflowState.IDENTITY_REVIEW,
            WorkflowState.CONTRIBUTOR_REVIEW,
            WorkflowState.DUPLICATE_REVIEW,
            WorkflowState.DATA_CONFLICT,
            WorkflowState.VERIFICATION_REQUIRED,
            WorkflowState.FACULTY_APPROVAL_PENDING,
        },
    }
