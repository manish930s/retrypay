# ReTryPay — Milestone 0 Architecture & Foundation Plan

**Document:** `docs/MILESTONE_0_PLAN.md`  
**Status:** Approved for Milestone 0 Baseline (Incorporating All Canonical PRD & Architectural Directives)  
**Date:** 23 August 2026  
**Scope:** Repository Baseline, Architecture Contracts, Quality Tooling, and Implementation Strategy for Buildathon MVP  

---

## 1. Proposed Repository Structure

The repository enforces strict module separation with a decoupled boundary between operational recovery logic, external adapters, and the isolated causal evaluation subsystem (as required by the canonical PRD suite).

```text
d:/Rozerpay/
├── .agents/
│   └── skills/
│       └── retrypay-delivery/
│           └── SKILL.md                  # Workflow skill and delivery guidelines
├── .github/
│   └── workflows/
│       └── ci.yml                        # Automated CI workflow (lint, type-check, multi-gate coverage, secret scan)
├── docs/
│   ├── PRD/                              # Canonical PRD Specification Suite
│   │   ├── PRD_INDEX.md                  # Canonical index, reading order, and override rules
│   │   ├── 00_CORE_PRD.md                # Core product, workflow, policy, data model, and evaluation baseline
│   │   ├── 01_DECISIONING_AMENDMENT_v1.1.md # Decision objective, ROS, budgets, explanations, incrementality
│   │   ├── 02_CAUSAL_DECISIONING_AMENDMENT_v1.2.md # NO_ACTION baseline, estimator, leakage requirements
│   │   └── 03_ESTIMATOR_BOUNDARY_AMENDMENT_v1.3.md # Estimator audit contract, access boundary, causal limits
│   ├── ARCHITECTURE.md                   # System topology, hierarchy, and invariants
│   ├── DOMAIN_CONTRACTS.md               # Entities, policy, and estimator contracts
│   ├── EVALUATION.md                     # Causal evaluation and report label protocol
│   ├── IMPLEMENTATION_PLAN.md            # Phased roadmap (Milestones 0 to 5)
│   ├── MILESTONE_0_PLAN.md               # This foundational plan document
│   ├── PRODUCT_BRIEF.md                  # Scope, bounds, and user definitions
│   ├── SECURITY_AND_PRIVACY.md           # PII, secret redaction, and webhook integrity
│   └── TEST_STRATEGY.md                  # Test pyramid and 10 mandatory regression tests
├── retrypay/                             # Core Python Application Package
│   ├── __init__.py
│   ├── config.py                         # Pydantic Settings & environment validation (hard gate checks)
│   ├── domain/                           # Pure Domain Entities & Information Boundaries
│   │   ├── __init__.py
│   │   ├── models.py                     # Case, Order, Attempt, Action, Link entities
│   │   ├── events.py                     # WebhookEvent, DomainEvent types
│   │   ├── boundaries.py                 # ObservableCaseFeatures, SimulationParams, HiddenPotentialOutcomes
│   │   ├── state_machine.py              # Case lifecycle state transitions
│   │   └── errors.py                     # Domain exceptions (e.g. PolicyViolation, StateConflict)
│   ├── policy/                           # Deterministic Policy Engine (Authoritative)
│   │   ├── __init__.py
│   │   ├── engine.py                     # Hard gate evaluator (opt-out, quiet hours, caps, risk)
│   │   ├── rules.py                      # Pure rule definitions and decision reason codes
│   │   └── budgets.py                    # Action and contact volume budget controller
│   ├── decision/                         # Prioritization, Diagnosis & Value Estimation
│   │   ├── __init__.py
│   │   ├── ros.py                        # Recovery Opportunity Score (deterministic, explainable)
│   │   ├── diagnosis.py                  # Provider-neutral diagnosis service with strict schema fallback
│   │   ├── estimator.py                  # SimulationEstimator (NO_ACTION baseline & uplift math)
│   │   └── utility.py                    # Net action utility ranking in integer paise
│   ├── adapters/                         # External Boundaries & Integrations
│   │   ├── __init__.py
│   │   ├── razorpay/                     # Razorpay Test Mode client & webhook signature verifier
│   │   │   ├── client.py
│   │   │   └── verifier.py               # Raw-body HMAC-SHA256 timing-safe verifier
│   │   ├── messaging/                    # Simulated notification adapter (WhatsApp/SMS log)
│   │   │   └── mock_channel.py
│   │   └── llm/                          # Provider-neutral LLM client interface
│   │       ├── base.py                   # DiagnosisAdapter abstract interface
│   │       ├── gemini.py                 # Google Gemini client (configured when LLM_ENABLED=true)
│   │       └── rules.py                  # Deterministic rule-based fallback client
│   ├── storage/                          # Persistence & Operational Repositories
│   │   ├── __init__.py
│   │   ├── database.py                   # SQLAlchemy async engine & session factories
│   │   ├── models.py                     # Operational ORM tables (cases, events, traces, actions)
│   │   └── repositories/                 # CaseRepo, EventRepo, AuditRepo
│   ├── evaluation/                       # Isolated Causal Simulation Subsystem
│   │   ├── __init__.py
│   │   ├── scenario_generator.py         # Generates observable cases + 3 strategy hidden outcomes
│   │   ├── store.py                      # Separate evaluation database repository
│   │   ├── simulator.py                  # 3-strategy simulation runner
│   │   └── metrics.py                    # Aggregate lift calculations & report formatter
│   └── api/                              # HTTP API & Webhook Ingestion
│       ├── __init__.py
│       ├── app.py                        # FastAPI application factory & lifespan
│       ├── dependencies.py               # Dependency injection container
│       └── routes/
│           ├── webhooks.py               # Raw-memory Razorpay webhook ingestion (minimized persistence)
│           ├── cases.py                  # Case list, detail, and timeline endpoints
│           ├── simulation.py             # Evaluation trigger & scenario inspection (restricted envs)
│           └── health.py                 # Health and configuration readiness
├── web/                                  # Merchant Dashboard (React + Vite, Milestone 3+ deliverable)
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
├── tests/                                # Test Suite (Pytest)
│   ├── conftest.py                       # Fixtures, test DBs, and provider fakes
│   ├── unit/
│   │   ├── test_policy_engine.py         # Hard gates, opt-out, quiet hours, caps
│   │   ├── test_state_machine.py         # State lifecycle transitions
│   │   ├── test_ros_calculation.py       # Deterministic scoring
│   │   ├── test_estimator_utility.py     # NO_ACTION baseline & invariant checks
│   │   ├── test_data_boundaries.py       # Information boundary invariance & forbidden imports test
│   │   └── test_diagnosis_fallback.py    # Schema validation & JSON failure handling
│   ├── integration/
│   │   ├── test_webhook_signatures.py    # Raw payload HMAC-SHA256 verification
│   │   ├── test_event_deduplication.py   # Duplicate & out-of-order webhook delivery
│   │   ├── test_razorpay_adapter.py      # Test Mode payment link creation & reconciliation
│   │   └── test_repositories.py          # Operational DB transactions
│   └── scenario/
│       ├── test_e2e_recovery_flow.py     # failed -> link -> captured closure
│       ├── test_paid_before_worker.py    # Pre-empted payment suppresses link
│       └── test_evaluation_protocol.py   # Multi-strategy reproducibility & seed test
├── scripts/
│   ├── seed_scenarios.py                 # Generates deterministic test cohorts
│   ├── run_evaluation.py                 # CLI evaluator runner
│   ├── check_coverage.py                 # Package-level coverage enforcement script
│   └── demo_walkthrough.py               # Automated 5-minute demo runner
├── .env.example
├── .gitignore
├── pyproject.toml                        # Build, Ruff, MyPy, and Pytest configuration
├── README.md
└── AGENTS.md
```

