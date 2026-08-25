"""CLI script to seed deterministic merchant demo data."""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient

from retrypay.api.app import app
from retrypay.api.routes.simulator import compute_signature
from retrypay.config import get_settings
from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
)
from retrypay.storage.database import get_engine, get_session_factory, init_db
from retrypay.storage.repositories.customers import CustomerRepository


async def async_main() -> None:
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)

    print("Seeding ReTryPay demo database...")
    async with session_factory() as session:
        cust_repo = CustomerRepository(session)

        # 1. Consented Customer with History
        c1 = Customer(
            customer_id="cust_demo_rahul",
            masked_phone="+91******1234",
            masked_email="rahul.sharma@example.com",
            successful_purchase_count=4,
        )
        await cust_repo.save_customer(c1)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=c1.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )

        # 2. Opted-out Customer
        c2 = Customer(
            customer_id="cust_demo_priya",
            masked_phone="+91******5678",
            masked_email="priya.mehta@example.com",
            successful_purchase_count=0,
        )
        await cust_repo.save_customer(c2)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=c2.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_OUT,
            )
        )

        # 3. High-Value Customer
        c3 = Customer(
            customer_id="cust_demo_arun",
            masked_phone="+91******9012",
            masked_email="arun.kumar@example.com",
            successful_purchase_count=8,
        )
        await cust_repo.save_customer(c3)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=c3.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )

        await session.commit()

    # 4. Trigger 3 diverse initial demo cases via internal webhook pipeline
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case 1: UPI Gateway Timeout -> Eligible -> Link Created -> Notified
        payload_1 = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": "evt_demo_seed_001",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_demo_upi_001",
                        "order_id": "order_demo_upi_001",
                        "amount": 299900,  # ₹2,999.00
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                        "error_description": "UPI PSP collect request timed out",
                        "error_source": "gateway",
                        "error_step": "payment_authorization",
                        "error_reason": "payment_timed_out",
                    }
                }
            },
        }
        raw_1 = str(payload_1).replace("'", '"').encode("utf-8")
        sig_1 = compute_signature(raw_1, settings.RAZORPAY_WEBHOOK_SECRET)
        await client.post(
            "/api/v1/webhooks/razorpay",
            content=raw_1,
            headers={"X-Razorpay-Signature": sig_1, "X-Razorpay-Event-Id": "evt_demo_seed_001"},
        )

        # Case 2: Opted-out Customer -> Policy Block
        payload_2 = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": "evt_demo_seed_002",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_demo_optout_002",
                        "order_id": "order_demo_optout_002",
                        "amount": 150000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "card",
                        "error_code": "AUTHENTICATION_FAILED",
                        "error_description": "OTP verification failed",
                        "error_source": "bank",
                        "error_step": "payment_authentication",
                        "error_reason": "otp_expired",
                    }
                }
            },
        }
        raw_2 = str(payload_2).replace("'", '"').encode("utf-8")
        sig_2 = compute_signature(raw_2, settings.RAZORPAY_WEBHOOK_SECRET)
        await client.post(
            "/api/v1/webhooks/razorpay",
            content=raw_2,
            headers={"X-Razorpay-Signature": sig_2, "X-Razorpay-Event-Id": "evt_demo_seed_002"},
        )

    print("Demo data seeded successfully.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
