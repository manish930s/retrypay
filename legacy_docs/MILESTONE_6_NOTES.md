# Milestone 6 Notes: Operator Dashboard, Webhook Simulator, and Demo Orchestration

## Overview
Milestone 6 delivers a local merchant-operator console and signed-webhook simulator that visibly validates the entire ReTryPay system from payment-event truth to two-evidence attribution reconciliation and causal counterfactual evaluation.

---

## Key Components

### 1. Merchant Operator Dashboard (`web/`)
Built with React 18, Vite, TypeScript, and modern dark-mode design system (`index.css`):
- **Overview Telemetry (`/`)**: Real-time KPI cards (failed events ingested, active cases, two-evidence verified recoveries, policy block rate, manual review rate, simulated notifications), pipeline state breakdown, recent cases, and live append-only audit stream.
- **Recovery Cases Explorer (`/cases`)**: Filterable table by state (`RECOVERED`, `PAYMENT_CONFIRMED_PENDING_ATTRIBUTION`, `NOTIFIED`, `LINK_CREATED`, `CLOSED_BLOCKED`, `EXPIRED`), policy decision, and ROS band (`HIGH`, `MEDIUM`, `LOW`).
- **Case Investigation Detail (`/cases/:id`)**: Chronological 5-step lifecycle timeline, customer & failed payment attempt context, deterministic policy gate reasons, ROS score feature decomposition, candidate action utility ranking, Test Mode Payment Link status, simulated notification logs, and sanitized audit event timeline.
- **Offline Causal Evaluation Dashboard (`/evaluation`)**:
  - Mandatory persistent disclaimer: `simulated offline estimate; not production conversion evidence`.
  - 3-arm comparison summary (`NO_ACTION`, `GENERIC_REMINDER`, `RETRYPAY_POLICY`).
  - Estimated Incremental Recovery Conversion and GMV with 95% bootstrap confidence intervals.
  - "Inconclusive in this synthetic run" status tag if confidence interval crosses zero.
  - Contact Efficiency (`₹X per synthetic contact`) and Incremental GMV per contact.
  - Policy safety metrics (0.0% unsafe action rate, policy block rate, quiet hours deferral rate).
- **Policy & Guardrails Configuration (`/settings`)**: Read-only merchant policy parameters, quiet hours, single action limit (₹10,000), daily GMV cap (₹50,000), daily action/contact caps (200), and scoring engine versions.

### 2. Local Signed-Webhook Simulator (`/simulator`)
Simulates 14 real-world payment failure and recovery scenarios:
1. **Policy Block: Missing Customer Consent** (Deterministic gate blocks unconsented customer).
2. **Eligible Recovery Outreach Flow** (Policy $\to$ ROS $\to$ Diagnosis $\to$ Test Mode Link $\to$ Notification).
3. **Duplicate Event Deduplication** (Idempotency check ignores duplicate provider event ID).
4. **Invalid Webhook Signature Rejection** (401 Unauthorized rejection before DB mutation).
5. **Independent Capture Without Link** (Customer pays directly $\to$ `CLOSED_BLOCKED`).
6. **Sequence A Reconciliation** (`payment_link.paid` $\to$ `payment.captured` $\to$ `RECOVERED`).
7. **Sequence B Reconciliation** (`payment.captured` $\to$ `PAYMENT_CONFIRMED_PENDING_ATTRIBUTION` $\to$ `payment_link.paid` $\to$ `RECOVERED`).
8. **Payment Link Expired** (`payment_link.expired` $\to$ `EXPIRED`).
9. **Payment Link Cancelled** (`payment_link.cancelled` $\to$ `CLOSED_UNRECOVERED`).
10. **Payment Link Partially Paid** (`payment_link.partially_paid` $\to$ `PAYMENT_CONFIRMED_PENDING_ATTRIBUTION`).
11. **Quiet-Hours Deferral** (Failure during 22:00-08:00 $\to$ `DEFER`).
12. **High-Risk / Hard-Decline Manual Review** (`SUSPECTED_FRAUD` for consented customer $\to$ `MANUAL_REVIEW`).
13. **Budget Cap & Guardrails** (High-value transaction exceeds single action limit).
14. **Attribution Reconciliation Timeout** (Case remains unconfirmed past 30m window $\to$ `CLOSED_BLOCKED`).

### 3. Demo Orchestration Scripts (`scripts/`)
- `scripts/seed_demo_data.py`: Pre-seeds consented customers and initial test cases.
- `scripts/reset_demo.py`: Resets operational database to clean baseline.
- `scripts/demo_walkthrough.py`: Automated 5-minute CLI walkthrough validating all 12 key presentation points.

---

## Safety and Boundary Invariants
1. **Zero External Calls**: All Payment Links and notifications are simulated locally. No real SMS/Email/WhatsApp or live Razorpay API calls are executed.
2. **Local Demo Authentication Notice**: Header explicitly displays: `Local demo operator console — not production authenticated.`
3. **Evaluation Boundaries**: Synthetic metrics are aggregate-only and strictly isolated from operational decisioning.
