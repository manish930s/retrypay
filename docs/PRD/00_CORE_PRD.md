# ReTryPay Core PRD — Buildathon MVP

**Document:** `docs/PRD/00_CORE_PRD.md`  
**Version:** 1.0  
**Date:** 23 August 2026  

---

## 1. System Overview and Objectives

ReTryPay is a bounded, merchant-facing checkout drop-off recovery system for Razorpay Test Mode. It listens to failed payment events, validates payment truth via cryptographic webhooks and state reconciliation, applies hard deterministic policy gates, creates attributable short-lived payment links, and records an immutable audit trail.

### Primary User
Merchant Operations Managers who require complete visibility, deterministic safety controls, and attributable proof for every payment recovery action.

---

## 2. Core Event and Recovery Lifecycle

```text
payment.failed webhook
  │
  ▼
Verify raw HMAC signature & deduplicate event ID
  │
  ▼
Reconcile current order/payment state with provider truth
  │
  ▼
Deterministic Policy Engine (Hard gates, consent, caps, quiet hours)
  │
  ▼
[If Eligible] -> Decisioning (ROS, Diagnosis, Estimator vs NO_ACTION)
  │
  ▼
Action Executor (Create Razorpay Test Mode Payment Link + Simulated Notification)
  │
  ▼
Outcome Resolution (payment.captured / expiry / opt-out)
  │
  ▼
Append-only Audit Log
```

---

## 3. Finite State Machine

Recovery cases follow a strict state progression:

`RECEIVED` → `ENRICHING` → `POLICY_EVALUATED` → `{ CLOSED_BLOCKED | MANUAL_REVIEW | DIAGNOSED → ACTION_APPROVED → LINK_CREATED → NOTIFIED → { RECOVERED | EXPIRED | OPTED_OUT | CLOSED_UNRECOVERED } }`

### Reliability Invariants:
1. **One Active Case Per Order:** An order can have at most one active (non-terminal) recovery case.
2. **Action Idempotency:** Exactly one action execution per `(case_id, action_type, policy_version)` key.
3. **Capture Pre-emption:** A captured or paid order immediately closes any pending or active recovery case and cancels scheduled notifications.
4. **Out-of-Order Safety:** Duplicate or delayed webhooks never generate duplicate links or notifications.

---

## 4. Deterministic Hard Policy Rules and Thresholds

Policy is the authoritative decision-maker. No AI, ranking algorithm, or UI can override a policy block.

| Policy Parameter | Standard Value | Demo Scenario Override |
|---|---|---|
| `DEFAULT_LINK_EXPIRY_MINUTES` | `1440` (24 hours) | `30` minutes (explicit demo scenario only) |
| `MAX_AUTO_RECOVERY_AMOUNT_PAISE` | `1000000` (₹10,000) | Configurable per merchant |
| `MAX_AUTO_RECOVERY_GMV_PER_DAY_PAISE` | `5000000` (₹50,000) | Daily cap |
| `MAX_AUTO_ACTIONS_PER_DAY` | `200` | Daily action volume limit |
| `MAX_CONTACT_COUNT_PER_DAY` | `200` | Merchant daily contact budget |
| `MAX_MESSAGES_PER_ORDER` | `2` | Hard limit per order |
| `MAX_MESSAGES_PER_CUSTOMER_30D` | `3` | Frequency cap across 30 days |
| `DEFAULT_QUIET_HOURS_START` | `22` (10:00 PM) | Suppresses messaging |
| `DEFAULT_QUIET_HOURS_END` | `08` (08:00 AM) | Resumes messaging |
| `CUSTOMER_CONSENT_REQUIRED` | `true` | Hard block if consent=false or opt_out=true |

---

## 5. Webhook Data Minimization and Ingestion Contract

- **Raw Request Verification:** Webhook signatures are verified in memory against raw request bytes using constant-time HMAC-SHA256 comparison (`X-Razorpay-Signature`).
- **Data Minimization:** Raw request bodies are **not stored by default**.
- **Persisted Event Record:**
  - `provider_event_id` (Unique, Primary Key)
  - `event_type`
  - `received_at`
  - `signature_verification_status`
  - `payload_sha256`
  - Normalized required payment/order fields (amount, currency, method, error code)
  - `processing_status`
  - `error_reason` (if parsing or verification fails)
- **Debug Flag:** `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD` defaults to `false` and is strictly forbidden when handling real customer data.

---

## 6. Security, Privacy, and Safe Testing Boundaries

1. **Test Mode Only:** Operates exclusively with Razorpay Test Mode keys (`rzp_test_...`). Live keys (`rzp_live_...`) are strictly prohibited and blocked at initialization.
2. **Zero Sensitive Payment Data:** Never store, log, or transmit PAN, CVV, OTP, UPI PIN, or unmasked secrets.
3. **Simulated Customer Contact:** No SMS or WhatsApp messages are sent to real customers. All customer notifications are simulated and logged to the audit store.
