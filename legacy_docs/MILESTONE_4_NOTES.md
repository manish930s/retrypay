# Milestone 4 Technical Notes: Bounded Recovery Execution, Payment Links, Budget Reservation & Out-of-Order Attribution

## 1. Execution State Machine & Transitions

The recovery case lifecycle extends through a linear, bounded execution pipeline with out-of-order payment reconciliation support:

```text
POLICY_EVALUATED
  → DIAGNOSED (Advisory diagnosis/ROS/estimator trace exists)
    → ACTION_APPROVED (Final policy re-check remains ELIGIBLE; action is active)
      → LINK_CREATED (Budget reserved transactionally & Payment Link created)
        → NOTIFIED (Simulated notification log persisted locally)
          → PAYMENT_CONFIRMED_PENDING_ATTRIBUTION (Payment captured; awaiting link webhook)
            → RECOVERED (Two-evidence correlation verified)
            → CLOSED_BLOCKED (Attribution timeout or unlinked payment)
          → RECOVERED | EXPIRED | CLOSED_UNRECOVERED | CLOSED_BLOCKED | OPTED_OUT
```

### Complete State Transition Matrix

| From State | Permitted Target State | Trigger Condition / Event |
|---|---|---|
| `POLICY_EVALUATED` | `DIAGNOSED` | Advisory trace pipeline records diagnosis and net utility. |
| `POLICY_EVALUATED` | `MANUAL_REVIEW` | Advisory recommendation is `MANUAL_REVIEW`. |
| `DIAGNOSED` | `ACTION_APPROVED` | Final policy re-check is `ELIGIBLE`; action is active (not `NO_ACTION`/`MANUAL_REVIEW`). |
| `DIAGNOSED` | `MANUAL_REVIEW` | Advisory recommendation is `MANUAL_REVIEW`. |
| `DIAGNOSED` | `CLOSED_BLOCKED` | Selected action is `NO_ACTION` or final policy re-check blocks. |
| `ACTION_APPROVED` | `LINK_CREATED` | Budget reservation succeeds & Payment Link is created. |
| `ACTION_APPROVED` | `MANUAL_REVIEW` | Operational budget guardrail is exhausted. |
| `ACTION_APPROVED` | `OPTED_OUT` | Customer revokes consent before link creation. |
| `LINK_CREATED` | `NOTIFIED` | Simulated local notification record is persisted. |
| `LINK_CREATED` / `NOTIFIED` | `PAYMENT_CONFIRMED_PENDING_ATTRIBUTION` | `payment.captured`/`order.paid` arrives for order with active link, awaiting `payment_link.paid`. |
| `LINK_CREATED` / `NOTIFIED` | `RECOVERED` | Two-evidence attribution satisfied (verified `payment_link.paid` + matching captured payment/order truth). |
| `LINK_CREATED` / `NOTIFIED` | `EXPIRED` | `payment_link.expired` event received or link expires past 24-hour lifetime. |
| `LINK_CREATED` / `NOTIFIED` | `CLOSED_UNRECOVERED` | `payment_link.cancelled` received or link creation fails definitively. |
| `LINK_CREATED` / `NOTIFIED` | `MANUAL_REVIEW` | `payment_link.partially_paid` received (unexpected state since `accept_partial=false`). |
| `LINK_CREATED` / `NOTIFIED` | `CLOSED_BLOCKED` | Independent merchant payment capture or `order.paid` arrives for order with NO active link. |
| `LINK_CREATED` / `NOTIFIED` | `OPTED_OUT` | Customer revokes consent before notification execution. |
| `PAYMENT_CONFIRMED_PENDING_ATTRIBUTION` | `RECOVERED` | `payment_link.paid` arrives and correlation is verified (`RECOVERED_VIA_LINK`). |
| `PAYMENT_CONFIRMED_PENDING_ATTRIBUTION` | `CLOSED_BLOCKED` | Attribution reconciliation window (30 mins) expires (`PAYMENT_ATTRIBUTION_UNCONFIRMED`). |
| *Terminal States* | *None* | **Terminal**: `CLOSED_BLOCKED`, `RECOVERED`, `EXPIRED`, `OPTED_OUT`, `CLOSED_UNRECOVERED`. |

