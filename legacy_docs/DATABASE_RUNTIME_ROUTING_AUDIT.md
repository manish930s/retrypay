# Database Runtime Routing & Process Immutability Audit

## Executive Summary

During operational smoke testing of the Razorpay webhook recovery pipeline, a database target mismatch was identified where webhook events were written to `retrypay_smoketest.db` instead of the expected target `retrypay_eligible_smoketest.db`.

This document records the root-cause diagnosis, PowerShell process environment scoping mechanics, implementation of immutable startup database identity, cross-process expected target validation, path/URI canonicalization rules, entry-point preflight enforcement, independent database preservation verification, complete backend/frontend verification results, completed workflow safeguards, and final audit status.

---

## 1. Root-Cause Analysis & Process Environment Scoping

### Root Cause of Mismatch
1. The default `.env` file at project root set `DATABASE_URL=sqlite+aiosqlite:///./retrypay_smoketest.db`.
2. When the Uvicorn web server process was launched in a PowerShell terminal session, environment variables set inline or in separate PowerShell terminals did not propagate to the background Uvicorn process if it was started prior to variable assignment or in a separate process space.
3. As a result, incoming webhooks processed by Uvicorn routed transactions to `retrypay_smoketest.db`.

### PowerShell Environment Scoping Mechanics
- In Windows PowerShell, environment variable assignments (e.g. `$env:DATABASE_URL="..."`) are strictly scoped to the active process and its child processes spawned *after* the assignment.
- Existing running processes (such as a long-running Uvicorn server) do not inherit environment variable mutations made in other terminal sessions.
- Process-level settings must be set before process launch or supplied via an explicit environment template (e.g., `.env.eligible-demo`).

---

## 2. Actual System Architecture & Preflight Execution Boundaries