---

## 2. Selected Technology Stack with Short Justification

| Layer / Tool | Selection | Justification |
|---|---|---|
| **Language & Supported Runtime** | **Python >=3.12, <3.14** | Fully typed, stable language baseline for financial logic, async APIs, and deterministic simulation algorithms. Python 3.12 is the primary target. |
| **API Framework** | **FastAPI + Uvicorn** | Async ASGI framework providing streaming memory access to raw request bytes (mandatory for timing-safe HMAC-SHA256 signature verification) and automatic OpenAPI documentation. |
| **Data Validation** | **Pydantic v2** | High-performance schema parsing and compile/runtime information boundary enforcement (`ObservableCaseFeatures`, `DiagnosisResult`, `EstimatorResult`). |
| **Database & ORM** | **SQLite + SQLAlchemy 2.0 (Async Engine via `aiosqlite`)** | Lightweight, zero-daemon persistence for local development with WAL mode. Two physically separate DB files (`data/retrypay.db` and `data/retrypay_eval.db`) act as a defense-in-depth isolation layer. |
| **LLM Diagnosis Adapter** | **Provider-Neutral Interface (Google Gemini 2.0 Flash / Deterministic Rules)** | Decoupled diagnosis layer. Fully functional with `LLM_ENABLED=false` using deterministic error-code mapping. |
| **Frontend UI (Milestone 3+)** | **React + Vite + Modern CSS** | Frontend UI begins after Milestone 2 policy and state-machine tests pass. The initial UI scope is implemented in Milestone 3 or later and consists only of a case list, case detail view, and audit timeline. |
| **Code Quality** | **Ruff + MyPy (Strict Mode)** | Sub-second linting, formatting, and strict type verification (`disallow_untyped_defs = true`). |
| **Test Framework** | **Pytest + pytest-asyncio + pytest-mock + pytest-cov** | Async test execution with multi-tiered coverage enforcement. |

