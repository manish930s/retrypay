# ReTryPay — Safety, Compliance & Guardrails Policy

This document outlines the hard safety boundaries, compliance invariants, and privacy protections enforced by ReTryPay.

---

## 1. Non-Negotiable Core Invariants

1. **Test Mode Exclusivity**: ReTryPay operates strictly in Razorpay Test Mode (`rzp_test_`). Any API key starting with `rzp_live_` raises an immediate startup exception.
2. **Zero Sensitive Data Leakage**: Never store, log, serialize, or transmit PAN, CVV, OTP, UPI PIN, webhook secrets, or API private keys.
3. **Deterministic Policy Precedence**: Policy rules (`recovery-v1.3`) are authoritative. AI, ROS scores, utility estimators, and UI operators cannot override a policy `BLOCK`.
4. **Idempotency & Replay Protection**: Every incoming webhook is recorded with a unique `provider_event_id`. Duplicate deliveries return `{"status": "ignored"}` with zero secondary mutations.
5. **Two-Evidence Attribution**: A case is marked `RECOVERED` only when both a verified `payment.captured` webhook and a matching `paid` Payment Link reference are confirmed within the 30-minute reconciliation window.

---

## 2. DPDP Consent & Privacy Guardrails

- **Explicit Opt-In Required**: Outreach reminders are dispatched only if the customer's channel consent is `OPTED_IN`.
- **Missing Consent Handling**: Cases with missing or unknown consent are automatically routed to `MANUAL_REVIEW` / `CLOSED_BLOCKED` with reason code `CONTACT_CONSENT_MISSING`.
- **Masked Identifiers**: Operator console displays strictly masked phone numbers (`+91******1234`) and emails (`u***@example.com`).

---

## 3. Merchant Operational Caps & Quiet Hours

- **Single Action GMV Limit**: Maximum recovery action amount is capped at ₹10,000 (1,000,000 paise). Orders exceeding this threshold are gated to `MANUAL_REVIEW`.
- **Contact Frequency Caps**:
  - Max **2 messages** per order (`max_messages_per_order = 2`).
  - Max **3 messages** per customer in any 30-day rolling window (`max_messages_per_customer_30d = 3`).
- **Merchant Quiet Hours**:
  - Active between **22:00 and 08:00 (Asia/Kolkata)**.
  - Failures occurring during quiet hours are transitioned to `DEFERRED` and scheduled for daytime processing.

---

## 4. LLM Advisory Sandbox Boundaries

- **LLM Output is Strictly Advisory**: The LLM diagnosis adapter provides structured classification and human-readable explanations only.
- **No Money-Movement Authorization**: AI is strictly prohibited from authorizing actions, calculating ROS scores, estimating financial lift, or bypassing policy checks.
