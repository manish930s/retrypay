# Milestone 2 Technical Notes: Recovery Domain, Policy Safeguards & Auditability

## 1. Recovery Case Finite State Machine (Control Plane)

### Supported States in Milestone 2
- `RECEIVED`: Webhook received and validated; initial recovery case created.
- `ENRICHING`: Gathering customer, consent, order, attempt, and contact history context.
- `POLICY_EVALUATED`: Passed all hard deterministic policy gates; eligible for recovery (awaits Milestone 3 diagnosis & action).
- `CLOSED_BLOCKED`: Terminal closed state resulting from hard policy blocks, capture pre-emption, order payment, or explicit opt-out.
- `MANUAL_REVIEW`: Triaged for human operator review (amount threshold exceeded, high fraud risk, or missing mandatory context).
- `DEFERRED`: Outreach temporarily held during quiet hours (22:00–08:00 Asia/Kolkata).

### State Transition Matrix

| From State | Permitted Target State | Trigger Condition / Event |
|---|---|---|
| *None* (New) | `RECEIVED` | Valid `payment.failed` event on unpaid order. |
| `RECEIVED` | `ENRICHING` | System begins customer & policy context enrichment. |
| `RECEIVED` | `CLOSED_BLOCKED` | Order captured or paid before enrichment finishes. |
| `ENRICHING` | `POLICY_EVALUATED` | Policy decision is `ELIGIBLE`. |
| `ENRICHING` | `CLOSED_BLOCKED` | Policy decision is `BLOCK` (e.g. opt-out, missing consent, unrecoverable, cap). |
| `ENRICHING` | `MANUAL_REVIEW` | Policy decision is `MANUAL_REVIEW` (amount > ₹10,000, high risk, insufficient context). |
| `ENRICHING` | `DEFERRED` | Policy decision is `DEFER` (evaluated during quiet hours). |
| `DEFERRED` | `ENRICHING` | Quiet hours expire; case re-enters evaluation. |
| `DEFERRED` | `CLOSED_BLOCKED` | Order captured or paid while deferred. |
| `MANUAL_REVIEW` | `CLOSED_BLOCKED` | Order captured, paid, or rejected by operator. |
| `POLICY_EVALUATED` | `CLOSED_BLOCKED` | Order captured or paid before outreach. |
| `CLOSED_BLOCKED` | *None* | **Terminal State**: Cannot transition to any active state. |

---

## 2. Policy Precedence & Deterministic Gate Hierarchy

The policy engine evaluates all applicable rules simultaneously and aggregates all triggered reason codes. The final decision type is resolved strictly via the following precedence order:

1. **Terminal Order/Payment Blocks** (`BLOCK`):
   - `ORDER_ALREADY_PAID`: Order is already in `PAID` status.
   - `ORDER_UNRECOVERABLE`: Order is in `CANCELLED`, `REFUNDED`, `EXPIRED` status, or amount is non-positive ($\le 0$).
2. **Consent & Opt-Out Blocks** (`BLOCK`):
   - `CUSTOMER_OPTED_OUT`: Customer explicitly opted out of proposed channel.
   - `CONTACT_CONSENT_MISSING`: Customer consent is `UNKNOWN` or unrecorded.
3. **Contact Frequency Cap Blocks** (`BLOCK`):
   - `ORDER_CONTACT_CAP_REACHED`: Case contact count $\ge 2$ messages.
   - `CUSTOMER_CONTACT_CAP_REACHED`: Customer 30-day contact count $\ge 3$ messages.
4. **High-Risk & Amount Review Gates** (`MANUAL_REVIEW`):
   - `AMOUNT_REQUIRES_REVIEW`: Order amount > ₹10,000 (`1_000_000` paise).
   - `RISK_REQUIRES_REVIEW`: Failed attempt has high-risk/hard decline error code.
5. **Context Sufficiency Review Gate** (`MANUAL_REVIEW`):
   - `INSUFFICIENT_CONTEXT`: Synthetic customer profile not found or unavailable.
6. **Quiet-Hours Gate** (`DEFER`):
   - `QUIET_HOURS`: Local evaluation time falls between 22:00 and 08:00 Asia/Kolkata.
7. **Default Eligibility** (`ELIGIBLE`):
   - `ELIGIBLE_FOR_RECOVERY`: All policy gates passed.

*Precedence Invariant:* `BLOCK` overrides `MANUAL_REVIEW`, `DEFER`, and `ELIGIBLE`. `MANUAL_REVIEW` overrides `DEFER` and `ELIGIBLE`. `DEFER` overrides `ELIGIBLE`.