---

## 3. Local Development Prerequisites

1. **Python:** `Python >=3.12, <3.14` (supported runtime target).
2. **Node.js & npm:** Node 18+ (for dashboard development in Milestone 3+).
3. **Git** for version control.
4. **Local Infrastructure Boundary:**
   > No managed database or cloud hosting is required for local development. Razorpay Test Mode and optional Gemini API calls are external services. The MVP remains runnable using mock Razorpay and deterministic diagnosis adapters when credentials are unavailable.

---

## 4. Environment-Variable Inventory (Placeholders Only)

```bash
# ==============================================================================
# ReTryPay Environment Configuration (Test Mode & Simulation Only)
# ==============================================================================

# Application Environment (test | demo | production_blocked)
RETRYPAY_ENV=test
RETRYPAY_HOST=127.0.0.1
RETRYPAY_PORT=8000
RETRYPAY_LOG_LEVEL=INFO
DEBUG=true

# Security & Razorpay Test Credentials (PLACEHOLDERS ONLY - MUST USE rzp_test_*)
RAZORPAY_KEY_ID=rzp_test_placeholder_key_id
RAZORPAY_KEY_SECRET=rzp_test_placeholder_secret
RAZORPAY_WEBHOOK_SECRET=retrypay_test_webhook_secret_key_123

# Webhook Ingestion & Data Minimization (Hard Gate: Test env only)
RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=false

# LLM Diagnosis Provider (Provider-Neutral Configuration)
LLM_PROVIDER=gemini
GEMINI_API_KEY=placeholder_gemini_api_key
LLM_MODEL=gemini-2.0-flash
LLM_TIMEOUT_SECONDS=5
LLM_ENABLED=false

# Persistence Storage (Defense-in-depth database separation)
DATABASE_URL=sqlite+aiosqlite:///./data/retrypay.db
EVALUATION_DATABASE_URL=sqlite+aiosqlite:///./data/retrypay_eval.db

# Recovery Policy Defaults (Canonical PRD Thresholds)
POLICY_VERSION=recovery-v1.3
DEFAULT_LINK_EXPIRY_MINUTES=1440
MAX_AUTO_RECOVERY_AMOUNT_PAISE=1000000
MAX_AUTO_RECOVERY_GMV_PER_DAY_PAISE=5000000
MAX_AUTO_ACTIONS_PER_DAY=200
MAX_CONTACT_COUNT_PER_DAY=200
MAX_MESSAGES_PER_ORDER=2
MAX_MESSAGES_PER_CUSTOMER_30D=3
DEFAULT_QUIET_HOURS_START=22
DEFAULT_QUIET_HOURS_END=8

# Evaluation & Simulation Defaults
EVALUATION_DEFAULT_SAMPLE_SIZE=500
EVALUATION_DEFAULT_SEED=42
```

---

## 5. Docker / Local Service Plan

- **Phase 1 (Milestones 0–4 Local Development):** Fully self-contained local Python environment. APIs run via `uvicorn retrypay.api.app:app --reload`. SQLite databases are managed inside `./data/`.
- **Phase 2 (Milestone 5 Evaluator / Containerization):** Multi-stage `Dockerfile` and `docker-compose.yml` to package:
  - `retrypay-backend`: FastAPI service on port `8000`.
  - `retrypay-frontend`: Production build of Vite SPA on port `3000`.
  - Volume mount `./data` for persistent audit logs and scenario evaluation databases.

