"""CLI tool to create a real Razorpay Test Mode Payment Link for a specific recovery case.

Strictly gated by RETRYPAY_ENV=demo, RAZORPAY_PROVIDER_ENABLED=true, and explicit confirmation.
Never creates live payments and never sends real customer messages.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from retrypay.adapters.razorpay.payment_links import (
    CreatePaymentLinkRequest,
    PaymentLinkDefinitiveFailureError,
    PaymentLinkProvider,
    PaymentLinkUnknownResultError,
    RazorpayPaymentLinkProvider,
)
from retrypay.budget.engine import BudgetEngine, BudgetExhaustedError
from retrypay.config import AppEnvironment, get_settings
from retrypay.decision.diagnosis import ActionType
from retrypay.domain.models import (
    ActorType,
    AuditEvent,
    AuditEventType,
    ContactChannel,
    ContactConsentStatus,
    EventSource,
    OrderStatus,
    PaymentLink,
    PaymentLinkStatus,
    PolicyDecisionType,
    ProviderOperationStatus,
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
    RecoveryPolicyContext,
    generate_deterministic_reference_id,
)
from retrypay.domain.state_machine import transition_case
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.database import (
    get_engine,
    get_session_factory,
    init_db,
    verify_database_routing_preflight,
)
from retrypay.storage.repositories.actions import RecoveryActionRepository
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository


async def run_cli(
    case_id: str,
    channel_str: str = "whatsapp",
    confirm_phrase: str | None = None,
    custom_provider: PaymentLinkProvider | None = None,
    auto_confirm: bool = False,
) -> int:
    """Execute the 5-stage guarded Test Mode Payment Link creation flow."""
    if auto_confirm and confirm_phrase is None:
        confirm_phrase = "CREATE TEST MODE PAYMENT LINK"
    settings = get_settings()

    print("=" * 70)
    print("  ReTryPay — Razorpay Test Mode Payment Link Creator")
    print("=" * 70)

    # ---------------------------------------------------------
    # STAGE 1: Read-Only Preflight Validation
    # ---------------------------------------------------------
    print(f"\n[Stage 1/5] Running preflight checks for case: {case_id}...")

    # Guard 1: Environment check
    if settings.RETRYPAY_ENV not in (AppEnvironment.DEMO, AppEnvironment.TEST):
        print(
            f"ERROR: Cannot create Test Mode link in '{settings.RETRYPAY_ENV.value}' environment. "
            "Must be 'demo' or 'test'.",
            file=sys.stderr,
        )
        return 1

    # Guard 2: Provider enabled
    if not settings.RAZORPAY_PROVIDER_ENABLED and custom_provider is None:
        print(
            "ERROR: RAZORPAY_PROVIDER_ENABLED is false in configuration. External calls disabled.",
            file=sys.stderr,
        )
        return 1

    # Guard 3: Live key rejection
    if settings.RAZORPAY_KEY_ID.startswith("rzp_live_"):
        print(
            "CRITICAL ERROR: Live Razorpay API keys (rzp_live_) are strictly forbidden!",
            file=sys.stderr,
        )
        return 1

    verify_database_routing_preflight(settings)
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)
        cust_repo = CustomerRepository(session)
        link_repo = PaymentLinkRepository(session)
        action_repo = RecoveryActionRepository(session)
        AuditRepository(session)
        budget_engine = BudgetEngine(session)
        policy_engine = PolicyEngine()

        # Fetch case
        case = await case_repo.get_case(case_id, source=EventSource.RAZORPAY_TEST_MODE.value)
        if not case:
            # Also check without source filter for diagnostic guidance
            any_case = await case_repo.get_case(case_id, source=EventSource.LOCAL_SIMULATION.value)
            if any_case:
                print(
                    f"ERROR: Case '{case_id}' exists but belongs to 'LOCAL_SIMULATION'. "
                    "Test Mode Payment Link creation is restricted to 'RAZORPAY_TEST_MODE' cases.",
                    file=sys.stderr,
                )
            else:
                print(f"ERROR: Recovery case '{case_id}' not found.", file=sys.stderr)
            return 1

        # Fetch order
        order = await order_repo.get_order(case.order_id, source=case.source.value)
        if not order:
            print(f"ERROR: Order '{case.order_id}' not found.", file=sys.stderr)
            return 1

        if order.status == OrderStatus.PAID:
            print(
                f"ERROR: Order '{order.order_id}' is already PAID. No recovery link needed.",
                file=sys.stderr,
            )
            return 1

        # Fetch customer & consent
        customer_id = case.customer_id or f"cust_{order.order_id}"
        customer = await cust_repo.get_customer(customer_id)
        consents = await cust_repo.get_consents(customer_id)

        target_channel = (
            ContactChannel.WHATSAPP
            if channel_str.lower() == "whatsapp"
            else ContactChannel.SMS
            if channel_str.lower() == "sms"
            else ContactChannel.EMAIL
        )

        consent_status = consents.get(target_channel)
        if consent_status == ContactConsentStatus.OPTED_OUT:
            print(
                f"ERROR: Customer '{customer_id}' has opted out of '{target_channel.value}'.",
                file=sys.stderr,
            )
            return 1

        # Check existing active link
        existing_link = await link_repo.get_active_link_for_case(
            case.case_id, source=case.source.value
        )
        if existing_link:
            print(
                f"ERROR: Active Payment Link '{existing_link.provider_link_id}' already exists "
                f"for case '{case_id}'.",
                file=sys.stderr,
            )
            return 1

        # Check for unknown result action
        latest_action = await action_repo.get_action_for_case(case.case_id)
        if (
            latest_action
            and latest_action.provider_operation_status == ProviderOperationStatus.UNKNOWN
        ):
            print(
                f"ERROR: Case '{case_id}' has unresolved action in UNKNOWN state.",
                file=sys.stderr,
            )
            return 1

        # Deterministic Policy pre-evaluation
        attempt = await order_repo.get_payment_attempt(
            case.failed_attempt_id, source=case.source.value
        )
        if not attempt:
            print(
                f"ERROR: Failed payment attempt '{case.failed_attempt_id}' not found.",
                file=sys.stderr,
            )
            return 1

        eval_time = attempt.occurred_at if (attempt and attempt.occurred_at) else datetime.now(UTC)
        policy_ctx = RecoveryPolicyContext(
            order=order,
            failed_attempt=attempt,
            customer=customer,
            consents=consents,
            target_channel=target_channel,
            prior_order_contact_count=case.contact_count,
            customer_30d_contact_count=0,
            evaluation_time=eval_time,
        )
        decision = policy_engine.evaluate(policy_ctx)
        if decision.decision_type != PolicyDecisionType.ELIGIBLE:
            reasons = [r.value for r in decision.reasons]
            print(
                f"ERROR: Case is NOT eligible under hard policy rules. "
                f"Decision: {decision.decision_type.value}, Reasons: {reasons}",
                file=sys.stderr,
            )
            return 1

        # ---------------------------------------------------------
        # STAGE 2: Display Summary
        # ---------------------------------------------------------
        masked_order_id = (
            f"order_***{order.order_id[-4:]}" if len(order.order_id) > 8 else order.order_id
        )
        amount_inr = order.amount_paise / 100.0

        print("\n[Stage 2/5] Preflight passed! Operation Summary:")
        print(f"  • Case ID:          {case.case_id}")
        print(f"  • Data Source:      {case.source.value} (Real Razorpay Test Mode)")
        print(f"  • Masked Order ID:  {masked_order_id}")
        print(f"  • Amount:           ₹{amount_inr:,.2f} {order.currency}")
        print(f"  • Target Channel:   {target_channel.value}")
        print(f"  • Policy Version:   {decision.policy_version}")
        print("  • Customer Notify:  DISABLED (notify={sms: false, email: false})")

        # ---------------------------------------------------------
        # STAGE 3: Interactive Exact Confirmation
        # ---------------------------------------------------------
        expected_confirmation = "CREATE TEST MODE PAYMENT LINK"
        user_input = confirm_phrase

        if not user_input:
            print("\n[Stage 3/5] Manual Confirmation Required:")
            print(f"  To proceed, type exactly: '{expected_confirmation}'")
            try:
                user_input = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted by user.", file=sys.stderr)
                return 1

        if user_input != expected_confirmation:
            print(
                f"\nERROR: Confirmation string mismatch. Received: '{user_input}'. "
                "Aborting without making any changes, reservations, or API calls.",
                file=sys.stderr,
            )
            return 1

        print(f"\n[Stage 3/5] Confirmation validated: '{user_input}'.")

        # ---------------------------------------------------------
        # STAGE 4: Final Policy Re-check, Reservation & Creation
        # ---------------------------------------------------------
        print("\n[Stage 4/5] Executing transactional reservation and link creation...")
        now = datetime.now(UTC)

        # Fresh state re-fetch and policy re-check
        fresh_case = await case_repo.get_case(case_id, source=case.source.value)
        fresh_order = await order_repo.get_order(case.order_id, source=case.source.value)
        if not fresh_case or not fresh_order or fresh_order.status == OrderStatus.PAID:
            print("ERROR: Fresh state check failed immediately before execution.", file=sys.stderr)
            return 1

        recheck_decision = policy_engine.evaluate(policy_ctx)
        if recheck_decision.decision_type != PolicyDecisionType.ELIGIBLE:
            dec_val = recheck_decision.decision_type.value
            print(
                f"ERROR: Final policy re-check failed. Decision: {dec_val}",
                file=sys.stderr,
            )
            return 1

        # Advance case through valid state machine transitions to ACTION_APPROVED
        if fresh_case.state == RecoveryCaseState.RECEIVED:
            fresh_case = transition_case(fresh_case, RecoveryCaseState.ENRICHING)
            await case_repo.save_case(fresh_case, source=case.source.value)
        if fresh_case.state == RecoveryCaseState.ENRICHING:
            fresh_case = transition_case(fresh_case, RecoveryCaseState.POLICY_EVALUATED)
            await case_repo.save_case(fresh_case, source=case.source.value)
        if fresh_case.state == RecoveryCaseState.POLICY_EVALUATED:
            fresh_case = transition_case(fresh_case, RecoveryCaseState.DIAGNOSED)
            await case_repo.save_case(fresh_case, source=case.source.value)
        if fresh_case.state == RecoveryCaseState.DIAGNOSED:
            fresh_case = transition_case(fresh_case, RecoveryCaseState.ACTION_APPROVED)
            await case_repo.save_case(fresh_case, source=case.source.value)

        # Create action record
        action_id = f"act_{uuid.uuid4().hex[:12]}"
        action = RecoveryAction(
            action_id=action_id,
            source=case.source,
            case_id=case.case_id,
            action_type=ActionType.SEND_RETRY_LINK,
            policy_version=case.policy_version,
            idempotency_key=f"{case.case_id}:TEST_MODE_CLI:{case.policy_version}",
            status=RecoveryActionStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        await action_repo.save_action(action, source=case.source.value)

        # Reserve budget
        try:
            reservation = await budget_engine.reserve_budget(
                case_id=case.case_id,
                action_id=action.action_id,
                amount_paise=order.amount_paise,
            )
        except BudgetExhaustedError as exc:
            print(f"ERROR: Daily operational recovery budget exhausted: {exc}", file=sys.stderr)
            return 1

        # Generate deterministic reference_id <= 40 chars
        reference_id = generate_deterministic_reference_id(case.case_id, action_id)

        # Provider request preparation
        expire_by = now + timedelta(hours=24)
        link_request = CreatePaymentLinkRequest(
            order_id=order.order_id,
            amount_paise=order.amount_paise,
            currency=order.currency,
            case_id=case.case_id,
            action_id=action.action_id,
            policy_version=case.policy_version,
            reference_id=reference_id,
            expire_by=expire_by,
            description="ReTryPay checkout recovery link (Test Mode)",
            notes={
                "recovery_case_id": case.case_id,
                "recovery_action_id": action.action_id,
                "policy_version": case.policy_version,
            },
        )

        # COMMIT PHASE 1 TRANSACTION BEFORE NETWORK CALL
        await session.commit()

        # External network provider call (held outside DB transaction)
        provider: PaymentLinkProvider = custom_provider or RazorpayPaymentLinkProvider(settings)
        try:
            link_result = await provider.create_payment_link(link_request)
        except PaymentLinkUnknownResultError as exc:
            print(f"WARNING: Provider timeout / unknown result: {exc}", file=sys.stderr)
            async with session_factory() as p2_session:
                p2_action_repo = RecoveryActionRepository(p2_session)
                act_unk = action.model_copy(
                    update={
                        "status": RecoveryActionStatus.FAILED,
                        "provider_operation_status": ProviderOperationStatus.UNKNOWN,
                        "updated_at": datetime.now(UTC),
                    }
                )
                await p2_action_repo.save_action(act_unk, source=case.source.value)
                await p2_session.commit()
            return 1
        except PaymentLinkDefinitiveFailureError as exc:
            print(f"ERROR: Provider definitively rejected link creation: {exc}", file=sys.stderr)
            async with session_factory() as p2_session:
                p2_budget_engine = BudgetEngine(p2_session)
                p2_action_repo = RecoveryActionRepository(p2_session)
                p2_case_repo = RecoveryCaseRepository(p2_session)

                await p2_budget_engine.release_reservation(reservation.reservation_id)
                act_fail = action.model_copy(
                    update={"status": RecoveryActionStatus.FAILED, "updated_at": datetime.now(UTC)}
                )
                await p2_action_repo.save_action(act_fail, source=case.source.value)
                closed_case = transition_case(
                    fresh_case,
                    RecoveryCaseState.CLOSED_UNRECOVERED,
                    closure_reason=RecoveryCaseClosureReason.UNRECOVERABLE,
                )
                await p2_case_repo.save_case(closed_case, source=case.source.value)
                await p2_session.commit()
            return 1

        # PHASE 2 TRANSACTION (Provider Succeeded)
        async with session_factory() as p2_session:
            p2_budget_engine = BudgetEngine(p2_session)
            p2_link_repo = PaymentLinkRepository(p2_session)
            p2_action_repo = RecoveryActionRepository(p2_session)
            p2_case_repo = RecoveryCaseRepository(p2_session)
            p2_audit_repo = AuditRepository(p2_session)

            p2_now = datetime.now(UTC)
            await p2_budget_engine.commit_reservation(reservation.reservation_id)

            link_id = f"plink_{uuid.uuid4().hex[:12]}"
            payment_link = PaymentLink(
                link_id=link_id,
                source=case.source,
                case_id=case.case_id,
                action_id=action.action_id,
                provider_link_id=link_result.provider_link_id,
                reference_id=link_result.reference_id,
                short_url=link_result.short_url,
                amount_paise=link_result.amount_paise,
                currency=link_result.currency,
                status=PaymentLinkStatus.CREATED,
                expire_by=link_result.expire_by,
                provider_created_at=link_result.provider_created_at,
                created_at=p2_now,
                updated_at=p2_now,
            )
            await p2_link_repo.save_link(payment_link, source=case.source.value)

            action = action.model_copy(
                update={"status": RecoveryActionStatus.EXECUTED, "updated_at": p2_now}
            )
            await p2_action_repo.save_action(action, source=case.source.value)

            # Terminal CLI transitions case to LINK_CREATED (no notification dispatched in terminal)
            fresh_case = transition_case(fresh_case, RecoveryCaseState.LINK_CREATED)
            await p2_case_repo.save_case(fresh_case, source=case.source.value)

            await p2_audit_repo.record_audit_event(
                AuditEvent(
                    event_id=f"aud_{uuid.uuid4().hex[:12]}",
                    source=case.source,
                    case_id=case.case_id,
                    event_type=AuditEventType.PAYMENT_LINK_CREATED,
                    actor_type=ActorType.OPERATOR,
                    metadata={
                        "provider_link_id": payment_link.provider_link_id,
                        "reference_id": payment_link.reference_id,
                        "mode": "MANUAL_CLI_TEST_MODE",
                    },
                    timestamp=p2_now,
                ),
                source=case.source.value,
            )

            await p2_session.commit()

        # ---------------------------------------------------------
        # STAGE 5: Display Terminal Success Output
        # ---------------------------------------------------------
        print("\n" + "=" * 70)
        print("  SUCCESS: Razorpay Test Mode Payment Link Created!")
        print("=" * 70)
        print(f"  • Case ID:           {fresh_case.case_id}")
        print(f"  • Case State:        {fresh_case.state.value}")
        print(f"  • Provider Link ID:  {payment_link.provider_link_id}")
        print(f"  • Reference ID:      {payment_link.reference_id}")
        print(f"  • Short URL:         {payment_link.short_url}")
        print(f"  • Expires At:        {payment_link.expire_by.isoformat()}")
        print("=" * 70)
        print("Note: You can paste the Short URL into a browser to simulate a Test Mode payment.")
        print(
            "When paid, Razorpay Test Mode will dispatch a verified webhook "
            "to complete the recovery."
        )

        return 0


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Create a real Razorpay Test Mode Payment Link for a specific recovery case."
    )
    parser.add_argument(
        "--case-id",
        required=True,
        help="Recovery case ID (e.g. rcv_order_test_123456)",
    )
    parser.add_argument(
        "--channel",
        default="whatsapp",
        choices=["whatsapp", "sms", "email"],
        help="Target recovery channel (default: whatsapp)",
    )
    parser.add_argument(
        "--confirm-phrase",
        type=str,
        default=None,
        help="Exact confirmation phrase 'CREATE TEST MODE PAYMENT LINK'",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Automated test flag (provides default confirmation phrase)",
    )

    args = parser.parse_args()
    code = asyncio.run(
        run_cli(
            case_id=args.case_id,
            channel_str=args.channel,
            confirm_phrase=args.confirm_phrase,
            auto_confirm=args.yes,
        )
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
