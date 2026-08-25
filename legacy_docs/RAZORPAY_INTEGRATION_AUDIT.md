# Razorpay Integration & Security Architecture Audit

**Audit Status**: **PASS**  
**Audit Date**: 2026-08-24  
**Auditor**: ReTryPay Lead Security & Integration Engineer  

---

## Executive Summary

ReTryPay has completed a comprehensive architecture audit of the **Razorpay Test Mode Integration Mode**. All 13 core integration safety requirements, data hygiene invariants, transactional outbox processing rules, two-phase side-effect boundaries, environment guards, and migration safety checks have been verified and proven with automated tests.

---

## 1. Files Inspected

- `AGENTS.md`
- `README.md`
- `docs/PRD/ReTryPay_PRD_v1.3.md`
- `docs/ARCHITECTURE.md`
- `docs/DOMAIN_CONTRACTS.md`
- `docs/SECURITY_AND_PRIVACY.md`
- `docs/EVALUATION.md`
- `docs/TEST_STRATEGY.md`
- `docs/MILESTONE_0_PLAN.md`
- `docs/RAZORPAY_TEST_MODE_DEMO.md`
- `retrypay/config.py`
- `retrypay/domain/models.py`
- `retrypay/domain/state_machine.py`
- `retrypay/storage/models.py`
- `retrypay/storage/database.py`
- `retrypay/storage/repositories/events.py`
- `retrypay/storage/repositories/cases.py`
- `retrypay/storage/repositories/orders.py`
- `retrypay/storage/repositories/links.py`
- `retrypay/storage/repositories/outbox.py`
- `retrypay/adapters/razorpay/payment_links.py`
- `retrypay/adapters/razorpay/verifier.py`
- `retrypay/adapters/razorpay/normalizer.py`
- `retrypay/execution/orchestrator.py`
- `retrypay/services/ingestion.py`
- `retrypay/api/routes/webhooks.py`
- `retrypay/api/routes/dashboard.py`
- `retrypay/api/routes/simulator.py`
- `scripts/create_test_mode_payment_link.py`
- `web/src/pages/CaseListPage.tsx`

---

## 2. Files Changed

- `retrypay/domain/models.py`: Added `validate_source_origin_compatibility`, `ProviderOperationStatus`, `generate_deterministic_reference_id`, and `NOTIFICATION_PENDING`/`NOTIFICATION_FAILED` case states.
- `retrypay/domain/state_machine.py`: Added valid state transitions for `NOTIFICATION_PENDING` and `NOTIFICATION_FAILED`.
- `retrypay/storage/models.py`: Added `WebhookOutboxJobModel` for transactional outbox persistence.
- `retrypay/storage/repositories/outbox.py`: Created repository managing durable outbox job claims, retries, and completions.
- `retrypay/storage/database.py`: Added pre-index conflict detection in SQLite initialization (`init_db`) that halts cleanly on duplicate composite identifiers without data loss.
- `retrypay/services/ingestion.py`: Added `validate_source_origin_compatibility` guard and `WebhookOutboxJobModel` recording during event ingestion.
- `retrypay/api/routes/dashboard.py`: Enforced strict isolation of `SYNTHETIC_EVALUATION` source cases from `/cases`, `/cases/{case_id}`, and overview operational metrics.
- `retrypay/api/routes/simulator.py`: Enforced strict environment guard rejecting simulator access outside of `RETRYPAY_ENV=test`.
- `scripts/create_test_mode_payment_link.py`: Implemented 2-phase transaction pattern around external provider HTTP call, used `generate_deterministic_reference_id`, and transitioned state to `LINK_CREATED`.
- `web/src/pages/CaseListPage.tsx`: Removed `SYNTHETIC_EVALUATION` option from operational case list filter dropdown.
- **Tests Added**:
  - `tests/unit/test_operational_evaluation_isolation.py`
  - `tests/unit/test_durable_outbox_processing.py`
  - `tests/unit/test_reference_id_safety.py`
  - `tests/unit/test_simulator_env_guard.py`
  - `tests/unit/test_sqlite_migration_safety.py`
  - `tests/unit/test_race_conditions_and_resiliency.py`

---

## 3. Current Architecture

ReTryPay separates merchant operational recovery telemetry from offline synthetic causal evaluation:

```
[ External Razorpay Webhook ] ──(Raw Bytes + HMAC)──> [ /api/v1/webhooks/razorpay ]
                                                              │
                                                        Tx 1 (Envelope + Outbox)
                                                              ▼
                                                     [ WebhookOutboxJobModel ]
                                                              │
                                                        Async Worker Claim
                                                              ▼
                                                     [ Ingestion Service ]
                                                              │
                                                    Policy Engine + Orchestrator
                                                              │
                                                    Phase 1 Tx (Reserve Budget)
                                                              │
                                                     [ Razorpay API Call ]
                                                              │
                                                  Phase 2 Tx (Create Link / State)
```

