"""Unit tests for the operational budget reservation engine and guardrail boundaries."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.budget.engine import (
    BudgetEngine,
    BudgetExhaustedError,
    ManualReviewCapacityExhaustedError,
)
from retrypay.domain.models import (
    BudgetReservation,
    BudgetReservationStatus,
    ContactChannel,
    NotificationLog,
    NotificationStatus,
    NotificationTemplateKey,
    RecoveryCase,
    RecoveryCaseState,
)
from retrypay.storage.repositories.budget import BudgetReservationRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.notifications import NotificationRepository


@pytest.mark.asyncio
async def test_budget_reservation_amount_threshold(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure single action amount exceeding threshold (>₹10,000) raises BudgetExhaustedError."""
    async with test_session_factory() as session:
        engine = BudgetEngine(session)
        # Attempting to reserve ₹10,000.01 (1,000,001 paise) -> fails
        with pytest.raises(BudgetExhaustedError) as exc_info:
            await engine.reserve_budget(
                case_id="rcv_test_001",
                action_id="act_test_001",
                amount_paise=1_000_001,
            )
        assert "exceeds max automated recovery amount" in str(exc_info.value)


@pytest.mark.asyncio
async def test_budget_reservation_lifecycle_and_release(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure reservation progresses PENDING -> RELEASED or PENDING -> COMMITTED."""
    async with test_session_factory() as session:
        engine = BudgetEngine(session)
        repo = BudgetReservationRepository(session)

        # 1. Create PENDING reservation
        res = await engine.reserve_budget(
            case_id="rcv_test_001",
            action_id="act_test_001",
            amount_paise=50000,  # ₹500
        )
        await session.commit()

        assert res.status == BudgetReservationStatus.PENDING

        # 2. Release reservation upon link creation failure
        await engine.release_reservation(res.reservation_id)
        await session.commit()

        updated_res = await repo.get_reservation(res.reservation_id)
        assert updated_res is not None
        assert updated_res.status == BudgetReservationStatus.RELEASED
        assert updated_res.released_at is not None


@pytest.mark.asyncio
async def test_budget_reservation_daily_gmv_cap_exhaustion(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure cumulative daily reservations exceeding ₹50,000 trigger BudgetExhaustedError."""
    async with test_session_factory() as session:
        engine = BudgetEngine(session)

        # Reserve ₹10,000 x 5 times = ₹50,000 (at cap)
        for i in range(5):
            res = await engine.reserve_budget(
                case_id=f"rcv_test_gmv_{i}",
                action_id=f"act_test_gmv_{i}",
                amount_paise=1_000_000,
            )
            await engine.commit_reservation(res.reservation_id)
        await session.commit()

        # Next reservation exceeding cap -> raises BudgetExhaustedError
        with pytest.raises(BudgetExhaustedError) as exc_info:
            await engine.reserve_budget(
                case_id="rcv_test_gmv_overflow",
                action_id="act_test_gmv_overflow",
                amount_paise=50000,
            )
        assert "Daily GMV budget exhausted" in str(exc_info.value)


@pytest.mark.asyncio
async def test_budget_reservation_daily_action_cap_exhaustion(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure daily action cap (200 actions) raises BudgetExhaustedError."""
    async with test_session_factory() as session:
        engine = BudgetEngine(session)
        today_str = engine.get_merchant_today_date()
        repo = BudgetReservationRepository(session)

        # Pre-seed 200 tiny reservations
        for i in range(200):
            await repo.save_reservation(
                BudgetReservation(
                    reservation_id=f"bres_act_cap_{i}",
                    merchant_scope="default_merchant",
                    case_id=f"rcv_act_cap_{i}",
                    action_id=f"act_cap_{i}",
                    amount_paise=100,
                    reservation_date=today_str,
                    status=BudgetReservationStatus.COMMITTED,
                )
            )
        await session.commit()

        # 201st reservation -> raises BudgetExhaustedError
        with pytest.raises(BudgetExhaustedError) as exc_info:
            await engine.reserve_budget(
                case_id="rcv_overflow",
                action_id="act_overflow",
                amount_paise=100,
            )
        assert "Daily action cap reached" in str(exc_info.value)


@pytest.mark.asyncio
async def test_budget_reservation_daily_contact_cap_exhaustion(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure daily contact cap (200 contacts) raises BudgetExhaustedError pre-link creation."""
    async with test_session_factory() as session:
        engine = BudgetEngine(session)
        notif_repo = NotificationRepository(session)

        # Pre-seed 200 simulated notifications
        now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)
        for i in range(200):
            await notif_repo.save_notification(
                NotificationLog(
                    notification_id=f"notif_cap_{i}",
                    case_id=f"rcv_cap_{i}",
                    action_id=f"act_cap_{i}",
                    channel=ContactChannel.WHATSAPP,
                    template_key=NotificationTemplateKey.PAYMENT_RETRY_GENERIC,
                    masked_recipient="+91******0000",
                    link_reference="https://rzp.io/i/test",
                    status=NotificationStatus.SIMULATED,
                    simulated_at=now,
                )
            )
        await session.commit()

        # Attempting budget reservation when contact cap exhausted -> fails pre-link
        with pytest.raises(BudgetExhaustedError) as exc_info:
            await engine.reserve_budget(
                case_id="rcv_overflow_contact",
                action_id="act_overflow_contact",
                amount_paise=1000,
                as_of=now,
            )
        assert "Daily contact cap reached" in str(exc_info.value)


@pytest.mark.asyncio
async def test_manual_review_capacity_exhaustion(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure manual review capacity cap (25 cases) raises ManualReviewCapacityExhaustedError."""
    async with test_session_factory() as session:
        engine = BudgetEngine(session)
        case_repo = RecoveryCaseRepository(session)
        now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)

        # Pre-seed 25 cases in MANUAL_REVIEW state
        for i in range(25):
            await case_repo.save_case(
                RecoveryCase(
                    case_id=f"rcv_rev_cap_{i}",
                    order_id=f"order_rev_cap_{i}",
                    failed_attempt_id=f"pay_rev_{i}",
                    state=RecoveryCaseState.MANUAL_REVIEW,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()

        # Checking manual review capacity -> raises ManualReviewCapacityExhaustedError
        with pytest.raises(ManualReviewCapacityExhaustedError) as exc_info:
            await engine.check_manual_review_capacity(as_of=now)
        assert "Manual review capacity exhausted" in str(exc_info.value)
