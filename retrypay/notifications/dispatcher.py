"""Simulated local notification dispatcher enforcing pre-dispatch consent verification."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import (
    ActorType,
    AuditEvent,
    AuditEventType,
    ContactChannel,
    ContactConsentStatus,
    NotificationLog,
    NotificationStatus,
    NotificationTemplateKey,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.domain.state_machine import transition_case
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.notifications import NotificationRepository


class SimulatedNotificationDispatcher:
    """Dispatches and logs simulated customer notifications locally."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._notif_repo = NotificationRepository(session)
        self._cust_repo = CustomerRepository(session)
        self._case_repo = RecoveryCaseRepository(session)
        self._audit_repo = AuditRepository(session)

    async def dispatch_simulated_notification(
        self,
        case: RecoveryCase,
        action_id: str,
        channel: ContactChannel,
        template_key: NotificationTemplateKey,
        link_reference: str,
    ) -> NotificationLog | None:
        """Simulate sending a recovery notification after validating real-time customer consent.

        Guarantees:
        1. Never makes external HTTP, SMS, email, or WhatsApp network calls.
        2. Re-checks consent immediately before persistence.
        3. If consent is OPTED_OUT or missing, suppresses notification and transitions case.
        4. Increments case contact count and persists simulated notification log.
        """
        now = datetime.now(UTC)

        # In TERMINAL_ONLY delivery mode (e.g. Razorpay Test Mode),
        # provider notifications are disabled and customer messaging is NOT SENT
        from retrypay.domain.models import EventSource

        if case.source == EventSource.RAZORPAY_TEST_MODE:
            await self._audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    case_id=case.case_id,
                    event_type=AuditEventType.NOTIFICATION_SUPPRESSED,
                    actor_type=ActorType.SYSTEM,
                    metadata={
                        "reason": "Provider notifications disabled in TERMINAL_ONLY delivery mode.",
                        "channel": channel.value,
                        "action_id": action_id,
                    },
                    timestamp=now,
                )
            )
            return None

        # Step 1: Pre-dispatch consent re-verification
        customer_id = case.customer_id or f"cust_{case.order_id}"
        customer = await self._cust_repo.get_customer(customer_id)
        consents = await self._cust_repo.get_consents(customer_id)
        consent_status = consents.get(channel, ContactConsentStatus.UNKNOWN)

        if consent_status != ContactConsentStatus.OPTED_IN:
            # Suppress notification and transition case to OPTED_OUT or CLOSED_BLOCKED
            closure_reason = (
                RecoveryCaseClosureReason.CUSTOMER_OPTED_OUT
                if consent_status == ContactConsentStatus.OPTED_OUT
                else RecoveryCaseClosureReason.POLICY_BLOCKED
            )
            to_state = (
                RecoveryCaseState.OPTED_OUT
                if consent_status == ContactConsentStatus.OPTED_OUT
                else RecoveryCaseState.CLOSED_BLOCKED
            )

            updated_case = transition_case(case, to_state=to_state, closure_reason=closure_reason)
            await self._case_repo.save_case(updated_case)

            await self._audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    case_id=case.case_id,
                    event_type=AuditEventType.NOTIFICATION_SUPPRESSED,
                    actor_type=ActorType.SYSTEM,
                    metadata={
                        "reason": f"Consent is {consent_status.value}; notification suppressed.",
                        "channel": channel.value,
                        "action_id": action_id,
                    },
                    timestamp=now,
                )
            )
            return None

        # Step 2: Construct tokenized/masked recipient reference
        masked_recipient = (
            customer.masked_phone or customer.masked_email or "+91******0000"
            if customer
            else "+91******0000"
        )

        notification_id = f"notif_{uuid.uuid4().hex[:12]}"
        notification = NotificationLog(
            notification_id=notification_id,
            case_id=case.case_id,
            action_id=action_id,
            channel=channel,
            template_key=template_key,
            masked_recipient=masked_recipient,
            link_reference=link_reference,
            status=NotificationStatus.SIMULATED,
            simulated_at=now,
        )
        await self._notif_repo.save_notification(notification)

        # Step 3: Increment case contact count
        updated_case = case.model_copy(
            update={
                "contact_count": case.contact_count + 1,
                "updated_at": now,
            }
        )
        await self._case_repo.save_case(updated_case)

        # Step 4: Record audit log entry
        await self._audit_repo.record_audit_event(
            AuditEvent(
                event_id=f"aud_{uuid.uuid4().hex[:12]}",
                case_id=case.case_id,
                event_type=AuditEventType.NOTIFICATION_SIMULATED,
                actor_type=ActorType.SYSTEM,
                metadata={
                    "notification_id": notification_id,
                    "channel": channel.value,
                    "template_key": template_key.value,
                    "masked_recipient": masked_recipient,
                    "link_reference": link_reference,
                },
                timestamp=now,
            )
        )

        return notification