---

## 4. Source and Origin Compatibility Matrix

Server-side routing strictly validates `(EventSource, IngestionOrigin)` pairs via `validate_source_origin_compatibility`:

| EventSource | IngestionOrigin | Description | Allowed Entry Point |
| :--- | :--- | :--- | :--- |
| `RAZORPAY_TEST_MODE` | `EXTERNAL_RAZORPAY_WEBHOOK` | Verified Razorpay Test Mode webhooks | `/api/v1/webhooks/razorpay` |
| `LOCAL_SIMULATION` | `INTERNAL_SIMULATOR` | Local signed-webhook test simulator | `/api/v1/simulator/trigger` |
| `FAKE_PROVIDER` | `UNIT_TEST_HARNESS` | Isolated automated test harness | Automated pytest fixtures |
| `SYNTHETIC_EVALUATION` | `OFFLINE_EVALUATOR` | Offline 1,000-case counterfactual evaluation | `scripts/run_evaluation.py` |

Any illegal pairing (e.g. `RAZORPAY_TEST_MODE` + `INTERNAL_SIMULATOR` or request header spoofing) raises `HTTP 400 Bad Request`.

---

## 5. Operational and Evaluation Isolation Design

- Operational endpoints (`/api/v1/dashboard/overview`, `/api/v1/dashboard/cases`, `/api/v1/dashboard/cases/{case_id}`) strictly exclude `SYNTHETIC_EVALUATION` records.
- Querying `/cases?source=SYNTHETIC_EVALUATION` returns `HTTP 400 Bad Request`.
- Requesting details for a synthetic case via `/cases/{case_id}` returns `HTTP 404 Not Found`.
- Hidden individual potential outcomes remain strictly encapsulated within the offline evaluation module (`retrypay.evaluation`).

---

## 6. Raw Payload Retention Behavior

- `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD` defaults to `false`.
- When `false`, raw request body bytes are never stored in database columns (`raw_payload`), audit logs, or API responses. Only the cryptographic hash (`payload_sha256`) is stored for deduplication.
- Raw payload retention is validated at application startup and permitted **only** when `RETRYPAY_ENV=test`.

---

## 7. Webhook Acknowledgement and Outbox Flow

- The external route `/api/v1/webhooks/razorpay` executes Transaction 1:
  1. Reads raw bytes and verifies HMAC SHA256 signature against `RAZORPAY_WEBHOOK_SECRET`.
  2. Extracts provider event ID and checks deduplication.
  3. Persists `WebhookEventModel` envelope and `WebhookOutboxJobModel` with status `PENDING`.
  4. Commits Transaction 1 and immediately returns `HTTP 200 OK`.
- Async outbox worker claims `PENDING` outbox jobs, executes normalization, policy evaluation, and case state transitions, then marks outbox jobs `COMPLETED` or `FAILED`.

---

## 8. Provider Side-Effect and Reconciliation Flow

External side effects follow the **Two-Phase Transaction Pattern**:

- **Phase 1 Transaction**:
  1. Fetch fresh case, order, and consent state.
  2. Re-evaluate policy engine gates.
  3. Verify & reserve operational daily budget.
  4. Persist `RecoveryActionModel` (`PENDING`) with deterministic `reference_id`.
  5. Commit Phase 1.
- **External Provider Call**:
  - `RazorpayPaymentLinkProvider.create_payment_link()` is invoked with **no open database transaction**.
- **Phase 2 Transaction**:
  - `PROVIDER_SUCCEEDED`: Persist `PaymentLinkModel`, mark action `EXECUTED`, transition case to `LINK_CREATED`, commit.
  - `PROVIDER_FAILED`: Mark action `FAILED`, release budget reservation, commit.
  - `PROVIDER_RESULT_UNKNOWN`: Mark action status `PROVIDER_RESULT_UNKNOWN`, preserve budget reservation for reconciliation, commit. No duplicate link is created.

---

## 9. Provider Operation State Machine

Separate state tracking prevents overloading recovery action status:

- `RecoveryActionStatus`: `PENDING`, `APPROVED`, `EXECUTED`, `FAILED`, `PROVIDER_RESULT_UNKNOWN`, `CANCELLED`.
- `ProviderOperationStatus`: `NOT_STARTED`, `PENDING`, `SUCCEEDED`, `FAILED`, `UNKNOWN`.
- `RecoveryCaseState`: `LINK_CREATED` is distinct from `NOTIFIED`. Manual CLI execution transitions case to `LINK_CREATED` without making unverified claims of customer notification.

---

## 10. Reference-ID Derivation

