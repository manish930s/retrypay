# ReTryPay PRD — Specification Index

**Status:** Canonical PRD Index for ReTryPay Buildathon MVP  
**Date:** 23 August 2026  

---

## 1. Specification Suite and Reading Order

The canonical product requirements for ReTryPay are defined across the following numbered documents in strict sequential order:

1. [`00_CORE_PRD.md`](file:///d:/Rozerpay/docs/PRD/00_CORE_PRD.md) — Core product, payment recovery workflow, policy, architecture, data model, security, and evaluation baseline.
2. [`01_DECISIONING_AMENDMENT_v1.1.md`](file:///d:/Rozerpay/docs/PRD/01_DECISIONING_AMENDMENT_v1.1.md) — Decision objective, Recovery Opportunity Score (ROS), budgets, decision explanation, incrementality metrics, and policy simulator scope.
3. [`02_CAUSAL_DECISIONING_AMENDMENT_v1.2.md`](file:///d:/Rozerpay/docs/PRD/02_CAUSAL_DECISIONING_AMENDMENT_v1.2.md) — `NO_ACTION` baseline, RecoveryValueEstimator, simulation versus future production modes, and no-outcome-leakage requirements.
4. [`03_ESTIMATOR_BOUNDARY_AMENDMENT_v1.3.md`](file:///d:/Rozerpay/docs/PRD/03_ESTIMATOR_BOUNDARY_AMENDMENT_v1.3.md) — Estimator audit contract, data-access boundary, implementation order, and causal-claim limits.

---

## 2. Precedence, Overrides, and Architectural Alignment

- **Additive & Overriding Principle:** Each amendment modifies or extends only the specific sections it explicitly references. Unmodified sections of previous documents remain in full effect.
- **Complete Canonical Specification:** `00_CORE_PRD.md` combined with amendments `v1.1`, `v1.2`, and `v1.3` constitutes the complete canonical specification.
- **Never Treat v1.3 Alone as the PRD:** Amendment v1.3 defines estimator audit contracts and data-access boundaries; it does not replace the core system, state machine, or policy gates defined in `00_CORE_PRD.md`.
- **Implementation Architecture Alignment:** The provider-neutral diagnosis adapter (supporting Google Gemini when enabled and deterministic rule-based error code classification when disabled or unavailable) is an implementation architecture choice designed to strictly fulfill the PRD's constrained-diagnosis and fail-safe fallback requirements.
- **Authority:** [`AGENTS.md`](file:///d:/Rozerpay/AGENTS.md) remains the ultimate authority for implementation safety, privacy boundaries, and agent behavior rules.
