"""Repository for managing operational daily budget reservations and guardrail metrics."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import BudgetReservation, BudgetReservationStatus, RecoveryCaseState
from retrypay.storage.models import (
    BudgetReservationModel,
    NotificationLogModel,
    RecoveryCaseModel,
)


class BudgetReservationRepository:
    """Async repository for operational budget tracking and atomic reservations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_reservation(self, reservation_id: str) -> BudgetReservation | None:
        """Fetch budget reservation by ID."""
        stmt = select(BudgetReservationModel).where(
            BudgetReservationModel.reservation_id == reservation_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_reservation_for_action(self, action_id: str) -> BudgetReservation | None:
        """Fetch budget reservation for a given action."""
        stmt = select(BudgetReservationModel).where(BudgetReservationModel.action_id == action_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_daily_usage(
        self, reservation_date: str, merchant_scope: str = "default_merchant"
    ) -> tuple[int, int]:
        """Calculate total (active_gmv_paise, action_count) reserved or committed for date.

        Includes PENDING and COMMITTED reservations; excludes RELEASED reservations.
        """
        stmt = select(
            func.coalesce(func.sum(BudgetReservationModel.amount_paise), 0),
            func.count(BudgetReservationModel.reservation_id),
        ).where(
            BudgetReservationModel.reservation_date == reservation_date,
            BudgetReservationModel.merchant_scope == merchant_scope,
            BudgetReservationModel.status.in_(
                [
                    BudgetReservationStatus.PENDING.value,
                    BudgetReservationStatus.COMMITTED.value,
                ]
            ),
        )
        result = await self._session.execute(stmt)
        row = result.one()
        return int(row[0]), int(row[1])

    async def get_daily_contacts_count(self, date_prefix: str) -> int:
        """Count simulated notifications dispatched for a specific date prefix (YYYY-MM-DD)."""
        stmt = select(func.count(NotificationLogModel.notification_id)).where(
            func.strftime("%Y-%m-%d", NotificationLogModel.simulated_at) == date_prefix
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_daily_manual_reviews_count(self, date_prefix: str) -> int:
        """Count recovery cases transitioned to MANUAL_REVIEW for a date prefix (YYYY-MM-DD)."""
        stmt = select(func.count(RecoveryCaseModel.case_id)).where(
            RecoveryCaseModel.state == RecoveryCaseState.MANUAL_REVIEW.value,
            func.strftime("%Y-%m-%d", RecoveryCaseModel.updated_at) == date_prefix,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def save_reservation(self, reservation: BudgetReservation) -> None:
        """Persist or update budget reservation."""
        stmt = select(BudgetReservationModel).where(
            BudgetReservationModel.reservation_id == reservation.reservation_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            model = BudgetReservationModel(
                reservation_id=reservation.reservation_id,
                merchant_scope=reservation.merchant_scope,
                case_id=reservation.case_id,
                action_id=reservation.action_id,
                amount_paise=reservation.amount_paise,
                reservation_date=reservation.reservation_date,
                status=reservation.status.value,
                created_at=reservation.created_at,
                released_at=reservation.released_at,
            )
            self._session.add(model)
        else:
            model.status = reservation.status.value
            model.released_at = reservation.released_at

        await self._session.flush()

    async def release_reservation(self, reservation_id: str) -> None:
        """Release a pending or active budget reservation."""
        stmt = select(BudgetReservationModel).where(
            BudgetReservationModel.reservation_id == reservation_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is not None:
            model.status = BudgetReservationStatus.RELEASED.value
            model.released_at = datetime.now(UTC)
            await self._session.flush()

    def _to_domain(self, model: BudgetReservationModel) -> BudgetReservation:
        return BudgetReservation(
            reservation_id=model.reservation_id,
            merchant_scope=model.merchant_scope,
            case_id=model.case_id,
            action_id=model.action_id,
            amount_paise=model.amount_paise,
            reservation_date=model.reservation_date,
            status=BudgetReservationStatus(model.status),
            created_at=model.created_at,
            released_at=model.released_at,
        )
