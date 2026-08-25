# Evaluation Protocol

## Purpose
Evaluate a synthetic offline simulation; do not claim production causal uplift.

## Strategies
- `NO_ACTION`
- `GENERIC_REMINDER`
- `RETRYPAY_POLICY`

## Potential Outcomes Per Synthetic Case
For every synthetic case, the scenario generator generates three potential counterfactual outcomes:
1. **Hidden outcome under `NO_ACTION`** ($Y(\text{NO\_ACTION})$)
2. **Hidden outcome under `GENERIC_REMINDER`** ($Y(\text{GENERIC\_REMINDER})$)
3. **Hidden outcome under `RETRYPAY_POLICY`** ($Y(\text{RETRYPAY\_POLICY})$)

## Information Boundary
- **Decision System sees:**
  - Observable features (`ObservableCaseFeatures`)
  - Allowed actions (`candidate_allowed_actions`)
  - Simulation distribution parameters (`SimulationDistributionParameters`)
- **Evaluation System only sees:**
  - Strategy assignment (`assignment_strategy`)
  - Hidden outcomes (`HiddenPotentialOutcomes`)
  - Revealed result for the assigned strategy (`realized_outcome`, `realized_gmv_paise`)

## Report Labels
- **Observed recovery GMV:** captured value associated with an active recovery link.
- **Estimated incremental recovery GMV:** simulated/experimental lift above the no-action baseline.
- **Natural recovery rate:** no-action conversion in the declared window.
- **Incremental GMV per contact:** estimated incremental GMV divided by contacted customers.

Every report includes cohort ID, scenario seed, assignment seed, policy version, estimator version, sample size, and the label: `simulated offline estimate; not production conversion evidence`.
