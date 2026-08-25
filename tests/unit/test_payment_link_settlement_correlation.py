"""Unit tests for Payment Link settlement correlation and edge-case handling.

Tests:
- payment_link.paid success
- unknown payment link ID
- mismatched reference ID
- mismatched amount
- duplicate payment_link.paid
- payment.captured without safe case correlation
- late payment.failed after payment_link.paid
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import (
    EventSource,
    Order,
    OrderStatus,
    PaymentLink,
    PaymentLinkStatus,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature


@pytest.mark.asyncio
async def test_payment_link_paid_success(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """payment_link.paid webhook settles link to PAID, order to PAID, and case to RECOVERED."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value
    order_id = "order_plink_succ_101"
    case_id = "rcv_plink_succ_101"
    link_id = "plink_test_succ_101"
    ref_id = "rpt_succ_ref_101"

    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        case_repo = RecoveryCaseRepository(session)

        await order_repo.save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=250000,
                currency="INR",
                status=OrderStatus.ATTEMPTED,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await case_repo.save_case(
            RecoveryCase(
                case_id=case_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                order_id=order_id,
                failed_attempt_id="pay_fail_succ_1",
                state=RecoveryCaseState.LINK_CREATED,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await PaymentLinkRepository(session).save_link(
            PaymentLink(
                link_id="link_db_101",
                source=EventSource.RAZORPAY_TEST_MODE,
                case_id=case_id,
                action_id="act_succ_101",
                provider_link_id=link_id,
                reference_id=ref_id,
                short_url=f"https://rzp.io/i/{link_id}",
                status=PaymentLinkStatus.CREATED,
                amount_paise=250000,
                currency="INR",
                expire_by=now + timedelta(days=1),
                provider_created_at=now,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await session.commit()

    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "event_id": "evt_plink_paid_101",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "reference_id": ref_id,
                    "amount": 250000,
                    "status": "paid",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_plink_paid_101"},
    )
    assert resp.status_code == 200

    async with test_session_factory() as session:
        order = await OrderRepository(session).get_order(order_id, source=source)
        case = await RecoveryCaseRepository(session).get_case(case_id, source=source)
        link = await PaymentLinkRepository(session).get_by_provider_link_id(link_id, source=source)

        assert order is not None and order.status == OrderStatus.PAID
        assert case is not None and case.state == RecoveryCaseState.RECOVERED
        assert case.closure_reason == RecoveryCaseClosureReason.RECOVERED_VIA_LINK
        assert link is not None and link.status == PaymentLinkStatus.PAID


@pytest.mark.asyncio
async def test_payment_link_paid_unknown_link_id(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """payment_link.paid with non-existent provider link ID returns unknown_payment_link."""
    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "event_id": "evt_plink_unknown_101",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_unknown_999999",
                    "reference_id": "rpt_unknown_999",
                    "amount": 250000,
                    "status": "paid",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_plink_unknown_101"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_payment_link_paid_mismatched_reference_id(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """payment_link.paid with mismatched reference_id does not settle case to RECOVERED."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value
    order_id = "order_mismatch_ref_101"
    case_id = "rcv_mismatch_ref_101"
    link_id = "plink_mismatch_ref_101"

    async with test_session_factory() as session:
        await OrderRepository(session).save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=250000,
                currency="INR",
                status=OrderStatus.ATTEMPTED,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await RecoveryCaseRepository(session).save_case(
            RecoveryCase(
                case_id=case_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                order_id=order_id,
                failed_attempt_id="pay_fail_mismatch_1",
                state=RecoveryCaseState.LINK_CREATED,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await PaymentLinkRepository(session).save_link(
            PaymentLink(
                link_id="link_db_mismatch_101",
                source=EventSource.RAZORPAY_TEST_MODE,
                case_id=case_id,
                action_id="act_mismatch_101",
                provider_link_id=link_id,
                reference_id="rpt_correct_reference_id",
                short_url=f"https://rzp.io/i/{link_id}",
                status=PaymentLinkStatus.CREATED,
                amount_paise=250000,
                currency="INR",
                expire_by=now + timedelta(days=1),
                provider_created_at=now,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await session.commit()

    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "event_id": "evt_plink_mismatch_ref_101",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "reference_id": "rpt_WRONG_reference_id",
                    "amount": 250000,
                    "status": "paid",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig},
    )
    assert resp.status_code == 200

    async with test_session_factory() as session:
        case = await RecoveryCaseRepository(session).get_case(case_id, source=source)
        assert case is not None and case.state == RecoveryCaseState.LINK_CREATED


@pytest.mark.asyncio
async def test_payment_link_paid_mismatched_amount(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """payment_link.paid with mismatched amount does not settle case to RECOVERED."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value
    order_id = "order_mismatch_amt_101"
    case_id = "rcv_mismatch_amt_101"
    link_id = "plink_mismatch_amt_101"
    ref_id = "rpt_mismatch_amt_ref"

    async with test_session_factory() as session:
        await OrderRepository(session).save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=250000,
                currency="INR",
                status=OrderStatus.ATTEMPTED,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await RecoveryCaseRepository(session).save_case(
            RecoveryCase(
                case_id=case_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                order_id=order_id,
                failed_attempt_id="pay_fail_amt_1",
                state=RecoveryCaseState.LINK_CREATED,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await PaymentLinkRepository(session).save_link(
            PaymentLink(
                link_id="link_db_amt_101",
                source=EventSource.RAZORPAY_TEST_MODE,
                case_id=case_id,
                action_id="act_amt_101",
                provider_link_id=link_id,
                reference_id=ref_id,
                short_url=f"https://rzp.io/i/{link_id}",
                status=PaymentLinkStatus.CREATED,
                amount_paise=250000,
                currency="INR",
                expire_by=now + timedelta(days=1),
                provider_created_at=now,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await session.commit()

    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "event_id": "evt_plink_mismatch_amt_101",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "reference_id": ref_id,
                    "amount": 99900,  # Mismatched amount
                    "status": "paid",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig},
    )
    assert resp.status_code == 200

    async with test_session_factory() as session:
        case = await RecoveryCaseRepository(session).get_case(case_id, source=source)
        assert case is not None and case.state == RecoveryCaseState.LINK_CREATED


@pytest.mark.asyncio
async def test_payment_link_paid_duplicate(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Duplicate payment_link.paid event is ignored gracefully."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value
    order_id = "order_dup_link_101"
    case_id = "rcv_dup_link_101"
    link_id = "plink_dup_link_101"
    ref_id = "rpt_dup_link_ref"

    async with test_session_factory() as session:
        await OrderRepository(session).save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=250000,
                currency="INR",
                status=OrderStatus.PAID,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await RecoveryCaseRepository(session).save_case(
            RecoveryCase(
                case_id=case_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                order_id=order_id,
                failed_attempt_id="pay_fail_dup_1",
                state=RecoveryCaseState.RECOVERED,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await PaymentLinkRepository(session).save_link(
            PaymentLink(
                link_id="link_db_dup_101",
                source=EventSource.RAZORPAY_TEST_MODE,
                case_id=case_id,
                action_id="act_dup_101",
                provider_link_id=link_id,
                reference_id=ref_id,
                short_url=f"https://rzp.io/i/{link_id}",
                status=PaymentLinkStatus.PAID,  # Already paid
                amount_paise=250000,
                currency="INR",
                expire_by=now + timedelta(days=1),
                provider_created_at=now,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await session.commit()

    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "event_id": "evt_plink_dup_second_call",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "reference_id": ref_id,
                    "amount": 250000,
                    "status": "paid",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_payment_captured_without_safe_case_correlation(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """payment.captured with uncorrelated order ID does not touch unrelated active recovery case."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value

    # Active case on order_A
    async with test_session_factory() as session:
        await OrderRepository(session).save_order(
            Order(
                order_id="order_active_case_A",
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=500000,
                currency="INR",
                status=OrderStatus.ATTEMPTED,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await RecoveryCaseRepository(session).save_case(
            RecoveryCase(
                case_id="rcv_active_case_A",
                source=EventSource.RAZORPAY_TEST_MODE,
                order_id="order_active_case_A",
                failed_attempt_id="pay_fail_A",
                state=RecoveryCaseState.LINK_CREATED,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await session.commit()

    # payment.captured for order_B (uncorrelated)
    payload = {
        "entity": "event",
        "event": "payment.captured",
        "event_id": "evt_cap_uncorrelated_999",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_cap_uncorrelated_999",
                    "order_id": "order_completely_different_B",
                    "amount": 100000,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig},
    )
    assert resp.status_code == 200

    # Assert active case A remains unchanged in LINK_CREATED
    async with test_session_factory() as session:
        case = await RecoveryCaseRepository(session).get_case("rcv_active_case_A", source=source)
        assert case is not None
        assert case.state == RecoveryCaseState.LINK_CREATED


@pytest.mark.asyncio
async def test_late_payment_failed_after_payment_link_paid(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Late payment.failed after payment_link.paid does NOT reopen paid order/case."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value
    order_id = "order_late_fail_101"
    case_id = "rcv_late_fail_101"

    async with test_session_factory() as session:
        await OrderRepository(session).save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=250000,
                currency="INR",
                status=OrderStatus.PAID,
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await RecoveryCaseRepository(session).save_case(
            RecoveryCase(
                case_id=case_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                order_id=order_id,
                failed_attempt_id="pay_orig_fail_1",
                state=RecoveryCaseState.RECOVERED,
                closure_reason=RecoveryCaseClosureReason.RECOVERED_VIA_LINK,
                closed_at=now,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            ),
            source=source,
        )
        await session.commit()

    # Late payment.failed webhook
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": "evt_late_fail_101",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_late_fail_101",
                    "order_id": order_id,
                    "amount": 250000,
                    "currency": "INR",
                    "status": "failed",
                }
            }
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={"X-Razorpay-Signature": sig},
    )
    assert resp.status_code == 200

    # Order must remain PAID, case must remain RECOVERED
    async with test_session_factory() as session:
        order = await OrderRepository(session).get_order(order_id, source=source)
        case = await RecoveryCaseRepository(session).get_case(case_id, source=source)

        assert order is not None and order.status == OrderStatus.PAID
        assert case is not None and case.state == RecoveryCaseState.RECOVERED
