"""Repository for append-only audit events and policy evaluation persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import (
    ActorType,
    AuditEvent,
    AuditEventType,
    EventSource,
    PolicyDecision,
    PolicyDecisionType,
    PolicyReasonCode,
)
from retrypay.storage.models import AuditEventModel, PolicyEvaluationModel


class AuditRepository:
    """Async repository managing append-only audit trail and policy evaluation records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_audit_event(self, event: AuditEvent, source: str = "LOCAL_SIMULATION") -> None:
        """Append an audit event."""
        model = AuditEventModel(
            event_id=event.event_id,
            source=event.source or source,
            case_id=event.case_id,
            event_type=event.event_type.value,
            actor_type=event.actor_type.value,
            before_state=event.before_state,
            after_state=event.after_state,
            sanitized_metadata=event.metadata,
            timestamp=event.timestamp,
        )
        self._session.add(model)

    async def record_policy_evaluation(
        self, case_id: str, decision: PolicyDecision, evaluation_id: str
    ) -> None:
        """Persist a policy evaluation outcome."""
        model = PolicyEvaluationModel(
            evaluation_id=evaluation_id,
            case_id=case_id,
            policy_version=decision.policy_version,
            decision_type=decision.decision_type.value,
            reasons=[r.value for r in decision.reasons],
            context_hash=decision.context_hash,
            evaluated_at=decision.evaluated_at,
        )
        self._session.add(model)

    async def get_audit_events_for_case(self, case_id: str) -> list[AuditEvent]:
        """Fetch all audit events for a recovery case in chronological order."""
        stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.case_id == case_id)
            .order_by(AuditEventModel.timestamp.asc())
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()

        return [
            AuditEvent(
                event_id=m.event_id,
                source=EventSource(m.source) if m.source else EventSource.LOCAL_SIMULATION,
                case_id=m.case_id,
                event_type=AuditEventType(m.event_type),
                actor_type=ActorType(m.actor_type),
                before_state=m.before_state,
                after_state=m.after_state,
                metadata=m.sanitized_metadata or {},
                timestamp=m.timestamp,
            )
            for m in models
        ]

    async def get_policy_evaluations_for_case(self, case_id: str) -> list[PolicyDecision]:
        """Fetch all policy evaluations for a recovery case."""
        stmt = (
            select(PolicyEvaluationModel)
            .where(PolicyEvaluationModel.case_id == case_id)
            .order_by(PolicyEvaluationModel.evaluated_at.asc())
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()

        return [
            PolicyDecision(
                decision_type=PolicyDecisionType(m.decision_type),
                reasons=[PolicyReasonCode(r) for r in m.reasons],
                policy_version=m.policy_version,
                evaluated_at=m.evaluated_at,
                context_hash=m.context_hash,
            )
            for m in models
        ]
