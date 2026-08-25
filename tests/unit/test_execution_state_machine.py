"""Unit tests for Milestone 4 execution state machine transitions and invariants."""

from datetime import UTC, datetime

import pytest

from retrypay.domain.errors import StateTransitionError
from retrypay.domain.models import (
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.domain.state_machine import transition_case

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


def create_case(state: RecoveryCaseState = RecoveryCaseState.RECEIVED) -> RecoveryCase:
    """Helper to create a RecoveryCase in a specific state."""
    return RecoveryCase(
        case_id="rcv_test_sm_001",
        order_id="order_test_001",
        failed_attempt_id="pay_test_001",
        state=state,
        created_at=NOW,
        updated_at=NOW,
    )


def test_permitted_execution_state_transitions() -> None:
    """Ensure normal linear execution state transitions succeed."""
    case = create_case(RecoveryCaseState.RECEIVED)

    # RECEIVED -> ENRICHING
    case = transition_case(case, RecoveryCaseState.ENRICHING)
    assert case.state == RecoveryCaseState.ENRICHING

    # ENRICHING -> POLICY_EVALUATED
    case = transition_case(case, RecoveryCaseState.POLICY_EVALUATED)
    assert case.state == RecoveryCaseState.POLICY_EVALUATED

    # POLICY_EVALUATED -> DIAGNOSED
    case = transition_case(case, RecoveryCaseState.DIAGNOSED)
    assert case.state == RecoveryCaseState.DIAGNOSED

    # DIAGNOSED -> ACTION_APPROVED
    case = transition_case(case, RecoveryCaseState.ACTION_APPROVED)
    assert case.state == RecoveryCaseState.ACTION_APPROVED

    # ACTION_APPROVED -> LINK_CREATED
    case = transition_case(case, RecoveryCaseState.LINK_CREATED)
    assert case.state == RecoveryCaseState.LINK_CREATED

    # LINK_CREATED -> NOTIFIED
    case = transition_case(case, RecoveryCaseState.NOTIFIED)
    assert case.state == RecoveryCaseState.NOTIFIED

    # NOTIFIED -> RECOVERED (Terminal success)
    case_rec = transition_case(
        case,
        RecoveryCaseState.RECOVERED,
        closure_reason=RecoveryCaseClosureReason.RECOVERED_VIA_LINK,
    )
    assert case_rec.state == RecoveryCaseState.RECOVERED
    assert case_rec.closed_at is not None
    assert case_rec.closure_reason == RecoveryCaseClosureReason.RECOVERED_VIA_LINK


def test_invalid_arbitrary_state_jumps_rejected() -> None:
    """Ensure arbitrary jumps are strictly rejected."""
    case = create_case(RecoveryCaseState.RECEIVED)

    # Cannot jump directly from RECEIVED to NOTIFIED or LINK_CREATED
    with pytest.raises(StateTransitionError):
        transition_case(case, RecoveryCaseState.NOTIFIED)

    with pytest.raises(StateTransitionError):
        transition_case(case, RecoveryCaseState.LINK_CREATED)

    # Cannot jump from POLICY_EVALUATED to NOTIFIED
    case_pe = create_case(RecoveryCaseState.POLICY_EVALUATED)
    with pytest.raises(StateTransitionError):
        transition_case(case_pe, RecoveryCaseState.NOTIFIED)


def test_terminal_states_cannot_transition_further() -> None:
    """Ensure all terminal states cannot transition further."""
    terminal_states = [
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.RECOVERED,
        RecoveryCaseState.EXPIRED,
        RecoveryCaseState.OPTED_OUT,
        RecoveryCaseState.CLOSED_UNRECOVERED,
    ]

    for term_state in terminal_states:
        case = create_case(RecoveryCaseState.NOTIFIED)
        closed_case = transition_case(
            case,
            term_state,
            closure_reason=RecoveryCaseClosureReason.PAYMENT_CAPTURED,
        )
        assert closed_case.closed_at is not None

        # Attempting any transition from terminal state must raise StateTransitionError
        with pytest.raises(StateTransitionError):
            transition_case(closed_case, RecoveryCaseState.ENRICHING)

        with pytest.raises(StateTransitionError):
            transition_case(closed_case, RecoveryCaseState.NOTIFIED)


def test_opt_out_transition_from_active_states() -> None:
    """Ensure active execution states can transition to OPTED_OUT when customer revokes consent."""
    active_states = [
        RecoveryCaseState.ACTION_APPROVED,
        RecoveryCaseState.LINK_CREATED,
        RecoveryCaseState.NOTIFIED,
    ]
    for st in active_states:
        case = create_case(st)
        opted_out = transition_case(
            case,
            RecoveryCaseState.OPTED_OUT,
            closure_reason=RecoveryCaseClosureReason.CUSTOMER_OPTED_OUT,
        )
        assert opted_out.state == RecoveryCaseState.OPTED_OUT
        assert opted_out.closed_at is not None
        assert opted_out.closure_reason == RecoveryCaseClosureReason.CUSTOMER_OPTED_OUT


def test_payment_capture_preemption_from_all_active_states() -> None:
    """Ensure independent payment capture safely closes case from any active state."""
    active_states = [
        RecoveryCaseState.RECEIVED,
        RecoveryCaseState.ENRICHING,
        RecoveryCaseState.POLICY_EVALUATED,
        RecoveryCaseState.DIAGNOSED,
        RecoveryCaseState.ACTION_APPROVED,
        RecoveryCaseState.LINK_CREATED,
        RecoveryCaseState.NOTIFIED,
    ]
    for st in active_states:
        case = create_case(st)
        closed = transition_case(
            case,
            RecoveryCaseState.CLOSED_BLOCKED,
            closure_reason=RecoveryCaseClosureReason.PAYMENT_CAPTURED,
        )
        assert closed.state == RecoveryCaseState.CLOSED_BLOCKED
        assert closed.closed_at is not None
        assert closed.closure_reason == RecoveryCaseClosureReason.PAYMENT_CAPTURED
