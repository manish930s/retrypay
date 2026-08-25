import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from retrypay.adapters.razorpay.payment_links import (
    FakePaymentLinkProvider,
    RazorpayPaymentLinkProvider,
)
from retrypay.adapters.razorpay.verifier import WebhookVerifier
from retrypay.api.dependencies import get_db_session, get_settings
from retrypay.config import Settings
from retrypay.domain.models import (
    ActorType,
    AuditEventType,
    EventSource,
    MerchantPolicyConfig,
    NotificationStatus,
    PaymentLinkStatus,
    RecoveryCaseState,
)
from retrypay.storage.models import (
    AuditEventModel,
    CustomerModel,
    DecisionTraceModel,
    NotificationLogModel,
    OrderModel,
    OutreachNotificationLogModel,
    PolicyEvaluationModel,
    RecoveryActionModel,
    RecoveryCaseModel,
    ReminderTokenModel,
    WebhookEventModel,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])

ALLOWED_METADATA_KEYS = {
    "order_id",
    "amount_paise",
    "currency",
    "decision_type",
    "reasons",
    "safe_reason",
    "evaluation_id",
    "policy_version",
    "ros_score",
    "diagnosis_category",
    "diagnosis_mode",
    "selected_action",
    "provider_link_id",
    "reference_id",
    "status",
    "channel",
    "template_key",
    "masked_recipient",
    "reservation_id",
    "closure_reason",
    "step",
    "reason",
    "medium",
    "correlation_id",
    "expires_at",
    "attempt_number",
    "notification_id",
    "delivery_status",
}

FORBIDDEN_KEY_SUBSTRINGS = (
    "secret",
    "signature",
    "body",
    "payload",
    "key",
    "raw",
    "token",
    "stack",
    "prompt",
    "potential_outcome",
    "unassigned",
    "exception",
    "password",
    "hash",
    "short_url",
)


def sanitize_audit_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Sanitize metadata to strictly allowed non-sensitive keys and primitive values."""
    if not raw or not isinstance(raw, dict):
        return {}
    clean: dict[str, Any] = {}
    for k, v in raw.items():
        k_str = str(k)
        k_lower = k_str.lower()
        if any(sub in k_lower for sub in FORBIDDEN_KEY_SUBSTRINGS):
            continue
        if k_str in ALLOWED_METADATA_KEYS or k_lower in ALLOWED_METADATA_KEYS:
            if isinstance(v, (str, int, float, bool)):
                clean[k_str] = v
            elif isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
                clean[k_str] = v
            elif isinstance(v, dict):
                clean[k_str] = sanitize_audit_metadata(v)
    return clean


class SanitizedAuditEventDTO(BaseModel):
    """Sanitized audit event representation safe for merchant operator console."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    source: str = "LOCAL_SIMULATION"
    case_id: str | None = None
    event_type: str
    actor_type: str
    before_state: str | None = None
    after_state: str | None = None
    safe_reason_code: str | None = None
    version_info: str | None = None
    timestamp: datetime
    sanitized_metadata: dict[str, Any] = Field(default_factory=dict)


def map_sanitized_audit_event(a: AuditEventModel) -> SanitizedAuditEventDTO:
    """Map database audit event to strictly allowlisted operator DTO."""
    safe_metadata = sanitize_audit_metadata(a.sanitized_metadata)
    safe_reason = (
        safe_metadata.get("closure_reason")
        or safe_metadata.get("reason")
        or safe_metadata.get("safe_reason")
    )
    if not safe_reason and safe_metadata.get("reasons"):
        reasons_val = safe_metadata["reasons"]
        safe_reason = (
            reasons_val[0] if isinstance(reasons_val, list) and reasons_val else str(reasons_val)
        )
    version = safe_metadata.get("policy_version") or "recovery-v1.3"
    return SanitizedAuditEventDTO(
        event_id=a.event_id,
        source=a.source,
        case_id=a.case_id,
        event_type=a.event_type,
        actor_type=a.actor_type,
        before_state=a.before_state,
        after_state=a.after_state,
        safe_reason_code=str(safe_reason) if safe_reason else None,
        version_info=str(version) if version else None,
        timestamp=a.timestamp,
        sanitized_metadata=safe_metadata,
    )


class OverviewStatsDTO(BaseModel):
    """Aggregate operational overview metrics for merchant operations."""

    model_config = ConfigDict(frozen=True)

    total_failed_events: int
    active_cases_count: int
    active_cases_by_state: dict[str, int]
    total_recovered_cases: int
    two_evidence_verified_recoveries: int
    policy_block_rate: float
    manual_review_rate: float
    deferred_rate: float
    no_action_selection_rate: float
    simulated_notifications_count: int
    latest_audit_activity: list[SanitizedAuditEventDTO]
    recent_cases: list[dict[str, Any]]


class CaseSummaryDTO(BaseModel):
    """Sanitized summary item for recovery case list view."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    source: str = "LOCAL_SIMULATION"
    order_id: str
    amount_paise: int
    currency: str
    masked_customer_phone: str | None
    masked_customer_email: str | None
    state: str
    closure_reason: str | None
    policy_decision: str | None
    ros_score: int | None
    ros_band: str | None
    diagnosis_category: str | None
    selected_action: str | None
    link_status: str | None
    masked_link_id: str | None = None
    masked_reference_id: str | None = None
    contact_count: int
    created_at: datetime
    updated_at: datetime


class CaseListResponse(BaseModel):
    """Paginated list response for recovery cases."""

    model_config = ConfigDict(frozen=True)

    items: list[CaseSummaryDTO]
    total: int
    limit: int
    offset: int


class TimelineEventDTO(BaseModel):
    """A discrete chronological step in the recovery case lifecycle."""

    model_config = ConfigDict(frozen=True)

    step_number: int
    title: str
    status: str  # "success" | "warning" | "error" | "info" | "pending"
    timestamp: datetime
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseDetailDTO(BaseModel):
    """Full investigation detail and chronological timeline for a single recovery case."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    source: str = "LOCAL_SIMULATION"
    order_id: str
    state: str
    closure_reason: str | None
    contact_count: int
    created_at: datetime
    updated_at: datetime

    # Customer & Order Context
    customer: dict[str, Any]
    order: dict[str, Any]
    payment_attempt: dict[str, Any]

    # Policy & Diagnosis & ROS
    policy_evaluation: dict[str, Any] | None
    decision_trace: dict[str, Any] | None

    # Execution & Link & Notification
    recovery_action: dict[str, Any] | None
    payment_link: dict[str, Any] | None
    notifications: list[dict[str, Any]]
    budget_reservation: dict[str, Any] | None

    # Chronological Timeline
    timeline: list[TimelineEventDTO]
    audit_events: list[SanitizedAuditEventDTO]


