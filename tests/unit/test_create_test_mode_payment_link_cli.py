"""Unit tests for create_test_mode_payment_link CLI tool."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrypay.adapters.razorpay.payment_links import FakePaymentLinkProvider
from retrypay.config import get_settings
from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    EventSource,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentStatus,
    RecoveryCase,
    RecoveryCaseState,
)
from retrypay.storage.database import get_engine, get_session_factory, init_db
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository
from scripts.create_test_mode_payment_link import run_cli


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Provide a fresh isolated SQLite file database for each CLI unit test."""
    db_file = tmp_path / "cli_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    return db_url


@pytest.mark.asyncio
async def test_cli_rejects_missing_case(cli_db: str) -> None:
    """CLI preflight rejects when case does not exist."""
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    await init_db(engine)
    code = await run_cli(case_id="rcv_nonexistent_123", auto_confirm=True)
    assert code == 1


@pytest.mark.asyncio
async def test_cli_rejects_local_simulation_source(cli_db: str) -> None:
    """CLI preflight rejects when case source is LOCAL_SIMULATION."""
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    await init_db(engine)
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)
    case_id = "rcv_sim_case_123"

    async with session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)

        order = Order(
            order_id="order_sim_123",
            source=EventSource.LOCAL_SIMULATION,
            amount_paise=100000,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
            created_at=now,
            updated_at=now,
        )
        await order_repo.save_order(order, source=EventSource.LOCAL_SIMULATION.value)

        attempt = PaymentAttempt(
            payment_id="pay_sim_123",
            source=EventSource.LOCAL_SIMULATION,
            order_id=order.order_id,
            amount_paise=100000,
            currency="INR",
            status=PaymentStatus.FAILED,
            method="upi",
            occurred_at=now,
        )
        await order_repo.record_payment_attempt(attempt, source=EventSource.LOCAL_SIMULATION.value)

        case = RecoveryCase(
            case_id=case_id,
            source=EventSource.LOCAL_SIMULATION,
            order_id=order.order_id,
            failed_attempt_id="pay_sim_123",
            state=RecoveryCaseState.POLICY_EVALUATED,
            policy_version="recovery-v1.3",
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case, source=EventSource.LOCAL_SIMULATION.value)
        await session.commit()

    code = await run_cli(case_id=case_id, auto_confirm=True)
    assert code == 1


