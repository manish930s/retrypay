# Domain and API Contracts

## Core entities
- `WebhookEvent`: provider_event_id, type, raw_payload_hash, verification_status, received_at.
- `Order`: internal_id, razorpay_order_id, amount_paise, currency, status.
- `PaymentAttempt`: provider_payment_id, order_id, method, status, error context, occurred_at.
- `RecoveryCase`: case_id, order_id, failed_attempt_id, state, policy_version, opened_at.
- `DecisionTrace`: decision_id, allowed_actions, selected_action, policy/ROS/model/estimator versions, hashes, rationale.
- `RecoveryAction`: action_id, case_id, type, idempotency_key, status.
- `PaymentLink`: provider_link_id, reference_id, expiry, amount_paise, status.

## Policy result
```json
{"decision":"ELIGIBLE|BLOCK|MANUAL_REVIEW|DEFER","reasons":["..."],"policy_version":"recovery-v1.3"}
```

## Diagnosis result
```json
{"category":"upi_intent_interrupted|temporary_bank_or_network|authentication_incomplete|soft_decline|customer_cancelled|hard_decline_or_risk|unknown","confidence":0.0,"recommended_action":"SEND_RETRY_LINK|SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT|DELAY_AND_SEND_RETRY_LINK|MANUAL_REVIEW|NO_ACTION","rationale":"..."}
```

## Estimator result
`baseline_action` is always `NO_ACTION`. `incremental_probability = p_recovery_given_action - p_natural_recovery`. Money uses integer paise. Estimator output must be schema validated and audit-hashed.

## External boundaries
Only adapters call Razorpay or a messaging provider. Application services use interfaces; tests use fakes. Never put provider SDK calls in policy, domain, or UI code.