class SettingsDTO(BaseModel):
    """Read-only operational and policy settings."""

    model_config = ConfigDict(frozen=True)

    environment: str
    policy_version: str
    quiet_hours: dict[str, Any]
    contact_caps: dict[str, Any]
    guardrails: dict[str, Any]
    attribution_reconciliation_window_minutes: int
    llm_enabled: bool
    llm_model: str
    mapper_version: str
    ros_version: str
    estimator_version: str


@router.get("/overview", response_model=OverviewStatsDTO)
async def get_overview_stats(
    session: AsyncSession = Depends(get_db_session),
) -> OverviewStatsDTO:
    """Retrieve operational dashboard overview metrics."""
    SYNTHETIC_SRC = "SYNTHETIC_EVALUATION"

    # 1. Failed webhook events count (operational only)
    failed_evts_q = select(func.count(WebhookEventModel.provider_event_id)).where(
        WebhookEventModel.event_type.in_(["payment.failed", "payment_failed"]),
        WebhookEventModel.source != SYNTHETIC_SRC,
    )
    total_failed_events = (await session.execute(failed_evts_q)).scalar() or 0

    # 2. Case states breakdown (operational only)
    cases_q = select(RecoveryCaseModel).where(RecoveryCaseModel.source != SYNTHETIC_SRC)
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
    }

    active_cases_by_state: dict[str, int] = {}
    active_count = 0
    recovered_count = 0

    for c in all_cases:
        st = c.state
        active_cases_by_state[st] = active_cases_by_state.get(st, 0) + 1
        if st in active_states:
            active_count += 1
        if st == RecoveryCaseState.RECOVERED.value:
            recovered_count += 1

    # 3. Policy decisions summary (operational only)
    evals_q = (
        select(PolicyEvaluationModel)
        .join(RecoveryCaseModel, PolicyEvaluationModel.case_id == RecoveryCaseModel.case_id)
        .where(RecoveryCaseModel.source != SYNTHETIC_SRC)
    )
    all_evals = (await session.execute(evals_q)).scalars().all()
    tot_evals = len(all_evals) or 1

    blocks = sum(1 for e in all_evals if e.decision_type == "BLOCK")
    reviews = sum(1 for e in all_evals if e.decision_type == "MANUAL_REVIEW")
    defers = sum(1 for e in all_evals if e.decision_type == "DEFER")

    # 4. Decision traces for no_action rate (operational only)
    traces_q = (
        select(DecisionTraceModel)
        .join(RecoveryCaseModel, DecisionTraceModel.case_id == RecoveryCaseModel.case_id)
        .where(RecoveryCaseModel.source != SYNTHETIC_SRC)
    )
    all_traces = (await session.execute(traces_q)).scalars().all()
    tot_traces = len(all_traces) or 1
    no_actions = sum(1 for t in all_traces if t.selected_action == "NO_ACTION")

    # 5. Simulated notifications (operational only)
    notifs_q = select(func.count(NotificationLogModel.notification_id)).where(
        NotificationLogModel.source != SYNTHETIC_SRC
    )
    tot_notifs = (await session.execute(notifs_q)).scalar() or 0

    # 6. Latest audit activity (last 10 operational)
    audits_q = (
        select(AuditEventModel)
        .where(AuditEventModel.source != SYNTHETIC_SRC)
        .order_by(AuditEventModel.timestamp.desc())
        .limit(10)
    )
    audit_models = (await session.execute(audits_q)).scalars().all()
    latest_audits = [map_sanitized_audit_event(a) for a in audit_models]

    # 7. Recent cases summary (last 5 operational)
    rec_cases_q = (
        select(RecoveryCaseModel)
        .options(
            selectinload(RecoveryCaseModel.order),
            selectinload(RecoveryCaseModel.policy_evaluations),
            selectinload(RecoveryCaseModel.decision_traces),
        )
        .where(RecoveryCaseModel.source != SYNTHETIC_SRC)
        .order_by(RecoveryCaseModel.created_at.desc())
        .limit(5)
    )
    rec_case_models = (await session.execute(rec_cases_q)).scalars().all()
    recent_cases: list[dict[str, Any]] = []
    for rc in rec_case_models:
        latest_eval = rc.policy_evaluations[-1] if rc.policy_evaluations else None
        latest_trace = rc.decision_traces[-1] if rc.decision_traces else None
        recent_cases.append(
            {
                "case_id": rc.case_id,
                "order_id": rc.order_id,
                "amount_paise": rc.order.amount_paise if rc.order else 0,
                "state": rc.state,
                "policy_decision": latest_eval.decision_type if latest_eval else None,
                "ros_score": latest_trace.ros_score if latest_trace else None,
                "selected_action": latest_trace.selected_action if latest_trace else None,
                "created_at": rc.created_at,
            }
        )

    return OverviewStatsDTO(
        total_failed_events=total_failed_events,
        active_cases_count=active_count,
        active_cases_by_state=active_cases_by_state,
        total_recovered_cases=recovered_count,
        two_evidence_verified_recoveries=recovered_count,
        policy_block_rate=round(blocks / tot_evals, 4),
        manual_review_rate=round(reviews / tot_evals, 4),
        deferred_rate=round(defers / tot_evals, 4),
        no_action_selection_rate=round(no_actions / tot_traces, 4),
        simulated_notifications_count=tot_notifs,
        latest_audit_activity=latest_audits,
        recent_cases=recent_cases,
    )


