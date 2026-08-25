# ReTryPay — Agent Instructions

## Mission
Build ReTryPay, a merchant-facing checkout recovery system. It processes failed-payment events, applies hard policy, optionally diagnoses a failure, chooses a permitted action relative to `NO_ACTION`, creates an attributable test Payment Link, and records an audit trail.

## Priority order
1. Correct payment state and webhook handling
2. Policy safety and idempotency
3. Auditability and tests
4. Working end-to-end Test Mode demo
5. Synthetic evaluation and UI polish

## Non-negotiable rules
- Treat verified Razorpay webhooks and reconciled provider state as payment truth; never trust browser callbacks alone.
- Verify webhook signatures from the raw request body. Persist provider event IDs and ignore duplicate business effects.
- Policy is authoritative. AI, ROS, utility ranking, budgets, and UI cannot override a policy block.
- `NO_ACTION` is always an allowed baseline after policy evaluation.
- Never store PAN, CVV, OTP, UPI PIN, API secrets, or webhook secrets in code, logs, fixtures, or UI.
- LLM output is schema-validated and restricted to diagnosis/explanation. It must not calculate ROS, causal uplift, payment risk, or authorize an action.
- Hidden synthetic potential outcomes may be read only by the evaluation module, never policy, estimator, diagnosis, API response, logs, or dashboard.
- Do not label observed payments as caused by ReTryPay. Use the exact dashboard labels defined in `docs/EVALUATION.md`.

## Required change process
- Read `docs/ARCHITECTURE.md`, `docs/DOMAIN_CONTRACTS.md`, and `docs/TEST_STRATEGY.md` before changing payment/recovery code.
- Add or update tests with every behavior change.
- Run formatter, type checks, unit tests, and relevant integration tests before marking work complete.
- Do not introduce a new framework, provider, schema field, or external communication channel without documenting it and asking first.

## Ask first
- Production API keys, live mode, sending messages to non-developer addresses, data deletion/migration, changing recovery policy defaults, adding external SaaS, or changing the causal-evaluation protocol.

## Never
- Execute live payments, message real customers, claim real-world uplift from synthetic data, disable signature checks, bypass policy for demo convenience, or use a hidden outcome in a decision.
