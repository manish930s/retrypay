"""Automated 5-minute demo walkthrough script showcasing the 12 core ReTryPay milestones."""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient

from retrypay.api.app import app
from retrypay.config import get_settings
from retrypay.storage.database import get_engine, init_db


def banner(step_num: int, title: str) -> None:
    print("\n" + "=" * 75)
    print(f"STEP {step_num}: {title.upper()}")
    print("=" * 75)


async def async_main() -> None:
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    await init_db(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Reset database first
        await client.post("/api/v1/simulator/reset")

        # Step 1: Dashboard Overview
        banner(1, "The Recovery Problem & Operational Telemetry")
        r = await client.get("/api/v1/dashboard/overview")
        print("Initial Overview Metrics:")
        print(f"  Active Cases: {r.json()['active_cases_count']}")
        print(f"  Total Recovered: {r.json()['total_recovered_cases']}")
        print(f"  Policy Block Rate: {r.json()['policy_block_rate'] * 100:.1f}%")

        # Step 2 & 3: Webhook Verification & Deduplication
        banner(2, "Webhook Signature Verification & Deduplication")
        r_dup = await client.post(
            "/api/v1/simulator/trigger",
            json={"scenario_id": "3_duplicate_event_deduplication"},
        )
        print("Dispatched original and duplicate webhook event:")
        for st in r_dup.json()["steps_executed"]:
            print(f"  - {st['name']} -> Status: {st['status_code']}")

        # Step 4: Policy Gating (Opted-Out Customer Block)
        banner(3, "Deterministic Policy Gate: Hard Block on Opted-out Customer")
        r_blk = await client.post(
            "/api/v1/simulator/trigger",
            json={"scenario_id": "1_policy_block_missing_consent"},
        )
        print(f"Case ID: {r_blk.json()['case_id']}")
        print(f"Final State: {r_blk.json()['final_case_state']}")
        print(f"Closure Reason: {r_blk.json()['closure_reason']}")
        print("Audit Trail: " + " -> ".join([a["event_type"] for a in r_blk.json()["audit_trail"]]))

        # Step 5 to 9: Eligible Recovery Flow (Diagnosis, ROS, Link, Notification)
        banner(
            4,
            "Eligible Recovery Flow: Diagnosis, ROS, Budget Check & Notification",
        )
        r_elig = await client.post(
            "/api/v1/simulator/trigger",
            json={"scenario_id": "2_eligible_outreach_flow"},
        )
        case_id = r_elig.json()["case_id"]
        print(f"Created Eligible Recovery Case: {case_id}")
        print(f"Case State: {r_elig.json()['final_case_state']}")

        # Inspect case details
        detail = (await client.get(f"/api/v1/dashboard/cases/{case_id}")).json()
        diag_cat = detail["decision_trace"]["diagnosis_category"]
        diag_mode = detail["decision_trace"]["diagnosis_mode"]
        ros_score = detail["decision_trace"]["ros_score"]
        link_id_val = detail["payment_link"]["provider_link_id"]
        link_stat = detail["payment_link"]["status"]
        notif_ch = detail["notifications"][0]["channel"]
        notif_rec = detail["notifications"][0]["masked_recipient"]
        notif_stat = detail["notifications"][0]["status"]

        print("\nCase Decisioning & ROS Decomposition:")
        print(f"  Diagnosis: {diag_cat} (Mode: {diag_mode})")
        print(f"  ROS Score: {ros_score}/100")
        print(f"  Contributions: {detail['decision_trace']['ros_contributions']}")
        print(f"  Candidate Actions: {detail['decision_trace']['action_candidates']}")
        print(f"  Selected Action: {detail['decision_trace']['selected_action']}")
        print(f"  Payment Link: {link_id_val} ({link_stat})")
        print(f"  Notification: {notif_ch} -> {notif_rec} ({notif_stat})")

        # Step 10 & 11: Two-Evidence Attribution Reconciliation
        banner(
            5,
            "Attribution Sequence A: payment_link.paid -> payment.captured -> RECOVERED",
        )
        r_seq_a = await client.post(
            "/api/v1/simulator/trigger",
            json={"scenario_id": "6_sequence_a_link_paid_then_captured"},
        )
        print(f"Sequence A Final State: {r_seq_a.json()['final_case_state']}")
        print(f"Closure Reason: {r_seq_a.json()['closure_reason']}")

        banner(
            6,
            "Attribution Sequence B: payment.captured -> Pending -> Link Paid -> RECOVERED",
        )
        r_seq_b = await client.post(
            "/api/v1/simulator/trigger",
            json={"scenario_id": "7_sequence_b_capture_then_link_paid"},
        )
        print(f"Sequence B Final State: {r_seq_b.json()['final_case_state']}")
        print(f"Closure Reason: {r_seq_b.json()['closure_reason']}")

        # Step 12: Offline Causal Evaluation Dashboard
        banner(7, "Offline Counterfactual Evaluation (1,000 Synthetic Cases)")
        r_eval = await client.get("/api/v1/dashboard/evaluation")
        ev = r_eval.json()
        print(f"DISCLAIMER: {ev['disclaimer'].upper()}")
        print(f"Evaluation Run ID: {ev['evaluation_run_id']}")
        print(f"Natural Recovery Rate (NO_ACTION): {ev['natural_recovery_rate'] * 100:.2f}%")

        inc_conv = ev["estimated_incremental_recovery_conversion"] * 100
        ci_c_l = ev["ci_incremental_conversion"]["lower"] * 100
        ci_c_u = ev["ci_incremental_conversion"]["upper"] * 100
        print(
            f"Est. Incremental Recovery Conversion: +{inc_conv:.2f}% "
            f"(95% CI: [{ci_c_l:.2f}%, {ci_c_u:.2f}%])"
        )

        inc_gmv = ev["estimated_incremental_recovery_gmv_paise"] / 100
        ci_g_l = ev["ci_incremental_gmv_paise"]["lower"] / 100
        ci_g_u = ev["ci_incremental_gmv_paise"]["upper"] / 100
        print(
            f"Est. Incremental Recovery GMV: +INR {inc_gmv:,.2f} "
            f"(95% CI: [INR {ci_g_l:,.2f}, INR {ci_g_u:,.2f}])"
        )

        eff = ev["contact_efficiency_paise_per_contact"] / 100
        print(f"Contact Efficiency: INR {eff:,.2f} per synthetic contact")

        inc_per_c = ev["incremental_gmv_per_contact_paise"] / 100
        print(f"Incremental GMV / Contact: +INR {inc_per_c:,.2f}")

        blk_rate = ev["policy_safety_metrics"]["policy_block_rate"] * 100
        unsf_rate = ev["policy_safety_metrics"]["unsafe_action_rate"] * 100
        print(f"Policy Safety: Block Rate={blk_rate:.1f}%, Unsafe Action Rate={unsf_rate:.1f}%")

        print("\n" + "=" * 75)
        print("DEMO WALKTHROUGH COMPLETED SUCCESSFULLY!")
        print("=" * 75)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
