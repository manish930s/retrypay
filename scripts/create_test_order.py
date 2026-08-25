"""CLI script to create a test order for Razorpay Test Mode smoke testing."""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime

import httpx

from retrypay.config import get_settings
from retrypay.domain.models import EventSource, Order, OrderStatus
from retrypay.storage.database import (
    get_engine,
    get_session_factory,
    init_db,
    verify_database_routing_preflight,
)
from retrypay.storage.repositories.orders import OrderRepository


async def create_test_order(amount_paise: int = 250000, currency: str = "INR") -> int:
    """Create order via Razorpay API when provider mode enabled; persist to database."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    settings = get_settings()
    verify_database_routing_preflight(settings)

    # Safety check on live key
    if settings.RAZORPAY_KEY_ID.startswith("rzp_live_"):
        print("CRITICAL SECURITY VIOLATION: Cannot run with live Razorpay keys.", file=sys.stderr)
        return 1

    actual_order_id: str
    now = datetime.now(UTC)

    if (
        settings.RAZORPAY_PROVIDER_ENABLED
        and settings.RAZORPAY_KEY_ID
        and not settings.RAZORPAY_KEY_ID.startswith("rzp_test_fixture")
    ):
        print(f"Creating Razorpay Order via API (amount: ₹{amount_paise / 100:.2f} {currency})...")
        url = "https://api.razorpay.com/v1/orders"
        auth = (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        receipt = f"rcpt_{uuid.uuid4().hex[:10]}"
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": {
                "purpose": "ReTryPay Test Mode Smoke Test",
                "environment": settings.RETRYPAY_ENV.value,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, auth=auth)
            if resp.status_code in (200, 201):
                data = resp.json()
                actual_order_id = data["id"]
                print("✓ Real Razorpay Order created successfully!")
                print(f"  • Razorpay Order ID: {actual_order_id}")
                print(f"  • Receipt:          {receipt}")
            else:
                print(
                    f"ERROR: Razorpay Orders API returned HTTP {resp.status_code}: {resp.text}",
                    file=sys.stderr,
                )
                return 1
        except Exception as exc:
            print(f"ERROR: Failed to connect to Razorpay API: {exc}", file=sys.stderr)
            return 1
    else:
        actual_order_id = f"order_{uuid.uuid4().hex[:12]}"
        print(f"Creating local test order (simulated): {actual_order_id}")

    # Persist order to database
    engine = get_engine(settings.DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        order_repo = OrderRepository(session)
        order = Order(
            order_id=actual_order_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            amount_paise=amount_paise,
            currency=currency,
            status=OrderStatus.ATTEMPTED,
            created_at=now,
            updated_at=now,
        )
        await order_repo.save_order(order, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    print("\n[SUCCESS] Order persisted to database.")
    print(f"  • Order ID: {actual_order_id}")
    print(f"  • Status:   {OrderStatus.ATTEMPTED.value}")
    print(f"  • Amount:   ₹{amount_paise / 100:.2f} {currency}")
    return 0


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Create a test order for Razorpay Test Mode")
    parser.add_argument(
        "--amount", type=int, default=250000, help="Amount in paise (default: 250000 = ₹2500)"
    )
    parser.add_argument("--currency", type=str, default="INR", help="Currency code (default: INR)")
    args = parser.parse_args()

    sys.exit(asyncio.run(create_test_order(amount_paise=args.amount, currency=args.currency)))


if __name__ == "__main__":
    main()