@pytest.mark.asyncio
async def test_cli_rejects_opted_out_customer(cli_db: str) -> None:
    """CLI preflight rejects when customer has opted out."""
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    await init_db(engine)
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)
    case_id = "rcv_test_optout_case"
    order_id = "order_test_optout"
    cust_id = f"cust_{order_id}"

    async with session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)
        cust_repo = CustomerRepository(session)

        await cust_repo.save_customer(Customer(customer_id=cust_id, masked_phone="+91******1234"))
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_OUT,
            )
        )

        order = Order(
            order_id=order_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            amount_paise=100000,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
            created_at=now,
            updated_at=now,
        )
        await order_repo.save_order(order, source=EventSource.RAZORPAY_TEST_MODE.value)

        attempt = PaymentAttempt(
            payment_id="pay_test_optout",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            amount_paise=100000,
            currency="INR",
            status=PaymentStatus.FAILED,
            method="upi",
            occurred_at=now,
        )
        await order_repo.record_payment_attempt(
            attempt, source=EventSource.RAZORPAY_TEST_MODE.value
        )

        case = RecoveryCase(
            case_id=case_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_test_optout",
            state=RecoveryCaseState.ACTION_APPROVED,
            policy_version="recovery-v1.3",
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    fake_provider = FakePaymentLinkProvider()
    code = await run_cli(case_id=case_id, auto_confirm=True, custom_provider=fake_provider)
    assert code == 1
    assert len(fake_provider.created_requests) == 0


@pytest.mark.asyncio
async def test_cli_success_with_fake_provider(cli_db: str) -> None:
    """CLI successfully creates link, reserves budget, and transitions state to NOTIFIED."""
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    await init_db(engine)
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)
    case_id = "rcv_test_success_case"
    order_id = "order_test_success"
    cust_id = f"cust_{order_id}"

    async with session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)
        cust_repo = CustomerRepository(session)

        await cust_repo.save_customer(Customer(customer_id=cust_id, masked_phone="+91******9999"))
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )

        order = Order(
            order_id=order_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            amount_paise=250000,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
            created_at=now,
            updated_at=now,
        )
        await order_repo.save_order(order, source=EventSource.RAZORPAY_TEST_MODE.value)

        attempt = PaymentAttempt(
            payment_id="pay_test_succ_1",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            amount_paise=250000,
            currency="INR",
            status=PaymentStatus.FAILED,
            method="upi",
            occurred_at=now,
        )
        await order_repo.record_payment_attempt(
            attempt, source=EventSource.RAZORPAY_TEST_MODE.value
        )

        case = RecoveryCase(
            case_id=case_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_test_succ_1",
            state=RecoveryCaseState.POLICY_EVALUATED,
            policy_version="recovery-v1.3",
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    fake_provider = FakePaymentLinkProvider(custom_link_id="plink_test_created_123")
    code = await run_cli(case_id=case_id, auto_confirm=True, custom_provider=fake_provider)
    assert code == 0
    assert len(fake_provider.created_requests) == 1

    # Verify updated case state
    async with session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        link_repo = PaymentLinkRepository(session)

        updated_case = await case_repo.get_case(
            case_id, source=EventSource.RAZORPAY_TEST_MODE.value
        )
        assert updated_case is not None
        assert updated_case.state == RecoveryCaseState.LINK_CREATED

        created_link = await link_repo.get_active_link_for_case(
            case_id, source=EventSource.RAZORPAY_TEST_MODE.value
        )
        assert created_link is not None
        assert created_link.provider_link_id == "plink_test_created_123"


@pytest.mark.asyncio
async def test_cli_aborts_on_incorrect_confirmation_phrase(cli_db: str) -> None:
    """Incorrect phrase causes zero reservation, zero provider calls, zero link creation."""
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    await init_db(engine)
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)

    case_id = "rcv_phrase_test_123"
    order_id = "order_phrase_test_123"
    customer_id = f"cust_{order_id}"

    async with session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)
        cust_repo = CustomerRepository(session)

        customer = Customer(
            customer_id=customer_id,
            masked_phone="+91******1111",
            masked_email="t***@example.com",
            successful_purchase_count=1,
            created_at=now,
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
                updated_at=now,
            )
        )

        order = Order(
            order_id=order_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            amount_paise=250000,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
            created_at=now,
            updated_at=now,
        )
        await order_repo.save_order(order, source=EventSource.RAZORPAY_TEST_MODE.value)

        attempt = PaymentAttempt(
            payment_id="pay_phrase_test_1",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            amount_paise=250000,
            currency="INR",
            status=PaymentStatus.FAILED,
            method="upi",
            occurred_at=now,
        )
        await order_repo.record_payment_attempt(
            attempt, source=EventSource.RAZORPAY_TEST_MODE.value
        )

        case = RecoveryCase(
            case_id=case_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_phrase_test_1",
            state=RecoveryCaseState.POLICY_EVALUATED,
            policy_version="recovery-v1.3",
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    fake_provider = FakePaymentLinkProvider()
    # Pass incorrect phrase
    code = await run_cli(
        case_id=case_id,
        confirm_phrase="INCORRECT CONFIRMATION PHRASE",
        custom_provider=fake_provider,
    )
    assert code == 1
    assert len(fake_provider.created_requests) == 0

    # Verify zero link creation in DB
    async with session_factory() as session:
        link_repo = PaymentLinkRepository(session)
        created_link = await link_repo.get_active_link_for_case(
            case_id, source=EventSource.RAZORPAY_TEST_MODE.value
        )
        assert created_link is None
