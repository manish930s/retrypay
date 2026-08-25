"""Operational daily budget reservation engine enforcing automated recovery guardrails."""

import uuid
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.config import Settings, get_settings
from retrypay.domain.models import BudgetReservation, BudgetReservationStatus
from retrypay.storage.repositories.budget import BudgetReservationRepository


class BudgetExhaustedError(Exception):
    """Raised when an automated recovery action exceeds daily budget guardrails."""


class ManualReviewCapacityExhaustedError(Exception):
    """Raised when the daily operator manual review queue capacity (25) is exhausted."""


class BudgetEngine:
    """Manages transactional operational budget reservations and daily guardrails."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = BudgetReservationRepository(session)

    def get_merchant_today_date(self, as_of: datetime | None = None) -> str:
        """Return date string (YYYY-MM-DD) in merchant timezone for given datetime."""
        tz: tzinfo
        try:
            tz = ZoneInfo(self._settings.RETRYPAY_MERCHANT_TIMEZONE)
        except Exception:
            tz = UTC
        target_dt = as_of or datetime.now(UTC)
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=UTC)
        return target_dt.astimezone(tz).strftime("%Y-%m-%d")

    async def check_manual_review_capacity(self, as_of: datetime | None = None) -> bool:
        """Check if manual review queue has capacity (< 25 cases today)."""
        today_str = self.get_merchant_today_date(as_of)
        count = await self._repo.get_daily_manual_reviews_count(today_str)
        max_capacity = 25
        if count >= max_capacity:
            raise ManualReviewCapacityExhaustedError(
                f"Manual review capacity exhausted for date {today_str}: "
                f"{count} cases >= {max_capacity} limit."
            )
        return True

    async def reserve_budget(
        self,
        case_id: str,
        action_id: str,
        amount_paise: int,
        merchant_scope: str = "default_merchant",
        as_of: datetime | None = None,
    ) -> BudgetReservation:
        """Reserve operational budget transactionally before link creation.

        Enforces all 5 configured budget controls:
        1. max_auto_recovery_amount_paise (₹10,000)
        2. max_contact_count_per_day (200 contacts) - checked pre-link creation
        3. max_auto_actions_per_day (200 actions)
        4. max_auto_recovery_gmv_per_day_paise (₹50,000)
        """
        # Guardrail 1: Single action amount threshold (₹10,000 default)
        if amount_paise > self._settings.RETRYPAY_MAX_AUTO_RECOVERY_PAISE:
            raise BudgetExhaustedError(
                f"Amount {amount_paise} paise exceeds max automated recovery amount "
                f"({self._settings.RETRYPAY_MAX_AUTO_RECOVERY_PAISE} paise)."
            )

        today_str = self.get_merchant_today_date(as_of)

        # Guardrail 2: Daily contact cap check (pre-link creation)
        max_daily_contacts = 200
        current_contacts = await self._repo.get_daily_contacts_count(today_str)
        if current_contacts >= max_daily_contacts:
            raise BudgetExhaustedError(
                f"Daily contact cap reached for date {today_str}: {current_contacts} contacts "
                f"exceeds limit of {max_daily_contacts}."
            )

        # Guardrail 3 & 4: Daily action and GMV budget checks
        max_daily_gmv = 5_000_000  # ₹50,000
        max_daily_actions = 200

        current_gmv, current_actions = await self._repo.get_daily_usage(today_str, merchant_scope)

        if current_actions >= max_daily_actions:
            raise BudgetExhaustedError(
                f"Daily action cap reached for date {today_str}: {current_actions} actions "
                f"exceeds limit of {max_daily_actions}."
            )

        if current_gmv + amount_paise > max_daily_gmv:
            raise BudgetExhaustedError(
                f"Daily GMV budget exhausted for date {today_str}: current {current_gmv} paise + "
                f"requested {amount_paise} paise exceeds limit of {max_daily_gmv} paise."
            )

        # Create PENDING reservation
        reservation_id = f"bres_{uuid.uuid4().hex[:12]}"
        reservation = BudgetReservation(
            reservation_id=reservation_id,
            merchant_scope=merchant_scope,
            case_id=case_id,
            action_id=action_id,
            amount_paise=amount_paise,
            reservation_date=today_str,
            status=BudgetReservationStatus.PENDING,
            created_at=datetime.now(UTC),
            released_at=None,
        )
        await self._repo.save_reservation(reservation)
        return reservation

    async def commit_reservation(self, reservation_id: str) -> None:
        """Mark budget reservation as COMMITTED following successful link creation."""
        res = await self._repo.get_reservation(reservation_id)
        if res is not None and res.status == BudgetReservationStatus.PENDING:
            updated = res.model_copy(update={"status": BudgetReservationStatus.COMMITTED})
            await self._repo.save_reservation(updated)

    async def release_reservation(self, reservation_id: str) -> None:
        """Release a PENDING reservation if link creation definitively fails."""
        await self._repo.release_reservation(reservation_id)
