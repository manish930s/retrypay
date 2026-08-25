# ReTryPay — Post-Webhook Case Telemetry Audit

**Document Version**: 2.0  
**Status**: Completed & Verified  
**Audit Target**: Case `rcv_order_TTde9JZWcuAyF2_924383` (Ingested via real Razorpay Test Mode webhook)  
**Author**: ReTryPay Lead Integration Engineer  

---

## 1. Audit Scope & State Model Resolution

Following the successful receipt of a real Razorpay `payment.failed` webhook for order `order_TTde9JZWcuAyF2`, an exhaustive telemetry audit was conducted.

### Resolved State-Model Hierarchy for Customer Consent
Per merchant operator guidelines and [`docs/CONSENT_POLICY_DECISION.md`](file:///d:/Rozerpay/docs/CONSENT_POLICY_DECISION.md):
- **Explicit Opt-Out (`OPTED_OUT`)**: `PolicyDecisionType.BLOCK` $\rightarrow$ `CLOSED_BLOCKED` (Reason: `CUSTOMER_OPTED_OUT`). No override allowed.
- **Unknown or Missing Consent (`UNKNOWN` / Missing)**: `PolicyDecisionType.MANUAL_REVIEW` $\rightarrow$ `MANUAL_REVIEW` (Reason: `CONTACT_CONSENT_MISSING`). Automated link creation and messaging are strictly prohibited.
- **Explicit Transactional Opt-In (`OPTED_IN`)**: Policy evaluation continues to ROS and candidate selection.

---

## 2. Audit Findings & Database Stale Notice

1. **Notification Adapter Execution**: **ZERO** real HTTP/SMS/WhatsApp network calls were made to external providers.
2. **Delivery Mode & Telemetry Display**:
   - Delivery Mode: `TERMINAL_ONLY`
   - Provider Notifications: `DISABLED`
   - Customer Messaging: `NOT SENT`
   - Contacts Sent: **`0`**
3. **Generic Error Diagnosis**: Generic `BAD_REQUEST_ERROR` / `payment_failed` maps to `FailureDiagnosisCategory.UNKNOWN` with `confidence <= 0.50` and `suggested_action = ActionType.MANUAL_REVIEW`.
4. **Automated Execution Guard**: Generic failures and missing-consent cases route to `MANUAL_REVIEW`. Zero Payment Links are created automatically.
5. **Database Stale Notice**: Historical records in `retrypay_smoketest.db` generated prior to the consent-model update contain legacy initial simulation values (`NOTIFIED`, `temporary_bank_or_network`). Per audit rules, these historical records are **marked as STALE** and not mutated silently. A fresh manual smoke test run will populate a clean database.

---

## 3. Regression Test Verification Matrix

A comprehensive regression test suite is verified in [`tests/unit/test_post_webhook_telemetry_audit.py`](file:///d:/Rozerpay/tests/unit/test_post_webhook_telemetry_audit.py):

| Test Name | Behavioral Invariant Tested | Result |
| :--- | :--- | :--- |
| `test_generic_payment_failure_produces_unknown_diagnosis` | Generic `BAD_REQUEST_ERROR` / `payment_failed` maps to `UNKNOWN` diagnosis and `MANUAL_REVIEW`. | ✅ **PASS** |
| `test_generic_failure_never_creates_payment_link_automatically` | Generic failures route to `MANUAL_REVIEW` and create 0 Payment Links automatically. | ✅ **PASS** |
| `test_unknown_consent_routes_to_manual_review` | Missing / `UNKNOWN` consent evaluates to `MANUAL_REVIEW` with `CONTACT_CONSENT_MISSING`. | ✅ **PASS** |
| `test_explicit_opt_out_blocks_recovery` | `OPTED_OUT` consent evaluates to `BLOCK` and `CLOSED_BLOCKED`. | ✅ **PASS** |
| `test_terminal_only_delivery_records_zero_contacts` | `RAZORPAY_TEST_MODE` source records 0 contacts and creates 0 notification logs. | ✅ **PASS** |
| `test_notified_state_cannot_appear_without_successful_notification_adapter` | Case state cannot transition to `NOTIFIED` without a non-None notification dispatch log. | ✅ **PASS** |
| `test_one_failed_attempt_is_not_displayed_as_five_attempts` | Order with 1 recorded failed attempt returns `len(attempts) == 1`. | ✅ **PASS** |

---

## 4. Empirical Test Suite Run Summary

- **Backend Formatters & Linters**: `157 files clean`, `0 ruff errors`.
- **Backend Type Checker**: `Success: no issues found in 128 source files` (`mypy`).
- **Backend Test Suite**: **`239 / 239 passed`** (Coverage: **89.80%**).
- **Frontend Test Suite**: **`16 / 16 Vitest tests passed`**, production build clean (`dist/assets/index-CyHIH50C.js`).