---

## 2. Out-of-Order Webhook Attribution Sequences

Payment Link webhook events and payment/order webhooks frequently arrive out of order across networks. The system deterministically handles both arrival orders:

### Sequence A (Link Webhook First)
```text
payment_link.paid (Link marked PAID; awaiting payment confirmation)
  → payment.captured or order.paid
    → Deterministic Correlation Check
      → RECOVERED (reason: RECOVERED_VIA_LINK)
```

### Sequence B (Payment Capture First)
```text
payment.captured or order.paid (Payment truth verified; active local link exists)
  → PAYMENT_CONFIRMED_PENDING_ATTRIBUTION (Non-terminal state; suppresses notifications)
    → payment_link.paid arrives
      → Deterministic Correlation Check
        → RECOVERED (reason: RECOVERED_VIA_LINK)
    → (If link webhook never arrives or window expires)
      → CLOSED_BLOCKED (reason: PAYMENT_ATTRIBUTION_UNCONFIRMED)
```

> **Core Attribution Invariant:**
> “A paid order is not automatically a ReTryPay recovery. ReTryPay marks RECOVERED only after verified Payment Link evidence and verified payment/order truth correlate.”

---

## 3. Deterministic Evidence Hierarchy

Attribution evaluation relies exclusively on normalized provider data and enforces a strict evidence hierarchy:

1. **Strongest Evidence:** Matching `provider_link_id` (e.g. `payment_link.paid` provider link matches local active link ID, or payment entity metadata explicitly references local link ID).
2. **Linked Payment ID:** Matching explicitly linked `payment_id` from a verified `payment_link.paid` event.
3. **Supporting Evidence:** Reference ID match (`reference_id` matching local reference in payment description or notes).
4. **Insufficient Evidence:** Matching original `order_id` alone is **insufficient** if multiple payment channels/paths are possible (customer could have paid directly on the checkout/site).
5. **Ambiguous / Missing Evidence:** Case transitions to `CLOSED_BLOCKED` upon reconciliation timeout, never `RECOVERED`.

---

## 4. Reconciliation Window Configuration & Timeout Behavior

- **Configuration:** `RETRYPAY_ATTRIBUTION_RECONCILIATION_WINDOW_MINUTES=30` (configurable 1–1440 minutes).
- **Timeout Enforcement:** When the reconciliation window expires without two-evidence correlation:
  - Case transitions to `CLOSED_BLOCKED`.
  - Closure reason: `PAYMENT_ATTRIBUTION_UNCONFIRMED`.
  - All audit evidence is retained; the case is never reported as recovered.

---

## 5. Operational Budget Guardrails & Concurrency Strategy

Budget enforcement is an operational guardrail, never an authorization override. Policy blocks always take precedence over available budget.

### Configured Operational Limits
- `max_auto_recovery_amount_paise`: $1,000,000$ paise (₹10,000 per action limit)
- `max_auto_recovery_gmv_per_day_paise`: $5,000,000$ paise (₹50,000 daily GMV cap)
- `max_auto_actions_per_day`: $200$ actions daily
- `max_contact_count_per_day`: $200$ contacts daily (checked pre-link creation)
- `manual_review_capacity_per_day`: $25$ reviews daily

### SQLite Concurrency & Locking Strategy
- **Immediate Write Transactions:** Budget checks and reservations are executed inside transactional database sessions (`BEGIN IMMEDIATE`), querying current aggregate sums directly within the transaction boundary before inserting the `PENDING` reservation.
- **Pre-Link Contact Cap Verification:** Daily contact count is verified before Payment Link creation to guarantee that uncontactable links never consume external-provider quota.
- **Manual Review Queue Protection:** When manual review capacity ($25$ cases/day) is reached, cases are safely deferred or blocked with reason `MANUAL_REVIEW_CAPACITY_EXHAUSTED` rather than creating unbounded operator backlogs.
