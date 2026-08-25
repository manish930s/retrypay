"""Unit tests for operational and evaluation isolation.

Proves that SYNTHETIC_EVALUATION records cannot enter operational APIs,
operational cases list, case details, or dashboard metrics.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import EventSource, OrderStatus, RecoveryCaseState
from retrypay.storage.models import OrderModel, RecoveryCaseModel


@pytest.mark.asyncio
async def test_dashboard_rejects_synthetic_evaluation_source_query(
    test_client: AsyncClient,
) -> None:
    """GET /api/v1/dashboard/cases?source=SYNTHETIC_EVALUATION returns HTTP 400."""
    resp = await test_client.get(
        "/api/v1/dashboard/cases", params={"source": "SYNTHETIC_EVALUATION"}
    )
    assert resp.status_code == 400
    assert "SYNTHETIC_EVALUATION source cannot be queried" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_synthetic_evaluation_cases_excluded_from_operational_list(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Operational /api/v1/dashboard/cases list ignores synthetic evaluation cases."""
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        # Save operational case
        session.add(
            OrderModel(
                order_id="order_op_1",
                source=EventSource.RAZORPAY_TEST_MODE.value,
                amount_paise=100000,
                currency="INR",
                status=OrderStatus.ATTEMPTED.value,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            RecoveryCaseModel(
                case_id="rcv_op_1",
                order_id="order_op_1",
                failed_attempt_id="pay_op_1",
                source=EventSource.RAZORPAY_TEST_MODE.value,
                state=RecoveryCaseState.LINK_CREATED.value,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            )
        )
        # Save synthetic evaluation case
        session.add(
            OrderModel(
                order_id="order_synth_1",
                source=EventSource.SYNTHETIC_EVALUATION.value,
                amount_paise=100000,
                currency="INR",
                status=OrderStatus.ATTEMPTED.value,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            RecoveryCaseModel(
                case_id="rcv_synth_1",
                order_id="order_synth_1",
                failed_attempt_id="pay_synth_1",
                source=EventSource.SYNTHETIC_EVALUATION.value,
                state=RecoveryCaseState.LINK_CREATED.value,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    resp = await test_client.get("/api/v1/dashboard/cases")
    assert resp.status_code == 200
    items = resp.json()["items"]
    case_ids = [c["case_id"] for c in items]
    assert "rcv_op_1" in case_ids
    assert "rcv_synth_1" not in case_ids


@pytest.mark.asyncio
async def test_case_detail_returns_404_for_synthetic_case(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """GET /api/v1/dashboard/cases/{case_id} returns 404 for synthetic evaluation cases."""
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        session.add(
            OrderModel(
                order_id="order_synth_detail",
                source=EventSource.SYNTHETIC_EVALUATION.value,
                amount_paise=50000,
                currency="INR",
                status=OrderStatus.ATTEMPTED.value,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            RecoveryCaseModel(
                case_id="rcv_synth_detail",
                order_id="order_synth_detail",
                failed_attempt_id="pay_synth_detail",
                source=EventSource.SYNTHETIC_EVALUATION.value,
                state=RecoveryCaseState.LINK_CREATED.value,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    resp = await test_client.get("/api/v1/dashboard/cases/rcv_synth_detail")
    assert resp.status_code == 404
