"""Repository for persisting append-only advisory decision traces."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.storage.models import DecisionTraceModel


class DecisionTraceRepository:
    """Async repository for persisting advisory decision traces."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_trace(
        self,
        trace_id: str,
        case_id: str,
        policy_version: str,
        policy_decision: str,
        ros_version: str,
        ros_score: int,
        ros_contributions: dict[str, Any],
        diagnosis_category: str,
        diagnosis_confidence: float,
        diagnosis_mode: str,
        diagnosis_fallback_used: bool,
        action_candidates: list[str],
        selected_action: str,
        estimator_mode: str,
        estimator_version: str,
        input_context_hash: str,
        estimator_output_hash: str,
        utility_paise: int,
        created_at: datetime | None = None,
    ) -> None:
        """Persist an immutable advisory decision trace."""
        model = DecisionTraceModel(
            trace_id=trace_id,
            case_id=case_id,
            policy_version=policy_version,
            policy_decision=policy_decision,
            ros_version=ros_version,
            ros_score=ros_score,
            ros_contributions=ros_contributions,
            diagnosis_category=diagnosis_category,
            diagnosis_confidence=diagnosis_confidence,
            diagnosis_mode=diagnosis_mode,
            diagnosis_fallback_used=diagnosis_fallback_used,
            action_candidates=action_candidates,
            selected_action=selected_action,
            estimator_mode=estimator_mode,
            estimator_version=estimator_version,
            input_context_hash=input_context_hash,
            estimator_output_hash=estimator_output_hash,
            utility_paise=utility_paise,
            created_at=created_at or datetime.now(UTC),
        )
        self._session.add(model)

    async def get_trace_for_case(self, case_id: str) -> DecisionTraceModel | None:
        """Fetch the advisory decision trace for a given recovery case."""
        stmt = (
            select(DecisionTraceModel)
            .where(DecisionTraceModel.case_id == case_id)
            .order_by(DecisionTraceModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
