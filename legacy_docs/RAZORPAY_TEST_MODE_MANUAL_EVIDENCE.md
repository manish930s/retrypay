# Razorpay Test Mode Manual Evidence Template — Not Yet Executed

**Document Version**: 1.0  
**Status**: Manual Evidence Template — Not Yet Executed  
**Author**: ReTryPay Integration Engineering  

---

## Executive Notice

> [!IMPORTANT]
> This document is a **Manual Evidence Template**. An actual developer-owned Razorpay Test Mode run through a live webhook tunnel has **not yet been executed**. All real execution record fields are marked `PENDING_MANUAL_EXECUTION`.
>
> When the manual test run is conducted, replace `PENDING_MANUAL_EXECUTION` values with actual redacted provider IDs, timestamps, HTTP statuses, and database states captured directly from the live run.

---

## 1. Environment & Setup Details

- **Environment (`RETRYPAY_ENV`)**: `demo` / `test`
- **Key Pair**: `rzp_test_...` (Razorpay Test Mode key pair)
- **Webhook Tunnel**: `https://<ngrok_subdomain>.ngrok-free.app/api/v1/webhooks/razorpay`
- **Raw Body Payload Retention**: `DISABLED` (`RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=false`)

---

## 2. Redacted Execution Identifiers & Timestamps

| Identifier Field | Redacted Value Format | Real Test Record Value |
| :--- | :--- | :--- |
| **Razorpay Order ID** | `order_***<last4>` | `PENDING_MANUAL_EXECUTION` |
| **Failed Payment ID** | `pay_***<last4>` | `PENDING_MANUAL_EXECUTION` |
| **Captured Payment ID** | `pay_***<last4>` | `PENDING_MANUAL_EXECUTION` |
| **Payment Link ID** | `plink_***<last4>` | `PENDING_MANUAL_EXECUTION` |
| **Failed Webhook Event ID** | `evt_***<last4>` | `PENDING_MANUAL_EXECUTION` |
| **Captured Webhook Event ID** | `evt_***<last4>` | `PENDING_MANUAL_EXECUTION` |
| **Timestamp (UTC)** | `YYYY-MM-DDTHH:MM:SSZ` | `PENDING_MANUAL_EXECUTION` |

---

## 3. Webhook Ingestion & HTTP Response Contracts

### A. Initial Payment Failure Webhook (`payment.failed`)
- **HTTP Request**: `POST /api/v1/webhooks/razorpay`
- **Headers**:
  - `X-Razorpay-Signature`: `<hmac_sha256_hex>`
  - `X-Razorpay-Event-Id`: `evt_***<last4>`
- **Expected Asynchronous Enqueued Response**:
  ```json
  {
    "status": "accepted",
    "event_id": "evt_***<last4>",
    "source": "RAZORPAY_TEST_MODE",
    "event_type": "payment.failed",
    "outbox_job_id": "job_***<last4>"
  }
  ```
- **Real Execution Record**: `PENDING_MANUAL_EXECUTION`

### B. Payment Link Paid Webhook (`payment_link.paid`)
- **HTTP Request**: `POST /api/v1/webhooks/razorpay`
- **Headers**:
  - `X-Razorpay-Signature`: `<hmac_sha256_hex>`
  - `X-Razorpay-Event-Id`: `evt_***<last4>`
- **Expected Asynchronous Enqueued Response**:
  ```json
  {
    "status": "accepted",
    "event_id": "evt_***<last4>",
    "source": "RAZORPAY_TEST_MODE",
    "event_type": "payment_link.paid",
    "outbox_job_id": "job_***<last4>"
  }
  ```
- **Real Execution Record**: `PENDING_MANUAL_EXECUTION`

---

## 4. Operator CLI Manual Dispatch Execution Log

