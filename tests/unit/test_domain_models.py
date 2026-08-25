"""Unit tests for domain models, validation constraints, and reconciliation state logic."""

import pytest
from pydantic import ValidationError

from retrypay.domain.models import (
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentFailureContext,
    PaymentStatus,
)


def test_order_creation_and_paise_validation() -> None:
    """Ensure Order requires positive integer paise amounts."""
    order = Order(
        order_id="order_valid_001",
        amount_paise=50000,
        currency="INR",
        status=OrderStatus.CREATED,
    )
    assert order.order_id == "order_valid_001"
    assert order.amount_paise == 50000
    assert order.status == OrderStatus.CREATED

    # Reject non-positive paise
    with pytest.raises(ValidationError):
        Order(order_id="order_inv_001", amount_paise=0)

    with pytest.raises(ValidationError):
        Order(order_id="order_inv_002", amount_paise=-100)


def test_order_reconciliation_captured_payment() -> None:
    """Ensure captured payment transitions order to PAID."""
    order = Order(
        order_id="order_rec_001",
        amount_paise=25000,
        status=OrderStatus.CREATED,
    )
    reconciled = order.reconcile_with_payment(PaymentStatus.CAPTURED)
    assert reconciled.status == OrderStatus.PAID
    assert reconciled.updated_at >= order.created_at


def test_order_reconciliation_failed_payment() -> None:
    """Ensure failed payment transitions CREATED order to ATTEMPTED."""
    order = Order(
        order_id="order_rec_002",
        amount_paise=25000,
        status=OrderStatus.CREATED,
    )
    reconciled = order.reconcile_with_payment(PaymentStatus.FAILED)
    assert reconciled.status == OrderStatus.ATTEMPTED


def test_order_reconciliation_paid_order_never_downgraded_by_failure() -> None:
    """Ensure an order already in PAID status is NEVER downgraded by subsequent failed payment."""
    order = Order(
        order_id="order_rec_003",
        amount_paise=25000,
        status=OrderStatus.PAID,
    )
    reconciled = order.reconcile_with_payment(PaymentStatus.FAILED)
    assert reconciled.status == OrderStatus.PAID


def test_order_reconciliation_order_paid_event() -> None:
    """Ensure order.paid transitions order to PAID idempotently."""
    order = Order(
        order_id="order_rec_004",
        amount_paise=25000,
        status=OrderStatus.ATTEMPTED,
    )
    reconciled = order.reconcile_with_order_paid()
    assert reconciled.status == OrderStatus.PAID

    # Idempotent re-application
    re_applied = reconciled.reconcile_with_order_paid()
    assert re_applied.status == OrderStatus.PAID


def test_payment_attempt_creation_with_failure_context() -> None:
    """Ensure payment attempts store normalized failure contexts without sensitive data."""
    ctx = PaymentFailureContext(
        error_code="BAD_REQUEST_PAYMENT_TIMED_OUT",
        error_description="Customer bank timed out",
        error_source="customer",
        error_step="payment_authorization",
        error_reason="payment_failed",
    )
    attempt = PaymentAttempt(
        payment_id="pay_fail_001",
        order_id="order_001",
        amount_paise=50000,
        currency="INR",
        status=PaymentStatus.FAILED,
        method="upi",
        failure_context=ctx,
    )
    assert attempt.payment_id == "pay_fail_001"
    assert attempt.status == PaymentStatus.FAILED
    assert attempt.failure_context is not None
    assert attempt.failure_context.error_code == "BAD_REQUEST_PAYMENT_TIMED_OUT"