---

## 6. Database and Migration Strategy

### Defense-in-Depth Storage Isolation & Data Access Boundaries
Physical database separation is a defense-in-depth control. The primary prevention mechanism is explicit module boundaries, restricted repository interfaces, no evaluation-store imports from operational modules, and automated information-boundary regression tests.

### Synthetic Potential Outcomes Per Case:
For every synthetic case, the generator creates three strategy-level counterfactual potential outcomes:
1. `hidden_outcome_no_action: bool` & `hidden_gmv_no_action_paise: int` ($Y(\text{NO\_ACTION})$)
2. `hidden_outcome_generic_reminder: bool` & `hidden_gmv_generic_reminder_paise: int` ($Y(\text{GENERIC\_REMINDER})$)
3. `hidden_outcome_retrypay_policy: bool` & `hidden_gmv_retrypay_policy_paise: int` ($Y(\text{RETRYPAY\_POLICY})$)

### Exact Component Access Boundary:
- **Decision System sees:**
  - Observable features (`ObservableCaseFeatures`)
  - Allowed actions (`candidate_allowed_actions`)
  - Simulation distribution parameters (`SimulationDistributionParameters`)
- **Evaluation System only sees:**
  - Strategy assignment (`assignment_strategy`)
  - Hidden outcomes (`HiddenPotentialOutcomes`)
  - Revealed result for the assigned strategy (`realized_outcome`, `realized_gmv_paise`)

### Webhook Data Minimization & Retention Hard Gate:
- Webhook signatures are verified against raw bytes in memory.
- `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=false` by default.
- **Hard Safety Rule:** Raw webhook payload retention may be enabled **only when `RETRYPAY_ENV=test`**.
- Application startup **must fail** if `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=true` and `RETRYPAY_ENV` is `demo`, `production_blocked`, or any unsupported environment.
- The `demo` environment must use minimized normalized fields only.
- This project must **never retain raw real-customer webhook payloads**.

### Required Module Import & Access Rules:
1. `retrypay/policy/` must not import `retrypay/evaluation/`.
2. `retrypay/decision/` must not import hidden-outcome models (`HiddenPotentialOutcomes`).
3. API responses, logs, and operational repositories must not expose hidden potential outcomes.
4. Automated unit test `test_data_boundaries.py` asserts that no forbidden imports exist.
5. Automated test verifies that altering hidden counterfactual outcomes produces identical decision outputs given fixed observable features.

### 1. Operational Database Schema (`retrypay.db`)
- `webhook_events`: Ingested event ledger with data minimization:
  - `provider_event_id` (PK, String)
  - `event_type` (String)
  - `received_at` (DateTime)
  - `signature_verification_status` (String)
  - `payload_sha256` (String)
  - Normalized fields: `order_id`, `payment_id`, `amount_paise`, `currency`, `method`, `error_code`
  - `processing_status` (String)
  - `error_reason` (Nullable String)
  - *(Raw request body is retained only in memory for verification; persisted only if `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=true` and `RETRYPAY_ENV=test`).*
- `orders`: `internal_id` (PK), `razorpay_order_id` (UK), `amount_paise`, `currency`, `status`, `customer_id_masked`, timestamps.
- `payment_attempts`: `provider_payment_id` (PK), `order_id` (FK), `method`, `status`, `error_code`, `error_description`, timestamps.
- `recovery_cases`: `case_id` (PK), `order_id` (FK, unique active case constraint), `failed_attempt_id` (FK), `state`, `policy_version`, `quiet_hours_applied`, `contact_count`, `closed_at`, `closure_reason`.
- `decision_traces`: `decision_id` (PK), `case_id` (FK), `baseline_action` (`NO_ACTION`), `allowed_actions` (JSON), `selected_action`, `policy_version`, `policy_result` (JSON), `ros_score`, `ros_contributions` (JSON), `diagnosis_category`, `diagnosis_confidence`, `estimator_version`, `estimator_input_hash`, `estimator_output_hash`, `utility_paise`, `budget_reservation_id`, `created_at`.
- `recovery_actions`: `action_id` (PK), `case_id` (FK), `action_type`, `idempotency_key` (UK: `case_id + action_type + policy_version`), `status`, `executed_at`.
- `payment_links`: `provider_link_id` (PK), `action_id` (FK), `reference_id` (UK), `short_url`, `amount_paise`, `status`, `expires_at`.
- `notification_logs`: `notification_id` (PK), `action_id` (FK), `channel`, `recipient_masked`, `message_preview`, `status` (`SIMULATED`), `sent_at`.

