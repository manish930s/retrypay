# ReTryPay PRD Amendment v1.2 — Causal Action Utility and Synthetic Evaluation Protocol

**Document:** `docs/PRD/02_CAUSAL_DECISIONING_AMENDMENT_v1.2.md`  
**Version:** 1.2  
**Date:** 23 August 2026  
**Modifies:** Section 2 and adds Evaluation Specifications to `00_CORE_PRD.md`  

---

## 1. Action Utility Optimization

Candidate recovery actions permitted by the Policy Engine are ranked by expected net utility in integer paise:

$$\text{Utility} = \text{Expected Incremental GMV} - \text{Variable Action Cost} - \text{Customer Harm Penalty} - \text{Operational Cost}$$

- **Baseline Rule:** If the top-ranked action yields negative net utility relative to `NO_ACTION`, `NO_ACTION` is automatically chosen.
- **Monetary Unit:** All internal calculations and storage use integer paise. The frontend converts to INR for display.

---

## 2. Three-Strategy Synthetic Evaluation Protocol

To benchmark policy and recovery effectiveness offline without affecting live customers, the evaluation engine runs a 3-arm comparative simulation on synthetic cohorts:

1. **`NO_ACTION` (Control Arm):** Measures natural baseline recovery rate without any merchant intervention.
2. **`GENERIC_REMINDER` (Naive Arm):** Sends generic payment retry reminders for all failures without diagnosis or policy optimization.
3. **`RETRYPAY_POLICY` (Intelligent Arm):** Full deterministic policy gates + ROS + structured diagnosis + utility optimization.

---

## 3. Evaluation Reporting and Wording Requirements

All evaluation metrics must adhere to the standardized labels defined in `docs/EVALUATION.md`:
- **Observed recovery GMV:** Captured value associated with an active recovery link.
- **Estimated incremental recovery GMV:** Simulated lift above the no-action baseline.
- **Natural recovery rate:** No-action conversion in the declared observation window.
- **Incremental GMV per contact:** Estimated incremental GMV divided by contacted customers.

### Mandatory Report Disclaimer
Every evaluation report and UI view must include:
> `simulated offline estimate; not production conversion evidence`

No claims of real-world causation, predictive customer knowledge, or autonomous recovery agency may be made.
