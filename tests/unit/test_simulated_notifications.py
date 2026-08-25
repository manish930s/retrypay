"""Unit tests for SimulatedNotificationDispatcher consent re-checks and template validation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    NotificationStatus,
    NotificationTemplateKey,
    RecoveryCase,
    RecoveryCaseState,
)
from retrypay.notifications.dispatcher import SimulatedNotificationDispatcher
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository


@pytest.mark.asyncio
async def test_simulated_notification_success_when_opted_in(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure simulated notification succeeds when customer has OPTED_IN consent."""
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        case_repo = RecoveryCaseRepository(session)

        customer = Customer(
            customer_id="cust_test_notif_001",
            masked_phone="+91******1234",
            masked_email="u***@example.com",
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )

        case = RecoveryCase(
            case_id="rcv_test_notif_001",
            order_id="order_test_notif_001",
            failed_attempt_id="pay_test_001",
            customer_id=customer.customer_id,
            state=RecoveryCaseState.LINK_CREATED,
        )
        await case_repo.save_case(case)
        await session.commit()

        dispatcher = SimulatedNotificationDispatcher(session)
        notif = await dispatcher.dispatch_simulated_notification(
            case=case,
            action_id="act_test_001",
            channel=ContactChannel.WHATSAPP,
            template_key=NotificationTemplateKey.PAYMENT_RETRY_GENERIC,
            link_reference="https://rzp.io/i/fake_123",
        )
        await session.commit()

        assert notif is not None
        assert notif.status == NotificationStatus.SIMULATED
        assert notif.masked_recipient == "+91******1234"
        assert notif.template_key == NotificationTemplateKey.PAYMENT_RETRY_GENERIC

        # Case contact count should have incremented
        updated_case = await case_repo.get_case(case.case_id)
        assert updated_case is not None
        assert updated_case.contact_count == 1


@pytest.mark.asyncio
async def test_simulated_notification_suppressed_when_opted_out(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure simulated notification is suppressed and case transitions to OPTED_OUT."""
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        case_repo = RecoveryCaseRepository(session)

        customer = Customer(
            customer_id="cust_test_optout_001",
            masked_phone="+91******1234",
            masked_email="u***@example.com",
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_OUT,
            )
        )

        case = RecoveryCase(
            case_id="rcv_test_optout_001",
            order_id="order_test_optout_001",
            failed_attempt_id="pay_test_001",
            customer_id=customer.customer_id,
            state=RecoveryCaseState.LINK_CREATED,
        )
        await case_repo.save_case(case)
        await session.commit()

        dispatcher = SimulatedNotificationDispatcher(session)
        notif = await dispatcher.dispatch_simulated_notification(
            case=case,
            action_id="act_test_001",
            channel=ContactChannel.WHATSAPP,
            template_key=NotificationTemplateKey.PAYMENT_RETRY_GENERIC,
            link_reference="https://rzp.io/i/fake_123",
        )
        await session.commit()

        assert notif is None

        # Case must be in terminal OPTED_OUT state
        updated_case = await case_repo.get_case(case.case_id)
        assert updated_case is not None
        assert updated_case.state == RecoveryCaseState.OPTED_OUT
        assert updated_case.closed_at is not None