- Function: `generate_deterministic_reference_id(case_id, action_id)`
- Format: `rpt_<sha256(case_id + ":" + action_id)[:32]>`
- Length: **36 characters** (strictly $\le 40$ chars).
- Independent of policy version changes and stable across retries for the same action execution.

---

## 11. Payment Link Request Payload Safety

Every Razorpay Test Mode Payment Link creation request explicitly includes:

```json
{
  "amount": 250000,
  "currency": "INR",
  "accept_partial": false,
  "reference_id": "rpt_...",
  "notify": {
    "sms": false,
    "email": false
  },
  "reminder_enable": false
}
```

Customer notifications and reminders are permanently disabled at the provider level.

---

## 12. Simulator Environment Policy

- `test`: Simulator enabled (`/api/v1/simulator/scenarios`, `/api/v1/simulator/trigger`).
- `demo`: Simulator **disabled** (`HTTP 403 Forbidden`). Demo workflow uses real Razorpay Test Mode webhooks.
- `production`: Simulator **disabled** (`HTTP 403 Forbidden`).

---

## 13. Migration Safety Behavior

During `init_db(engine)`:
1. Non-destructive `ALTER TABLE` adds `source VARCHAR(32) DEFAULT 'LOCAL_SIMULATION'` if missing.
2. Backfills existing rows to `LOCAL_SIMULATION`.
3. Executes pre-index conflict detection queries across composite keys `(source, order_id)`, `(source, payment_id)`, `(source, provider_event_id)`, `(source, reference_id)`.
4. If duplicate groups exist, halts immediately with `RuntimeError("MIGRATION HALTED FOR SAFETY...")` without deleting or modifying records.
5. Applies `CREATE UNIQUE INDEX IF NOT EXISTS` only after conflict-free validation.

---

## 14. Payment Event Ordering Behavior

- **Out-of-Order Events**: A `payment.captured` or `order.paid` event arriving before or after failure reconciles cleanly using durable state.
- **Paid Order Invariant**: A captured/paid order cannot be reopened as unpaid. Late `payment.failed` events on a paid order are acknowledged but create no active recovery case.
- **Pending Action Cancellation**: When an order becomes paid via direct store checkout, pending recovery actions are cancelled and active cases transition to `CLOSED_BLOCKED` (`ORDER_ALREADY_PAID` / `PAYMENT_CAPTURED`).

---

## 15. Tests Added or Verified

- `test_dashboard_rejects_synthetic_evaluation_source_query`: Verified 400 rejection.
- `test_synthetic_evaluation_cases_excluded_from_operational_list`: Verified operational case list filtering.
- `test_case_detail_returns_404_for_synthetic_case`: Verified 404 rejection.
- `test_header_cannot_override_event_source`: Verified header non-authority.
- `test_invalid_source_origin_pairs_rejected`: Verified boundary validation.
- `test_raw_payload_not_persisted_when_retention_disabled`: Verified raw payload masking.
- `test_outbox_job_created_atomically`: Verified outbox creation in Tx 1.
- `test_worker_claims_and_completes_outbox_job`: Verified async outbox execution.
- `test_unprocessed_outbox_job_survives_worker_restart`: Verified worker restart resilience.
- `test_reference_id_length_bounded`: Verified length $\le 40$ chars.
- `test_reference_id_stable_across_retries`: Verified deterministic stability.
- `test_reference_id_collision_resistance`: Verified 1,000-run zero collisions.
- `test_payment_link_request_payload_safety`: Verified `notify.sms=False`, `notify.email=False`, `reminder_enable=False`.
- `test_simulator_disabled_in_development_environment`: Verified HTTP 403 env guard.
- `test_migration_halts_safely_on_duplicate_order_ids`: Verified non-destructive migration halt.
- `test_payment_succeeds_before_recovery_worker`: Verified race condition handling.
- `test_duplicate_captured_event_idempotency`: Verified duplicate capture idempotency.
- `test_order_paid_without_prior_local_captured_event`: Verified direct `order.paid` handling.

---

## 16. Known Limitations

- SQLite polling worker is used for outbox execution in MVP single-process mode; PostgreSQL `LISTEN/NOTIFY` or background Celery queue can be adopted in production deployments.
- Manual CLI link creation requires merchant operator terminal access in `demo` environment.

---

## 17. Exact Validation Commands

```bash
# 1. Formatters and Type Checks
python -m ruff check .
python -m ruff format --check .
python -m mypy retrypay tests scripts

# 2. Complete Test Suite & Coverage
$env:PYTHONPATH="."
python -m pytest --cov=retrypay --cov-report=json:coverage.json tests/
python scripts/check_coverage.py coverage.json

# 3. Frontend Verification
cd web
npm run build
```
