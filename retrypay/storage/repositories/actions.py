"""Repository for managing recovery actions and idempotency."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.decision.diagnosis import ActionType
from retrypay.domain.models import EventSource, RecoveryAction, RecoveryActionStatus
from retrypay.storage.models import RecoveryActionModel


class RecoveryActionRepository:
    """Async repository for managing bounded recovery action persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_idempotency_key(self, idempotency_key: str) -> RecoveryAction | None:
        """Fetch recovery action by deterministic idempotency key."""
        stmt = select(RecoveryActionModel).where(
            RecoveryActionModel.idempotency_key == idempotency_key
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_action(self, action_id: str) -> RecoveryAction | None:
        """Fetch recovery action by ID."""
        stmt = select(RecoveryActionModel).where(RecoveryActionModel.action_id == action_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_action_for_case(self, case_id: str) -> RecoveryAction | None:
        """Fetch recovery action for a given recovery case."""
        stmt = (
            select(RecoveryActionModel)
            .where(RecoveryActionModel.case_id == case_id)
            .order_by(RecoveryActionModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def save_action(self, action: RecoveryAction, source: str = "LOCAL_SIMULATION") -> None:
        """Persist or update recovery action."""
        target_source = action.source or source
        stmt = select(RecoveryActionModel).where(RecoveryActionModel.action_id == action.action_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            model = RecoveryActionModel(
                action_id=action.action_id,
                source=target_source,
                case_id=action.case_id,
                action_type=action.action_type.value,
                policy_version=action.policy_version,
                idempotency_key=action.idempotency_key,
                status=action.status.value,
                provider_operation_status=action.provider_operation_status.value,
                created_at=action.created_at,
                updated_at=action.updated_at,
            )
            self._session.add(model)
        else:
            model.status = action.status.value
            model.provider_operation_status = action.provider_operation_status.value
            model.updated_at = action.updated_at

        try:
            await self._session.flush()
        except IntegrityError:
            # Handle potential concurrent race condition on idempotency key
            raise

    def _to_domain(self, model: RecoveryActionModel) -> RecoveryAction:
        from retrypay.domain.models import ProviderOperationStatus

        return RecoveryAction(
            action_id=model.action_id,
            source=EventSource(model.source) if model.source else EventSource.LOCAL_SIMULATION,
            case_id=model.case_id,
            action_type=ActionType(model.action_type),
            policy_version=model.policy_version,
            idempotency_key=model.idempotency_key,
            status=RecoveryActionStatus(model.status),
            provider_operation_status=(
                ProviderOperationStatus(model.provider_operation_status)
                if getattr(model, "provider_operation_status", None)
                else ProviderOperationStatus.NOT_STARTED
            ),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