### 2. Isolated Evaluation Database Schema (`retrypay_eval.db`)
Supports reproducible multiple evaluation runs over synthetic case cohorts:
- `evaluation_records`:
  - `evaluation_record_id` (PK, String)
  - `evaluation_run_id` (String, Indexed) — Unique identifier per evaluation batch
  - `cohort_id` (String)
  - `case_id` (String) — Reference to synthetic case
  - *Unique Constraint: `(evaluation_run_id, case_id)`*
  - `scenario_seed` (Integer)
  - `assignment_seed` (Integer)
  - `policy_version` (String)
  - `estimator_version` (String)
  - `assigned_strategy` (String: `NO_ACTION` | `GENERIC_REMINDER` | `RETRYPAY_POLICY`)
  - `assigned_action` (String)
  - `hidden_outcome_no_action` (Boolean) — $Y(\text{NO\_ACTION})$
  - `hidden_outcome_generic_reminder` (Boolean) — $Y(\text{GENERIC\_REMINDER})$
  - `hidden_outcome_retrypay_policy` (Boolean) — $Y(\text{RETRYPAY\_POLICY})$
  - `hidden_gmv_no_action_paise` (Integer)
  - `hidden_gmv_generic_reminder_paise` (Integer)
  - `hidden_gmv_retrypay_policy_paise` (Integer)
  - `realized_outcome` (Boolean — revealed ONLY for assigned strategy)
  - `realized_gmv_paise` (Integer — revealed ONLY for assigned strategy)
  - `evaluated_at` (DateTime)

---

## 7. Code-Quality Tools & Multi-Tiered Coverage Enforcement

Configured centrally in `pyproject.toml` and verified via CI:
- **Formatter & Linter:** `ruff` (configured with E, F, W, I, UP, B, C4 rules).
- **Static Type Checker:** `mypy` (strict mode enabled: `disallow_untyped_defs = true`, `warn_return_any = true`).
- **Test Framework:** `pytest` with `pytest-asyncio` and `pytest-cov`.
- **Multi-Tiered Coverage Enforcement Architecture:**
  - Overall project coverage threshold: **>= 80%**.
  - Package-level coverage threshold for core safety components (`retrypay/domain`, `retrypay/policy`, `retrypay/evaluation`): **>= 95%**.
  - Package-level thresholds are enforced explicitly in CI via a dedicated validation script (`scripts/check_coverage.py`) and discrete `pytest-cov` reporting, rather than relying on a single global `fail_under` configuration.

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "C4"]
ignore = []

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
minversion = "7.0"
addopts = "-ra -q --strict-markers"
testpaths = ["tests"]
asyncio_mode = "auto"
```

---

## 8. CI Workflow Plan (`.github/workflows/ci.yml`)

1. **Lint & Code Format:** `ruff check .` and `ruff format --check .`
2. **Static Type Analysis:** `mypy retrypay tests`
3. **Automated Test Suite with Multi-Tier Coverage Gates:**
   - Execute test suite: `pytest --cov=retrypay --cov-report=json tests/`
   - Run `python scripts/check_coverage.py` asserting overall coverage >= 80% and domain/policy/evaluation >= 95%.
4. **Secret Scanning & Live-Mode Rejection Test:**
   - Automated test asserting that initializing `Settings` with live Razorpay keys (`rzp_live_*`) raises a hard validation error.
   - Dedicated scanning to prevent committed keys, credentials, or unmasked PAN/CVV tokens.
5. **Environment Security & Ingestion Gate Tests:**
   - Automated test verifying that setting `RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=true` outside `RETRYPAY_ENV=test` fails at startup.
   - Automated test verifying that `POST /api/v1/simulations/run` returns `403 Forbidden` / `404 Not Found` when `RETRYPAY_ENV` is not `test` or `demo`.
6. **Causal Data Boundary Assertion:**
   - AST import scan verifying that `retrypay/policy/` and `retrypay/decision/` do not import evaluation modules or hidden models.
   - Invariance test verifying that varying hidden counterfactuals produces identical decision traces.

---

## 9. Initial API and Domain Module Layout

### Domain Information Boundaries (`retrypay/domain/boundaries.py`)
```python
from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass(frozen=True)
class ObservableCaseFeatures:
    case_id: str
    order_id: str
    amount_paise: int
    payment_method: str
    error_code: str
    error_description: str
    customer_contact_consent: bool
    customer_opt_out: bool
    previous_recovery_attempts: int
    attempt_timestamp: str


