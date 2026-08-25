# ReTryPay PRD Amendment v1.3 — Estimator Boundary and Audit Contract

**Document:** `docs/PRD/03_ESTIMATOR_BOUNDARY_AMENDMENT_v1.3.md`  
**Version:** 1.3  
**Date:** 23 August 2026  
**Modifies:** Replaces Estimator result contracts and defines strict information boundaries across all PRD specifications  

---

## 1. Decision

1. Add `baseline_action: NO_ACTION` to every RecoveryValueEstimator estimate and audit record.
2. Enforce a typed information boundary between scenario generation, decisioning, execution, and evaluation.

No further core decisioning features are in scope before implementation. The next work is implementation contracts, scenario data, tests, and a working payment-recovery loop.

---

## 2. Estimator Result Contract

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

### Invariant:
`incremental_probability` must equal `p_recovery_given_action - p_natural_recovery`, within the configured numeric tolerance. The evaluator rejects records that violate this invariant.

Monetary amounts are stored as integer paise; UI converts to INR. The fixed harm/cost penalties in the MVP are simulation assumptions, not estimates of real customer harm.

---

## 3. Information-Boundary Contract

For every synthetic case, the scenario generator generates three strategy-level counterfactual potential outcomes:
1. **Hidden outcome under `NO_ACTION`** (`hidden_outcome_no_action`, `hidden_gmv_no_action_paise`)
2. **Hidden outcome under `GENERIC_REMINDER`** (`hidden_outcome_generic_reminder`, `hidden_gmv_generic_reminder_paise`)
3. **Hidden outcome under `RETRYPAY_POLICY`** (`hidden_outcome_retrypay_policy`, `hidden_gmv_retrypay_policy_paise`)

### Exact Component Access Boundary

```text
Scenario Generator
  ├─ ObservableCaseFeatures ────────────────► Decision Engine (Policy / ROS / Diagnosis / Estimator)
  ├─ Candidate Allowed Actions ─────────────► Decision Engine
  ├─ SimulationDistributionParameters ──────► SimulationEstimator only
  └─ HiddenPotentialOutcomes ───────────────► Evaluation Store only
       ├─ hidden_outcome_no_action & hidden_gmv_no_action_paise
       ├─ hidden_outcome_generic_reminder & hidden_gmv_generic_reminder_paise
       └─ hidden_outcome_retrypay_policy & hidden_gmv_retrypay_policy_paise

Decision Engine
  ├─ AllowedAction + DecisionTrace ─────────► Execution Store
  └─ AssignedStrategy ──────────────────────► Evaluation Store

Evaluation Store
  └─ Reveals outcome ONLY for assigned strategy ──► Aggregate metrics
```

### Access Matrix Summary:
- **Decision System sees:**
  - Observable features (`ObservableCaseFeatures`)
  - Allowed actions (`candidate_allowed_actions`)
  - Simulation distribution parameters (`SimulationDistributionParameters`)
- **Evaluation System only sees:**
  - Strategy assignment (`assignment_strategy`)
  - Hidden outcomes (`HiddenPotentialOutcomes`)
  - Revealed result for the assigned strategy (`realized_outcome`, `realized_gmv_paise`)

### Component Data Access Table

| Component | May read | Must not read |
|---|---|---|
| Policy Engine | Observable features, consent, order/payment state, budgets | Hidden potential outcomes, evaluator result |
| ROS | Observable, deterministic feature set | LLM output, hidden potential outcomes |
| Diagnosis Service | Sanitised observable payment context | Contact data not needed for diagnosis, hidden potential outcomes |
| SimulationEstimator | Observable features, documented distribution parameters, allowed actions | Individual hidden potential outcomes, realised assigned outcome |
| Action Utility Engine | Valid estimator output, costs, allowed actions | Raw hidden outcomes |
| Payment/Notification Executor | Selected action, link/contact data permitted by policy | Outcome under unselected strategy |
| Evaluation Engine | Strategy assignment and hidden outcomes | Authority to select actions |

### Enforcement Requirements
- Use separate Python data classes/schemas: `ObservableCaseFeatures`, `SimulationDistributionParameters`, `HiddenPotentialOutcomes`, `DecisionTrace`, and `EvaluationRecord`.
- Define `HiddenPotentialOutcomes` with 3 strategy outcomes and GMV values:
  ```python
  @dataclass(frozen=True)
  class HiddenPotentialOutcomes:
      hidden_outcome_no_action: bool
      hidden_outcome_generic_reminder: bool
      hidden_outcome_retrypay_policy: bool
      hidden_gmv_no_action_paise: int
      hidden_gmv_generic_reminder_paise: int
      hidden_gmv_retrypay_policy_paise: int
  ```
- Do not serialize `HiddenPotentialOutcomes` into API responses, dashboard payloads, application logs, or the decision database.
- Evaluation data is stored separately from operational case data in the demo repository.
- Add a test that changes hidden potential outcomes while keeping observable inputs fixed; decision output must remain identical.
- Add a test that policy rejects a case before `RecoveryValueEstimator.estimate()` is called.

---

## 4. Audit Record Additions

Every selected action records:
- Decision ID
- Case ID
- Baseline action (`NO_ACTION`)
- Candidate allowed actions
- Selected action
- Policy version and result
- ROS version and feature contributions
- Diagnosis model/version/confidence
- Estimator version/mode/input hash/output hash
- Budget reservation ID
- Execution outcome

---

## 5. Exit Criteria for Causal Claims

- **Allowed Claim:** “On a seeded synthetic cohort, ReTryPay produced an estimated incremental GMV lift relative to a simulated no-action control.”
- **Forbidden Claims:** “ReTryPay causes X% more real customer revenue,” “the model knows who will pay,” or “every linked payment was recovered by the agent.”
