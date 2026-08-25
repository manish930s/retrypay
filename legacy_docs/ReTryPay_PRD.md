# ReTryPay PRD v1.3 — Estimator Boundary and Audit Contract

**Status:** Final core-PRD clarification for Buildathon MVP  
**Date:** 23 August 2026  
**Supersedes:** v1.2 only where stated below

## Decision

Adopt two changes:

1. Add `baseline_action: NO_ACTION` to every RecoveryValueEstimator estimate and audit record.
2. Enforce a typed information boundary between scenario generation, decisioning, execution, and evaluation.

No further core decisioning features are in scope before implementation. The next work is implementation contracts, scenario data, tests, and a working payment-recovery loop.

## Estimator result contract

```json
{
  "case_id": "rcv_01J...",
  "baseline_action": "NO_ACTION",
  "action": "SEND_RETRY_LINK",
  "p_natural_recovery": 0.42,
  "p_recovery_given_action": 0.58,
  "incremental_probability": 0.16,
  "expected_incremental_gmv_paise": 23984,
  "variable_action_cost_paise": 0,
  "customer_harm_penalty_paise": 500,
  "operational_cost_paise": 100,
  "utility_paise": 23384,
  "confidence": 0.75,
  "estimator_version": "sim-estimator-v1",
  "mode": "SIMULATION"
}
```

`incremental_probability` must equal `p_recovery_given_action - p_natural_recovery`, within the configured numeric tolerance. The evaluator rejects records that violate this invariant.

Monetary amounts are stored as integer paise; UI converts to INR. The fixed harm/cost penalties in the MVP are simulation assumptions, not estimates of real customer harm.

## Information-boundary contract

```text
Scenario Generator
  ├─ ObservableCaseFeatures ────────────────► Decision Store / Policy / ROS / Diagnosis
  ├─ SimulationDistributionParameters ──────► SimulationEstimator only
  └─ HiddenPotentialOutcomes ───────────────► Evaluation Store only

Decision Engine
  ├─ AllowedAction + DecisionTrace ─────────► Execution Store
  └─ AssignedStrategy ──────────────────────► Evaluation Store

Evaluation Store
  └─ Reveals outcome only for assigned strategy ─► Aggregate metrics
```

### Allowed data by component

| Component | May read | Must not read |
|---|---|---|
| Policy Engine | Observable features, consent, order/payment state, budgets | Hidden potential outcomes, evaluator result |
| ROS | Observable, deterministic feature set | LLM output, hidden potential outcomes |
| Diagnosis Service | Sanitised observable payment context | Contact data not needed for diagnosis, hidden potential outcomes |
| SimulationEstimator | Observable features, documented distribution parameters, allowed actions | Individual hidden potential outcomes, realised assigned outcome |
| Action Utility Engine | Valid estimator output, costs, allowed actions | Raw hidden outcomes |
| Payment/Notification Executor | Selected action, link/contact data permitted by policy | Outcome under unselected strategy |
| Evaluation Engine | Strategy assignment and hidden outcomes | Authority to select actions |

### Enforcement requirements

- Use separate Python data classes/schemas: `ObservableCaseFeatures`, `SimulationParameters`, `HiddenPotentialOutcomes`, `DecisionTrace`, and `EvaluationRecord`.
- Do not serialize `HiddenPotentialOutcomes` into API responses, dashboard payloads, application logs, or the decision database.
- Evaluation data is stored separately from operational case data in the demo repository.
- Add a test that changes hidden potential outcomes while keeping observable inputs fixed; decision output must remain identical.
- Add a test that policy rejects a case before `RecoveryValueEstimator.estimate()` is called.

## Audit record additions

Every selected action records:

```text
Decision ID
Case ID
Baseline action
Candidate allowed actions
Selected action
Policy version and result
ROS version and feature contributions
Diagnosis model/version/confidence
Estimator version/mode/input hash/output hash
Budget reservation ID
Execution outcome
```

## Implementation order

1. Define schemas and database tables for event, case, decision, action, audit, and evaluation records.
2. Implement webhook verification, event-id deduplication, reconciliation, and state machine.
3. Implement hard policy gates and tests.
4. Implement scenario generator and separated evaluation store.
5. Implement `SimulationEstimator` and utility ranking with `NO_ACTION` baseline.
6. Implement test Payment Link creation, notification mock, captured-event closure, and dashboard trace.
7. Run the three-strategy synthetic evaluation.

## Exit criteria for causal claims

The demo may say: “On a seeded synthetic cohort, ReTryPay produced an estimated incremental GMV lift relative to a simulated no-action control.”

The demo must not say: “ReTryPay causes X% more real customer revenue,” “the model knows who will pay,” or “every linked payment was recovered by the agent.”
