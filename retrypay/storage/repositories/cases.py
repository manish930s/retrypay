"""Repository for managing recovery case persistence and one-active-case-per-order invariant."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.errors import DuplicateActiveCaseError
from retrypay.domain.models import (
    EventSource,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.domain.state_machine import transition_case
from retrypay.storage.models import RecoveryCaseModel


class RecoveryCaseRepository:
    """Async repository for recovery case entities enforcing active uniqueness per source."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_case_for_order(
        self, order_id: str, source: str = "LOCAL_SIMULATION"
    ) -> RecoveryCase | None:
        """Fetch active recovery case for an order and source if one exists."""
        stmt = (
            select(RecoveryCaseModel)
            .where(
                RecoveryCaseModel.order_id == order_id,
                RecoveryCaseModel.source == source,
                RecoveryCaseModel.closed_at.is_(None),
                RecoveryCaseModel.state != RecoveryCaseState.CLOSED_BLOCKED.value,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_case(self, case_id: str, source: str | None = None) -> RecoveryCase | None:
        """Fetch recovery case by ID and optional source."""
        stmt = select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == case_id)
        if source is not None:
            stmt = stmt.where(RecoveryCaseModel.source == source)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def save_case(self, case: RecoveryCase, source: str = "LOCAL_SIMULATION") -> None:
        """Persist or update recovery case, asserting at most one active case per order and source.

        Enforces uniqueness via:
        1. Repository pre-check for clear domain error reporting.
        2. Database partial unique index (uq_one_active_recovery_case_per_order).
        """
        target_source = case.source or source
        stmt = select(RecoveryCaseModel).where(
            RecoveryCaseModel.case_id == case.case_id,
            RecoveryCaseModel.source == target_source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            # Domain-level pre-check for friendly error reporting
            if case.is_active:
                existing_active = await self.get_active_case_for_order(
                    case.order_id, source=target_source
                )
                if existing_active is not None and existing_active.case_id != case.case_id:
                    raise DuplicateActiveCaseError(
                        f"An active recovery case '{existing_active.case_id}' already exists "
                        f"for order '{case.order_id}' and source '{target_source}'."
                    )

            model = RecoveryCaseModel(
                case_id=case.case_id,
                source=target_source,
                order_id=case.order_id,
                failed_attempt_id=case.failed_attempt_id,
                customer_id=case.customer_id,
                state=case.state.value,
                policy_version=case.policy_version,
                contact_count=case.contact_count,
                quiet_hours_deferred_until=case.quiet_hours_deferred_until,
                closed_at=case.closed_at,
                closure_reason=(case.closure_reason.value if case.closure_reason else None),
                created_at=case.created_at,
                updated_at=case.updated_at,
            )
            self._session.add(model)
        else:
            model.state = case.state.value
            model.policy_version = case.policy_version
            model.contact_count = case.contact_count
            model.customer_id = case.customer_id
            model.quiet_hours_deferred_until = case.quiet_hours_deferred_until
            model.closed_at = case.closed_at
            model.closure_reason = case.closure_reason.value if case.closure_reason else None
            model.updated_at = case.updated_at

        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Intercept database uniqueness violation on partial index or foreign keys
            err_msg = str(exc)
            if (
                "uq_one_active_recovery_case_per_order" in err_msg
                or "UNIQUE constraint failed" in err_msg
            ):
                msg = (
                    f"Database constraint: Active case already exists for order '{case.order_id}' "
                    f"and source '{target_source}'."
                )
                raise DuplicateActiveCaseError(msg) from exc
            raise

    async def close_active_case_for_order(
        self,
        order_id: str,
        closure_reason: RecoveryCaseClosureReason,
        source: str = "LOCAL_SIMULATION",
    ) -> RecoveryCase | None:
        """Close active recovery case for an order and source if present."""
        active = await self.get_active_case_for_order(order_id, source=source)
        if active is None:
            return None

        closed = transition_case(
            active,
            to_state=RecoveryCaseState.CLOSED_BLOCKED,
            closure_reason=closure_reason,
        )
        await self.save_case(closed, source=source)
        return closed

    def _to_domain(self, model: RecoveryCaseModel) -> RecoveryCase:
        closure_reason = (
            RecoveryCaseClosureReason(model.closure_reason) if model.closure_reason else None
        )
        return RecoveryCase(
            case_id=model.case_id,
            source=EventSource(model.source) if model.source else EventSource.LOCAL_SIMULATION,
            order_id=model.order_id,
            failed_attempt_id=model.failed_attempt_id,
            customer_id=model.customer_id,
            state=RecoveryCaseState(model.state),
            policy_version=model.policy_version,
            contact_count=model.contact_count,
            quiet_hours_deferred_until=model.quiet_hours_deferred_until,
            closed_at=model.closed_at,
            closure_reason=closure_reason,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
