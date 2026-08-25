"""Webhook ingestion endpoints for Razorpay payment and payment link lifecycle events."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.adapters.razorpay.verifier import WebhookVerifier
from retrypay.api.dependencies import (
    get_db_session,
    get_policy_engine,
    get_webhook_verifier,
)
from retrypay.config import Settings, get_settings
from retrypay.domain.models import (
    ActorType,
    AuditEvent,
    AuditEventType,
    EventSource,
    IngestionOrigin,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.domain.state_machine import transition_case
from retrypay.policy.engine import PolicyEngine
from retrypay.services.ingestion import ingest_verified_event
from retrypay.storage.models import RecoveryCaseModel
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


async def reconcile_expired_attribution_cases(
    session: AsyncSession,
    window_minutes: int = 30,
) -> list[str]:
    """Transition cases in PAYMENT_CONFIRMED_PENDING_ATTRIBUTION past window to CLOSED_BLOCKED."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=window_minutes)
    stmt = select(RecoveryCaseModel).where(
        RecoveryCaseModel.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value,
        RecoveryCaseModel.updated_at <= cutoff,
    )
    res = await session.execute(stmt)
    expired_models = res.scalars().all()
    closed_case_ids: list[str] = []

    case_repo = RecoveryCaseRepository(session)
    audit_repo = AuditRepository(session)

    for m in expired_models:
        case = await case_repo.get_case(m.case_id, source=m.source)
        if case and case.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION:
            closed_case = transition_case(
                case,
                RecoveryCaseState.CLOSED_BLOCKED,
                closure_reason=RecoveryCaseClosureReason.PAYMENT_ATTRIBUTION_UNCONFIRMED,
            )
            await case_repo.save_case(closed_case, source=m.source)
            await audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=case.source,
                    case_id=closed_case.case_id,
                    event_type=AuditEventType.CASE_CLOSED,
                    actor_type=ActorType.SYSTEM,
                    before_state=RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value,
                    after_state=RecoveryCaseState.CLOSED_BLOCKED.value,
                    metadata={
                        "closure_reason": (
                            RecoveryCaseClosureReason.PAYMENT_ATTRIBUTION_UNCONFIRMED.value
                        ),
                        "timeout_minutes": window_minutes,
                    },
                    timestamp=now,
                ),
                source=m.source,
            )
            closed_case_ids.append(closed_case.case_id)

    return closed_case_ids


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def ingest_razorpay_webhook(
    request: Request,
    response: Response,
    x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str | None = Header(default=None, alias="X-Razorpay-Event-Id"),
    session: AsyncSession = Depends(get_db_session),
    verifier: WebhookVerifier = Depends(get_webhook_verifier),
    policy_engine: PolicyEngine = Depends(get_policy_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Ingest, verify, reconcile raw Razorpay webhooks, and coordinate recovery execution.

    All incoming events on this route are server-classified as RAZORPAY_TEST_MODE.
    """
    raw_body = await request.body()
    print("INCOMING WEBHOOK HEADERS:", dict(request.headers))
    sig = (
        x_razorpay_signature
        or request.headers.get("x-razorpay-signature")
        or request.headers.get("X-Razorpay-Signature")
    )
    evt_id = (
        x_razorpay_event_id
        or request.headers.get("x-razorpay-event-id")
        or request.headers.get("X-Razorpay-Event-Id")
    )
    try:
        result = await ingest_verified_event(
            raw_body=raw_body,
            signature=sig,
            source=EventSource.RAZORPAY_TEST_MODE,
            ingestion_origin=IngestionOrigin.EXTERNAL_RAZORPAY_WEBHOOK,
            session=session,
            verifier=verifier,
            policy_engine=policy_engine,
            settings=settings,
            event_id_override=evt_id,
        )
    except HTTPException as exc:
        print(f"WEBHOOK INGESTION REJECTED ({exc.status_code}): {exc.detail}")
        raise exc

    res_dict: dict[str, Any] = {
        "status": "accepted" if result.status == "processed" else result.status,
        "event_id": result.event_id,
        "source": result.source,
    }
    if result.event_type:
        res_dict["event_type"] = result.event_type
    if result.outbox_job_id:
        res_dict["outbox_job_id"] = result.outbox_job_id
    if result.message:
        res_dict["message"] = result.message

    return res_dict
