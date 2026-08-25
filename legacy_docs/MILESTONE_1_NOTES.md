# ReTryPay — Milestone 1 Notes & Environment Audit

**Document:** `docs/MILESTONE_1_NOTES.md`  
**Date:** 23 August 2026  
**Scope:** Milestone 1 Event Truth, Webhook Ingestion, Reconciliation Invariants, and Environment Notes  

---

## 1. Supported Runtime & Environment Audit

- **Project Constraint:** `Python >=3.12, <3.14` (as defined in `pyproject.toml`).
- **CI Test Target:** GitHub Actions matrix tests strictly against `Python 3.12` and `Python 3.13`.
- **Local Environment Audit Note:** The developer workstation has active interpreter `C:\Python314\python.exe` (Python 3.14.0). The Windows `py` launcher contains a stale entry for Python 3.12 (`C:\Users\Manish\AppData\Local\Programs\Python\Python312\python.exe` not on disk). All local development tools (`pytest`, `mypy`, `ruff`) run cleanly under the active interpreter with zero type/syntax deprecations, while official CI guarantees Python 3.12/3.13 compatibility.
- **Coverage Evolution Note:**
  > *Milestone 0 coverage is baseline scaffold coverage. Behavioral coverage targets become meaningful as domain and integration logic are implemented.*

---

## 2. Milestone 1 Architecture: Event Truth & Webhook Ingestion

### A. Supported Event Scope & State Mapping

| Razorpay Event Type | Normalized Payment Status | Order Status Effect | Processing Status |
|---|---|---|---|
| `payment.failed` | `PaymentStatus.FAILED` | `OrderStatus.ATTEMPTED` (or `FAILED` if no prior success; **never downgrades `PAID`**) | `PROCESSED` |
| `payment.captured` | `PaymentStatus.CAPTURED` | `OrderStatus.PAID` | `PROCESSED` |
| `order.paid` | N/A (Order level) | `OrderStatus.PAID` (Idempotent) | `PROCESSED` |
| Other / Custom | N/A | No change to Order / Payment | `UNSUPPORTED` |

### B. Invariants Enforced
1. **Timing-Safe Cryptographic Validation:** Webhook signatures are verified in memory against raw bytes using `hmac.compare_digest`.
2. **Data Minimization:** Raw request bodies are **never persisted by default**. Only normalized non-sensitive fields (`order_id`, `payment_id`, `amount_paise`, `method`, `error_code`), signature verification status, and SHA-256 payload digests are stored.
3. **Idempotency & Deduplication:** `provider_event_id` is unique in `webhook_events`. Duplicate deliveries return HTTP 200 immediately without updating order/payment attempts.
4. **Order Reconciliation Precedence:** A captured payment or paid order transitions the order to `PAID`. Subsequent `payment.failed` webhooks are recorded as payment attempts but **never downgrade** the order from `PAID`.
5. **Atomic Transactions:** Event ingestion, order creation/update, and payment attempt recording happen within a single ACID database transaction.
