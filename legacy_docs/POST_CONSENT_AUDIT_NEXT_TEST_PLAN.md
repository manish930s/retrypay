# ReTryPay — Post-Consent Audit Test & Verification Plan

**Document Version**: 1.0  
**Status**: Ready for Merchant Operator Approval  
**Author**: ReTryPay Lead Integration Engineer  

---

## 1. Overview & Dual-Path Architecture

Following the approval of the post-webhook consent and telemetry audit, ReTryPay testing is structured into two explicitly separated execution paths:

```
                          ┌────────────────────────────────────────────────────────┐
                          │ Real Webhook Ingestion & Recovery Evaluation           │
                          └──────────────────────────┬─────────────────────────────┘
                                                     │
                      ┌──────────────────────────────┴──────────────────────────────┐
                      ▼                                                             ▼
     ┌──────────────────────────────────┐                          ┌──────────────────────────────────┐
     │ PATH A — Safety Path             │                          │ PATH B — Eligible Recovery Path  │
     │ (Real Generic Payment Failure)   │                          │ (Consented Recoverable Scenario) │
     └────────────────┬─────────────────┘                          └────────────────┬─────────────────┘
                      │                                                             │
     • Diagnosis: UNKNOWN (0.30)                                   • Pre-event OPTED_IN consent
     • Policy Gate: MANUAL_REVIEW                                  • Customer identity pre-seeded
     • Contacts Sent: 0                                            • Order issued ONLY after approval
     • Links Created: 0                                            • Inspect actual provider failure
     • Auto-Recovery: HALTED AT SAFETY GATE                        • Operator CLI: exact phrase
```

---

## 2. Path A — Safety Path Verification Result

The real Razorpay Test Mode payment failure event received for order `order_TTde9JZWcuAyF2` serves as permanent evidence of ReTryPay's policy safety gate.

### Empirically Verified Telemetry

| Metric / Field | Observed System Value | Safety Specification | Compliance Status |
| :--- | :--- | :--- | :--- |
| **Case ID** | `rcv_order_TTde9JZWcuAyF2_924383` | Developer-owned test case | ✅ Preserved as Evidence |
| **Provider Order ID** | `order_TTde9JZWcuAyF2` | Real Razorpay Test Mode Order | ✅ Verified |
| **Diagnosis Category** | `UNKNOWN` (Confidence `0.30`) | Must not classify as temporary bank error | ✅ **PASS** |
| **Policy Decision** | `MANUAL_REVIEW` | Required for unclassified generic errors | ✅ **PASS** |
| **Contacts Sent** | **`0`** | Must equal 0 in `TERMINAL_ONLY` mode | ✅ **PASS** |
| **Notification Adapter Calls** | **`0`** | No external SMS/WhatsApp/Email calls | ✅ **PASS** |
| **Payment Links Created** | **`0`** | No link created automatically | ✅ **PASS** |
| **Automated Outreach** | **`NOT SENT`** | Customer messaging disabled | ✅ **PASS** |

### Why Generic Failures Must NOT Be Auto-Recovered
Generic provider errors (e.g., `BAD_REQUEST_ERROR` with reason `payment_failed`) do not contain specific bank degradation or network timeout signals. Automatically triggering outreach for generic failures creates severe operational risks:
1. **Customer Harm**: Sending recovery links for hard declines or user errors causes customer annoyance.
2. **Attribution Pollution**: Recoveries cannot be causally attributed to ReTryPay without high-confidence failure diagnosis.
3. **Policy Violation**: Automated outreach on generic failures violates merchant policy safety constraints.

---

## 3. Path B — Eligible Recovery Path Plan & Prerequisites

### Prerequisites (Must Be Satisfied Prior to Order Creation)
1. **Database Reset**: Re-initialize `retrypay_smoketest.db` to ensure a clean database state free of stale simulation records.
2. **Pre-Event Customer Consent**:
   - Customer profile `cust_demo_optin_001` pre-seeded with identity (`phone: +919876543210`, `email: optin_customer@example.com`).
   - Transactional consent (`ContactConsentStatus.OPTED_IN`) captured and persisted in DB **before** issuing the payment order or ingesting the failure webhook.
   - **No post-event database mutations to bypass consent are permitted.**

### Execution Protocol

#### Step 1: Pre-Seed Customer Profile & Consent
Run the developer helper script to register customer identity and consent in the clean database:
```bash
python -c "
import asyncio
from retrypay.storage.database import get_configured_session_factory
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.domain.models import Customer, CustomerConsent, ContactChannel, ContactConsentStatus

async def main():
    session_factory = get_configured_session_factory()
    async with session_factory() as session:
        repo = CustomerRepository(session)
        await repo.save_customer(Customer(customer_id='cust_demo_optin_001', masked_phone='+91******3210', masked_email='o***@example.com'))
        await repo.save_consent(CustomerConsent(customer_id='cust_demo_optin_001', channel=ContactChannel.WHATSAPP, status=ContactConsentStatus.OPTED_IN))
        await session.commit()
    print('Customer profile and consent pre-seeded successfully.')

asyncio.run(main())
"
```

#### Step 2: Request Explicit Approval for Order Creation
Wait for merchant operator approval before running `scripts/create_test_order.py`.

#### Step 3: Failure Flow & Error Inspection
Upon receiving the webhook, inspect the raw error fields:
- If error is generic (`BAD_REQUEST_ERROR` / `payment_failed`), policy halts at `MANUAL_REVIEW` / safety boundary (reconfirming Path A safety).
- If error maps to an approved recoverable category (e.g. `TEMPORARY_BANK_OR_NETWORK`), the policy engine evaluates `ELIGIBLE`.

#### Step 4: Operator CLI Payment Link Generation
If the case is `ELIGIBLE`, execute the operator CLI targeted at the specific case ID with the required confirmation phrase:
```bash
python -m retrypay.cli.operator create-link --case-id <TARGET_CASE_ID> --confirm "CREATE TEST MODE PAYMENT LINK"
```

#### Step 5: Settlement & Attribution
Simulate or record `payment_link.paid` webhook, verifying `reference_id` and `provider_link_id` correlation to transition case state to `RECOVERED`.

#### Fallback Protocol
If Razorpay Test Mode checkout yields generic failures exclusively, execute a parallel `LOCAL_SIMULATION` run using a specific recoverable scenario (`TEMPORARY_BANK_OR_NETWORK`) to demonstrate the complete end-to-end `RECOVERED` state transition without fabricating provider IDs.

---

## 4. Required Evidence Checklist

- [ ] Clean DB migration log for `retrypay_smoketest.db`.
- [ ] DB audit record verifying pre-event consent timestamp prior to failure event.
- [ ] Raw Razorpay webhook payload JSON with error fields.
- [ ] Outbox event log showing policy decision (`MANUAL_REVIEW` or `ELIGIBLE`).
- [ ] CLI execution log with exact phrase `CREATE TEST MODE PAYMENT LINK`.
- [ ] Dashboard screenshot showing delivery telemetry.

---

## 5. Remaining Limitations

- **Razorpay Test Mode Limitations**: Razorpay Checkout in Test Mode produces generic `BAD_REQUEST_ERROR` for card failure options, which correctly halts at `MANUAL_REVIEW`. Specific bank downtime codes require simulator mode or fake provider endpoints.
- **Provider Notifications Disabled**: SMS/WhatsApp dispatch remains disabled in `TERMINAL_ONLY` mode to protect test recipients.
