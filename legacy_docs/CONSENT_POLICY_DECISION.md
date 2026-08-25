# ReTryPay — Customer Consent Policy & Precedence Architecture

**Document Version**: 1.0  
**Status**: Active & Verified  
**Author**: ReTryPay Lead Integration Engineer  

---

## 1. Executive Summary & Consent Hierarchy

ReTryPay enforces a strict, deterministic customer consent hierarchy to guarantee that no automated customer messaging or unauthorized outreach occurs without explicit consent.

### Policy Precedence Matrix

| Consent Status | Policy Decision | Case Target State | Automated Payment Link Creation | Automated Outreach Dispatched | Operator Manual Review Allowed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`OPTED_OUT`** | `PolicyDecisionType.BLOCK` | `CLOSED_BLOCKED` | ❌ **PROHIBITED** | ❌ **PROHIBITED** | ❌ **NO OVERRIDE** |
| **`UNKNOWN` / Missing** | `PolicyDecisionType.MANUAL_REVIEW` | `MANUAL_REVIEW` | ❌ **PROHIBITED** | ❌ **PROHIBITED** | ✅ **REVIEW REQUIRED** |
| **`OPTED_IN`** | `PolicyDecisionType.ELIGIBLE` | Proceed to Evaluation | Conditional on ROS & Budget | Conditional on Delivery Mode | Operator CLI permitted |

---

## 2. Invariants & Behavioral Distinction

1. **Explicit Opt-Out (`OPTED_OUT`)**:
   - Triggers `PolicyReasonCode.CUSTOMER_OPTED_OUT`.
   - Resolves to `PolicyDecisionType.BLOCK` $\rightarrow$ transitions immediately to `CLOSED_BLOCKED` (`closure_reason = CUSTOMER_OPTED_OUT`).
   - Zero overrides allowed. Payment links and notifications are strictly suppressed.

2. **Unknown or Missing Consent (`UNKNOWN` / Missing)**:
   - Triggers `PolicyReasonCode.CONTACT_CONSENT_MISSING`.
   - Resolves to `PolicyDecisionType.MANUAL_REVIEW` $\rightarrow$ transitions to `MANUAL_REVIEW`.
   - Prevents automated payment link creation and automated outreach.
   - Operator console highlights **`Consent: UNKNOWN (NO AUTOMATED MESSAGING)`**.

3. **Explicit Transactional Opt-In (`OPTED_IN`)**:
   - Satisfies Rule 2 consent gate.
   - Allows deterministic policy evaluation to proceed to ROS calculation, utility ranking, and budget reservation.

---

## 3. Pre-Event Consent Protocol for Test Mode Smoke Tests

For developer-owned Test Mode smoke tests:
- Transactional consent must be established **prior to the payment failure event**.
- Do not perform post-event database mutations to bypass consent checks.
- When executing simulated or live merchant order smoke tests, pre-seed or pass customer profile records with `OPTED_IN` consent prior to executing `create_test_order.py` or triggering `payment.failed`.
