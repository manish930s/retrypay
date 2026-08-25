# Milestone 3 Technical Notes: Deterministic ROS, Structured Diagnosis, Simulation-Only Estimator & Advisory Traces

## 1. Decisioning Authority Hierarchy

The authority hierarchy remains strictly deterministic and immutable across all evaluation and decision steps:

```text
Verified Webhook & Reconciled Payment State
  → Deterministic Policy Engine (Authoritative Gate)
    → Structured Failure Diagnosis (Conservative 5-Tuple Technical Categorization)
      → Deterministic Recovery Opportunity Score (Prioritization Signal Only)
        → Permitted Action Candidates (Always Includes NO_ACTION)
          → Simulation-Only RecoveryValueEstimator (Synthetic Net Utility)
            → Advisory Action Utility Ranker (Deterministic Advisory Trace)
```

### Core Invariants
- **Policy Always Wins:** If deterministic policy returns `BLOCK`, `MANUAL_REVIEW`, or `DEFER`, the case immediately halts. Zero downstream AI, diagnosis, ROS scoring, candidate generation, or value estimation is executed.
- **AI Cannot Override Policy:** LLMs / Gemini are schema-constrained to technical failure classification only. They cannot authorize actions, assess payment risk, calculate recovery probabilities, or override hard policy.
- **NO_ACTION Baseline:** `NO_ACTION` is always an allowed candidate after an `ELIGIBLE` policy evaluation, with invariant zero incremental probability and zero utility.
- **Simulation-Only Value Estimation:** All value and utility computations are marked with mode `SIMULATION` and version `sim-estimator-v1`. No real-world causal uplift claim is made.

---

## 2. Failure Diagnosis & Versioned Error Mapper (`razorpay-error-map-v1`)

- **Provider Context:** Razorpay may provide `code`, `source`, `step`, `reason`, and metadata for payment errors.
- **Sanitized 5-Tuple Matching:** ReTryPay maps sanitized provider error tuples `(code, source, step, reason, payment_method)` into a small internal diagnostic taxonomy. It never classifies from error code alone.
- **Conservative Mapping Rules:** The mapper is versioned (`razorpay-error-map-v1`) and intentionally conservative.
- **Handling Unknown / Ambiguous Errors:** Unknown, ambiguous, unsupported, or conflicting tuples classify as `unknown` (confidence $0.30$) and lead to `[NO_ACTION, MANUAL_REVIEW]` advisory candidate handling.

### Diagnosis Categories & Mappings

| Diagnosis Category | Evaluated 5-Tuple Patterns (Source, Step, Reason, Method) | Suggested Candidate Action | Baseline Confidence |
|---|---|---|---|
| `temporary_bank_or_network` | `source in (gateway, bank)`, `reason in (bad_request_payment_timed_out, gateway_error, bank_system_error, network_error, timeout)` | `DELAY_AND_SEND_RETRY_LINK` | 0.92 |
| `upi_intent_interrupted` | `method == upi`, `source in (customer, gateway, bank)`, `reason in (upi_payment_timed_out, collect_request_rejected, vpa_not_found, upi_transaction_failed)` | `SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT` | 0.88 |
| `authentication_incomplete` | `source in (customer, bank, gateway)`, `step in (payment_authentication, payment_authorization)`, `reason in (otp_timed_out, invalid_otp, 3ds_authentication_failed)` | `SEND_RETRY_LINK` | 0.85 |
| `soft_decline` | `source in (bank, customer)`, `step == payment_authorization`, `reason in (insufficient_funds, limit_exceeded, card_expired_or_incorrect)` | `SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT` | 0.85 |
| `customer_cancelled` | `source == customer`, `step in (payment_authorization, payment_authentication)`, `reason in (payment_cancelled_by_user, user_dropped_off, transaction_cancelled)` | `SEND_RETRY_LINK` | 0.90 |
| `hard_decline_or_risk` | `source in (gateway, bank, risk)`, `reason in (card_security_violation, suspected_fraud, hard_decline, risk_check_failed, stolen_card, restricted_card)` | `MANUAL_REVIEW` | 1.00 |
| `unknown` | Missing tuple fields, unmapped combinations, or conflicting fields (e.g. card method with UPI code) | `MANUAL_REVIEW` | 0.30 |

---

## 3. Gemini Provider Configuration & Privacy Guarantees

