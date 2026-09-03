"""Tests for the workflow state machine."""
from app.services.workflow import (
    WorkflowState,
    advance_state,
    can_transition,
    coerce_state,
    derive_state_from_verification,
)


def test_coerce_state_valid():
    assert coerce_state("VERIFIED") == WorkflowState.VERIFIED


def test_coerce_state_unknown_falls_back_to_needs_review():
    assert coerce_state("LEGACY_UNKNOWN") == WorkflowState.NEEDS_REVIEW


def test_coerce_state_none_defaults_to_uploaded():
    assert coerce_state(None) == WorkflowState.UPLOADED


def test_can_transition_uploaded_to_processing():
    assert can_transition("UPLOADED", "PROCESSING") is True


def test_cannot_transition_verified_backwards():
    assert can_transition("VERIFIED", "PROCESSING") is False


def test_advance_state_valid_transition():
    assert advance_state("UPLOADED", "PROCESSING") == "PROCESSING"


def test_advance_state_rejects_invalid_transition():
    assert advance_state("VERIFIED", "PROCESSING") == "VERIFIED"


def test_advance_state_allows_same_state():
    assert advance_state("VERIFIED", "VERIFIED") == "VERIFIED"


def test_derive_state_from_verification_verified():
    assert derive_state_from_verification("VERIFIED") == WorkflowState.VERIFIED


def test_derive_state_from_verification_mismatch():
    assert derive_state_from_verification("MISMATCH") == WorkflowState.DATA_CONFLICT


def test_derive_state_from_verification_unknown():
    assert derive_state_from_verification("UNKNOWN") == WorkflowState.VERIFICATION_PENDING
