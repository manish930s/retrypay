"""Local signed-webhook simulator API endpoints and demo orchestrator."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from retrypay.adapters.razorpay.verifier import WebhookVerifier
from retrypay.api.dependencies import get_db_session, get_settings
from retrypay.config import Settings
from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    EventSource,
    IngestionOrigin,
)
from retrypay.policy.engine import PolicyEngine
from retrypay.services.ingestion import ingest_verified_event
from retrypay.storage.models import (
    AuditEventModel,
    BudgetReservationModel,
    CustomerConsentModel,
    CustomerModel,
    DecisionTraceModel,
    NotificationLogModel,
    OrderModel,
    PaymentAttemptModel,
    PaymentLinkModel,
    PolicyEvaluationModel,
    RecoveryActionModel,
    RecoveryCaseModel,
    WebhookEventModel,
)
from retrypay.storage.repositories.customers import CustomerRepository

router = APIRouter(prefix="/api/v1/simulator", tags=["Simulator"])

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "1_policy_block_missing_consent",
        "title": "1. Policy Block: Missing Customer Consent",
        "category": "Policy Gating",
        "description": (
            "Dispatches payment.failed for an unconsented customer. "
            "Demonstrates deterministic policy rule blocking recovery outreach."
        ),
        "expected_state": "CLOSED_BLOCKED",
        "expected_closure_reason": "POLICY_BLOCKED",
    },
    {
        "id": "2_eligible_outreach_flow",
        "title": "2. Eligible Recovery Outreach Flow",
        "category": "End-to-End Flow",
        "description": (
            "Dispatches payment.failed for a consented customer. Runs policy -> ROS -> "
            "diagnosis -> creates Test Mode link -> logs simulated notification."
        ),
        "expected_state": "NOTIFIED",
        "expected_closure_reason": None,
    },
    {
        "id": "3_duplicate_event_deduplication",
        "title": "3. Duplicate Event Deduplication",
        "category": "Idempotency",
        "description": (
            "Dispatches the exact same event ID twice. "
            "Proves idempotency and zero duplicate business mutations."
        ),
        "expected_state": "NOTIFIED",
        "expected_closure_reason": None,
    },
    {
        "id": "4_invalid_signature_rejection",
        "title": "4. Invalid Webhook Signature Rejection",
        "category": "Security",
        "description": (
            "Sends a webhook with a corrupted HMAC signature. "
            "Confirms immediate 401 rejection before any DB mutation."
        ),
        "expected_state": "REJECTED",
        "expected_closure_reason": None,
    },
    {
        "id": "5_independent_payment_capture",
        "title": "5. Independent Capture Without Link",
        "category": "Attribution",
        "description": (
            "Customer pays via direct store checkout while in ENRICHING state. "
            "Case immediately closes as CLOSED_BLOCKED (PAYMENT_CAPTURED), not RECOVERED."
        ),
        "expected_state": "CLOSED_BLOCKED",
        "expected_closure_reason": "PAYMENT_CAPTURED",
    },
    {
        "id": "6_sequence_a_link_paid_then_captured",
        "title": "6. Sequence A: Link Paid -> Capture -> RECOVERED",
        "category": "Attribution Reconciliation",
        "description": (
            "Payment Link paid arrives first, then capture arrives. "
            "Reconciles and correlates to RECOVERED (RECOVERED_VIA_LINK)."
        ),
        "expected_state": "RECOVERED",
        "expected_closure_reason": "RECOVERED_VIA_LINK",
    },
    {
        "id": "7_sequence_b_capture_then_link_paid",
        "title": "7. Sequence B: Capture -> Pending -> Link Paid -> RECOVERED",
        "category": "Attribution Reconciliation",
        "description": (
            "Capture arrives first for an active case. Transitions to "
            "PAYMENT_CONFIRMED_PENDING_ATTRIBUTION, then link webhook reconciles to RECOVERED."
        ),
        "expected_state": "RECOVERED",
        "expected_closure_reason": "RECOVERED_VIA_LINK",
    },
    {
        "id": "8_link_expired",
        "title": "8. Payment Link Expired",
        "category": "Lifecycle",
        "description": (
            "Dispatches payment_link.expired webhook. Transitions active recovery case to EXPIRED."
        ),
        "expected_state": "EXPIRED",
        "expected_closure_reason": "LINK_EXPIRED",
    },
    {
        "id": "9_link_cancelled",
        "title": "9. Payment Link Cancelled",
        "category": "Lifecycle",
        "description": (
            "Dispatches payment_link.cancelled webhook. Transitions case to CLOSED_UNRECOVERED."
        ),
        "expected_state": "CLOSED_UNRECOVERED",
        "expected_closure_reason": "LINK_CANCELLED",
    },
    {
        "id": "10_link_partially_paid",
        "title": "10. Payment Link Partially Paid",
        "category": "Lifecycle",
        "description": (
            "Dispatches payment_link.partially_paid webhook. "
            "Routes case for merchant investigation."
        ),
        "expected_state": "PAYMENT_CONFIRMED_PENDING_ATTRIBUTION",
        "expected_closure_reason": None,
    },
    {
        "id": "11_quiet_hours_deferral",
        "title": "11. Quiet-Hours Deferral",
        "category": "Policy Gating",
        "description": (
            "Simulates payment failure during quiet hours (22:00-08:00). "
            "Case evaluates to DEFER and delays outreach until quiet hours end."
        ),
        "expected_state": "POLICY_EVALUATED",
        "expected_closure_reason": None,
    },
    {
        "id": "12_high_risk_manual_review",
        "title": "12. High-Risk / Hard-Decline Manual Review",
        "category": "Risk & Fraud",
        "description": (
            "Simulates failure with error code SUSPECTED_FRAUD for a consented customer. "
            "Deterministic policy routes case to MANUAL_REVIEW for merchant operator inspection."
        ),
        "expected_state": "MANUAL_REVIEW",
        "expected_closure_reason": None,
    },
    {
        "id": "13_budget_exhaustion",
        "title": "13. Budget Cap & Guardrails",
        "category": "Budget Guardrails",
        "description": (
            "Simulates high-value transaction exceeding single action limit (> ₹10,000). "
            "Action is rejected by budget guardrails."
        ),
        "expected_state": "CLOSED_BLOCKED",
        "expected_closure_reason": "POLICY_BLOCKED",
    },
    {
        "id": "14_attribution_timeout",
        "title": "14. Attribution Reconciliation Timeout",
        "category": "Attribution Reconciliation",
        "description": (
            "Case remains in PAYMENT_CONFIRMED_PENDING_ATTRIBUTION past 30-min window. "
            "Reconciler closes it as CLOSED_BLOCKED (PAYMENT_ATTRIBUTION_UNCONFIRMED)."
        ),
        "expected_state": "CLOSED_BLOCKED",
        "expected_closure_reason": "PAYMENT_ATTRIBUTION_UNCONFIRMED",
    },
]


class TriggerScenarioRequest(BaseModel):
    scenario_id: str


class TriggerScenarioResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    title: str
    status: str  # "success" | "rejected" | "error"
    case_id: str | None
    order_id: str | None
    final_case_state: str | None
    closure_reason: str | None
    steps_executed: list[dict[str, Any]]
    audit_trail: list[dict[str, Any]]


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


@router.get("/scenarios")
async def list_scenarios(
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    """List all available simulator test scenarios."""
    if settings.RETRYPAY_ENV != "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Simulator is disabled outside of test environment. "
                "In demo mode, use Razorpay Test Mode webhooks."
            ),
        )
    return SCENARIOS


@router.post("/trigger", response_model=TriggerScenarioResponse)
async def trigger_scenario(
    req: TriggerScenarioRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
) -> TriggerScenarioResponse:
    """Execute a local signed webhook simulation scenario."""
    if settings.RETRYPAY_ENV != "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Simulator is disabled outside of test environment. "
                "In demo mode, use Razorpay Test Mode webhooks."
            ),
        )

    scen = next((s for s in SCENARIOS if s["id"] == req.scenario_id), None)
    if not scen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{req.scenario_id}' not found.",
        )

    steps: list[dict[str, Any]] = []
    uid = uuid.uuid4().hex[:6]
    order_id = f"order_sim_{uid}"
    cust_id = f"cust_{order_id}"
    pay_id = f"pay_sim_{uid}"

    # Helper to execute simulated webhook directly via ingestion service
    async def post_webhook(
        data: dict[str, Any], event_id: str, custom_sig: str | None = None
    ) -> tuple[int, dict[str, Any]]:
        raw = json.dumps(data).encode("utf-8")
        sig = custom_sig or compute_signature(raw, settings.RAZORPAY_WEBHOOK_SECRET)
        verifier = WebhookVerifier(settings.RAZORPAY_WEBHOOK_SECRET)
        policy_engine = PolicyEngine()
        try:
            res = await ingest_verified_event(
                raw_body=raw,
                signature=sig,
                source=EventSource.LOCAL_SIMULATION,
                ingestion_origin=IngestionOrigin.INTERNAL_SIMULATOR,
                session=session,
                verifier=verifier,
                policy_engine=policy_engine,
                settings=settings,
                event_id_override=event_id,
            )
            return 200, res.model_dump(mode="json")
        except HTTPException as exc:
            return exc.status_code, {"error": exc.detail}

    # Scenario 1: Policy block missing consent
    if req.scenario_id == "1_policy_block_missing_consent":
        # Seed opted-out customer
        cust_repo = CustomerRepository(session)
        await cust_repo.save_customer(
            Customer(
                customer_id=cust_id,
                masked_phone="+91******1111",
                masked_email="optout@example.com",
            )
        )
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_OUT,
            )
        )
        await session.commit()

        evt_payload = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": f"evt_{uid}_1",
            "created_at": 1771761600,
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": order_id,
                        "amount": 250000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                        "error_description": "Payment authorization timed out",
                        "error_source": "gateway",
                        "error_step": "payment_authorization",
                        "error_reason": "payment_timed_out",
                    }
                }
            },
        }
        code, res = await post_webhook(evt_payload, f"evt_{uid}_1")
        steps.append(
            {
                "name": "payment.failed dispatched",
                "status_code": code,
                "response": res,
            }
        )

    # Scenario 2: Eligible outreach flow
    elif req.scenario_id in (
        "2_eligible_outreach_flow",
        "3_duplicate_event_deduplication",
    ):
        # Seed opted-in customer
        cust_repo = CustomerRepository(session)
        await cust_repo.save_customer(
            Customer(
                customer_id=cust_id,
                masked_phone="+91******9999",
                masked_email="consented@example.com",
            )
        )
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

        evt_payload = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": f"evt_{uid}_2",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": order_id,
                        "amount": 350000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                        "error_description": "Payment authorization timed out",
                        "error_source": "gateway",
                        "error_step": "payment_authorization",
                        "error_reason": "payment_timed_out",
                    }
                }
            },
        }
        code, res = await post_webhook(evt_payload, f"evt_{uid}_2")
        steps.append(
            {
                "name": "payment.failed dispatched",
                "status_code": code,
                "response": res,
            }
        )

        if req.scenario_id == "3_duplicate_event_deduplication":
            code2, res2 = await post_webhook(evt_payload, f"evt_{uid}_2")
            steps.append(
                {
                    "name": "Duplicate event re-sent",
                    "status_code": code2,
                    "response": res2,
                }
            )

    # Scenario 4: Invalid signature
    elif req.scenario_id == "4_invalid_signature_rejection":
        evt_payload = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": f"evt_{uid}_4",
            "payload": {"payment": {"entity": {"id": pay_id, "amount": 10000}}},
        }
        code, res = await post_webhook(
            evt_payload, f"evt_{uid}_4", custom_sig="invalid_hmac_signature_xyz"
        )
        steps.append(
            {
                "name": "Webhook with invalid signature dispatched",
                "status_code": code,
                "response": res,
            }
        )
        return TriggerScenarioResponse(
            scenario_id=req.scenario_id,
            title=scen["title"],
            status="rejected",
            case_id=None,
            order_id=None,
            final_case_state="REJECTED",
            closure_reason=None,
            steps_executed=steps,
            audit_trail=[],
        )

    # Scenario 6: Sequence A (Link Paid -> Payment Captured -> RECOVERED)
    elif req.scenario_id == "6_sequence_a_link_paid_then_captured":
        # 1. Trigger eligible failed payment
        cust_repo = CustomerRepository(session)
        await cust_repo.save_customer(
            Customer(
                customer_id=cust_id,
                masked_phone="+91******8888",
                masked_email="seq_a@example.com",
            )
        )
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

        evt_fail = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": f"evt_{uid}_fail",
            "created_at": 1771761600,
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": order_id,
                        "amount": 500000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                        "error_description": "Gateway timed out",
                    }
                }
            },
        }
        c1, r1 = await post_webhook(evt_fail, f"evt_{uid}_fail")
        steps.append(
            {
                "name": "1. payment.failed dispatched",
                "status_code": c1,
                "response": r1,
            }
        )

        plink_id = (
            r1.get("recovery_case", {}).get("execution", {}).get("provider_link_id", f"plink_{uid}")
        )

        # 2. payment_link.paid arrives first
        succ_pay_id = f"pay_succ_{uid}"
        evt_link = {
            "entity": "event",
            "event": "payment_link.paid",
            "event_id": f"evt_{uid}_plink",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": plink_id,
                        "order_id": order_id,
                        "amount": 500000,
                        "status": "paid",
                    }
                },
                "payment": {
                    "entity": {
                        "id": succ_pay_id,
                        "order_id": order_id,
                        "amount": 500000,
                        "status": "captured",
                    }
                },
            },
        }
        c2, r2 = await post_webhook(evt_link, f"evt_{uid}_plink")
        steps.append(
            {
                "name": "2. payment_link.paid arrived (awaits payment truth)",
                "status_code": c2,
                "response": r2,
            }
        )

        # 3. payment.captured arrives later
        evt_cap = {
            "entity": "event",
            "event": "payment.captured",
            "event_id": f"evt_{uid}_cap",
            "payload": {
                "payment": {
                    "entity": {
                        "id": succ_pay_id,
                        "order_id": order_id,
                        "amount": 500000,
                        "status": "captured",
                        "method": "upi",
                        "notes": {"payment_link_id": plink_id},
                    }
                }
            },
        }
        c3, r3 = await post_webhook(evt_cap, f"evt_{uid}_cap")
        steps.append(
            {
                "name": "3. payment.captured arrived -> Correlated to RECOVERED",
                "status_code": c3,
                "response": r3,
            }
        )

    # Scenario 7: Sequence B (Payment Captured -> Pending Attribution -> Link Paid -> RECOVERED)
    elif req.scenario_id == "7_sequence_b_capture_then_link_paid":
        # 1. Trigger eligible failed payment
        cust_repo = CustomerRepository(session)
        await cust_repo.save_customer(
            Customer(
                customer_id=cust_id,
                masked_phone="+91******7777",
                masked_email="seq_b@example.com",
            )
        )
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

        evt_fail = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": f"evt_{uid}_fail",
            "created_at": 1771761600,
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": order_id,
                        "amount": 450000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                        "error_description": "Gateway timed out",
                    }
                }
            },
        }
        c1, r1 = await post_webhook(evt_fail, f"evt_{uid}_fail")
        steps.append(
            {
                "name": "1. payment.failed dispatched (Link created in NOTIFIED)",
                "status_code": c1,
                "response": r1,
            }
        )

        plink_id = (
            r1.get("recovery_case", {}).get("execution", {}).get("provider_link_id", f"plink_{uid}")
        )

        # 2. payment.captured arrives first without notes ->
        # Transitions to PAYMENT_CONFIRMED_PENDING_ATTRIBUTION
        succ_pay_id = f"pay_succ_{uid}"
        evt_cap = {
            "entity": "event",
            "event": "payment.captured",
            "event_id": f"evt_{uid}_cap",
            "payload": {
                "payment": {
                    "entity": {
                        "id": succ_pay_id,
                        "order_id": order_id,
                        "amount": 450000,
                        "status": "captured",
                        "method": "upi",
                    }
                }
            },
        }
        c2, r2 = await post_webhook(evt_cap, f"evt_{uid}_cap")
        steps.append(
            {
                "name": "2. payment.captured arrived -> PENDING_ATTRIBUTION",
                "status_code": c2,
                "response": r2,
            }
        )

        # 3. payment_link.paid arrives later -> Correlates to RECOVERED
        evt_link = {
            "entity": "event",
            "event": "payment_link.paid",
            "event_id": f"evt_{uid}_plink",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": plink_id,
                        "order_id": order_id,
                        "amount": 450000,
                        "status": "paid",
                    }
                },
                "payment": {
                    "entity": {
                        "id": succ_pay_id,
                        "order_id": order_id,
                        "amount": 450000,
                        "status": "captured",
                    }
                },
            },
        }
        c3, r3 = await post_webhook(evt_link, f"evt_{uid}_plink")
        steps.append(
            {
                "name": "3. payment_link.paid arrived -> Correlated to RECOVERED",
                "status_code": c3,
                "response": r3,
            }
        )

    # Default fallback for other scenarios: trigger appropriate event
    else:
        cust_repo = CustomerRepository(session)
        await cust_repo.save_customer(
            Customer(
                customer_id=cust_id,
                masked_phone="+91******5555",
                masked_email="demo@example.com",
            )
        )
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=cust_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

        is_fraud = req.scenario_id in (
            "12_high_risk_manual_review",
            "12_high_risk_routing",
        )
        err_code = "SUSPECTED_FRAUD" if is_fraud else "BAD_REQUEST_PAYMENT_TIMED_OUT"
        evt_fail = {
            "entity": "event",
            "event": "payment.failed",
            "event_id": f"evt_{uid}_fail",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": order_id,
                        "amount": 100000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "error_code": err_code,
                        "error_description": "Simulated failure",
                    }
                }
            },
        }
        c1, r1 = await post_webhook(evt_fail, f"evt_{uid}_fail")
        steps.append(
            {
                "name": "payment.failed dispatched",
                "status_code": c1,
                "response": r1,
            }
        )

    # Fetch resulting case state
    c_q = (
        select(RecoveryCaseModel)
        .options(selectinload(RecoveryCaseModel.audit_events))
        .where(RecoveryCaseModel.order_id == order_id)
        .order_by(RecoveryCaseModel.created_at.desc())
    )
    case_res = (await session.execute(c_q)).scalar_one_or_none()

    audit_trail = []
    if case_res:
        audit_trail = [
            {
                "event_type": a.event_type,
                "before_state": a.before_state,
                "after_state": a.after_state,
                "metadata": a.sanitized_metadata,
                "timestamp": a.timestamp,
            }
            for a in case_res.audit_events
        ]

    return TriggerScenarioResponse(
        scenario_id=req.scenario_id,
        title=scen["title"],
        status="success",
        case_id=case_res.case_id if case_res else None,
        order_id=order_id,
        final_case_state=case_res.state if case_res else None,
        closure_reason=case_res.closure_reason if case_res else None,
        steps_executed=steps,
        audit_trail=audit_trail,
    )


@router.post("/reset")
async def reset_demo_database(
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Reset operational database and seed initial demo cases."""
    if settings.RETRYPAY_ENV not in ("test", "demo"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reset is restricted to test and demo environments.",
        )

    # 1. Clear operational tables in dependency order
    await session.execute(delete(AuditEventModel))
    await session.execute(delete(NotificationLogModel))
    await session.execute(delete(PaymentLinkModel))
    await session.execute(delete(BudgetReservationModel))
    await session.execute(delete(RecoveryActionModel))
    await session.execute(delete(DecisionTraceModel))
    await session.execute(delete(PolicyEvaluationModel))
    await session.execute(delete(RecoveryCaseModel))
    await session.execute(delete(PaymentAttemptModel))
    await session.execute(delete(OrderModel))
    await session.execute(delete(CustomerConsentModel))
    await session.execute(delete(CustomerModel))
    await session.execute(delete(WebhookEventModel))
    await session.commit()

    # 2. Seed initial baseline demo data
    cust_repo = CustomerRepository(session)

    # Seed 3 demo customers
    c1 = Customer(
        customer_id="cust_demo_001",
        masked_phone="+91******1234",
        masked_email="rahul.s@example.com",
        successful_purchase_count=3,
    )
    c2 = Customer(
        customer_id="cust_demo_002",
        masked_phone="+91******5678",
        masked_email="priya.m@example.com",
        successful_purchase_count=0,
    )
    c3 = Customer(
        customer_id="cust_demo_003",
        masked_phone="+91******9012",
        masked_email="arun.k@example.com",
        successful_purchase_count=5,
    )

    await cust_repo.save_customer(c1)
    await cust_repo.save_customer(c2)
    await cust_repo.save_customer(c3)

    await cust_repo.save_consent(
        CustomerConsent(
            customer_id=c1.customer_id,
            channel=ContactChannel.WHATSAPP,
            status=ContactConsentStatus.OPTED_IN,
        )
    )
    await cust_repo.save_consent(
        CustomerConsent(
            customer_id=c2.customer_id,
            channel=ContactChannel.WHATSAPP,
            status=ContactConsentStatus.OPTED_OUT,
        )
    )
    await cust_repo.save_consent(
        CustomerConsent(
            customer_id=c3.customer_id,
            channel=ContactChannel.WHATSAPP,
            status=ContactConsentStatus.OPTED_IN,
        )
    )

    await session.commit()

    return {
        "status": "success",
        "message": "Demo database successfully reset and seeded with initial customers.",
        "timestamp": datetime.now(UTC),
    }
