"""Unit tests for webhook simulator and demo orchestrator routes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_simulator_scenarios(test_client: AsyncClient) -> None:
    resp = await test_client.get("/api/v1/simulator/scenarios")
    assert resp.status_code == 200
    scenarios = resp.json()
    assert len(scenarios) == 14
    scenario_ids = [s["id"] for s in scenarios]
    assert "1_policy_block_missing_consent" in scenario_ids
    assert "2_eligible_outreach_flow" in scenario_ids
    assert "3_duplicate_event_deduplication" in scenario_ids
    assert "4_invalid_signature_rejection" in scenario_ids
    assert "6_sequence_a_link_paid_then_captured" in scenario_ids
    assert "7_sequence_b_capture_then_link_paid" in scenario_ids


@pytest.mark.asyncio
async def test_trigger_invalid_signature_scenario(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "4_invalid_signature_rejection"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["final_case_state"] == "REJECTED"


@pytest.mark.asyncio
async def test_trigger_sequence_a_scenario(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "6_sequence_a_link_paid_then_captured"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["final_case_state"] == "RECOVERED"
    assert data["closure_reason"] == "RECOVERED_VIA_LINK"


@pytest.mark.asyncio
async def test_trigger_sequence_b_scenario(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "7_sequence_b_capture_then_link_paid"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["final_case_state"] == "RECOVERED"
    assert data["closure_reason"] == "RECOVERED_VIA_LINK"


@pytest.mark.asyncio
async def test_simulator_reset_endpoint(test_client: AsyncClient) -> None:
    resp = await test_client.post("/api/v1/simulator/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_trigger_high_risk_manual_review_scenario(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "12_high_risk_manual_review"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["final_case_state"] == "MANUAL_REVIEW"
    assert data["closure_reason"] is None