### Architectural Clarification: API-Integrated Outbox
- There is **no `retrypay/services/outbox_worker.py`** and **no standalone outbox worker runner**.
- Outbox job processing is **API-integrated** in [`retrypay/services/ingestion.py`](file:///d:/Rozerpay/retrypay/services/ingestion.py), specifically inside `WebhookIngestionService.process_webhook_event()`.
- Outbox job creation (`create_outbox_job`) and completion (`mark_completed`) occur atomically within the transactional webhook HTTP request boundary inside the API handler.

### Effective Target & Preflight Boundary Summary

| Execution Boundary / Entry Point | Preflight Mechanism | Effective Resolved Target | Expected Target |
| :--- | :--- | :--- | :--- |
| **1. Uvicorn / FastAPI Lifespan** | Startup preflight in `retrypay/api/app.py` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` |
| **2. API Session Factory** | Preflight check in `retrypay/api/dependencies.py` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` |
| **3. Test Order Script** | Startup preflight in `scripts/create_test_order.py` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` |
| **4. Payment Link CLI** | Startup preflight in `scripts/create_test_mode_payment_link.py` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` | `sqlite+aiosqlite:///./retrypay_eligible_smoketest.db` |

---

## 3. Architectural Design Principles

### 1. Immutable Process Database Identity
- At process startup, `verify_database_routing_preflight(settings)` resolves the canonical target of `DATABASE_URL` and binds it as an immutable global process identity (`_process_canonical_db_target`).
- Any attempt to mutate `DATABASE_URL` or rebind to a different database target within the running process raises a fatal error: `DATABASE_URL mutation detected: process restart required`.
- Session-factory invalidation is allowed only in isolated unit tests (`reset_process_db_target_for_testing()`).

### 2. Cross-Process Expected-Target Validation
- Processes can optionally define `RETRYPAY_EXPECTED_DATABASE_TARGET`.
- During preflight startup, each process validates that:
  $$\text{canonical}(\text{DATABASE\_URL}) == \text{canonical}(\text{RETRYPAY\_EXPECTED\_DATABASE\_TARGET})$$
- If the resolved database target does not match the expected target, the process immediately aborts during preflight with a `DATABASE TARGET MISMATCH` error.

### 3. Canonical Target Resolver Rules
The target resolver (`resolve_canonical_db_target`) normalizes database connection strings by handling:
- **SQLite Schemes**: Standardizes `sqlite+aiosqlite:///`, `sqlite:///`, and relative/absolute paths.
- **Path Resolution**: Converts relative paths (with or without `./`) into absolute lowercase filesystem paths using forward slashes (`/`).
- **Slash Direction**: Replaces backslashes (`\`) with forward slashes (`/`).
- **Query Parameter Filtering & Sorting**: Semantic SQLite parameters (`mode`, `cache`, `immutable`, `vfs`) are preserved in key-sorted order; non-semantic parameters (such as `check_same_thread`) are stripped.

### 4. Safe Diagnostic Health Output
The `/health` endpoint exposes only the startup-bound masked database filename via `get_startup_masked_db_target()`:
```json
{
  "status": "healthy",
  "environment": "demo",
  "policy_version": "recovery-v1.3",
  "llm_enabled": false,
  "database_target": "retrypay_eligible_smoketest.db"
}
```
*Never exposed*: Absolute file paths, credentials, query parameters, or secrets.

---

## 4. Preserved Safety Evidence & Database Integrity Verification

### Safety Constraints Compliance
No intentional database write, VACUUM, initialization, reset, seed, or manual checkpoint command was executed during final closeout.

retrypay_safety_evidence.db remains byte-for-byte unchanged.

retrypay_smoketest.db is preserved in its current post-checkpoint state, but is not byte-for-byte identical to its earlier pre-checkpoint digest.

### Database Preservation Details

- **`retrypay_safety_evidence.db`**:
  Byte-for-byte unchanged and preserved.
  SHA-256 Digest: `25f12427f179ca318366767a07875ee2dbbf9dc53bdc167da8d583287c77ba2f`
- **`retrypay_smoketest.db`**:
  Preserved in its current post-checkpoint state. It is not byte-for-byte identical to the earlier pre-checkpoint digest.
  SHA-256 Digest: `07cf214d3d6f6561ba51fabf6801acc594d690d7971be867ada7db5744f5eaf6`

---

## 5. Completed Workflow Safeguards

- **provider_event_id is mandatory and rejects missing or blank values**: Enforced via request validation, returning `HTTP 400 Bad Request`.
- **X-Razorpay-Signature is cryptographically verified**: Real HMAC-SHA256 verification using the raw request body and `RAZORPAY_WEBHOOK_SECRET`.
- **Provider delivery authentication is separate from dashboard authorization**: Endpoint accepts provider signatures without coupling to dashboard operator auth headers.
- **Replay detection uses AuditEventModel.provider_event_id**: Direct query against the indexed `provider_event_id` column.
- **Concurrent duplicate delivery events are handled idempotently**: Multiple simultaneous deliveries for the same event ID are reconciled safely.
- **IntegrityError is rolled back and returns an ignored response**: Unhandled HTTP 500 errors on race conditions are prevented.
- **Delivery events use source RAZORPAY_WEBHOOK**: Telemetry strictly distinguishes provider webhook events from simulations.
- **before_state is captured dynamically**: Pre-mutation notification status is recorded as `before_state` in the audit event.
- **Invalid terminal-state transitions are rejected**: Transitioning terminal notifications (such as `DELIVERED` to `UNDELIVERABLE`) returns `HTTP 400 Bad Request`.
- **MANUAL_REVIEW cases remain disabled with exactly**:
  - `CONTACT_CONSENT_MISSING`
  - `INSUFFICIENT_CONTEXT`
  - `PAYMENT_LINK_NOT_CREATED`
- **Channel-specific SMS and email consent is enforced**: Consent for one medium (e.g. WhatsApp) does not authorize another (e.g. SMS).
- **No raw PII, secrets, signatures, or provider responses are written to audit metadata**: All audit payloads are strictly sanitized against the allowlist.

---

## 6. Complete Verification Test Results

### Backend
- **python -m pytest**: `284 passed, 0 failed`
- **python -m mypy retrypay tests scripts**: `Success: no issues found in 130 source files`
- **python -m ruff format --check .**: `162 files already formatted`
- **python -m ruff check .**: `All checks passed`

### Frontend
- **npm --prefix web run lint**: `passed, 0 errors`
- **npm --prefix web run test -- --run**: `5 test files passed, 16 tests passed`
- **npm --prefix web run build**: `passed successfully`

---

## 7. Audit Final Status

Recovery Case Reminder Workflow: PASS
Full backend verification: PASS — 284 passed, 0 failed
Frontend verification: PASS
Safety evidence database: PASS
Smoke-test database: preserved post-checkpoint state
Live Razorpay reminder sending: intentionally not tested
Overall status: PASS WITH CONDITIONS
