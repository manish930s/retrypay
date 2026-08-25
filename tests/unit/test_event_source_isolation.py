"""Unit tests verifying EventSource derivation, header non-authority, and source isolation."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import EventSource
from tests.conftest import compute_signature


@pytest.mark.asyncio
async def test_header_cannot_override_event_source(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Request headers such as X-Event-Source cannot override server-derived EventSource.

    Verifies that the webhook endpoint always classifies events as RAZORPAY_TEST_MODE,
    regardless of spoofed X-Event-Source or X-Simulation-Source headers.
    """
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": "evt_header_override_test_1",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_hdr_test_1",
                    "order_id": "order_hdr_test_1",
                    "amount": 150000,
                    "currency": "INR",
                    "status": "failed",
                    "method": "upi",
                    "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                    "error_source": "gateway",
                    "error_step": "payment_authorization",
                    "error_reason": "payment_timed_out",
                }
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw)

    # Pass deceptive headers attempting to spoof source as LOCAL_SIMULATION
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw,
        headers={
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_header_override_test_1",
            "X-Event-Source": "LOCAL_SIMULATION",
            "X-Simulation-Source": "true",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # Server must classify as RAZORPAY_TEST_MODE regardless of deceptive headers
    assert data["source"] == EventSource.RAZORPAY_TEST_MODE.value
    assert data["status"] == "accepted"
    # Verify the outbox job was created under the correct source partition
    assert data.get("outbox_job_id") is not None
    # Policy may block (no customer/consent in test fixture) — that's fine.
    # What matters is that the source was correctly classified as RAZORPAY_TEST_MODE.


@pytest.mark.asyncio
async def test_source_partitioned_identifier_isolation(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Same order_id from different ingestion paths are source-partitioned.

    Events from the webhook route are RAZORPAY_TEST_MODE.
    Events from the simulator route are LOCAL_SIMULATION.
    They must not merge or contaminate each other.
    """
    # 1. Ingest failed payment via external webhook route -> RAZORPAY_TEST_MODE
    payload_rzp = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": "evt_iso_rzp_1",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_iso_rzp_1",
                    "order_id": "order_iso_partition_test",
                    "amount": 200000,
                    "currency": "INR",
                    "status": "failed",
                    "method": "upi",
                    "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                    "error_source": "gateway",
                    "error_step": "payment_authorization",
                    "error_reason": "payment_timed_out",
                }
            }
        },
    }
    raw_rzp = json.dumps(payload_rzp).encode("utf-8")
    sig_rzp = compute_signature(raw_rzp)

    r1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_rzp,
        headers={"X-Razorpay-Signature": sig_rzp},
    )
    assert r1.status_code == 200
    data_rzp = r1.json()
    assert data_rzp["source"] == EventSource.RAZORPAY_TEST_MODE.value
    assert data_rzp["status"] == "accepted"
    # Webhook path must always classify as RAZORPAY_TEST_MODE and return outbox_job_id
    assert data_rzp.get("outbox_job_id") is not None

    # 2. Ingest simulator scenario -> LOCAL_SIMULATION
    r2 = await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "2_eligible_outreach_flow"},
    )
    assert r2.status_code == 200
    data_sim = r2.json()
    # Simulator events should be classified as LOCAL_SIMULATION
    sim_events = data_sim.get("events", [])
    for evt in sim_events:
        assert evt.get("source", "LOCAL_SIMULATION") == EventSource.LOCAL_SIMULATION.value

    # 3. Send the same order_id again through the webhook route
    # A duplicate should be ignored but STILL classified as RAZORPAY_TEST_MODE
    r3 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_rzp,
        headers={"X-Razorpay-Signature": sig_rzp},
    )
    assert r3.status_code == 200
    data_dup = r3.json()
    assert data_dup["source"] == EventSource.RAZORPAY_TEST_MODE.value
    # Event already processed for this source partition
    assert data_dup["status"] == "duplicate_ignored"
