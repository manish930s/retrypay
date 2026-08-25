"""Execution orchestrator coordinating policy re-check, links, and notifications."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.adapters.razorpay.payment_links import (
    CreatePaymentLinkRequest,
    PaymentLinkDefinitiveFailureError,
    PaymentLinkProvider,
    PaymentLinkUnknownResultError,
)
from retrypay.budget.engine import BudgetEngine, BudgetExhaustedError
from retrypay.decision.diagnosis import ActionType
from retrypay.decision.ranker import AdvisoryRecommendation
from retrypay.domain.models import (
    ActorType,
    AuditEvent,
    AuditEventType,
    ContactChannel,
    NotificationTemplateKey,
    Order,
    PaymentLink,
    PolicyDecisionType,
    ProviderOperationStatus,
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
    RecoveryPolicyContext,
    generate_deterministic_reference_id,
)
from retrypay.domain.state_machine import transition_case
from retrypay.notifications.dispatcher import SimulatedNotificationDispatcher
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.repositories.actions import RecoveryActionRepository
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.links import PaymentLinkRepository


class ExecutionOrchestrator:
    """Orchestrates bounded, idempotent recovery execution to notification."""

    def __init__(
        self,
        session: AsyncSession,
        link_provider: PaymentLinkProvider,
        policy_engine: PolicyEngine,
    ) -> None:
        self._session = session
        self._link_provider = link_provider
        self._policy_engine = policy_engine
        self._case_repo = RecoveryCaseRepository(session)
        self._action_repo = RecoveryActionRepository(session)
        self._link_repo = PaymentLinkRepository(session)
        self._audit_repo = AuditRepository(session)
        self._cust_repo = CustomerRepository(session)
        self._budget_engine = BudgetEngine(session)
        self._notif_dispatcher = SimulatedNotificationDispatcher(session)

    async def execute_advisory_recommendation(
        self,
        case: RecoveryCase,
        order: Order,
        recommendation: AdvisoryRecommendation,
        target_channel: ContactChannel = ContactChannel.WHATSAPP,
    ) -> dict[str, Any]:
        """Move case from POLICY_EVALUATED through full idempotent execution flow."""
        now = datetime.now(UTC)
        selected_action = recommendation.selected_action

        # Step 1: Transition POLICY_EVALUATED -> DIAGNOSED
        if case.state == RecoveryCaseState.POLICY_EVALUATED:
            case = transition_case(case, RecoveryCaseState.DIAGNOSED)
            await self._case_repo.save_case(case)
            await self._audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    case_id=case.case_id,
                    event_type=AuditEventType.STATE_TRANSITION,
                    actor_type=ActorType.SYSTEM,
                    before_state=RecoveryCaseState.POLICY_EVALUATED.value,
                    after_state=RecoveryCaseState.DIAGNOSED.value,
                    metadata={"step": "diagnosis_recorded"},
                    timestamp=now,
                )
            )

        # Step 2: Handle non-executable actions (NO_ACTION / MANUAL_REVIEW)
        if selected_action in (ActionType.NO_ACTION, ActionType.MANUAL_REVIEW):
            target_state = (
                RecoveryCaseState.MANUAL_REVIEW
                if selected_action == ActionType.MANUAL_REVIEW
                else RecoveryCaseState.CLOSED_BLOCKED
            )
            closure = (
                RecoveryCaseClosureReason.POLICY_BLOCKED
                if target_state == RecoveryCaseState.CLOSED_BLOCKED
                else None
            )
            updated_case = transition_case(case, to_state=target_state, closure_reason=closure)
            await self._case_repo.save_case(updated_case)
            return {
                "case_id": case.case_id,
                "case_state": updated_case.state.value,
                "execution_status": "NO_OUTREACH",
                "action": selected_action.value,
            }

        # Step 3: Final deterministic policy re-check
        customer_id = case.customer_id or f"cust_{case.order_id}"
        customer = await self._cust_repo.get_customer(customer_id)
        consents = await self._cust_repo.get_consents(customer_id)
        customer_30d_contacts = (
            await self._cust_repo.get_customer_30d_contact_count(customer_id, as_of=now)
            if customer
            else 0
        )

        latest_att = await self._get_latest_attempt(case.failed_attempt_id)
        eval_time = latest_att.occurred_at if (latest_att and latest_att.occurred_at) else now
        recheck_context = RecoveryPolicyContext(
            order=order,
            failed_attempt=latest_att,
            customer=customer,
            consents=consents,
            target_channel=target_channel,
            prior_order_contact_count=case.contact_count,
            customer_30d_contact_count=customer_30d_contacts,
            evaluation_time=eval_time,
        )
        recheck_decision = self._policy_engine.evaluate(recheck_context)
        if recheck_decision.decision_type != PolicyDecisionType.ELIGIBLE:
            # Policy re-check blocked
            closed_case = transition_case(
                case,
                RecoveryCaseState.CLOSED_BLOCKED,
                closure_reason=RecoveryCaseClosureReason.POLICY_BLOCKED,
            )
            await self._case_repo.save_case(closed_case)
            return {
                "case_id": case.case_id,
                "case_state": closed_case.state.value,
                "execution_status": "POLICY_RECHECK_BLOCKED",
                "reasons": [r.value for r in recheck_decision.reasons],
            }

        # Step 4: Transition DIAGNOSED -> ACTION_APPROVED
        case = transition_case(case, RecoveryCaseState.ACTION_APPROVED)
        await self._case_repo.save_case(case)
        await self._audit_repo.record_audit_event(
            AuditEvent(
                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                case_id=case.case_id,
                event_type=AuditEventType.STATE_TRANSITION,
                actor_type=ActorType.SYSTEM,
                before_state=RecoveryCaseState.DIAGNOSED.value,
                after_state=RecoveryCaseState.ACTION_APPROVED.value,
                metadata={"action": selected_action.value},
                timestamp=now,
            )
        )

        # Step 5: Idempotency enforcement
        idempotency_key = f"{case.case_id}:{selected_action.value}:{case.policy_version}"
        existing_action = await self._action_repo.get_by_idempotency_key(idempotency_key)
        if existing_action is not None:
            # Return existing action idempotently
            return {
                "case_id": case.case_id,
                "case_state": case.state.value,
                "execution_status": "IDEMPOTENT_REPLAY",
                "action_id": existing_action.action_id,
                "action_status": existing_action.status.value,
            }

        action_id = f"act_{uuid.uuid4().hex[:12]}"
        action = RecoveryAction(
            action_id=action_id,
            source=case.source,
            case_id=case.case_id,
            action_type=selected_action,
            policy_version=case.policy_version,
            idempotency_key=idempotency_key,
            status=RecoveryActionStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        await self._action_repo.save_action(action, source=case.source)

        # Step 6: Transactional operational budget reservation
        try:
            reservation = await self._budget_engine.reserve_budget(
                case_id=case.case_id,
                action_id=action.action_id,
                amount_paise=order.amount_paise,
            )
            await self._audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=case.source,
                    case_id=case.case_id,
                    event_type=AuditEventType.BUDGET_RESERVED,
                    actor_type=ActorType.SYSTEM,
                    metadata={
                        "reservation_id": reservation.reservation_id,
                        "amount_paise": order.amount_paise,
                    },
                    timestamp=now,
                ),
                source=case.source,
            )
        except BudgetExhaustedError as exc:
            # Route to MANUAL_REVIEW on budget exhaustion
            case = transition_case(case, RecoveryCaseState.MANUAL_REVIEW)
            await self._case_repo.save_case(case, source=case.source)
            action = action.model_copy(update={"status": RecoveryActionStatus.CANCELLED})
            await self._action_repo.save_action(action, source=case.source)
            await self._audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=case.source,
                    case_id=case.case_id,
                    event_type=AuditEventType.BUDGET_EXHAUSTED,
                    actor_type=ActorType.SYSTEM,
                    metadata={"reason": str(exc)},
                    timestamp=now,
                ),
                source=case.source,
            )
            return {
                "case_id": case.case_id,
                "case_state": case.state.value,
                "execution_status": "BUDGET_EXHAUSTED",
                "detail": str(exc),
            }

        # Step 7: Payment Link creation via provider
        from retrypay.domain.models import generate_deterministic_reference_id

        reference_id = generate_deterministic_reference_id(case.case_id, action.action_id)
        safe_eval_time = eval_time.replace(tzinfo=UTC) if eval_time.tzinfo is None else eval_time
        safe_now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        expire_by = max(safe_now, safe_eval_time) + timedelta(hours=24)

        link_request = CreatePaymentLinkRequest(
            order_id=order.order_id,
            amount_paise=order.amount_paise,
            currency=order.currency,
            case_id=case.case_id,
            action_id=action.action_id,
            policy_version=case.policy_version,
            reference_id=reference_id,
            expire_by=expire_by,
            description="ReTryPay checkout recovery link",
            notes={
                "recovery_case_id": case.case_id,
                "recovery_action_id": action.action_id,
                "policy_version": case.policy_version,
            },
        )

        try:
            link_result = await self._link_provider.create_payment_link(link_request)
        except PaymentLinkUnknownResultError as exc:
            # Mark action as PROVIDER_RESULT_UNKNOWN, hold reservation pending, do not retry
            action = action.model_copy(
                update={
                    "status": RecoveryActionStatus.FAILED,
                    "provider_operation_status": ProviderOperationStatus.UNKNOWN,
                    "updated_at": now,
                }
            )
            await self._action_repo.save_action(action, source=case.source)
            await self._audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=case.source,
                    case_id=case.case_id,
                    event_type=AuditEventType.STATE_TRANSITION,
                    actor_type=ActorType.SYSTEM,
                    metadata={"error": str(exc), "status": "PROVIDER_RESULT_UNKNOWN"},
                    timestamp=now,
                ),
                source=case.source,
            )
            return {
                "case_id": case.case_id,
                "case_state": case.state.value,
                "execution_status": "PROVIDER_RESULT_UNKNOWN",
                "action_status": action.status.value,
            }
        except PaymentLinkDefinitiveFailureError as exc:
            # Release budget reservation on definitive failure
            await self._budget_engine.release_reservation(reservation.reservation_id)
            action = action.model_copy(
                update={"status": RecoveryActionStatus.FAILED, "updated_at": now}
            )
            await self._action_repo.save_action(action, source=case.source)
            closed_case = transition_case(
                case,
                RecoveryCaseState.CLOSED_UNRECOVERED,
                closure_reason=RecoveryCaseClosureReason.UNRECOVERABLE,
            )
            await self._case_repo.save_case(closed_case, source=case.source)
            return {
                "case_id": case.case_id,
                "case_state": closed_case.state.value,
                "execution_status": "LINK_CREATION_FAILED",
                "error": str(exc),
            }

        # Step 8: Persist created payment link and commit budget
        link_id = f"plink_{uuid.uuid4().hex[:12]}"
        payment_link = PaymentLink(
            link_id=link_id,
            source=case.source,
            case_id=case.case_id,
            action_id=action.action_id,
            provider_link_id=link_result.provider_link_id,
            reference_id=link_result.reference_id,
            short_url=link_result.short_url,
            amount_paise=link_result.amount_paise,
            currency=link_result.currency,
            status=link_result.status,
            expire_by=link_result.expire_by,
            provider_created_at=link_result.provider_created_at,
            created_at=now,
            updated_at=now,
        )
        await self._link_repo.save_link(payment_link, source=case.source)
        await self._budget_engine.commit_reservation(reservation.reservation_id)

        action = action.model_copy(
            update={
                "status": RecoveryActionStatus.COMPLETED,
                "provider_operation_status": ProviderOperationStatus.SUCCEEDED,
                "updated_at": now,
            }
        )
        await self._action_repo.save_action(action, source=case.source)

        # Transition: ACTION_APPROVED -> LINK_CREATED
        case = transition_case(case, RecoveryCaseState.LINK_CREATED)
        await self._case_repo.save_case(case, source=case.source)
        await self._audit_repo.record_audit_event(
            AuditEvent(
                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                source=case.source,
                case_id=case.case_id,
                event_type=AuditEventType.PAYMENT_LINK_CREATED,
                actor_type=ActorType.SYSTEM,
                metadata={
                    "provider_link_id": payment_link.provider_link_id,
                    "reference_id": payment_link.reference_id,
                    "short_url": payment_link.short_url,
                },
                timestamp=now,
            ),
            source=case.source,
        )

        # Step 9: Simulated notification dispatch
        template_key = NotificationTemplateKey.PAYMENT_RETRY_GENERIC
        if selected_action == ActionType.DELAY_AND_SEND_RETRY_LINK:
            template_key = NotificationTemplateKey.PAYMENT_RETRY_DELAYED
        elif selected_action == ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT:
            template_key = NotificationTemplateKey.PAYMENT_RETRY_ALTERNATE_METHOD

        notif_log = await self._notif_dispatcher.dispatch_simulated_notification(
            case=case,
            action_id=action.action_id,
            channel=target_channel,
            template_key=template_key,
            link_reference=payment_link.short_url,
        )

        if notif_log is not None:
            # Transition: LINK_CREATED -> NOTIFIED
            refreshed_case = await self._case_repo.get_case(case.case_id)
            if refreshed_case:
                case = refreshed_case
            case = transition_case(case, RecoveryCaseState.NOTIFIED)
            await self._case_repo.save_case(case)

        return {
            "case_id": case.case_id,
            "case_state": case.state.value,
            "execution_status": "SUCCESS",
            "action_id": action.action_id,
            "provider_link_id": payment_link.provider_link_id,
            "short_url": payment_link.short_url,
            "notification_simulated": notif_log is not None,
        }

    async def reconcile_provider_operation(
        self, case_id: str, action_id: str, reservation_id: str | None = None
    ) -> dict[str, Any]:
        """Reconcile an UNKNOWN provider operation status using reference_id."""
        now = datetime.now(UTC)
        case = await self._case_repo.get_case(case_id)
        if not case:
            return {"reconciled": False, "reason": "Case not found"}

        action = await self._action_repo.get_action(action_id)
        if not action:
            return {"reconciled": False, "reason": "Action not found"}

        reference_id = generate_deterministic_reference_id(case_id, action_id)

        # Check if local PaymentLink already exists
        existing_link = await self._link_repo.get_by_reference_id(reference_id, source=case.source)
        if not existing_link:
            # Fetch from provider using reference_id
            link_result = await self._link_provider.fetch_payment_link_by_reference_id(reference_id)
        else:
            link_result = None

        if existing_link or link_result:
            # Provider created link successfully. Repair local state.
            if not existing_link and link_result:
                link_id = f"plink_{uuid.uuid4().hex[:12]}"
                existing_link = PaymentLink(
                    link_id=link_id,
                    source=case.source,
                    case_id=case.case_id,
                    action_id=action.action_id,
                    provider_link_id=link_result.provider_link_id,
                    reference_id=link_result.reference_id,
                    short_url=link_result.short_url,
                    amount_paise=link_result.amount_paise,
                    currency=link_result.currency,
                    status=link_result.status,
                    expire_by=link_result.expire_by,
                    provider_created_at=link_result.provider_created_at,
                    created_at=now,
                    updated_at=now,
                )
                await self._link_repo.save_link(existing_link, source=case.source)

            if reservation_id:
                await self._budget_engine.commit_reservation(reservation_id)

            action = action.model_copy(
                update={
                    "status": RecoveryActionStatus.COMPLETED,
                    "provider_operation_status": ProviderOperationStatus.SUCCEEDED,
                    "updated_at": now,
                }
            )
            await self._action_repo.save_action(action, source=case.source)

            if case.is_active:
                case = transition_case(case, RecoveryCaseState.LINK_CREATED)
                await self._case_repo.save_case(case, source=case.source)

            return {
                "reconciled": True,
                "link_found": True,
                "action_status": RecoveryActionStatus.COMPLETED.value,
                "provider_operation_status": ProviderOperationStatus.SUCCEEDED.value,
                "provider_link_id": existing_link.provider_link_id if existing_link else None,
            }
        else:
            # No link found at provider
            if reservation_id:
                await self._budget_engine.release_reservation(reservation_id)

            action = action.model_copy(
                update={
                    "status": RecoveryActionStatus.FAILED,
                    "provider_operation_status": ProviderOperationStatus.FAILED,
                    "updated_at": now,
                }
            )
            await self._action_repo.save_action(action, source=case.source)

            if case.is_active:
                case = transition_case(case, RecoveryCaseState.MANUAL_REVIEW)
                await self._case_repo.save_case(case, source=case.source)

            return {
                "reconciled": True,
                "link_found": False,
                "action_status": RecoveryActionStatus.FAILED.value,
                "provider_operation_status": ProviderOperationStatus.FAILED.value,
            }

    async def _get_latest_attempt(self, attempt_id: str) -> Any:
        from sqlalchemy import select

        from retrypay.storage.models import PaymentAttemptModel

        stmt = select(PaymentAttemptModel).where(PaymentAttemptModel.payment_id == attempt_id)
        res = await self._session.execute(stmt)
        m = res.scalar_one()
        from retrypay.domain.models import PaymentAttempt, PaymentFailureContext, PaymentStatus

        fc = None
        if m.error_code:
            fc = PaymentFailureContext(
                error_code=m.error_code,
                error_description=m.error_description or "",
                error_source=m.error_source or "gateway",
                error_step=m.error_step or "payment_authorization",
                error_reason=m.error_reason or "payment_failed",
            )
        return PaymentAttempt(
            payment_id=m.payment_id,
            order_id=m.order_id,
            amount_paise=m.amount_paise,
            currency=m.currency,
            status=PaymentStatus(m.status),
            method=m.method,
            failure_context=fc,
            occurred_at=m.occurred_at,
        )
