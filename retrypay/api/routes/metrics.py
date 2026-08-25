"""Batch recovery metrics and real-time operational aggregation endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from retrypay.api.dependencies import get_db_session
from retrypay.domain.models import RecoveryCaseState
from retrypay.storage.models import (
    PolicyEvaluationModel,
    RecoveryCaseModel,
    WebhookEventModel,
)

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])


class BatchRecoveryMetricsDTO(BaseModel):
    """Aggregated batch recovery metrics computed from live database records."""

    model_config = ConfigDict(frozen=True)

    total_failures_ingested: int
    active_cases: int
    recovered_count: int
    recovered_gmv_inr: float
    recovered_gmv_paise: int
    policy_block_rate: float
    manual_review_rate: float
    avg_time_to_recover_seconds: float
    state_distribution: dict[str, int]


async def compute_batch_recovery_metrics(session: AsyncSession) -> BatchRecoveryMetricsDTO:
    """Compute verified operational recovery metrics across all ingested cases."""
    SYNTHETIC_SRC = "SYNTHETIC_EVALUATION"

    # 1. Total failures ingested from webhook records
    failed_evts_q = select(func.count(WebhookEventModel.provider_event_id)).where(
        WebhookEventModel.event_type.in_(["payment.failed", "payment_failed"]),
        WebhookEventModel.source != SYNTHETIC_SRC,
    )
    total_failed_events = (await session.execute(failed_evts_q)).scalar() or 0

    # 2. Query all operational recovery cases with order relationship
    cases_q = (
        select(RecoveryCaseModel)
        .options(
            selectinload(RecoveryCaseModel.order),
            selectinload(RecoveryCaseModel.policy_evaluations),
        )
        .where(RecoveryCaseModel.source != SYNTHETIC_SRC)
    )
    all_cases = (await session.execute(cases_q)).scalars().all()

    active_states = {
        RecoveryCaseState.RECEIVED.value,
        RecoveryCaseState.ENRICHING.value,
        RecoveryCaseState.POLICY_EVALUATED.value,
        RecoveryCaseState.DIAGNOSED.value,
        RecoveryCaseState.ACTION_APPROVED.value,
        RecoveryCaseState.LINK_CREATED.value,
        RecoveryCaseState.NOTIFICATION_PENDING.value,
        RecoveryCaseState.NOTIFIED.value,
        RecoveryCaseState.NOTIFICATION_FAILED.value,
        RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value,
        RecoveryCaseState.DEFERRED.value,
    }

    state_distribution: dict[str, int] = {}
    active_cases = 0
    recovered_count = 0
    recovered_gmv_paise = 0
    recovery_durations: list[float] = []

    for c in all_cases:
        st = c.state
        state_distribution[st] = state_distribution.get(st, 0) + 1
        if st in active_states:
            active_cases += 1
        elif st == RecoveryCaseState.RECOVERED.value:
            recovered_count += 1
            if c.order and c.order.amount_paise:
                recovered_gmv_paise += c.order.amount_paise
            if c.created_at and c.updated_at:
                dur = (c.updated_at - c.created_at).total_seconds()
                if dur >= 0:
                    recovery_durations.append(dur)

    tot_cases = len(all_cases) or 1

    # 3. Policy evaluations breakdown
    evals_q = (
        select(PolicyEvaluationModel)
        .join(RecoveryCaseModel, PolicyEvaluationModel.case_id == RecoveryCaseModel.case_id)
        .where(RecoveryCaseModel.source != SYNTHETIC_SRC)
    )
    all_evals = (await session.execute(evals_q)).scalars().all()
    tot_evals = len(all_evals) or tot_cases

    blocks = sum(1 for e in all_evals if e.decision_type == "BLOCK")
    reviews = sum(1 for e in all_evals if e.decision_type == "MANUAL_REVIEW")

    avg_time = (
        round(sum(recovery_durations) / len(recovery_durations), 2) if recovery_durations else 0.0
    )

    return BatchRecoveryMetricsDTO(
        total_failures_ingested=total_failed_events if total_failed_events > 0 else len(all_cases),
        active_cases=active_cases,
        recovered_count=recovered_count,
        recovered_gmv_inr=round(recovered_gmv_paise / 100.0, 2),
        recovered_gmv_paise=recovered_gmv_paise,
        policy_block_rate=round(blocks / tot_evals, 4),
        manual_review_rate=round(reviews / tot_evals, 4),
        avg_time_to_recover_seconds=avg_time,
        state_distribution=state_distribution,
    )


@router.get("/batch", response_model=BatchRecoveryMetricsDTO)
async def get_batch_recovery_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> BatchRecoveryMetricsDTO:
    """Retrieve quantified batch recovery metrics computed from live database rows."""
    return await compute_batch_recovery_metrics(session)
