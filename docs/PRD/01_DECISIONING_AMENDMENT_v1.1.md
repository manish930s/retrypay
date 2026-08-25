# ReTryPay PRD Amendment v1.1 — Deterministic ROS and Diagnosis Contract

**Document:** `docs/PRD/01_DECISIONING_AMENDMENT_v1.1.md`  
**Version:** 1.1  
**Date:** 23 August 2026  
**Modifies:** Section 2 and Section 4 of `00_CORE_PRD.md`  

---

## 1. Recovery Opportunity Score (ROS)

The Recovery Opportunity Score is a deterministic, fully explainable numerical score (0 to 100) indicating the likelihood of customer recovery prior to action ranking.

- **Inputs:** Observable payment attempt signals (failure category, previous attempt count, amount tier, device/network hint, time since failure).
- **Rule:** ROS computation must be completely deterministic and accompanied by an explicit feature contribution breakdown in the audit log.
- **Boundary:** ROS never authorizes actions alone and cannot override policy blocks.

---

## 2. Structured Failure Diagnosis Service

Provides qualitative context and categorization for why a payment failed to select the most appropriate recovery channel and message template.

### Provider-Neutral Interface
The diagnosis service operates behind a provider-neutral interface (`DiagnosisAdapter`), supporting:
1. `GeminiDiagnosisClient` (Google Gemini 2.0 Flash) when `LLM_ENABLED=true` and `GEMINI_API_KEY` is present.
2. `DeterministicRuleDiagnosisClient` (Rule-based classification fallback based on Razorpay error codes) when `LLM_ENABLED=false` or when the remote model is unavailable.

### Structured Output Schema
```json
{
  "category": "upi_intent_interrupted | temporary_bank_or_network | authentication_incomplete | soft_decline | customer_cancelled | hard_decline_or_risk | unknown",
  "confidence": 0.85,
  "recommended_action": "SEND_RETRY_LINK | SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT | DELAY_AND_SEND_RETRY_LINK | MANUAL_REVIEW | NO_ACTION",
  "rationale": "Customer experienced UPI bank server timeout; retrying with netbanking or card suggestion has high recovery probability."
}
```

### Strict Non-Negotiable AI Boundaries
- **No Action Authorization:** The LLM cannot authorize, approve, or execute an action.
- **No Risk Scoring:** The LLM must not compute ROS, financial risk, or fraud scores.
- **Schema Validation:** All LLM outputs must be strictly validated against the Pydantic diagnosis schema. Any malformed output falls back to deterministic rule diagnosis immediately.