Standardized configuration settings:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=placeholder_gemini_api_key
LLM_MODEL=gemini-3.7-flash
LLM_TIMEOUT_SECONDS=5
LLM_ENABLED=false
```

### Safety & Validation Rules
1. When `LLM_ENABLED=false`:
   - `GEMINI_API_KEY` is not required.
   - `RulesDiagnosisAdapter` remains the default and active adapter.
   - Zero network requests are made to external LLM providers.
2. When `LLM_ENABLED=true` and `LLM_PROVIDER=gemini`:
   - `GEMINI_API_KEY` is strictly required and validated on application startup.
   - Missing or blank key immediately raises a clear configuration `ValidationError`.
3. **Privacy & Redaction Guarantees:**
   - API keys are never logged, never persisted in operational tables, never returned by health endpoints (`/health`), and never included in exception messages.

---

## 4. Deterministic Recovery Opportunity Score (ROS)

The Recovery Opportunity Score (ROS) is an interpretable deterministic integer score clamped to $[0, 100]$. It serves solely as an internal prioritization signal.

$$\text{ROS} = \operatorname{clamp}_{[0, 100]}\left(\sum \text{Feature Family Contributions}\right)$$

### Feature Family Contributions

| Feature Family | Condition / Rule | Score Points | Max Family Points |
|---|---|---|---:|
| **Failure Recoverability** | `temporary_bank_or_network`<br>`upi_intent_interrupted`<br>`authentication_incomplete`<br>`soft_decline`<br>`customer_cancelled`<br>`unknown`<br>`hard_decline_or_risk` | +30<br>+28<br>+22<br>+15<br>+8<br>+5<br>+0 | +30 |
| **Purchase Intent** | Checkout attempt count $\ge 2$<br>Checkout attempt count $= 1$<br>Otherwise | +20<br>+12<br>+0 | +20 |
| **Prior Merchant Relationship** | Customer successful purchases $\ge 3$<br>Customer successful purchases $1-2$<br>First-time customer ($0$) | +15<br>+8<br>+0 | +15 |
| **Risk Penalty** | High risk / hard decline code present<br>Otherwise | -15<br>0 | -15 |
| **Freshness (from Failure UTC)** | Elapsed time $\le 10$ minutes<br>Elapsed time $11-60$ minutes<br>Elapsed time $61-240$ minutes<br>Elapsed time $> 240$ minutes | +10<br>+6<br>+3<br>+0 | +10 |
| **Recovery-Route Suitability** | UPI intent interrupted with alternate payment instrument<br>Temporary network or 2FA failure with retry path<br>Soft decline with alternate instrument<br>Otherwise | +10<br>+7<br>+5<br>+0 | +10 |

#### Stored Advisory Bands:
- `80–100`: `HIGH_OPPORTUNITY`
- `60–79`: `CONSERVATIVE_OPPORTUNITY`
- `0–59`: `LOW_OPPORTUNITY`

---

## 5. Approved Action Types

The decisioning pipeline is restricted exclusively to the following `ActionType` enum values:
- `NO_ACTION`: Baseline null action candidate (always included).
- `SEND_RETRY_LINK`: Create and send a direct retry Payment Link for the order.
- `SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT`: Send retry link with instructional guidance to switch payment methods (e.g. from failed UPI to Cards/Netbanking).
- `DELAY_AND_SEND_RETRY_LINK`: Hold outreach past temporary bank downtime before dispatching retry link.
- `MANUAL_REVIEW`: Escalate case for merchant operator triage.

---

## 6. Simulation-Only RecoveryValueEstimator Formulas

The estimator operates strictly in `SIMULATION` mode (`sim-estimator-v1`):

### Formulas

1. **Incremental Recovery Probability:**
   $$\Delta p = p(\text{recovery} \mid \text{action}) - p(\text{recovery} \mid \text{NO\_ACTION})$$
2. **Expected Incremental GMV:**
   $$\text{Expected Incremental GMV (paise)} = \operatorname{round}(\Delta p \times \text{order\_amount\_paise})$$
3. **Net Expected Action Utility:**
   $$\text{Utility (paise)} = \text{Expected Incremental GMV} - \text{Variable Cost} - \text{Customer Harm Penalty} - \text{Operational Cost}$$

### Fixed Simulation Action Costs (in Paise)

| Action Candidate | Variable Outreach Cost | Customer Harm Penalty | Operational Cost | Total Deductions |
|---|---:|---:|---:|---:|
| `NO_ACTION` | 0 | 0 | 0 | 0 |
| `SEND_RETRY_LINK` | 250 (₹2.50) | 100 (₹1.00) | 50 (₹0.50) | 400 (₹4.00) |
| `SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT` | 250 (₹2.50) | 80 (₹0.80) | 50 (₹0.50) | 380 (₹3.80) |
| `DELAY_AND_SEND_RETRY_LINK` | 250 (₹2.50) | 50 (₹0.50) | 50 (₹0.50) | 350 (₹3.50) |
| `MANUAL_REVIEW` | 500 (₹5.00) | 0 (₹0.00) | 200 (₹2.00) | 700 (₹7.00) |

### Deterministic Tie-Breaking Order
1. Maximum `utility_paise`
2. Lower `customer_harm_penalty_paise`
3. Lower `variable_action_cost_paise`
4. Preference for `NO_ACTION`
5. Lexical order

*Rule:* If all active action candidates produce utility $\le 0$, the ranker deterministically selects `NO_ACTION`.

---

## 7. Strict Data-Access Isolation Boundary

- **No Hidden Outcomes in Decisioning:** Modules inside `retrypay/decision/` (`diagnosis.py`, `ros.py`, `candidates.py`, `estimator.py`, `ranker.py`, `razorpay_error_map.py`) contain zero imports or references to `retrypay/evaluation` or `HiddenPotentialOutcomes`.
- **AST Verification:** Validated by automated AST import inspection in [`test_decision_module_ast_import_isolation`](file:///d:/Rozerpay/tests/unit/test_estimator.py).

---

## 8. Deferred Functionality (Milestone 4+)

The following execution and evaluation features remain out of scope for Milestone 3 and are deferred:
1. **Razorpay Payment Link Creation & Attribution** (Milestone 4)
2. **Customer Messaging & Notification Outreach** (Milestone 4)
3. **Daily Budget Reservation & Consumption Tracking** (Milestone 4)
4. **Synthetic Counterfactual Evaluation Runner & Protocol** (Milestone 5)
5. **Merchant Recovery Dashboard UI** (Milestone 6)
