# Razorpay Test Mode Smoke Test & Developer Walkthrough

**Document Version**: 2.0  
**Status**: Active & Verified (Automated E2E Passed; Manual Real Razorpay Test Mode Walkthrough Pending Developer Execution)  
**Author**: ReTryPay Lead Integration Engineer  

---

## Executive Overview & Test Tier Separation

This document establishes the two distinct smoke-test tiers for ReTryPay:

1. **Automated Simulated E2E Test** ([`tests/scenario/test_razorpay_test_mode_smoke.py`](file:///d:/Rozerpay/tests/scenario/test_razorpay_test_mode_smoke.py)):
   - **Status**: **COMPLETED** (232 / 232 backend tests passed, including the Razorpay simulated E2E scenario).
   - Runs in CI/CD using isolated in-memory SQLite and test fixture boundaries.
   - Validates all 19 state machine steps, signature verification, outbox jobs, policy engine rules, and audit trails automatically.
2. **Manual Real Razorpay Test Mode Smoke Test** ([`docs/RAZORPAY_TEST_MODE_MANUAL_EVIDENCE.md`](file:///d:/Rozerpay/docs/RAZORPAY_TEST_MODE_MANUAL_EVIDENCE.md)):
   - **Status**: **PENDING MANUAL DEVELOPER EXECUTION**.
   - Uses real Razorpay Test Mode API keys (`rzp_test_...`) and live ngrok webhook tunnels.
   - Creates real Razorpay Orders via `POST /v1/orders` and real Payment Links via `POST /v1/payment_links`.
   - Records manual execution evidence in `docs/RAZORPAY_TEST_MODE_MANUAL_EVIDENCE.md`.

> [!IMPORTANT]
> The automated simulated E2E test proves system logic correctness. The manual real Razorpay smoke test is executed manually by the developer using an external webhook tunnel and documented in `docs/RAZORPAY_TEST_MODE_MANUAL_EVIDENCE.md`.

---

## Safety & Non-Negotiable Controls

- **Keys**: Must use Razorpay Test Mode key pairs (`rzp_test_...`). Live keys (`rzp_live_...`) are strictly prohibited and cause application startup to fail.
- **Communications**: All provider-side communications and reminders are hard-disabled (`notify.sms = false`, `notify.email = false`, `reminder_enable = false`). ReTryPay never sends messages to real customer addresses or numbers in Test Mode.
- **Delivery Scoping**:
  - `Delivery: TERMINAL_ONLY`
  - `Provider notifications: DISABLED`
  - `Customer messaging: NOT SENT`
- **Sanitized Payload Retention**: `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD` defaults to `false`. Raw body text is never stored outside `RETRYPAY_ENV=test`. In production/demo, ReTryPay persists only a **sanitized event envelope and payload hash**.
- **Causal Evaluation Isolation**: Synthetic cohort data (`SYNTHETIC_EVALUATION`) is isolated behind the offline evaluator and excluded from operational case list and metric APIs.

---

## 1. Required Runtime Configuration (.env)

```env
# Application Environment
RETRYPAY_ENV=demo

# Razorpay Integration Flags
RAZORPAY_PROVIDER_ENABLED=true
RAZORPAY_TEST_MODE_ONLY=true

# Developer Razorpay Test Credentials (rzp_test_ ONLY)
RAZORPAY_KEY_ID=rzp_test_abcdef12345678
RAZORPAY_KEY_SECRET=secret_test_abcdef12345678
RAZORPAY_WEBHOOK_SECRET=whsec_test_abcdef12345678

# Database Connection (SQLite Default)
DATABASE_URL=sqlite+aiosqlite:///./retrypay_testmode.db

# Privacy & Security Guards
RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=false
```

---

## 2. Safe Test Mode Setup

1. **Log in to Razorpay Dashboard** (https://dashboard.razorpay.com/).
2. Toggle top-right environment selector to **Test Mode** (orange badge).
3. Navigate to **Account & Settings > API Keys** and generate a **Test Key Pair** (`rzp_test_...`).
4. Copy `Key ID` and `Key Secret` into `.env`.
5. Navigate to **Account & Settings > Webhooks**.
6. Click **Add New Webhook**.

---

## 3. Webhook Tunnel Setup

To receive real Razorpay Test Mode webhooks on a local development instance:

```bash
# Start local ReTryPay server on port 8000
python -m uvicorn retrypay.api.app:app --host 127.0.0.1 --port 8000 --reload

# In a separate terminal, expose port 8000 via ngrok
ngrok http 8000
```
- Copy the generated HTTPS URL: `https://<subdomain>.ngrok-free.app`
- In Razorpay Webhooks settings, set **Webhook URL**: `https://<subdomain>.ngrok-free.app/api/v1/webhooks/razorpay`
- Enter **Secret**: `whsec_test_abcdef12345678`
- Select **Active Events**:
  - `payment.failed`
  - `payment.authorized`
  - `payment.captured`
  - `order.paid`
  - `payment_link.paid`
  - `payment_link.cancelled`
  - `payment_link.expired`
- Click **Save Webhook**.

---

## 4. Developer Walkthrough (Steps 1 through 19)

### Step 1: Create a Test Order via Razorpay API
Run the order creation helper script:
```bash
python scripts/create_test_order.py --amount 250000 --currency INR
```
- When `RAZORPAY_PROVIDER_ENABLED=true`, `create_test_order.py` sends `POST https://api.razorpay.com/v1/orders` to Razorpay.
- Persists the actual provider-returned Order ID (`order_P...`).

---

### Step 2 & 3: Trigger a Failed Payment in Test Mode
Open Razorpay Checkout JS or standard Test Mode checkout using the created Razorpay Order ID:
- Select payment method (Card / Netbanking / UPI).
- Choose failure or cancel option in Razorpay Test Mode dialog.
- **Recording Instruction**: Do not assume any specific provider error code. Inspect the received webhook payload and record the exact provider `event`, `error_code`, `error_source`, `error_step`, and `error_reason` fields in `docs/RAZORPAY_TEST_MODE_MANUAL_EVIDENCE.md`.

---

### Step 4 & 5: Webhook Ingestion & Signature Verification
ReTryPay receives `POST /api/v1/webhooks/razorpay`:
- **Header**: `X-Razorpay-Signature: <hmac_sha256>`
- **Action**: Verifies HMAC signature against `RAZORPAY_WEBHOOK_SECRET`.
- **Classification**: Server sets `source = RAZORPAY_TEST_MODE`, `ingestion_origin = EXTERNAL_RAZORPAY_WEBHOOK`.

---

### Step 6: Asynchronous Webhook Response & Sanitized Envelope
**Transaction 1 (DB Commit)**:
- Persists **sanitized event envelope and payload hash** (`provider_event_id = evt_...`). (Raw body text is NOT stored when `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=false`).
- Atomically creates `WebhookOutboxJobModel` (`status = PENDING`).
- **Response Contract**: Returns HTTP 200 after the event envelope and outbox job are committed:
  ```json
  {
    "status": "accepted",
    "event_id": "evt_...",
    "source": "RAZORPAY_TEST_MODE",
    "event_type": "payment.failed",
    "outbox_job_id": "job_..."
  }
  ```

---

### Step 7 & 8: Async Outbox Processing & Case Creation
Background worker claims outbox job:
- Normalizes webhook payload.
- Creates `OrderModel` (`status = ATTEMPTED`) and `PaymentAttemptModel` (`status = FAILED`).
- Creates `RecoveryCaseModel` (`case_id = rcv_order_...`, `state = RECEIVED`).
- Transitions case: `RECEIVED` $\rightarrow$ `ENRICHING`.
- Marks outbox job `COMPLETED`.

---

### Step 9: Deterministic Policy Decision
ReTryPay policy engine evaluates recovery context:
- Re-check consent, frequency limits, quiet hours, and daily budget.
- Returns `PolicyDecisionType.ELIGIBLE` under policy version `recovery-v1.3`.
- Case state transitions: `ENRICHING` $\rightarrow$ `POLICY_EVALUATED` $\rightarrow$ `DIAGNOSED` $\rightarrow$ `ACTION_APPROVED`.

---

### Step 10 & 11: Execute Case-Specific CLI & Confirmation
Run the merchant operator CLI to approve and issue the Test Mode Payment Link:

```bash
python scripts/create_test_mode_payment_link.py --case-id rcv_order_...
```

**Stage 3 Confirmation Protection**:
- Prompt displays: `To proceed, type exactly: 'CREATE TEST MODE PAYMENT LINK'`
- Operator inputs: `CREATE TEST MODE PAYMENT LINK`
- Passing any incorrect confirmation phrase (e.g. `--confirm-phrase "WRONG"`) aborts execution with code 1, making **zero budget reservation**, **zero provider API calls**, and **zero Payment Link creation**.

---

### Step 12 & 13: Verify Payment Link Payload Safety & Scoping
Inspecting the created Razorpay Payment Link request payload:
```json
{
  "amount": 250000,
  "currency": "INR",
  "accept_partial": false,
  "reference_id": "rpt_3a9f0e1d8c...",
  "notify": {
    "sms": false,
    "email": false
  },
  "reminder_enable": false
}
```
*Verification*:
- `notify.sms = false`, `notify.email = false`, `reminder_enable = false`
- `Delivery: TERMINAL_ONLY`
- `Provider notifications: DISABLED`
- `Customer messaging: NOT SENT`

---

### Step 14 & 15: Complete Recovery Payment via Payment Link
Open the generated Test Mode Payment Link URL:
1. Complete payment using Test Mode Success Magic Credentials.
2. Razorpay dispatches webhook `payment_link.paid` (`evt_...`).

---

### Step 16, 17, 18: Payment Link Settlement Correlation & Case Closure
Ingest `payment_link.paid`:
- Correlates link via `provider_link_id` / `reference_id` $\rightarrow$ local `PaymentLinkModel` $\rightarrow$ recovery case $\rightarrow$ original order.
- Validates `reference_id` and `amount_paise` match local DB records.
- `OrderModel.status` transitions from `ATTEMPTED` $\rightarrow$ `PAID`.
- Active recovery case transitions to `RECOVERED` (`closure_reason = RECOVERED_VIA_LINK`).
- Any remaining pending recovery actions are marked `CANCELLED`.
- Paid order invariant enforced: late failure webhooks cannot reopen the case.

---

### Step 19: Display Complete Audit Timeline

Querying `/api/v1/dashboard/cases/rcv_order_...`:

| Event Type | Actor | State Change | Metadata Summary |
| :--- | :--- | :--- | :--- |
| `CASE_CREATED` | `SYSTEM` | None $\rightarrow$ `RECEIVED` | `order_id`: `order_...` |
| `STATE_TRANSITION` | `SYSTEM` | `RECEIVED` $\rightarrow$ `ENRICHING` | Automated enrichment |
| `POLICY_EVALUATED` | `SYSTEM` | `ENRICHING` $\rightarrow$ `POLICY_EVALUATED` | Decision: `ELIGIBLE` |
| `ACTION_APPROVED` | `SYSTEM` | `POLICY_EVALUATED` $\rightarrow$ `ACTION_APPROVED` | Selected: `SEND_RETRY_LINK` |
| `BUDGET_RESERVED` | `SYSTEM` | N/A | Reserved: ₹2,500.00 |
| `PAYMENT_LINK_CREATED` | `MERCHANT` | `ACTION_APPROVED` $\rightarrow$ `LINK_CREATED` | Provider ID: `plink_...` |
| `CASE_CLOSED` | `SYSTEM` | `LINK_CREATED` $\rightarrow$ `RECOVERED` | Closure: `RECOVERED_VIA_LINK` |

---

## 5. Cleanup Instructions

1. **Local DB Reset**:
   ```bash
   rm -f retrypay_testmode.db
   python -c "import asyncio; from retrypay.storage.database import init_db, engine; asyncio.run(init_db(engine))"
   ```
2. **Revoke Test Keys**: If testing is complete, revoke test keys in Razorpay Dashboard > API Keys.

---

## 6. Known Test Mode Limitations

- **Webhook Latency**: Local tunnels (ngrok) can occasionally experience 1–2s network latency.
- **Magic Payments**: Razorpay Test Mode simulates bank auth instantly without actual OTP routing.
- **CLI Manual Flow**: CLI link creation requires operator terminal execution in `demo` mode.

---

## 7. Troubleshooting Section

| Symptom | Probable Cause | Fix / Solution |
| :--- | :--- | :--- |
| Startup failure `Razorpay live keys prohibited` | Key ID starts with `rzp_live_` | Replace `.env` key with `rzp_test_...`. |
| Webhook returns `400 Invalid signature` | Incorrect `RAZORPAY_WEBHOOK_SECRET` | Verify secret matches Razorpay Webhooks settings. |
| CLI fails with `Confirmation string mismatch` | Entered phrase does not match `CREATE TEST MODE PAYMENT LINK` | Type the phrase exactly as shown. |
| CLI fails with `Budget exhausted` | Daily operational budget reached | Reset database or increase budget limit in policy config. |
| HTTP `403 Forbidden` on simulator route | Simulator route called outside `RETRYPAY_ENV=test` | Simulator routes are disabled in `demo` or `prod` environments. |
| Outbox job stuck in `PENDING` | Worker process terminated | Restart application worker (`python -m retrypay.services.worker`). |
