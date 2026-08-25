# Product Brief

## Product
ReTryPay recovers eligible failed high-intent payments with the minimum necessary customer intervention. It is a bounded recovery decision system, not an autonomous payment agent.

## Primary user
Merchant operations managers who need recovery visibility, safety controls, and proof of what happened for each case.

## Core loop
`payment.failed` → verify/deduplicate → reconcile current order state → hard policy → ROS → diagnosis → allowed actions → value estimate against `NO_ACTION` → budget/final policy → payment link → notification simulation → captured/expiry/opt-out → audit and evaluation.

## MVP outcomes
- Working Test Mode failed-payment-to-recovery-link flow.
- Zero duplicate recovery actions under duplicate webhook delivery.
- Zero automated actions for paid, opted-out, risk-blocked, or capped cases.
- Dashboard with case timeline, explanation, and synthetic evaluation.

## Out of scope
Real customer messaging, discounts, autonomous instrument retries, production fraud scoring, live uplift claims, and production deployment.

## Source of truth
The finalized PRD and amendments belong in `docs/PRD/`. If this brief conflicts with the PRD, the PRD wins.
