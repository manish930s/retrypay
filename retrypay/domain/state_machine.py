"""Finite state machine defining permitted recovery case lifecycle transitions."""

from datetime import UTC, datetime
from typing import Final

from retrypay.domain.errors import StateTransitionError
from retrypay.domain.models import (
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)

# Explicit valid state transition matrix
VALID_TRANSITIONS: Final[dict[RecoveryCaseState, set[RecoveryCaseState]]] = {
    RecoveryCaseState.RECEIVED: {
        RecoveryCaseState.ENRICHING,
        RecoveryCaseState.CLOSED_BLOCKED,
    },
    RecoveryCaseState.ENRICHING: {
        RecoveryCaseState.POLICY_EVALUATED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.DEFERRED,
    },
    RecoveryCaseState.DEFERRED: {
        RecoveryCaseState.ENRICHING,
        RecoveryCaseState.CLOSED_BLOCKED,
    },
    RecoveryCaseState.MANUAL_REVIEW: {
        RecoveryCaseState.CLOSED_BLOCKED,
    },
    RecoveryCaseState.POLICY_EVALUATED: {
        RecoveryCaseState.DIAGNOSED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.MANUAL_REVIEW,
    },
    RecoveryCaseState.DIAGNOSED: {
        RecoveryCaseState.ACTION_APPROVED,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.CLOSED_BLOCKED,
    },
    RecoveryCaseState.ACTION_APPROVED: {
        RecoveryCaseState.LINK_CREATED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.OPTED_OUT,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.DEFERRED,
    },
    RecoveryCaseState.LINK_CREATED: {
        RecoveryCaseState.NOTIFICATION_PENDING,
        RecoveryCaseState.NOTIFIED,
        RecoveryCaseState.NOTIFICATION_FAILED,
        RecoveryCaseState.RECOVERED,
        RecoveryCaseState.EXPIRED,
        RecoveryCaseState.CLOSED_UNRECOVERED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.OPTED_OUT,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION,
    },
    RecoveryCaseState.NOTIFICATION_PENDING: {
        RecoveryCaseState.NOTIFIED,
        RecoveryCaseState.NOTIFICATION_FAILED,
        RecoveryCaseState.RECOVERED,
        RecoveryCaseState.EXPIRED,
        RecoveryCaseState.CLOSED_UNRECOVERED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.OPTED_OUT,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION,
    },
    RecoveryCaseState.NOTIFICATION_FAILED: {
        RecoveryCaseState.NOTIFICATION_PENDING,
        RecoveryCaseState.NOTIFIED,
        RecoveryCaseState.RECOVERED,
        RecoveryCaseState.EXPIRED,
        RecoveryCaseState.CLOSED_UNRECOVERED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.OPTED_OUT,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION,
    },
    RecoveryCaseState.NOTIFIED: {
        RecoveryCaseState.RECOVERED,
        RecoveryCaseState.EXPIRED,
        RecoveryCaseState.CLOSED_UNRECOVERED,
        RecoveryCaseState.CLOSED_BLOCKED,
        RecoveryCaseState.OPTED_OUT,
        RecoveryCaseState.MANUAL_REVIEW,
        RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION,
    },
    RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION: {
        RecoveryCaseState.RECOVERED,
        RecoveryCaseState.CLOSED_BLOCKED,
    },
    # Terminal states have no valid outgoing transitions
    RecoveryCaseState.CLOSED_BLOCKED: set(),
    RecoveryCaseState.RECOVERED: set(),
    RecoveryCaseState.EXPIRED: set(),
    RecoveryCaseState.OPTED_OUT: set(),
    RecoveryCaseState.CLOSED_UNRECOVERED: set(),
}

TERMINAL_STATES: Final[set[RecoveryCaseState]] = {
    RecoveryCaseState.CLOSED_BLOCKED,
    RecoveryCaseState.RECOVERED,
    RecoveryCaseState.EXPIRED,
    RecoveryCaseState.OPTED_OUT,
    RecoveryCaseState.CLOSED_UNRECOVERED,
}


def transition_case(
    case: RecoveryCase,
    to_state: RecoveryCaseState,
    closure_reason: RecoveryCaseClosureReason | None = None,
    deferred_until: datetime | None = None,
    at_time: datetime | None = None,
) -> RecoveryCase:
    """Validate and execute a recovery case state transition.

    Enforces invariants:
    1. Rejects transitions from terminal states.
    2. Enforces explicit permitted transition matrix; rejects arbitrary state jumps.
    3. Terminal target states automatically populate `closed_at` and `closure_reason`.
    4. Transition to DEFERRED stores `quiet_hours_deferred_until`.
    """
    now = at_time or datetime.now(UTC)

    # Invariant 1: Terminal states cannot transition
    if case.state in TERMINAL_STATES or case.closed_at is not None:
        raise StateTransitionError(
            from_state=case.state.value,
            to_state=to_state.value,
            message=(
                f"Cannot transition recovery case '{case.case_id}' from terminal state "
                f"'{case.state.value}'."
            ),
        )

    # Invariant 2: Permitted transition lookup
    permitted = VALID_TRANSITIONS.get(case.state, set())
    if to_state not in permitted:
        raise StateTransitionError(
            from_state=case.state.value,
            to_state=to_state.value,
            message=(
                f"Invalid state transition for case '{case.case_id}': "
                f"cannot jump from '{case.state.value}' to '{to_state.value}'."
            ),
        )

    # Handle terminal target states
    closed_at = now if to_state in TERMINAL_STATES else None
    resolved_closure_reason = closure_reason if to_state in TERMINAL_STATES else None

    # Handle DEFERRED target state
    quiet_until = deferred_until if to_state == RecoveryCaseState.DEFERRED else None

    return case.model_copy(
        update={
            "state": to_state,
            "closed_at": closed_at,
            "closure_reason": resolved_closure_reason,
            "quiet_hours_deferred_until": quiet_until,
            "updated_at": now,
        }
    )