@dataclass(frozen=True)
class SimulationDistributionParameters:
    base_recovery_rate: float
    intent_multiplier: float
    channel_responsiveness: float


@dataclass(frozen=True)
class HiddenPotentialOutcomes:
    hidden_outcome_no_action: bool
    hidden_outcome_generic_reminder: bool
    hidden_outcome_retrypay_policy: bool
    hidden_gmv_no_action_paise: int
    hidden_gmv_generic_reminder_paise: int
    hidden_gmv_retrypay_policy_paise: int


@dataclass(frozen=True)
class DecisionTrace:
    decision_id: str
    case_id: str
    baseline_action: str  # Invariant: always "NO_ACTION"
    candidate_allowed_actions: List[str]
    selected_action: str
    policy_version: str
    policy_decision: str
    policy_reasons: List[str]
    ros_score: float
    ros_contributions: Dict[str, float]
    diagnosis_category: str
    diagnosis_confidence: float
    estimator_version: str
    estimator_mode: str
    estimator_input_hash: str
    estimator_output_hash: str
    budget_reservation_id: Optional[str]
    utility_paise: int
```

### Initial API Routes Layout
- `POST /api/v1/webhooks/razorpay`: Ingests raw-body webhooks in memory, verifies HMAC-SHA256, deduplicates event ID, initiates recovery evaluation without storing raw body by default.
- `GET /api/v1/cases`: Lists recovery cases with filters for state, date, and status.
- `GET /api/v1/cases/{case_id}`: Returns single case details, order details, and action history.
- `GET /api/v1/cases/{case_id}/audit-trail`: Complete immutable decision trace including rule evaluations, ROS scores, and hashes.
- `POST /api/v1/cases/{case_id}/review`: Operator override for `MANUAL_REVIEW` cases.
- `POST /api/v1/simulations/run`: **Restricted endpoint.** Executes multi-strategy simulation on synthetic cohort only when `RETRYPAY_ENV` is `test` or `demo` (returns 403/404 in all other environments).
- `GET /api/v1/evaluations/report`: Returns aggregate lift statistics with mandatory synthetic evaluation disclaimer.
- `GET /api/v1/health`: System health and readiness checks.

---

## 10. Risks, Unresolved Assumptions, and Questions Requiring Confirmation

### Risks & Mitigations
1. **Webhook Ingestion Signature & Minimization:** Starlette/FastAPI body streams must be captured in memory as bytes before parsing JSON.
   - *Mitigation:* Ingest endpoint uses `await request.body()` for HMAC verification, extracts normalized fields, and discards raw bytes.
2. **Hidden Outcome Data Leakage:**
   - *Mitigation:* Enforced via AST import tests, separate DB connections, and invariance tests.
3. **Environment Security Invariants:**
   - *Mitigation:* Application startup validator in `retrypay/config.py` rejects live Razorpay credentials, blocks simulation routes outside test/demo modes, and rejects raw webhook body retention outside test mode.

### Assumptions
- Python 3.12 is the primary development baseline.
- Deterministic rule-based diagnosis operates as the default mode (`LLM_ENABLED=false`).

---

## 11. Precise Milestone 0 Definition of Done

Milestone 0 is complete when:
- [x] Canonical PRD suite is organized in `docs/PRD/` with complete reading order index in `docs/PRD/PRD_INDEX.md`.
- [x] `docs/MILESTONE_0_PLAN.md` reflects all architectural directives, security invariants, coverage gates, and boundary protections.
- [ ] Project scaffolding (`retrypay/`, `tests/`, `scripts/`) is created with empty placeholder modules.
- [ ] Configuration manager (`retrypay/config.py`) loads and validates settings with live-mode rejection and raw-retention gating.
- [ ] Dependency files (`pyproject.toml`, `.env.example`, `.gitignore`) are committed.
- [ ] Quality tools (`ruff`, `mypy`, `pytest`) run clean with zero errors.
- [ ] Base test harness runs and asserts baseline passes.