---

## 3. Discrete Policy Reason Code Reference

| Reason Code | Classification | Description |
|---|---|---|
| `ORDER_ALREADY_PAID` | `BLOCK` | Order already marked `PAID`. |
| `ORDER_UNRECOVERABLE` | `BLOCK` | Order is `CANCELLED`, `REFUNDED`, `EXPIRED`, or has non-positive amount. |
| `CUSTOMER_OPTED_OUT` | `BLOCK` | Customer explicitly opted out of channel outreach. |
| `CONTACT_CONSENT_MISSING` | `BLOCK` | Channel consent is `UNKNOWN` or unrecorded. |
| `ORDER_CONTACT_CAP_REACHED` | `BLOCK` | Max 2 contacts per order limit reached. |
| `CUSTOMER_CONTACT_CAP_REACHED` | `BLOCK` | Max 3 contacts per customer in 30 days reached. |
| `AMOUNT_REQUIRES_REVIEW` | `MANUAL_REVIEW` | Order amount exceeds max auto recovery amount (₹10,000). |
| `RISK_REQUIRES_REVIEW` | `MANUAL_REVIEW` | Error code indicates high risk or hard decline. |
| `INSUFFICIENT_CONTEXT` | `MANUAL_REVIEW` | Customer entity context unavailable. |
| `QUIET_HOURS` | `DEFER` | Current time is within quiet hours (22:00–08:00). |
| `ELIGIBLE_FOR_RECOVERY` | `ELIGIBLE` | Eligible for recovery workflow. |

---

## 4. Privacy & Consent Safeguards

- **Synthetic Identification:** All customer profiles use synthetic internal identifiers (`cust_xxx`).
- **Masked Contact References:** Stored contacts are tokenized or masked (e.g. `+91******1234`, `u***@example.com`).
- **Independent Channel Consent:** Consents are stored independently per channel (`EMAIL`, `SMS`, `WHATSAPP`).
- **Default Hard Block:** `UNKNOWN` consent is treated as a hard block for automatic recovery outreach in this MVP.
- **Zero Real Outreach:** No external messaging provider or notification client is invoked.

---

## 5. Quiet-Hours Logic

- **Configured Hours:** 22:00 (10:00 PM) to 08:00 (8:00 AM) in `Asia/Kolkata` (UTC+05:30).
- **Crossing Midnight:** Times between 22:00 and 23:59:59 calculate the next permitted contact time as 08:00 AM of the next calendar day. Times between 00:00 and 07:59:59 calculate the next permitted contact time as 08:00 AM of the current calendar day.
- **Stored Invariant:** `quiet_hours_deferred_until` is converted and stored as UTC timestamp.

---

## 6. Authoritative Database-Enforced Active-Case Uniqueness

- **Authoritative Concurrency Invariant:** Enforced directly in SQLite via a partial unique index:
  ```sql
  CREATE UNIQUE INDEX uq_one_active_recovery_case_per_order
  ON recovery_cases(order_id)
  WHERE closed_at IS NULL;
  ```
- **Concurrency Safety vs. Pre-check:** The repository pre-check (`get_active_case_for_order()`) exists solely to provide human-readable domain feedback. The database-level partial unique index is the true concurrency safeguard that guarantees zero race conditions during concurrent webhook ingestion.
- **Subsequent Ingestions:** When a case is closed (`closed_at IS NOT NULL`), a new active case can be legally created if a new eligible failure occurs.
- **Capture Pre-emption:** Ingested `payment.captured` or `order.paid` webhooks immediately close any active recovery case for that order with audit trail recording.

---

## 7. Deferred Functionality (Milestone 3+)

The following capabilities are deliberately excluded from Milestone 2 and deferred to subsequent milestones:
1. **Diagnosis Engine & LLM Integration** (Milestone 3)
2. **Recovery Opportunity Score (ROS) & Utility Ranking** (Milestone 3)
3. **RecoveryValueEstimator & Causal Uplift Modeling** (Milestone 3)
4. **Attributable Payment Link Creation** (Milestone 4)
5. **Customer Outreach & Notification Messaging** (Milestone 4)
6. **Budget Reservation & Daily GMV Tracking** (Milestone 4)
7. **Synthetic Evaluation Protocol & Counterfactual Simulation** (Milestone 5)
8. **Merchant Recovery Dashboard UI** (Milestone 6)
