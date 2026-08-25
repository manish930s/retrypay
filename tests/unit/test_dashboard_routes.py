"""Unit tests for operator dashboard API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_overview_endpoint(test_client: AsyncClient) -> None:
    resp = await test_client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_failed_events" in data
    assert "active_cases_count" in data
    assert "active_cases_by_state" in data
    assert "policy_block_rate" in data
    assert "recent_cases" in data
    assert "latest_audit_activity" in data


@pytest.mark.asyncio
async def test_dashboard_cases_filter_and_pagination(test_client: AsyncClient) -> None:
    # 1. Trigger a test scenario first to have case data
    await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "2_eligible_outreach_flow"},
    )

    resp = await test_client.get("/api/v1/dashboard/cases?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_dashboard_case_detail_not_found(test_client: AsyncClient) -> None:
    resp = await test_client.get("/api/v1/dashboard/cases/nonexistent_case_123")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dashboard_evaluation_report_endpoint(test_client: AsyncClient) -> None:
    resp = await test_client.get("/api/v1/dashboard/evaluation")
    assert resp.status_code == 200
    data = resp.json()
    assert "disclaimer" in data
    assert data["disclaimer"] == "simulated offline estimate; not production conversion evidence"
    assert "arm_metrics" in data
    assert "RETRYPAY_POLICY" in data["arm_metrics"]
    assert "NO_ACTION" in data["arm_metrics"]
    assert "ci_incremental_conversion" in data


@pytest.mark.asyncio
async def test_dashboard_settings_endpoint(test_client: AsyncClient) -> None:
    resp = await test_client.get("/api/v1/dashboard/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["policy_version"] == "recovery-v1.3"
    assert "guardrails" in data
    assert (
        data["guardrails"]["single_action_limit_paise"] == 1_000_000
    )  # ₹10,000 max single action limit


@pytest.mark.asyncio
async def test_dashboard_audit_dto_serialization_security(test_client: AsyncClient) -> None:
    """Assert forbidden field names and sensitive values cannot appear in audit DTOs."""
    # 1. Trigger an eligible flow
    t_resp = await test_client.post(
        "/api/v1/simulator/trigger",
        json={"scenario_id": "2_eligible_outreach_flow"},
    )
    assert t_resp.status_code == 200
    case_id = t_resp.json()["case_id"]

    # 2. Check overview audit events
    ov_resp = await test_client.get("/api/v1/dashboard/overview")
    assert ov_resp.status_code == 200
    ov_data = ov_resp.json()
    assert "latest_audit_activity" in ov_data

    # 3. Check case detail audit events
    cd_resp = await test_client.get(f"/api/v1/dashboard/cases/{case_id}")
    assert cd_resp.status_code == 200
    cd_data = cd_resp.json()
    assert "audit_events" in cd_data

    forbidden_terms = (
        "secret",
        "signature",
        "raw_payload",
        "webhook_body",
        "prompt",
        "potential_outcome",
        "unassigned",
        "stack_trace",
        "api_key",
        "password",
    )

    allowed_dto_fields = {
        "event_id",
        "source",
        "case_id",
        "event_type",
        "actor_type",
        "before_state",
        "after_state",
        "safe_reason_code",
        "version_info",
        "timestamp",
        "sanitized_metadata",
    }

    all_audits = ov_data["latest_audit_activity"] + cd_data["audit_events"]
    assert len(all_audits) > 0

    for a in all_audits:
        # Assert strictly allowlisted fields
        assert set(a.keys()) == allowed_dto_fields
        # Assert metadata is sanitized dict
        assert isinstance(a["sanitized_metadata"], dict)

        import json

        raw_serialized = json.dumps(a).lower()
        for term in forbidden_terms:
            assert term not in raw_serialized, f"Found forbidden term '{term}' in audit DTO: {a}"