```text
======================================================================
  ReTryPay — Razorpay Test Mode Payment Link Creator
======================================================================

[Stage 1/5] Running preflight checks for case: rcv_***...

[Stage 2/5] Preflight passed! Operation Summary:
  • Case ID:          rcv_***
  • Data Source:      RAZORPAY_TEST_MODE (Real Razorpay Test Mode)
  • Masked Order ID:  order_***
  • Amount:           ₹2,500.00 INR
  • Delivery:         TERMINAL_ONLY
  • Provider notifications: DISABLED
  • Customer messaging: NOT SENT
  • Policy Version:   recovery-v1.3
  • Customer Notify:  DISABLED (notify={sms: false, email: false})

[Stage 3/5] Manual Confirmation Required:
  To proceed, type exactly: 'CREATE TEST MODE PAYMENT LINK'
  > CREATE TEST MODE PAYMENT LINK

[Stage 3/5] Confirmation validated: 'CREATE TEST MODE PAYMENT LINK'.

[Stage 4/5] Executing transactional reservation and link creation...
✓ Phase 1: Budget reserved (₹2,500.00) & pending action saved.
✓ External Provider: Razorpay API returned HTTP 200 OK.
✓ Phase 2: Link state saved & case transitioned to LINK_CREATED.

[Stage 5/5] SUCCESS! Razorpay Test Mode Payment Link Created:
  • Payment Link ID:  plink_***
  • Short URL:        https://rzp.io/i/*** (Masked in logs)
  • Reference ID:     rpt_*** (Length: 36 chars <= 40)
  • Notify SMS:       False
  • Notify Email:     False
  • Reminder Enable:  False

======================================================================
STATUS: PENDING_MANUAL_EXECUTION
```

---

## 5. Final Database Entity States (Pending Manual Run)

```sql
-- Orders Table
SELECT order_id, source, status, amount_paise FROM orders WHERE order_id = '<real_order_id>';
-- Real Execution Record: PENDING_MANUAL_EXECUTION

-- Recovery Cases Table
SELECT case_id, source, state, is_active, closure_reason FROM recovery_cases WHERE case_id = '<real_case_id>';
-- Real Execution Record: PENDING_MANUAL_EXECUTION

-- Payment Links Table
SELECT provider_link_id, reference_id, status FROM payment_links WHERE case_id = '<real_case_id>';
-- Real Execution Record: PENDING_MANUAL_EXECUTION

-- Recovery Actions Table
SELECT action_id, status, provider_operation_status FROM recovery_actions WHERE case_id = '<real_case_id>';
-- Real Execution Record: PENDING_MANUAL_EXECUTION
```

---

## 6. Final Audit Timeline Log (Pending Manual Run)

| Event ID | Event Type | Actor | State Change | Metadata Summary | Real Execution Record |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `aud_***` | `CASE_CREATED` | `SYSTEM` | `None` $\rightarrow$ `RECEIVED` | `order_id`: `order_***` | `PENDING_MANUAL_EXECUTION` |
| `aud_***` | `STATE_TRANSITION` | `SYSTEM` | `RECEIVED` $\rightarrow$ `ENRICHING` | Automated enrichment | `PENDING_MANUAL_EXECUTION` |
| `aud_***` | `POLICY_EVALUATED` | `SYSTEM` | `ENRICHING` $\rightarrow$ `POLICY_EVALUATED` | Decision: `ELIGIBLE` | `PENDING_MANUAL_EXECUTION` |
| `aud_***` | `ACTION_APPROVED` | `SYSTEM` | `POLICY_EVALUATED` $\rightarrow$ `ACTION_APPROVED` | Selected action: `SEND_RETRY_LINK` | `PENDING_MANUAL_EXECUTION` |
| `aud_***` | `BUDGET_RESERVED` | `SYSTEM` | N/A | Reserved: ₹2,500.00 | `PENDING_MANUAL_EXECUTION` |
| `aud_***` | `PAYMENT_LINK_CREATED` | `MERCHANT` | `ACTION_APPROVED` $\rightarrow$ `LINK_CREATED` | Provider ID: `plink_***` | `PENDING_MANUAL_EXECUTION` |
| `aud_***` | `CASE_CLOSED` | `SYSTEM` | `LINK_CREATED` $\rightarrow$ `RECOVERED` | Closure: `RECOVERED_VIA_LINK` | `PENDING_MANUAL_EXECUTION` |
