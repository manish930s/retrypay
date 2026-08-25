"""Internal server-side webhook ingestion service."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.adapters.razorpay.normalizer import parse_and_normalize_webhook
from retrypay.adapters.razorpay.payment_links import FakePaymentLinkProvider
from retrypay.adapters.razorpay.verifier import WebhookVerifier
from retrypay.config import AppEnvironment, Settings
from retrypay.decision.candidates import ActionCandidateBuilder
from retrypay.decision.diagnosis import (
    DiagnosisInput,
    FallbackDiagnosisAdapter,
    GeminiDiagnosisAdapter,
    RulesDiagnosisAdapter,
)
from retrypay.decision.estimator import (
    EstimatorInput,
    ObservableCaseFeatures,
    SimulationEstimator,
)
from retrypay.decision.ranker import ActionUtilityRanker
from retrypay.decision.ros import ROSCalculator, ROSInput
from retrypay.domain.events import EventProcessingStatus, PaymentEventType, WebhookEvent
from retrypay.domain.models import (
    ActorType,
    AuditEvent,
    AuditEventType,
    ContactChannel,
    EventSource,
    IngestionOrigin,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentLinkStatus,
    PaymentStatus,
    PolicyDecisionType,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
    RecoveryPolicyContext,
    validate_source_origin_compatibility,
)
from retrypay.domain.state_machine import transition_case
from retrypay.execution.attribution import AttributionEvidence, evaluate_attribution
from retrypay.execution.orchestrator import ExecutionOrchestrator
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.events import WebhookEventRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository
from retrypay.storage.repositories.outbox import WebhookOutboxRepository
from retrypay.storage.repositories.traces import DecisionTraceRepository


class IngestionResult(BaseModel):
    """Result of server-side webhook event ingestion and reconciliation."""

    status: str
    event_id: str
    event_type: str | None = None
    outbox_job_id: str | None = None
    order_id: str | None = None
    order_status: str | None = None
    recovery_case: dict[str, Any] | None = None
    message: str | None = None
    source: str = EventSource.LOCAL_SIMULATION.value
    ingestion_origin: str = IngestionOrigin.INTERNAL_SIMULATOR.value


async def ingest_verified_event(
    raw_body: bytes,
    signature: str | None,
    source: EventSource,
    ingestion_origin: IngestionOrigin,
    session: AsyncSession,
    verifier: WebhookVerifier,
    policy_engine: PolicyEngine,
    settings: Settings,
    event_id_override: str | None = None,
    diagnostic_metadata: dict[str, Any] | None = None,
) -> IngestionResult:
    """Ingest, verify, deduplicate, and reconcile a webhook event.

    Strict source partitioning is enforced across all tables and lookups.
    """
    # Step 0: Server-side source/origin compatibility validation
    try:
        validate_source_origin_compatibility(source, ingestion_origin)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    source_val = source.value
    origin_val = ingestion_origin.value

    # Step 1: Cryptographic signature verification
    verification = verifier.verify(raw_body, signature)
    if not verification.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid webhook signature: {verification.reason}",
        )

    # Step 2: Parse raw JSON payload
    try:
        raw_json = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload in request body",
        ) from None

    if not isinstance(raw_json, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON payload must be a root object",
        )

    # Step 3: Determine provider event ID
    provider_event_id = (
        event_id_override
        or raw_json.get("event_id")
        or raw_json.get("id")
        or f"evt_{verification.payload_sha256[:16]}"
    )

    event_repo = WebhookEventRepository(session)
    order_repo = OrderRepository(session)
    case_repo = RecoveryCaseRepository(session)
    audit_repo = AuditRepository(session)
    customer_repo = CustomerRepository(session)
    trace_repo = DecisionTraceRepository(session)
    link_repo = PaymentLinkRepository(session)
    outbox_repo = WebhookOutboxRepository(session)

    # Step 4: Source-partitioned deduplication check
    if await event_repo.is_event_processed(provider_event_id, source=source_val):
        return IngestionResult(
            status="duplicate_ignored",
            event_id=provider_event_id,
            message="Event has already been processed for this source partition.",
            source=source_val,
            ingestion_origin=origin_val,
        )

    # Persist durable outbox job atomically with event processing
    outbox_job = await outbox_repo.create_outbox_job(provider_event_id, source=source_val)

    # Step 5: Normalize supported payload
    normalized = parse_and_normalize_webhook(raw_json, provider_event_id)

    raw_payload_to_store: str | None = None
    if (
        settings.RETRYPAY_ENV == AppEnvironment.TEST
        and settings.RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD
    ):
        raw_payload_to_store = raw_body.decode("utf-8")

    # Step 6: Handle unsupported or unparseable event types
    if normalized is None:
        event_name = raw_json.get("event", "unknown")
        unsupported_event = WebhookEvent(
            provider_event_id=provider_event_id,
            source=source_val,
            event_type=PaymentEventType.UNSUPPORTED,
            received_at=datetime.now(UTC),
            signature_verification_status="valid",
            payload_sha256=verification.payload_sha256,
            normalized_payload=None,
            processing_status=EventProcessingStatus.UNSUPPORTED,
            error_reason=f"Unsupported or malformed event: {event_name}",
        )
        await event_repo.record_event(
            unsupported_event, raw_payload_text=raw_payload_to_store, source=source_val
        )
        await session.commit()
        return IngestionResult(
            status="unsupported_event_acknowledged",
            event_id=provider_event_id,
            event_type=event_name,
            source=source_val,
            ingestion_origin=origin_val,
        )

    # Step 7: Atomic reconciliation of order and payment attempt scoped by source
    now = datetime.now(UTC)
    order: Order | None = None
    if normalized.order_id:
        existing_order = await order_repo.get_order(normalized.order_id, source=source_val)
        if existing_order is None:
            if normalized.event_type == PaymentEventType.PAYMENT_FAILED:
                initial_status = OrderStatus.ATTEMPTED
            elif normalized.event_type in (
                PaymentEventType.PAYMENT_CAPTURED,
                PaymentEventType.ORDER_PAID,
            ):
                initial_status = OrderStatus.PAID
            else:
                initial_status = OrderStatus.CREATED

            order = Order(
                order_id=normalized.order_id,
                source=source,
                amount_paise=normalized.amount_paise,
                currency=normalized.currency,
                status=initial_status,
                created_at=normalized.occurred_at,
                updated_at=now,
            )
        else:
            if normalized.payment_status is not None:
                order = existing_order.reconcile_with_payment(normalized.payment_status)
            elif normalized.event_type == PaymentEventType.ORDER_PAID:
                order = existing_order.reconcile_with_order_paid()
            else:
                order = existing_order

        await order_repo.save_order(order, source=source_val)

    recorded_attempt: PaymentAttempt | None = None
    if normalized.payment_id and normalized.payment_status and normalized.order_id:
        recorded_attempt = PaymentAttempt(
            payment_id=normalized.payment_id,
            source=source,
            order_id=normalized.order_id,
            amount_paise=normalized.amount_paise,
            currency=normalized.currency,
            status=normalized.payment_status,
            method=normalized.method,
            failure_context=normalized.failure_context,
            occurred_at=normalized.occurred_at,
        )
        await order_repo.record_payment_attempt(recorded_attempt, source=source_val)

    # Step 8: Recovery Case Control Plane, Policy, and Execution scoped by source
    case_summary: dict[str, Any] | None = None

    if normalized.event_type == PaymentEventType.PAYMENT_FAILED and recorded_attempt and order:
        existing_order_obj = await order_repo.get_order(order.order_id, source=source_val)
        if existing_order_obj and existing_order_obj.status == OrderStatus.PAID:
            closed_case = await case_repo.close_active_case_for_order(
                order.order_id,
                closure_reason=RecoveryCaseClosureReason.ORDER_ALREADY_PAID,
                source=source_val,
            )
            if closed_case:
                await audit_repo.record_audit_event(
                    AuditEvent(
                        event_id=f"aud_{uuid.uuid4().hex[:12]}",
                        source=source,
                        case_id=closed_case.case_id,
                        event_type=AuditEventType.CASE_CLOSED,
                        actor_type=ActorType.SYSTEM,
                        before_state=closed_case.state.value,
                        after_state=RecoveryCaseState.CLOSED_BLOCKED.value,
                        metadata={
                            "closure_reason": RecoveryCaseClosureReason.ORDER_ALREADY_PAID.value,
                            "trigger": "late_failure_on_paid_order",
                        },
                        timestamp=now,
                    ),
                    source=source_val,
                )
        else:
            active_case = await case_repo.get_active_case_for_order(
                order.order_id, source=source_val
            )
            if active_case is None:
                case_id = f"rcv_{order.order_id}_{uuid.uuid4().hex[:6]}"
                case = RecoveryCase(
                    case_id=case_id,
                    source=source,
                    order_id=order.order_id,
                    failed_attempt_id=recorded_attempt.payment_id,
                    state=RecoveryCaseState.RECEIVED,
                    policy_version=policy_engine.config.policy_version,
                    created_at=now,
                    updated_at=now,
                )
                await case_repo.save_case(case, source=source_val)
                await audit_repo.record_audit_event(
                    AuditEvent(
                        event_id=f"aud_{uuid.uuid4().hex[:12]}",
                        source=source,
                        case_id=case.case_id,
                        event_type=AuditEventType.CASE_CREATED,
                        actor_type=ActorType.SYSTEM,
                        before_state=None,
                        after_state=RecoveryCaseState.RECEIVED.value,
                        metadata={"order_id": order.order_id, "amount_paise": order.amount_paise},
                        timestamp=now,
                    ),
                    source=source_val,
                )
            else:
                case = active_case

            # Transition: RECEIVED -> ENRICHING
            prior_state = case.state
            case = transition_case(case, RecoveryCaseState.ENRICHING)
            await case_repo.save_case(case, source=source_val)
            await audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=source,
                    case_id=case.case_id,
                    event_type=AuditEventType.STATE_TRANSITION,
                    actor_type=ActorType.SYSTEM,
                    before_state=prior_state.value,
                    after_state=RecoveryCaseState.ENRICHING.value,
                    metadata={"step": "enrichment_started"},
                    timestamp=now,
                ),
                source=source_val,
            )

            # Resolve customer profile and channel consents
            customer_id = case.customer_id or f"cust_{order.order_id}"
            customer = await customer_repo.get_customer(customer_id)
            consents = await customer_repo.get_consents(customer.customer_id) if customer else {}
            customer_30d_contacts = (
                await customer_repo.get_customer_30d_contact_count(customer.customer_id, as_of=now)
                if customer
                else 0
            )

            eval_time = (
                recorded_attempt.occurred_at
                if (recorded_attempt and recorded_attempt.occurred_at)
                else now
            )
            if eval_time.tzinfo is None:
                eval_time = eval_time.replace(tzinfo=UTC)
            policy_context = RecoveryPolicyContext(
                order=order,
                failed_attempt=recorded_attempt,
                customer=customer,
                consents=consents,
                target_channel=ContactChannel.WHATSAPP,
                prior_order_contact_count=case.contact_count,
                customer_30d_contact_count=customer_30d_contacts,
                evaluation_time=eval_time,
            )

            decision = policy_engine.evaluate(policy_context)
            eval_id = f"eval_{uuid.uuid4().hex[:12]}"
            await audit_repo.record_policy_evaluation(case.case_id, decision, eval_id)
            await audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=source,
                    case_id=case.case_id,
                    event_type=AuditEventType.POLICY_EVALUATED,
                    actor_type=ActorType.SYSTEM,
                    metadata={
                        "evaluation_id": eval_id,
                        "decision_type": decision.decision_type.value,
                        "reasons": [r.value for r in decision.reasons],
                    },
                    timestamp=now,
                ),
                source=source_val,
            )

            enriching_state = case.state
            execution_summary: dict[str, Any] | None = None
            advisory_trace_summary: dict[str, Any] | None = None

            if decision.decision_type == PolicyDecisionType.ELIGIBLE:
                case = transition_case(case, RecoveryCaseState.POLICY_EVALUATED)

                # Advisory diagnosis & decision trace pipeline
                gemini_adapter = GeminiDiagnosisAdapter(
                    api_key=settings.GEMINI_API_KEY,
                    model_name=settings.LLM_MODEL,
                    timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
                )
                rules_adapter = RulesDiagnosisAdapter()
                diag_adapter = FallbackDiagnosisAdapter(
                    enabled=settings.LLM_ENABLED,
                    gemini_adapter=gemini_adapter,
                    rules_adapter=rules_adapter,
                )

                diag_input = DiagnosisInput(
                    error_code=(
                        recorded_attempt.failure_context.error_code
                        if recorded_attempt.failure_context
                        else "UNKNOWN"
                    ),
                    error_source=(
                        recorded_attempt.failure_context.error_source
                        if recorded_attempt.failure_context
                        else None
                    ),
                    error_step=(
                        recorded_attempt.failure_context.error_step
                        if recorded_attempt.failure_context
                        else None
                    ),
                    error_reason=(
                        recorded_attempt.failure_context.error_reason
                        if recorded_attempt.failure_context
                        else None
                    ),
                    payment_method=recorded_attempt.method,
                    attempt_count=1,
                    event_timestamp=recorded_attempt.occurred_at,
                )
                diag_res = diag_adapter.diagnose(diag_input)

                ros_calc = ROSCalculator()
                ros_input = ROSInput(
                    diagnosis_category=diag_res.category,
                    attempt_count=1,
                    customer_successful_purchases=(
                        customer.successful_purchase_count if customer else 0
                    ),
                    is_high_risk=False,
                    failure_occurred_at=recorded_attempt.occurred_at,
                    evaluation_time=now,
                    has_alternate_payment_method=True,
                    payment_method=recorded_attempt.method,
                )
                ros_res = ros_calc.calculate(ros_input)

                cand_builder = ActionCandidateBuilder()
                cand_res = cand_builder.build_candidates(decision, diag_res, ros_res)

                estimator = SimulationEstimator()
                obs_features = ObservableCaseFeatures(
                    order_amount_paise=order.amount_paise,
                    ros_score=ros_res.score,
                    diagnosis_category=diag_res.category,
                    prior_contacts=case.contact_count,
                )
                est_input = EstimatorInput(
                    observable_features=obs_features,
                    action_candidates=cand_res.candidates,
                    ros_result=ros_res,
                )
                estimates = estimator.estimate(est_input)

                ranker = ActionUtilityRanker()
                recommendation = ranker.rank(estimates)

                trace_id = f"trc_{uuid.uuid4().hex[:12]}"
                est_out_encoded = json.dumps(
                    [e.model_dump(mode="json") for e in estimates], sort_keys=True
                ).encode("utf-8")
                est_out_hash = hashlib.sha256(est_out_encoded).hexdigest()

                await trace_repo.record_trace(
                    trace_id=trace_id,
                    case_id=case.case_id,
                    policy_version=decision.policy_version,
                    policy_decision=decision.decision_type.value,
                    ros_version=ros_res.scoring_version,
                    ros_score=ros_res.score,
                    ros_contributions=ros_res.feature_contributions,
                    diagnosis_category=diag_res.category.value,
                    diagnosis_confidence=diag_res.confidence,
                    diagnosis_mode=diag_res.diagnosis_mode.value,
                    diagnosis_fallback_used=diag_res.fallback_used,
                    action_candidates=[a.value for a in cand_res.candidates],
                    selected_action=recommendation.selected_action.value,
                    estimator_mode="SIMULATION",
                    estimator_version=estimator.VERSION,
                    input_context_hash=decision.context_hash,
                    estimator_output_hash=est_out_hash,
                    utility_paise=recommendation.selected_utility_paise,
                    created_at=now,
                )

                advisory_trace_summary = {
                    "ros_score": ros_res.score,
                    "selected_advisory_action": recommendation.selected_action.value,
                    "diagnosis_category": diag_res.category.value,
                }

                # Milestone 4 Execution Flow (Uses FakePaymentLinkProvider during webhook ingestion)
                link_provider = FakePaymentLinkProvider()
                orchestrator = ExecutionOrchestrator(
                    session=session,
                    link_provider=link_provider,
                    policy_engine=policy_engine,
                )
                execution_summary = await orchestrator.execute_advisory_recommendation(
                    case=case,
                    order=order,
                    recommendation=recommendation,
                    target_channel=ContactChannel.WHATSAPP,
                )

                # Reload case after orchestration transitions
                updated_case_obj = await case_repo.get_case(case.case_id, source=source_val)
                if updated_case_obj:
                    case = updated_case_obj

            elif decision.decision_type == PolicyDecisionType.BLOCK:
                case = transition_case(
                    case,
                    RecoveryCaseState.CLOSED_BLOCKED,
                    closure_reason=RecoveryCaseClosureReason.POLICY_BLOCKED,
                )
                await case_repo.save_case(case, source=source_val)
            elif decision.decision_type == PolicyDecisionType.MANUAL_REVIEW:
                case = transition_case(case, RecoveryCaseState.MANUAL_REVIEW)
                await case_repo.save_case(case, source=source_val)
            elif decision.decision_type == PolicyDecisionType.DEFER:
                case = transition_case(
                    case,
                    RecoveryCaseState.DEFERRED,
                    deferred_until=decision.deferred_until,
                )
                await case_repo.save_case(case, source=source_val)

            if decision.decision_type != PolicyDecisionType.ELIGIBLE:
                await audit_repo.record_audit_event(
                    AuditEvent(
                        event_id=f"aud_{uuid.uuid4().hex[:12]}",
                        source=source,
                        case_id=case.case_id,
                        event_type=AuditEventType.STATE_TRANSITION,
                        actor_type=ActorType.SYSTEM,
                        before_state=enriching_state.value,
                        after_state=case.state.value,
                        metadata={"decision_type": decision.decision_type.value},
                        timestamp=now,
                    ),
                    source=source_val,
                )

            case_summary = {
                "case_id": case.case_id,
                "case_state": case.state.value,
                "policy_decision": decision.decision_type.value,
                "reasons": [r.value for r in decision.reasons],
            }
            if advisory_trace_summary:
                case_summary["advisory_trace"] = advisory_trace_summary
            if execution_summary:
                case_summary["execution"] = execution_summary

    elif normalized.event_type in (PaymentEventType.PAYMENT_CAPTURED, PaymentEventType.ORDER_PAID):
        if normalized.order_id:
            active_case = await case_repo.get_active_case_for_order(
                normalized.order_id, source=source_val
            )
            if active_case is not None and active_case.is_active:
                active_link = await link_repo.get_active_link_for_case(
                    active_case.case_id, source=source_val
                )

                payment_notes = (
                    raw_json.get("payload", {})
                    .get("payment", {})
                    .get("entity", {})
                    .get("notes", {})
                )
                payment_desc = str(
                    raw_json.get("payload", {})
                    .get("payment", {})
                    .get("entity", {})
                    .get("description", "")
                )

                if active_link is None:
                    closure_reason = (
                        RecoveryCaseClosureReason.PAYMENT_CAPTURED
                        if normalized.event_type == PaymentEventType.PAYMENT_CAPTURED
                        else RecoveryCaseClosureReason.ORDER_PAID
                    )
                    closed_case = transition_case(
                        active_case,
                        RecoveryCaseState.CLOSED_BLOCKED,
                        closure_reason=closure_reason,
                    )
                    await case_repo.save_case(closed_case, source=source_val)
                    await audit_repo.record_audit_event(
                        AuditEvent(
                            event_id=f"aud_{uuid.uuid4().hex[:12]}",
                            source=source,
                            case_id=closed_case.case_id,
                            event_type=AuditEventType.CASE_CLOSED,
                            actor_type=ActorType.SYSTEM,
                            before_state=active_case.state.value,
                            after_state=closed_case.state.value,
                            metadata={
                                "closure_reason": closure_reason.value,
                                "trigger_event": normalized.event_type.value,
                                "attributed_to_recovery_link": False,
                            },
                            timestamp=now,
                        ),
                        source=source_val,
                    )
                    case_summary = {
                        "case_id": closed_case.case_id,
                        "case_state": closed_case.state.value,
                        "closure_reason": closure_reason.value,
                    }
                else:
                    evidence = AttributionEvidence(
                        local_link=active_link,
                        case=active_case,
                        webhook_provider_link_id=(
                            active_link.provider_link_id
                            if active_link.status == PaymentLinkStatus.PAID
                            else None
                        ),
                        webhook_payment_id=normalized.payment_id,
                        webhook_order_id=normalized.order_id,
                        webhook_reference_id=normalized.reference_id,
                        payment_notes=payment_notes if isinstance(payment_notes, dict) else None,
                        payment_description=payment_desc,
                    )
                    attr_result = evaluate_attribution(evidence)

                    if attr_result.is_attributed:
                        updated_link = active_link.model_copy(
                            update={"status": PaymentLinkStatus.PAID, "updated_at": now}
                        )
                        await link_repo.save_link(updated_link, source=source_val)
                        closed_case = transition_case(
                            active_case,
                            RecoveryCaseState.RECOVERED,
                            closure_reason=RecoveryCaseClosureReason.RECOVERED_VIA_LINK,
                        )
                        await case_repo.save_case(closed_case, source=source_val)
                        await audit_repo.record_audit_event(
                            AuditEvent(
                                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                                source=source,
                                case_id=closed_case.case_id,
                                event_type=AuditEventType.CASE_CLOSED,
                                actor_type=ActorType.SYSTEM,
                                before_state=active_case.state.value,
                                after_state=closed_case.state.value,
                                metadata={
                                    "closure_reason": (
                                        RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value
                                    ),
                                    "trigger_event": normalized.event_type.value,
                                    "evidence_level": attr_result.evidence_level,
                                    "reason": attr_result.confidence_reason,
                                },
                                timestamp=now,
                            ),
                            source=source_val,
                        )
                        case_summary = {
                            "case_id": closed_case.case_id,
                            "case_state": closed_case.state.value,
                            "closure_reason": (RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value),
                        }
                    else:
                        pending_case = transition_case(
                            active_case,
                            RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION,
                        )
                        await case_repo.save_case(pending_case, source=source_val)
                        await audit_repo.record_audit_event(
                            AuditEvent(
                                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                                source=source,
                                case_id=pending_case.case_id,
                                event_type=AuditEventType.PAYMENT_TRUTH_AWAITING_LINK_ATTRIBUTION,
                                actor_type=ActorType.SYSTEM,
                                before_state=active_case.state.value,
                                after_state=pending_case.state.value,
                                metadata={
                                    "payment_id": normalized.payment_id,
                                    "order_id": normalized.order_id,
                                    "amount_paise": normalized.amount_paise,
                                    "provider_link_id": active_link.provider_link_id,
                                    "note": "Payment verified; awaiting link correlation webhook.",
                                },
                                timestamp=now,
                            ),
                            source=source_val,
                        )
                        case_summary = {
                            "case_id": pending_case.case_id,
                            "case_state": pending_case.state.value,
                            "status": "AWAITING_LINK_ATTRIBUTION",
                        }

    # Step 9: Payment Link Lifecycle Webhook Handling scoped by source
    elif normalized.event_type in (
        PaymentEventType.PAYMENT_LINK_PAID,
        PaymentEventType.PAYMENT_LINK_EXPIRED,
        PaymentEventType.PAYMENT_LINK_CANCELLED,
        PaymentEventType.PAYMENT_LINK_PARTIALLY_PAID,
    ):
        if normalized.provider_link_id:
            link = await link_repo.get_by_provider_link_id(
                normalized.provider_link_id, source=source_val
            )
            if link is None and normalized.event_type == PaymentEventType.PAYMENT_LINK_PAID:
                return IngestionResult(
                    status="unknown_payment_link",
                    event_id=provider_event_id,
                    message="Provider payment link ID not found in database.",
                    source=source_val,
                    ingestion_origin=origin_val,
                )

            if link is not None:
                related_case = await case_repo.get_case(link.case_id, source=source_val)

                if normalized.event_type == PaymentEventType.PAYMENT_LINK_PAID:
                    # Check for duplicate payment_link.paid
                    if link.status == PaymentLinkStatus.PAID:
                        return IngestionResult(
                            status="duplicate_ignored",
                            event_id=provider_event_id,
                            message="Payment link is already marked PAID.",
                            source=source_val,
                            ingestion_origin=origin_val,
                        )

                    # Validate reference_id match if provided in webhook payload
                    if (
                        normalized.reference_id
                        and link.reference_id
                        and normalized.reference_id != link.reference_id
                    ):
                        return IngestionResult(
                            status="mismatched_reference_id",
                            event_id=provider_event_id,
                            message="Payment link reference_id mismatch.",
                            source=source_val,
                            ingestion_origin=origin_val,
                        )

                    # Validate amount match if provided in webhook payload
                    if (
                        normalized.amount_paise is not None
                        and normalized.amount_paise != link.amount_paise
                    ):
                        return IngestionResult(
                            status="mismatched_amount",
                            event_id=provider_event_id,
                            message="Payment link amount_paise mismatch.",
                            source=source_val,
                            ingestion_origin=origin_val,
                        )

                    # Mark payment link PAID
                    updated_link = link.model_copy(
                        update={"status": PaymentLinkStatus.PAID, "updated_at": now}
                    )
                    await link_repo.save_link(updated_link, source=source_val)

                    # Reconcile order & case if related case exists
                    if related_case and (
                        related_case.is_active
                        or related_case.state
                        == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION
                    ):
                        order_obj = await order_repo.get_order(
                            related_case.order_id, source=source_val
                        )
                        if order_obj:
                            order_paid = order_obj.reconcile_with_payment(PaymentStatus.CAPTURED)
                            await order_repo.save_order(order_paid, source=source_val)

                        closed_case = transition_case(
                            related_case,
                            RecoveryCaseState.RECOVERED,
                            closure_reason=RecoveryCaseClosureReason.RECOVERED_VIA_LINK,
                        )
                        await case_repo.save_case(closed_case, source=source_val)
                        await audit_repo.record_audit_event(
                            AuditEvent(
                                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                                source=source,
                                case_id=closed_case.case_id,
                                event_type=AuditEventType.CASE_CLOSED,
                                actor_type=ActorType.SYSTEM,
                                before_state=related_case.state.value,
                                after_state=closed_case.state.value,
                                metadata={
                                    "closure_reason": (
                                        RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value
                                    ),
                                    "provider_link_id": link.provider_link_id,
                                    "trigger_event": normalized.event_type.value,
                                },
                                timestamp=now,
                            ),
                            source=source_val,
                        )

                elif normalized.event_type == PaymentEventType.PAYMENT_LINK_EXPIRED:
                    updated_link = link.model_copy(
                        update={"status": PaymentLinkStatus.EXPIRED, "updated_at": now}
                    )
                    await link_repo.save_link(updated_link, source=source_val)
                    if related_case and related_case.is_active:
                        closed_case = transition_case(
                            related_case,
                            RecoveryCaseState.EXPIRED,
                            closure_reason=RecoveryCaseClosureReason.LINK_EXPIRED,
                        )
                        await case_repo.save_case(closed_case, source=source_val)
                        await audit_repo.record_audit_event(
                            AuditEvent(
                                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                                source=source,
                                case_id=closed_case.case_id,
                                event_type=AuditEventType.CASE_CLOSED,
                                actor_type=ActorType.SYSTEM,
                                before_state=related_case.state.value,
                                after_state=closed_case.state.value,
                                metadata={"closure_reason": "LINK_EXPIRED"},
                                timestamp=now,
                            ),
                            source=source_val,
                        )

                elif normalized.event_type == PaymentEventType.PAYMENT_LINK_CANCELLED:
                    updated_link = link.model_copy(
                        update={"status": PaymentLinkStatus.CANCELLED, "updated_at": now}
                    )
                    await link_repo.save_link(updated_link, source=source_val)
                    if related_case and related_case.is_active:
                        closed_case = transition_case(
                            related_case,
                            RecoveryCaseState.CLOSED_UNRECOVERED,
                            closure_reason=RecoveryCaseClosureReason.LINK_CANCELLED,
                        )
                        await case_repo.save_case(closed_case, source=source_val)
                        await audit_repo.record_audit_event(
                            AuditEvent(
                                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                                source=source,
                                case_id=closed_case.case_id,
                                event_type=AuditEventType.CASE_CLOSED,
                                actor_type=ActorType.SYSTEM,
                                before_state=related_case.state.value,
                                after_state=closed_case.state.value,
                                metadata={"closure_reason": "LINK_CANCELLED"},
                                timestamp=now,
                            ),
                            source=source_val,
                        )

                elif normalized.event_type == PaymentEventType.PAYMENT_LINK_PARTIALLY_PAID:
                    updated_link = link.model_copy(
                        update={"status": PaymentLinkStatus.PARTIALLY_PAID, "updated_at": now}
                    )
                    await link_repo.save_link(updated_link, source=source_val)
                    if related_case and related_case.is_active:
                        try:
                            rev_case = transition_case(
                                related_case, RecoveryCaseState.MANUAL_REVIEW
                            )
                            await case_repo.save_case(rev_case, source=source_val)
                        except Exception:
                            pass
                        await audit_repo.record_audit_event(
                            AuditEvent(
                                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                                source=source,
                                case_id=related_case.case_id,
                                event_type=AuditEventType.STATE_TRANSITION,
                                actor_type=ActorType.SYSTEM,
                                metadata={
                                    "warning": (
                                        "Unexpected partial payment on link (accept_partial=false)"
                                    ),
                                    "provider_link_id": link.provider_link_id,
                                },
                                timestamp=now,
                            ),
                            source=source_val,
                        )

    # Record the processed WebhookEvent with source
    webhook_event = WebhookEvent(
        provider_event_id=provider_event_id,
        source=source_val,
        event_type=normalized.event_type,
        received_at=now,
        signature_verification_status="valid",
        payload_sha256=verification.payload_sha256,
        normalized_payload=normalized,
        processing_status=EventProcessingStatus.PROCESSED,
        error_reason=None,
    )
    await event_repo.record_event(
        webhook_event, raw_payload_text=raw_payload_to_store, source=source_val
    )
    await outbox_repo.mark_completed(outbox_job.job_id)
    await session.commit()

    return IngestionResult(
        status="processed",
        event_id=provider_event_id,
        event_type=normalized.event_type.value,
        outbox_job_id=outbox_job.job_id,
        order_id=order.order_id if order else None,
        order_status=order.status.value if order else None,
        recovery_case=case_summary,
        source=source_val,
        ingestion_origin=origin_val,
    )