@router.get("/cases", response_model=CaseListResponse)
async def list_cases(
    source: str | None = Query(None),
    state: str | None = Query(None),
    policy_decision: str | None = Query(None),
    diagnosis_category: str | None = Query(None),
    ros_band: str | None = Query(None),
    link_status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> CaseListResponse:
    """List recovery cases with rich filters for operator inspection."""
    if source == "SYNTHETIC_EVALUATION":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SYNTHETIC_EVALUATION source cannot be queried via operational case APIs.",
        )

    stmt = (
        select(RecoveryCaseModel)
        .options(
            selectinload(RecoveryCaseModel.order),
            selectinload(RecoveryCaseModel.policy_evaluations),
            selectinload(RecoveryCaseModel.decision_traces),
            selectinload(RecoveryCaseModel.recovery_actions).selectinload(
                RecoveryActionModel.payment_link
            ),
        )
        .order_by(desc(RecoveryCaseModel.created_at))
    )

    if source:
        stmt = stmt.where(RecoveryCaseModel.source == source)
    else:
        stmt = stmt.where(RecoveryCaseModel.source != "SYNTHETIC_EVALUATION")

    if state:
        stmt = stmt.where(RecoveryCaseModel.state == state)

    result = await session.execute(stmt)
    all_matched = result.scalars().all()

    # Load customers for masking
    cust_ids = [c.customer_id for c in all_matched if c.customer_id]
    cust_map: dict[str, CustomerModel] = {}
    if cust_ids:
        c_res = await session.execute(
            select(CustomerModel).where(CustomerModel.customer_id.in_(cust_ids))
        )
        for cust in c_res.scalars().all():
            cust_map[cust.customer_id] = cust

    # Apply in-memory filters for nested models
    filtered_items: list[CaseSummaryDTO] = []
    for c in all_matched:
        latest_eval = c.policy_evaluations[-1] if c.policy_evaluations else None
        latest_trace = c.decision_traces[-1] if c.decision_traces else None

        # Determine link status and masked link identity
        curr_link_status = None
        masked_pl_id = None
        masked_ref_id = None
        for act in c.recovery_actions:
            if act.payment_link:
                curr_link_status = act.payment_link.status
                masked_pl_id = (
                    f"plink_***{act.payment_link.provider_link_id[-4:]}"
                    if act.payment_link.provider_link_id
                    else None
                )
                masked_ref_id = (
                    f"ref_***{act.payment_link.reference_id[-4:]}"
                    if act.payment_link.reference_id
                    else None
                )
                break

        # Filter by policy decision
        if policy_decision and (not latest_eval or latest_eval.decision_type != policy_decision):
            continue

        # Filter by diagnosis category
        if diagnosis_category and (
            not latest_trace or latest_trace.diagnosis_category != diagnosis_category
        ):
            continue

        # Filter by link status
        if link_status and curr_link_status != link_status:
            continue

        # Filter by ROS band
        ros_sc = latest_trace.ros_score if latest_trace else None
        curr_ros_band = None
        if ros_sc is not None:
            if ros_sc < 35:
                curr_ros_band = "LOW"
            elif ros_sc <= 65:
                curr_ros_band = "MEDIUM"
            else:
                curr_ros_band = "HIGH"

        if ros_band and curr_ros_band != ros_band:
            continue

        cust_obj = cust_map.get(c.customer_id) if c.customer_id else None

        filtered_items.append(
            CaseSummaryDTO(
                case_id=c.case_id,
                source=c.source,
                order_id=c.order_id,
                amount_paise=c.order.amount_paise if c.order else 0,
                currency=c.order.currency if c.order else "INR",
                masked_customer_phone=cust_obj.masked_phone if cust_obj else None,
                masked_customer_email=cust_obj.masked_email if cust_obj else None,
                state=c.state,
                closure_reason=c.closure_reason,
                policy_decision=latest_eval.decision_type if latest_eval else None,
                ros_score=ros_sc,
                ros_band=curr_ros_band,
                diagnosis_category=(latest_trace.diagnosis_category if latest_trace else None),
                selected_action=latest_trace.selected_action if latest_trace else None,
                link_status=curr_link_status,
                masked_link_id=masked_pl_id,
                masked_reference_id=masked_ref_id,
                contact_count=c.contact_count,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )

    total_count = len(filtered_items)
    paginated_items = filtered_items[offset : offset + limit]

    return CaseListResponse(
        items=paginated_items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get("/cases/{case_id}", response_model=CaseDetailDTO)
async def get_case_detail(
    case_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> CaseDetailDTO:
    """Retrieve full chronological investigation detail for a single recovery case."""
    stmt = (
        select(RecoveryCaseModel)
        .options(
            selectinload(RecoveryCaseModel.order).selectinload(OrderModel.payment_attempts),
            selectinload(RecoveryCaseModel.policy_evaluations),
            selectinload(RecoveryCaseModel.decision_traces),
            selectinload(RecoveryCaseModel.audit_events),
            selectinload(RecoveryCaseModel.recovery_actions).selectinload(
                RecoveryActionModel.payment_link
            ),
            selectinload(RecoveryCaseModel.recovery_actions).selectinload(
                RecoveryActionModel.notifications
            ),
            selectinload(RecoveryCaseModel.recovery_actions).selectinload(
                RecoveryActionModel.budget_reservation
            ),
        )
        .where(RecoveryCaseModel.case_id == case_id)
    )

    case_model = (await session.execute(stmt)).scalar_one_or_none()
    if case_model is None or case_model.source == "SYNTHETIC_EVALUATION":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery case '{case_id}' not found.",
        )

    # Fetch customer & consent
    cust_data: dict[str, Any] = {"customer_id": "unknown", "consents": {}}
    if case_model.customer_id:
        c_res = await session.execute(
            select(CustomerModel)
            .options(selectinload(CustomerModel.consents))
            .where(CustomerModel.customer_id == case_model.customer_id)
        )
        cust_obj = c_res.scalar_one_or_none()
        if cust_obj:
            cust_data = {
                "customer_id": cust_obj.customer_id,
                "masked_phone": cust_obj.masked_phone,
                "masked_email": cust_obj.masked_email,
                "successful_purchase_count": cust_obj.successful_purchase_count,
                "consents": {con.channel: con.status for con in cust_obj.consents},
            }

    # Fetch failed attempt
    failed_attempt_data: dict[str, Any] = {}
    if case_model.order and case_model.order.payment_attempts:
        for att in case_model.order.payment_attempts:
            if att.payment_id == case_model.failed_attempt_id:
                failed_attempt_data = {
                    "payment_id": att.payment_id,
                    "amount_paise": att.amount_paise,
                    "currency": att.currency,
                    "status": att.status,
                    "method": att.method,
                    "error_code": att.error_code,
                    "error_description": att.error_description,
                    "error_source": att.error_source,
                    "error_step": att.error_step,
                    "error_reason": att.error_reason,
                    "occurred_at": att.occurred_at,
                }
                break

    # Build chronological timeline
    timeline: list[TimelineEventDTO] = []
    step = 1

    # Step 1: Payment Failed Event Received
    timeline.append(
        TimelineEventDTO(
            step_number=step,
            title="Payment Failed Event Ingested",
            status="info",
            timestamp=case_model.created_at,
            description=(
                f"Received failed payment {case_model.failed_attempt_id} "
                f"for order {case_model.order_id}."
            ),
            metadata={
                "error_code": failed_attempt_data.get("error_code"),
                "method": failed_attempt_data.get("method"),
            },
        )
    )
    step += 1

    # Step 2: Policy Evaluation
    latest_eval = case_model.policy_evaluations[-1] if case_model.policy_evaluations else None
    policy_eval_data = None
    if latest_eval:
        policy_eval_data = {
            "evaluation_id": latest_eval.evaluation_id,
            "policy_version": latest_eval.policy_version,
            "decision_type": latest_eval.decision_type,
            "reasons": latest_eval.reasons,
            "evaluated_at": latest_eval.evaluated_at,
        }
        dec_status = (
            "success"
            if latest_eval.decision_type == "ELIGIBLE"
            else "warning"
            if latest_eval.decision_type == "DEFER"
            else "error"
        )
        reasons_str = ", ".join(latest_eval.reasons) or "None"
        timeline.append(
            TimelineEventDTO(
                step_number=step,
                title=f"Deterministic Policy: {latest_eval.decision_type}",
                status=dec_status,
                timestamp=latest_eval.evaluated_at,
                description=(
                    f"Evaluated against rules version {latest_eval.policy_version}. "
                    f"Reasons: {reasons_str}"
                ),
                metadata={"reasons": latest_eval.reasons},
            )
        )
        step += 1

    # Step 3: Decision Trace (Diagnosis + ROS + Candidates + Recommendation)
    latest_trace = case_model.decision_traces[-1] if case_model.decision_traces else None
    decision_trace_data = None
    if latest_trace:
        decision_trace_data = {
            "trace_id": latest_trace.trace_id,
            "policy_decision": latest_trace.policy_decision,
            "ros_score": latest_trace.ros_score,
            "ros_contributions": latest_trace.ros_contributions,
            "diagnosis_category": latest_trace.diagnosis_category,
            "diagnosis_confidence": latest_trace.diagnosis_confidence,
            "diagnosis_mode": latest_trace.diagnosis_mode,
            "diagnosis_fallback_used": latest_trace.diagnosis_fallback_used,
            "action_candidates": latest_trace.action_candidates,
            "selected_action": latest_trace.selected_action,
            "utility_paise": latest_trace.utility_paise,
            "created_at": latest_trace.created_at,
        }
        conf_pct = latest_trace.diagnosis_confidence * 100
        timeline.append(
            TimelineEventDTO(
                step_number=step,
                title=f"Failure Diagnosed: {latest_trace.diagnosis_category}",
                status="info",
                timestamp=latest_trace.created_at,
                description=(
                    f"Mode: {latest_trace.diagnosis_mode}, Confidence: {conf_pct:.1f}%. "
                    f"ROS Score: {latest_trace.ros_score}/100."
                ),
                metadata={"ros_contributions": latest_trace.ros_contributions},
            )
        )
        step += 1

        cand_len = len(latest_trace.action_candidates)
        timeline.append(
            TimelineEventDTO(
                step_number=step,
                title=f"Advisory Selected: {latest_trace.selected_action}",
                status="success",
                timestamp=latest_trace.created_at,
                description=(
                    f"Selected from {cand_len} candidates based on simulation utility ranking."
                ),
                metadata={"candidates": latest_trace.action_candidates},
            )
        )
        step += 1

    # Step 4: Execution / Link / Notification
    action_data = None
    link_data = None
    notifs_data: list[dict[str, Any]] = []
    budget_data = None

    if case_model.recovery_actions:
        act = case_model.recovery_actions[-1]
        action_data = {
            "action_id": act.action_id,
            "action_type": act.action_type,
            "status": act.status,
            "created_at": act.created_at,
        }

        if act.budget_reservation:
            b_res = act.budget_reservation
            budget_data = {
                "reservation_id": b_res.reservation_id,
                "amount_paise": b_res.amount_paise,
                "reservation_date": b_res.reservation_date,
                "status": b_res.status,
            }
            res_amt = b_res.amount_paise / 100
            timeline.append(
                TimelineEventDTO(
                    step_number=step,
                    title="Budget Reserved",
                    status="success",
                    timestamp=b_res.created_at,
                    description=f"Reserved ₹{res_amt:,.2f} under operational daily guardrails.",
                    metadata=budget_data,
                )
            )
            step += 1

        if act.payment_link:
            pl = act.payment_link
            link_data = {
                "link_id": pl.link_id,
                "provider_link_id": pl.provider_link_id,
                "reference_id": pl.reference_id,
                "short_url": pl.short_url,
                "amount_paise": pl.amount_paise,
                "currency": pl.currency,
                "status": pl.status,
                "expire_by": pl.expire_by,
            }
            timeline.append(
                TimelineEventDTO(
                    step_number=step,
                    title=f"Payment Link Created ({pl.status.upper()})",
                    status="success",
                    timestamp=pl.created_at,
                    description=f"Created attributable Test Mode link {pl.provider_link_id}.",
                    metadata={
                        "short_url": pl.short_url,
                        "reference_id": pl.reference_id,
                    },
                )
            )
            step += 1

        for n in act.notifications:
            notif_item = {
                "notification_id": n.notification_id,
                "channel": n.channel,
                "template_key": n.template_key,
                "masked_recipient": n.masked_recipient,
                "link_reference": n.link_reference,
                "status": n.status,
                "simulated_at": n.simulated_at,
            }
            notifs_data.append(notif_item)
            timeline.append(
                TimelineEventDTO(
                    step_number=step,
                    title=f"Notification Dispatched ({n.channel})",
                    status="success",
                    timestamp=n.simulated_at,
                    description=(
                        f"Simulated message sent to {n.masked_recipient} "
                        f"with template {n.template_key}."
                    ),
                    metadata=notif_item,
                )
            )
            step += 1

    # Step 5: Terminal / Current State
    curr_status = (
        "success"
        if case_model.state == RecoveryCaseState.RECOVERED.value
        else "warning"
        if case_model.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value
        else "info"
        if case_model.closed_at is None
        else "error"
    )
    closure_str = case_model.closure_reason or "None"
    timeline.append(
        TimelineEventDTO(
            step_number=step,
            title=f"Current State: {case_model.state}",
            status=curr_status,
            timestamp=case_model.updated_at,
            description=f"Case status is {case_model.state}. Closure reason: {closure_str}.",
            metadata={"closure_reason": case_model.closure_reason},
        )
    )

    # Sanitize audit events
    audit_list = [map_sanitized_audit_event(a) for a in case_model.audit_events]

    return CaseDetailDTO(
        case_id=case_model.case_id,
        source=case_model.source,
        order_id=case_model.order_id,
        state=case_model.state,
        closure_reason=case_model.closure_reason,
        contact_count=case_model.contact_count,
        created_at=case_model.created_at,
        updated_at=case_model.updated_at,
        customer=cust_data,
        order={
            "order_id": case_model.order.order_id if case_model.order else "",
            "amount_paise": (case_model.order.amount_paise if case_model.order else 0),
            "currency": case_model.order.currency if case_model.order else "INR",
            "status": case_model.order.status if case_model.order else "",
        },
        payment_attempt=failed_attempt_data,
        policy_evaluation=policy_eval_data,
        decision_trace=decision_trace_data,
        recovery_action=action_data,
        payment_link=link_data,
        notifications=notifs_data,
        budget_reservation=budget_data,
        timeline=timeline,
        audit_events=audit_list,
    )


@router.get("/evaluation", response_model=dict[str, Any])
async def get_evaluation_report(
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Retrieve aggregate-only offline counterfactual evaluation report."""
    if settings.RETRYPAY_ENV not in ("test", "demo"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluation dashboard is restricted to test and demo environments.",
        )

    import json
    from pathlib import Path

    report_path = Path("data/evaluation_report.json")
    if report_path.exists():
        with open(report_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data

    # Default baseline aggregate representation if file not yet pre-generated
    return {
        "evaluation_run_id": "eval_run_demo_1000",
        "cohort_id": "cohort_42_1000",
        "sample_size": 1000,
        "scenario_seed": 42,
        "assignment_seed": 100,
        "generator_version": "synth-gen-v1.0",
        "policy_version": "recovery-v1.3",
        "ros_version": "ros-v1.0",
        "estimator_version": "sim-estimator-v1",
        "disclaimer": "simulated offline estimate; not production conversion evidence",
        "natural_recovery_rate": 0.1557,
        "estimated_incremental_recovery_conversion": 0.0455,
        "ci_incremental_conversion": {"lower": -0.0114, "upper": 0.1084},
        "estimated_incremental_recovery_gmv_paise": 6853314,
        "ci_incremental_gmv_paise": {"lower": -6061613, "upper": 19193727},
        "contact_efficiency_paise_per_contact": 357670,
        "incremental_gmv_per_contact_paise": 69225,
        "policy_safety_metrics": {
            "policy_block_rate": 0.201,
            "defer_rate": 0.052,
            "manual_review_rate": 0.031,
            "unsafe_action_rate": 0.0,
        },
        "arm_metrics": {},
        "decision_distribution": {},
        "diagnosis_distribution": {},
    }


@router.get("/settings", response_model=SettingsDTO)
async def get_settings_summary(
    settings: Settings = Depends(get_settings),
) -> SettingsDTO:
    """Retrieve read-only merchant policy configurations and operational guardrails."""
    policy_cfg = MerchantPolicyConfig()
    return SettingsDTO(
        environment=settings.RETRYPAY_ENV.value
        if hasattr(settings.RETRYPAY_ENV, "value")
        else str(settings.RETRYPAY_ENV),
        policy_version=policy_cfg.policy_version,
        quiet_hours={
            "enabled": True,
            "start_hour": policy_cfg.quiet_hours_start,
            "end_hour": policy_cfg.quiet_hours_end,
            "timezone": policy_cfg.merchant_timezone,
        },
        contact_caps={
            "max_contacts_per_order": policy_cfg.max_messages_per_order,
            "max_contacts_per_customer_30d": policy_cfg.max_messages_per_customer_30d,
        },
        guardrails={
            "single_action_limit_paise": 1_000_000,
            "daily_gmv_cap_paise": 5_000_000,
            "daily_action_cap": 200,
            "daily_contact_cap": 200,
            "max_manual_review_queue_depth": 25,
        },
        attribution_reconciliation_window_minutes=settings.RETRYPAY_ATTRIBUTION_RECONCILIATION_WINDOW_MINUTES,
        llm_enabled=settings.LLM_ENABLED,
        llm_model=settings.LLM_MODEL,
        mapper_version="razorpay-error-map-v1",
        ros_version="ros-v1.0",
        estimator_version="sim-estimator-v1",
    )


class ReminderPreviewRequestDTO(BaseModel):
    """Request payload for previewing a recovery case reminder."""

    model_config = ConfigDict(frozen=True)

    medium: str = Field(..., description="Notification medium: 'sms' or 'email'")


class ReminderPreviewDTO(BaseModel):
    """Response payload containing preview metadata and short-lived confirmation token."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    eligible: bool
    blocking_reasons: list[str]
    preview_token: str | None = None
    expires_at: datetime | None = None
    selected_medium: str
    masked_recipient: str | None = None
    provider_link_id: str | None = None
    policy_version: str


class ReminderSendRequestDTO(BaseModel):
    """Request payload for executing a confirmed case reminder dispatch."""

    model_config = ConfigDict(frozen=True)

    preview_token: str = Field(
        ..., description="Short-lived, single-use confirmation token from /preview"
    )
    medium: str = Field(..., description="Selected notification medium: 'sms' or 'email'")


class ReminderSendResponseDTO(BaseModel):
    """Response payload for reminder dispatch execution."""

    model_config = ConfigDict(frozen=True)

    status: str
    case_id: str
    medium: str
    provider_link_id: str
    provider_notification_id: str | None = None
    request_id: str | None = None
    sent_at: datetime


class ReminderDeliveryStatusUpdateDTO(BaseModel):
    """Payload for updating reminder delivery status from verified events."""

    model_config = ConfigDict(frozen=True)

    notification_id: str = Field(..., description="Internal notification ID")
    delivery_status: str = Field(..., description="'DELIVERED' or 'UNDELIVERABLE'")
    provider_event_id: str | None = Field(
        default=None, description="Optional provider webhook event ID"
    )


def get_contact_fingerprint(phone: str | None, email: str | None) -> str:
    """Generate a non-sensitive SHA-256 fingerprint for contact data binding without PII."""
    raw = f"phone:{phone or ''}|email:{email or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@router.post("/cases/{case_id}/reminder/preview", response_model=ReminderPreviewDTO)
async def preview_case_reminder(
    case_id: str,
    req: ReminderPreviewRequestDTO,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None, alias="X-Dashboard-Authorization"),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> ReminderPreviewDTO:
    """Generate a short-lived, single-use confirmation token for a recovery case reminder."""
    corr_id = correlation_id or f"req_{uuid.uuid4().hex[:10]}"
    if req.medium not in ("sms", "email"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported notification medium '{req.medium}'. "
                "Only 'sms' and 'email' are supported."
            ),
        )

    stmt = (
        select(RecoveryCaseModel)
        .options(
            selectinload(RecoveryCaseModel.policy_evaluations),
            selectinload(RecoveryCaseModel.recovery_actions).selectinload(
                RecoveryActionModel.payment_link
            ),
        )
        .where(RecoveryCaseModel.case_id == case_id)
    )
    case_model = (await session.execute(stmt)).scalar_one_or_none()
    if not case_model or case_model.source == "SYNTHETIC_EVALUATION":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery case '{case_id}' not found.",
        )

    blocking_reasons: list[str] = []

    # 1. Check Policy & Case State
    latest_eval = case_model.policy_evaluations[-1] if case_model.policy_evaluations else None
    policy_version = latest_eval.policy_version if latest_eval else settings.RETRYPAY_POLICY_VERSION

    if case_model.state == RecoveryCaseState.MANUAL_REVIEW.value or (
        latest_eval and latest_eval.decision_type in ("BLOCK", "MANUAL_REVIEW")
    ):
        if "INSUFFICIENT_CONTEXT" not in blocking_reasons:
            blocking_reasons.append("INSUFFICIENT_CONTEXT")

    # 2. Check Customer Contact & Consent
    masked_recipient: str | None = None
    cust_obj = None
    if case_model.customer_id:
        c_res = await session.execute(
            select(CustomerModel)
            .options(selectinload(CustomerModel.consents))
            .where(CustomerModel.customer_id == case_model.customer_id)
        )
        cust_obj = c_res.scalar_one_or_none()
        if cust_obj:
            consents_map = {con.channel.upper(): con.status for con in cust_obj.consents}
            req_channel = "SMS" if req.medium == "sms" else "EMAIL"
            channel_consent = consents_map.get(req_channel, "UNKNOWN")

            if req.medium == "sms":
                masked_recipient = cust_obj.masked_phone
            else:
                masked_recipient = cust_obj.masked_email

            if channel_consent != "OPTED_IN" or not masked_recipient:
                if "CONTACT_CONSENT_MISSING" not in blocking_reasons:
                    blocking_reasons.append("CONTACT_CONSENT_MISSING")
        else:
            if "CONTACT_CONSENT_MISSING" not in blocking_reasons:
                blocking_reasons.append("CONTACT_CONSENT_MISSING")
    else:
        if "CONTACT_CONSENT_MISSING" not in blocking_reasons:
            blocking_reasons.append("CONTACT_CONSENT_MISSING")

    # 3. Check Payment Link
    provider_link_id: str | None = None
    now = datetime.now(UTC)
    for act in case_model.recovery_actions:
        if act.payment_link and act.payment_link.status == PaymentLinkStatus.CREATED.value:
            exp_by = act.payment_link.expire_by
            if exp_by.tzinfo is None:
                exp_by = exp_by.replace(tzinfo=UTC)
            if exp_by > now:
                provider_link_id = act.payment_link.provider_link_id
                break

    if not provider_link_id:
        if "PAYMENT_LINK_NOT_CREATED" not in blocking_reasons:
            blocking_reasons.append("PAYMENT_LINK_NOT_CREATED")

    # If case is MANUAL_REVIEW, ensure ALL applicable exact blocking reasons are listed
    if case_model.state == RecoveryCaseState.MANUAL_REVIEW.value:
        for exact_code in (
            "CONTACT_CONSENT_MISSING",
            "INSUFFICIENT_CONTEXT",
            "PAYMENT_LINK_NOT_CREATED",
        ):
            if exact_code not in blocking_reasons:
                blocking_reasons.append(exact_code)
        blocking_reasons = sorted(blocking_reasons)

        audit_evt = AuditEventModel(
            event_id=f"evt_prev_{uuid.uuid4().hex[:12]}",
            source=case_model.source,
            case_id=case_id,
            event_type=AuditEventType.REMINDER_PREVIEWED.value,
            actor_type=ActorType.MERCHANT_OPERATOR.value,
            before_state=case_model.state,
            after_state=case_model.state,
            sanitized_metadata={
                "medium": req.medium,
                "eligible": False,
                "blocking_reasons": blocking_reasons,
                "correlation_id": corr_id,
                "policy_version": policy_version,
            },
            timestamp=now,
        )
        session.add(audit_evt)
        await session.commit()

        return ReminderPreviewDTO(
            case_id=case_id,
            eligible=False,
            blocking_reasons=blocking_reasons,
            preview_token=None,
            expires_at=None,
            selected_medium=req.medium,
            masked_recipient=masked_recipient,
            provider_link_id=provider_link_id,
            policy_version=policy_version,
        )

    if blocking_reasons:
        audit_evt = AuditEventModel(
            event_id=f"evt_prev_{uuid.uuid4().hex[:12]}",
            source=case_model.source,
            case_id=case_id,
            event_type=AuditEventType.REMINDER_PREVIEWED.value,
            actor_type=ActorType.MERCHANT_OPERATOR.value,
            before_state=case_model.state,
            after_state=case_model.state,
            sanitized_metadata={
                "medium": req.medium,
                "eligible": False,
                "blocking_reasons": sorted(blocking_reasons),
                "correlation_id": corr_id,
                "policy_version": policy_version,
            },
            timestamp=now,
        )
        session.add(audit_evt)
        await session.commit()

        return ReminderPreviewDTO(
            case_id=case_id,
            eligible=False,
            blocking_reasons=sorted(blocking_reasons),
            preview_token=None,
            expires_at=None,
            selected_medium=req.medium,
            masked_recipient=masked_recipient,
            provider_link_id=provider_link_id,
            policy_version=policy_version,
        )

    # Eligible preview: Generate short-lived persistent single-use token
    preview_token = f"remtok_{uuid.uuid4().hex}"
    expires_at = now + timedelta(minutes=5)
    fingerprint = get_contact_fingerprint(
        cust_obj.masked_phone if cust_obj else None, cust_obj.masked_email if cust_obj else None
    )

    token_model = ReminderTokenModel(
        token_id=preview_token,
        case_id=case_id,
        medium=req.medium,
        policy_version=policy_version,
        contact_fingerprint=fingerprint,
        provider_link_id=provider_link_id or "",
        status="ACTIVE",
        expires_at=expires_at,
        created_at=now,
    )
    session.add(token_model)

    audit_evt = AuditEventModel(
        event_id=f"evt_prev_{uuid.uuid4().hex[:12]}",
        source=case_model.source,
        case_id=case_id,
        event_type=AuditEventType.REMINDER_PREVIEWED.value,
        actor_type=ActorType.MERCHANT_OPERATOR.value,
        before_state=case_model.state,
        after_state=case_model.state,
        sanitized_metadata={
            "medium": req.medium,
            "eligible": True,
            "provider_link_id": provider_link_id,
            "correlation_id": corr_id,
            "expires_at": expires_at.isoformat(),
            "policy_version": policy_version,
        },
        timestamp=now,
    )
    session.add(audit_evt)
    await session.commit()

    return ReminderPreviewDTO(
        case_id=case_id,
        eligible=True,
        blocking_reasons=[],
        preview_token=preview_token,
        expires_at=expires_at,
        selected_medium=req.medium,
        masked_recipient=masked_recipient,
        provider_link_id=provider_link_id,
        policy_version=policy_version,
    )


@router.post("/cases/{case_id}/reminder/send", response_model=ReminderSendResponseDTO)
async def send_case_reminder(
    case_id: str,
    req: ReminderSendRequestDTO,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None, alias="X-Dashboard-Authorization"),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> ReminderSendResponseDTO:
    """Execute a confirmed reminder dispatch using a short-lived single-use confirmation token."""
    corr_id = correlation_id or f"req_{uuid.uuid4().hex[:10]}"
    now = datetime.now(UTC)

    # 1. Atomic Single-Use Token Claim (SQLite-safe atomic UPDATE)
    upd_stmt = (
        update(ReminderTokenModel)
        .where(
            ReminderTokenModel.token_id == req.preview_token,
            ReminderTokenModel.case_id == case_id,
            ReminderTokenModel.medium == req.medium,
            ReminderTokenModel.status == "ACTIVE",
            ReminderTokenModel.expires_at > now,
        )
        .values(status="USED", used_at=now)
    )
    upd_res = await session.execute(upd_stmt)
    if getattr(upd_res, "rowcount", 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, reused, or mismatched confirmation token.",
        )

    fetch_stmt = select(ReminderTokenModel).where(ReminderTokenModel.token_id == req.preview_token)
    token_obj = (await session.execute(fetch_stmt)).scalar_one()

    # 2. Fetch case with relationships
    c_stmt = (
        select(RecoveryCaseModel)
        .options(
            selectinload(RecoveryCaseModel.policy_evaluations),
            selectinload(RecoveryCaseModel.recovery_actions).selectinload(
                RecoveryActionModel.payment_link
            ),
        )
        .where(RecoveryCaseModel.case_id == case_id)
    )
    case_model = (await session.execute(c_stmt)).scalar_one_or_none()
    if not case_model or case_model.source == "SYNTHETIC_EVALUATION":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery case '{case_id}' not found.",
        )

    # 3. Pre-send Safeguard Validations
    if case_model.state == RecoveryCaseState.MANUAL_REVIEW.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reminders are strictly disabled for MANUAL_REVIEW cases.",
        )

    latest_eval = case_model.policy_evaluations[-1] if case_model.policy_evaluations else None
    if latest_eval and latest_eval.decision_type in ("BLOCK", "MANUAL_REVIEW"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Policy decision '{latest_eval.decision_type}' prohibits outreach.",
        )

    # Check active Payment Link match
    matched_link = None
    for act in case_model.recovery_actions:
        if act.payment_link and act.payment_link.provider_link_id == token_obj.provider_link_id:
            exp_by = act.payment_link.expire_by
            if exp_by.tzinfo is None:
                exp_by = exp_by.replace(tzinfo=UTC)
            if act.payment_link.status == PaymentLinkStatus.CREATED.value and exp_by > now:
                matched_link = act.payment_link
                break

    if not matched_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment Link is invalid, expired, or missing for this case.",
        )

    # Check Customer & Consent
    if not case_model.customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer contact data missing.",
        )

    c_res = await session.execute(
        select(CustomerModel)
        .options(selectinload(CustomerModel.consents))
        .where(CustomerModel.customer_id == case_model.customer_id)
    )
    cust_obj = c_res.scalar_one_or_none()
    if not cust_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer record not found.",
        )

    consents_map = {con.channel.upper(): con.status for con in cust_obj.consents}
    req_channel = "SMS" if req.medium == "sms" else "EMAIL"
    if consents_map.get(req_channel) != "OPTED_IN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Customer has not OPTED_IN for channel '{req_channel}'.",
        )

    # Verify contact fingerprint match
    current_fp = get_contact_fingerprint(cust_obj.masked_phone, cust_obj.masked_email)
    if current_fp != token_obj.contact_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer contact details changed since confirmation token was generated.",
        )

    # 4. Duplicate Send & Retry Policy Check
    sent_stmt = select(OutreachNotificationLogModel).where(
        OutreachNotificationLogModel.case_id == case_id,
        OutreachNotificationLogModel.medium == req.medium,
        OutreachNotificationLogModel.notification_type == "REMINDER",
        OutreachNotificationLogModel.status.in_(["SENT", "DELIVERED"]),
    )
    existing_sent = (await session.execute(sent_stmt)).scalars().all()
    if existing_sent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Duplicate send rejected: A reminder via {req.medium} "
                "has already been sent for this case."
            ),
        )

    attempt_stmt = select(func.count(OutreachNotificationLogModel.notification_id)).where(
        OutreachNotificationLogModel.case_id == case_id,
        OutreachNotificationLogModel.medium == req.medium,
        OutreachNotificationLogModel.notification_type == "REMINDER",
    )
    attempts_count = (await session.execute(attempt_stmt)).scalar() or 0
    if attempts_count >= 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Maximum reminder dispatch attempts ({attempts_count}) "
                f"reached for medium '{req.medium}'."
            ),
        )
    attempt_number = attempts_count + 1

    # 5. Record REMINDER_APPROVED audit event BEFORE provider call
    appr_evt = AuditEventModel(
        event_id=f"evt_appr_{uuid.uuid4().hex[:12]}",
        source=case_model.source,
        case_id=case_id,
        event_type=AuditEventType.REMINDER_APPROVED.value,
        actor_type=ActorType.MERCHANT_OPERATOR.value,
        before_state=case_model.state,
        after_state=case_model.state,
        sanitized_metadata={
            "medium": req.medium,
            "provider_link_id": token_obj.provider_link_id,
            "correlation_id": corr_id,
            "attempt_number": attempt_number,
        },
        timestamp=now,
    )
    session.add(appr_evt)
    await session.flush()

    # 6. Select Provider Adapter
    if (
        case_model.source == "RAZORPAY_TEST_MODE"
        and settings.RAZORPAY_PROVIDER_ENABLED
        and not settings.RAZORPAY_KEY_ID.startswith("rzp_test_fixture")
    ):
        provider: Any = RazorpayPaymentLinkProvider(settings)
    else:
        provider = FakePaymentLinkProvider()

    # 7. Dispatch Provider Notification
    notif_id = f"notif_{uuid.uuid4().hex[:12]}"
    try:
        res = await provider.send_notification(token_obj.provider_link_id, req.medium)
    except Exception as exc:
        fail_log = OutreachNotificationLogModel(
            notification_id=notif_id,
            case_id=case_id,
            medium=req.medium,
            notification_type="REMINDER",
            provider_link_id=token_obj.provider_link_id,
            status="FAILED",
            attempt_number=attempt_number,
            error_code="PROVIDER_ERROR",
            error_message="Transport error during provider notification dispatch.",
            created_at=now,
            updated_at=now,
        )
        session.add(fail_log)

        fail_evt = AuditEventModel(
            event_id=f"evt_fail_{uuid.uuid4().hex[:12]}",
            source=case_model.source,
            case_id=case_id,
            event_type=AuditEventType.REMINDER_FAILED.value,
            actor_type=ActorType.SYSTEM.value,
            before_state=case_model.state,
            after_state=case_model.state,
            sanitized_metadata={
                "medium": req.medium,
                "provider_link_id": token_obj.provider_link_id,
                "correlation_id": corr_id,
                "error_code": "PROVIDER_ERROR",
            },
            timestamp=datetime.now(UTC),
        )
        session.add(fail_evt)
        await session.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Provider notification dispatch failed: {exc}",
        ) from exc

    if res.status != NotificationStatus.ACCEPTED:
        fail_log = OutreachNotificationLogModel(
            notification_id=notif_id,
            case_id=case_id,
            medium=req.medium,
            notification_type="REMINDER",
            provider_link_id=token_obj.provider_link_id,
            status="FAILED",
            attempt_number=attempt_number,
            error_code=res.error_code or "REJECTED",
            error_message=res.error_message or "Provider rejected reminder dispatch request.",
            created_at=now,
            updated_at=now,
        )
        session.add(fail_log)

        fail_evt = AuditEventModel(
            event_id=f"evt_fail_{uuid.uuid4().hex[:12]}",
            source=case_model.source,
            case_id=case_id,
            event_type=AuditEventType.REMINDER_FAILED.value,
            actor_type=ActorType.SYSTEM.value,
            before_state=case_model.state,
            after_state=case_model.state,
            sanitized_metadata={
                "medium": req.medium,
                "provider_link_id": token_obj.provider_link_id,
                "correlation_id": corr_id,
                "error_code": res.error_code,
            },
            timestamp=datetime.now(UTC),
        )
        session.add(fail_evt)
        await session.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider rejected reminder dispatch: {res.error_message}",
        )

    # Success: Save SENT notification log, update case contact count
    sent_log = OutreachNotificationLogModel(
        notification_id=notif_id,
        case_id=case_id,
        medium=req.medium,
        notification_type="REMINDER",
        provider_link_id=token_obj.provider_link_id,
        provider_notification_id=res.provider_notification_id,
        status="SENT",
        attempt_number=attempt_number,
        created_at=now,
        updated_at=now,
    )
    session.add(sent_log)

    case_model.contact_count += 1
    case_model.updated_at = now

    sent_evt = AuditEventModel(
        event_id=f"evt_sent_{uuid.uuid4().hex[:12]}",
        source=case_model.source,
        case_id=case_id,
        event_type=AuditEventType.REMINDER_SENT.value,
        actor_type=ActorType.SYSTEM.value,
        before_state=case_model.state,
        after_state=case_model.state,
        sanitized_metadata={
            "medium": req.medium,
            "provider_link_id": token_obj.provider_link_id,
            "provider_notification_id": res.provider_notification_id,
            "request_id": res.request_id,
            "correlation_id": corr_id,
        },
        timestamp=now,
    )
    session.add(sent_evt)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Concurrent notification send in progress or duplicate attempt rejected.",
        ) from None

    return ReminderSendResponseDTO(
        status="SENT",
        case_id=case_id,
        medium=req.medium,
        provider_link_id=token_obj.provider_link_id,
        provider_notification_id=res.provider_notification_id,
        request_id=res.request_id,
        sent_at=now,
    )


