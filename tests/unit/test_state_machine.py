"""Unit tests for the recovery case state machine transitions and invariants."""

import pytest

from retrypay.domain.errors import StateTransitionError
from retrypay.domain.models import (
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.domain.state_machine import transition_case


def test_valid_forward_transitions() -> None:
    """Ensure standard lifecycle transitions succeed."""
    case = RecoveryCase(
        case_id="rcv_001",
        order_id="order_001",
        failed_attempt_id="pay_fail_001",
        state=RecoveryCaseState.RECEIVED,
    )

    # RECEIVED -> ENRICHING
    case = transition_case(case, RecoveryCaseState.ENRICHING)
    assert case.state == RecoveryCaseState.ENRICHING
    assert case.closed_at is None

    # ENRICHING -> POLICY_EVALUATED
    case = transition_case(case, RecoveryCaseState.POLICY_EVALUATED)
    assert case.state == RecoveryCaseState.POLICY_EVALUATED
    assert case.closed_at is None

    # POLICY_EVALUATED -> CLOSED_BLOCKED
    case = transition_case(
        case,
        RecoveryCaseState.CLOSED_BLOCKED,
        closure_reason=RecoveryCaseClosureReason.PAYMENT_CAPTURED,
    )
    assert case.state == RecoveryCaseState.CLOSED_BLOCKED
    assert case.closed_at is not None
    assert case.closure_reason == RecoveryCaseClosureReason.PAYMENT_CAPTURED


def test_transition_to_deferred_and_re_enriching() -> None:
    """Ensure transitioning to DEFERRED and back to ENRICHING functions properly."""
    case = RecoveryCase(
        case_id="rcv_002",
        order_id="order_002",
        failed_attempt_id="pay_fail_002",
        state=RecoveryCaseState.ENRICHING,
    )

    case = transition_case(case, RecoveryCaseState.DEFERRED)
    assert case.state == RecoveryCaseState.DEFERRED

    case = transition_case(case, RecoveryCaseState.ENRICHING)
    assert case.state == RecoveryCaseState.ENRICHING


def test_transition_to_manual_review() -> None:
    """Ensure transitioning to MANUAL_REVIEW and closing functions properly."""
    case = RecoveryCase(
        case_id="rcv_003",
        order_id="order_003",
        failed_attempt_id="pay_fail_003",
        state=RecoveryCaseState.ENRICHING,
    )

    case = transition_case(case, RecoveryCaseState.MANUAL_REVIEW)
    assert case.state == RecoveryCaseState.MANUAL_REVIEW

    case = transition_case(
        case,
        RecoveryCaseState.CLOSED_BLOCKED,
        closure_reason=RecoveryCaseClosureReason.ORDER_PAID,
    )
    assert case.state == RecoveryCaseState.CLOSED_BLOCKED


def test_closed_case_cannot_reopen() -> None:
    """Invariant: A closed recovery case can never return to an active state."""
    case = RecoveryCase(
        case_id="rcv_004",
        order_id="order_004",
        failed_attempt_id="pay_fail_004",
        state=RecoveryCaseState.CLOSED_BLOCKED,
        closure_reason=RecoveryCaseClosureReason.POLICY_BLOCKED,
    )

    for target_state in (
        RecoveryCaseState.RECEIVED,
        RecoveryCaseState.ENRICHING,
        RecoveryCaseState.POLICY_EVALUATED,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.DEFERRED,
    ):
        with pytest.raises(StateTransitionError) as exc_info:
            transition_case(case, target_state)
        assert exc_info.value.from_state == RecoveryCaseState.CLOSED_BLOCKED.value


def test_invalid_arbitrary_transitions() -> None:
    """Ensure non-allowed state jumps raise StateTransitionError."""
    case = RecoveryCase(
        case_id="rcv_005",
        order_id="order_005",
        failed_attempt_id="pay_fail_005",
        state=RecoveryCaseState.RECEIVED,
    )

    # Cannot jump directly from RECEIVED to POLICY_EVALUATED
    with pytest.raises(StateTransitionError):
        transition_case(case, RecoveryCaseState.POLICY_EVALUATED)

    # Cannot jump directly from RECEIVED to MANUAL_REVIEW
    with pytest.raises(StateTransitionError):
        transition_case(case, RecoveryCaseState.MANUAL_REVIEW)