@router.post("/cases/{case_id}/reminder/delivery-status")
async def update_reminder_delivery_status(
    case_id: str,
    request: Request,
    req: ReminderDeliveryStatusUpdateDTO,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    provider_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> dict[str, Any]:
    """Ingest verified provider delivery status updates with auth & replay protection."""
    corr_id = correlation_id or f"req_{uuid.uuid4().hex[:10]}"
    now = datetime.now(UTC)

    # 1. Verified Provider Signature Authentication
    raw_body = await request.body()
    sig = (
        provider_signature
        or request.headers.get("x-razorpay-signature")
        or request.headers.get("X-Razorpay-Signature")
    )
    verifier = WebhookVerifier(settings.RAZORPAY_WEBHOOK_SECRET)
    verify_res = verifier.verify(raw_body=raw_body, received_signature=sig)
    if not verify_res.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Razorpay-Signature provider signature.",
        )

    # 2. Require non-empty provider_event_id
    if not req.provider_event_id or not req.provider_event_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required non-empty 'provider_event_id'.",
        )
    clean_provider_event_id = req.provider_event_id.strip()

    # 3. Provider Notification Correlation (matches notification_id OR provider_notification_id)
    stmt = select(OutreachNotificationLogModel).where(
        (OutreachNotificationLogModel.notification_id == req.notification_id)
        | (OutreachNotificationLogModel.provider_notification_id == req.notification_id),
        OutreachNotificationLogModel.case_id == case_id,
    )
    notif_obj = (await session.execute(stmt)).scalar_one_or_none()
    if not notif_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification record '{req.notification_id}' not found for case '{case_id}'.",
        )

    if req.delivery_status not in ("DELIVERED", "UNDELIVERABLE"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid delivery status '{req.delivery_status}'. "
                "Expected 'DELIVERED' or 'UNDELIVERABLE'."
            ),
        )

    # 4. Replay Protection & Idempotency Check
    existing_evt = (
        await session.execute(
            select(AuditEventModel).where(
                AuditEventModel.provider_event_id == clean_provider_event_id
            )
        )
    ).scalar_one_or_none()
    if existing_evt:
        return {
            "status": "ignored",
            "message": (f"Provider delivery event '{clean_provider_event_id}' already processed."),
        }

    # 5. Delivery State Transition Guard
    if notif_obj.status == req.delivery_status:
        return {"status": "ignored", "message": "Delivery status already updated."}

    if notif_obj.status in ("DELIVERED", "UNDELIVERABLE"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid delivery status transition: cannot transition from terminal status "
                f"'{notif_obj.status}' to '{req.delivery_status}'."
            ),
        )

    # 6. Atomic Delivery Status Update & Audit Emission
    before_status = notif_obj.status
    notif_obj.status = req.delivery_status
    notif_obj.updated_at = now

    deliv_evt = AuditEventModel(
        event_id=f"evt_deliv_{uuid.uuid4().hex[:12]}",
        provider_event_id=clean_provider_event_id,
        source=EventSource.RAZORPAY_WEBHOOK.value,
        case_id=case_id,
        event_type=AuditEventType.REMINDER_DELIVERY_UPDATED.value,
        actor_type=ActorType.SYSTEM.value,
        before_state=before_status,
        after_state=req.delivery_status,
        sanitized_metadata={
            "notification_id": notif_obj.notification_id,
            "medium": notif_obj.medium,
            "delivery_status": req.delivery_status,
            "provider_event_id": clean_provider_event_id,
            "correlation_id": corr_id,
        },
        timestamp=now,
    )
    session.add(deliv_evt)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return {
            "status": "ignored",
            "message": (f"Provider delivery event '{clean_provider_event_id}' already processed."),
        }

    return {
        "status": "success",
        "notification_id": notif_obj.notification_id,
        "delivery_status": req.delivery_status,
        "updated_at": now.isoformat(),
    }
