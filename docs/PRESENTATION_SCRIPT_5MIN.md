# ReTryPay — 5-Minute Video Presentation & Demo Script

**Project**: ReTryPay — AI Revenue Recovery Engine for Razorpay  
**Hackathon**: Razorpay AI Buildathon (Track 03: AI Revenue Recovery)  
**Target Duration**: 5:00 Minutes (300 Seconds)  
**Repository**: [https://github.com/manish930s/retrypay.git](https://github.com/manish930s/retrypay.git)

---

## 🎬 Pre-Recording Checklist & Setup (Before Recording Starts)

Open two terminal windows and your browser:

### Terminal 1: Backend API
```powershell
$env:RETRYPAY_ENV = "test"
$env:DATABASE_URL = "sqlite+aiosqlite:///./retrypay_test.db"
$env:RETRYPAY_EXPECTED_DATABASE_TARGET = "retrypay_test.db"
python -m uvicorn retrypay.api.app:app --host 127.0.0.1 --port 8000
```

### Terminal 2: Frontend Dashboard
```powershell
npm --prefix web run dev
```

### Browser Window:
- Open `http://localhost:5173` in Chrome/Edge, maximized.
- Have a second tab ready with `http://127.0.0.1:8000/docs` (FastAPI Swagger UI).

---

## ⏱️ Minute-by-Minute Presentation Timeline

```
[0:00 - 0:45] ── 1. The Hook, Problem & Product Pitch
[0:45 - 1:45] ── 2. Architecture, Safety Hierarchy & DPDP Gating
[1:45 - 3:00] ── 3. Live Demo: End-to-End Recovery & Policy Controls
[3:00 - 4:00] ── 4. Measured Batch Recovery & Two-Evidence Reconciliation
[4:00 - 4:40] ── 5. Causal Counterfactual Evaluation (3-Arm Benchmark)
[4:40 - 5:00] ── 6. Conclusion, Test Verification & Close
```

---

## 🎙️ Detailed Video Script

---

### Part 1: The Problem & Pitch (0:00 – 0:45)
**Screen**: Show Dashboard Overview (`http://localhost:5173`) or Title Slide.

> **Spoken Voiceover**:  
> *"Hi everyone! In India's digital payment ecosystem, merchants lose up to 15 to 20 percent of checkouts due to transient errors — UPI PSP network timeouts, OTP delays, and temporary bank gateway dropouts. When a customer's payment fails, they frequently abandon the cart.*
>
> *Traditional recovery systems spam customers with generic messages regardless of fraud risk or consent, destroying brand trust and burning messaging budgets.*
>
> *Introducing **ReTryPay**: an autonomous, deterministic checkout recovery engine built specifically for the Razorpay ecosystem. ReTryPay detects payment failures in real time from cryptographically verified webhooks, evaluates hard privacy and DPDP consent guardrails, scores recovery opportunities using an explainable ROS model, generates attributable Test Mode payment links, and reconciles money recovered using a strict **two-evidence protocol**."*

---

### Part 2: Architecture & Safety Invariants (0:45 – 1:45)
**Screen**: Navigate to **Policy & Guardrails** (`/settings`), then show the architecture diagram from `docs/ARCHITECTURE.md`.

> **Spoken Voiceover**:  
> *"Before we show the live demo, let's look at ReTryPay's non-negotiable core philosophy: **Deterministic Policy is Authoritative**.*
>
> *In financial systems, AI should advise, but NEVER authorize money movement alone. We enforce a strict authority hierarchy:*
>
> $$\text{Verified Webhook} > \text{Database State} > \text{Policy Engine} > \text{ROS Service} > \text{AI Diagnosis} > \text{UI}$$
>
> *Here on the **Policy & Guardrails** screen, you can see our live merchant governance settings:*
> 1. * **DPDP Consent Gating**: No message is ever sent without explicit `OPTED_IN` customer consent.*
> 2. * **Frequency Caps**: Capped at 2 messages per order and 3 messages per customer in 30 days to eliminate customer fatigue.*
> 3. * **Quiet Hours**: Automatic deferral between 10:00 PM and 8:00 AM IST.*
> 4. * **Single Action Limit**: Hard ₹10,000 GMV ceiling. Anything above is routed to Manual Review.*
> 5. * **Zero PII Storage**: PAN, CVV, OTP, and webhook secrets are never logged or exposed in UI audit trails."*

---

### Part 3: Live Demo — End-to-End Recovery Flow (1:45 – 3:00)
**Screen**: 
1. Navigate to **Webhook Simulator** (`/simulator`).
2. Select scenario `2. Eligible Outreach Flow (UPI Intent Timeout)`.
3. Click **Trigger Simulation Scenario**.
4. Click the link to open the newly created case in **Recovery Cases** (`/cases/:caseId`).

> **Spoken Voiceover**:  
> *"Let's see ReTryPay in action. I'm opening our **Local Signed-Webhook Simulator**.*
>
> *When a customer experiences a UPI timeout, Razorpay fires a signed `payment.failed` webhook. Our backend verifies the raw HMAC signature, deduplicates the `provider_event_id`, and transitions the case into `ENRICHING` and `POLICY_EVALUATED`.*
>
> *(Click 'Trigger Simulation Scenario')*
>
> *The scenario executed instantly! Let's click into the created case.*
>
> *(On Case Detail View)*
>
> *Here is the dedicated **Case Investigation Workspace**:*
> - * **Customer Context**: Notice the customer's phone and email are strictly masked, with verified WhatsApp consent.*
> - * **Failed Attempt Context**: Highlights the error code `BAD_REQUEST_PAYMENT_TIMED_OUT`.*
> - * **Decision Telemetry**: The policy engine declared this `ELIGIBLE`, and our ROS engine calculated a score of **82/100** due to high intent and prior purchase history.*
>
> *Look at the **Outreach & Reminder Controls**: Before dispatch, the system generates a single-use confirmation token to prevent race conditions.*
>
> *(Click 'Send reminder' $\rightarrow$ Show Preview Modal $\rightarrow$ Click 'Confirm & Send')*
>
> *Now, let me show you our safety gate in action on a High-Risk case:*
>
> *(Quickly trigger Scenario 12: High-Risk / Hard-Decline)*
>
> *For `MANUAL_REVIEW` cases, reminder dispatch is strictly locked with clear policy blocking reason codes: `CONTACT_CONSENT_MISSING`, `INSUFFICIENT_CONTEXT`, and `PAYMENT_LINK_NOT_CREATED`."*

---

### Part 4: Measured Batch Recovery & Two-Evidence Reconciliation (3:00 – 4:00)
**Screen**: Navigate back to **Overview** (`/`). Highlight the **Measured Batch Recovery Results** panel.

> **Spoken Voiceover**:  
> *"Now let's look at the centerpiece of Track 03: **Measured Revenue Recovery Across a Batch**.*
>
> *Here at the top of the Overview console is our real-time **Measured Batch Recovery Results** panel, aggregated live from our database rows with zero synthetic inflation:*
> - * **Recovered Cases**: Tracks verified recoveries against total ingested failures.*
> - * **Recovered GMV**: Exact rupee amount recovered (e.g. ₹4,000.00).*
> - * **Policy Block Rate**: Real-time ratio of failures safely blocked by policy gates.*
> - * **Manual Review Rate**: Flagged edge cases.*
> - * **Mean Time to Recover**: The exact duration from failure webhook to payment confirmation.*
>
> *Crucially, how does ReTryPay verify that money was truly recovered? We enforce the **Two-Evidence Attribution Protocol**:*
> *A case cannot become `RECOVERED` on a single webhook alone. It strictly requires:*
> 1. *A `payment.captured` webhook event from Razorpay, AND*
> 2. *A Payment Link state transition to `paid` matching our deterministic reference ID within a 30-minute reconciliation window.*
> *This guarantees zero false attribution claims."*

---

### Part 5: Offline Counterfactual Causal Evaluation (4:00 – 4:40)
**Screen**: Navigate to **Causal Evaluation** (`/evaluation`).

> **Spoken Voiceover**:  
> *"How do merchants know if ReTryPay is creating true incremental uplift rather than taking credit for natural recovery?*
>
> *We built a dedicated **Offline Counterfactual Evaluation Engine**.*
>
> *(Scroll through the 3 Treatment Arms)*
>
> *We benchmark three distinct strategies on synthetic cohorts:*
> 1. * `NO_ACTION`: The control group showing natural recovery.*
> 2. * `GENERIC_REMINDER`: Indiscriminate messaging.*
> 3. * `RETRYPAY_POLICY`: Our targeted, consent-gated, ROS-prioritized engine.*
>
> *ReTryPay measures:*
> - * **Incremental Conversion Lift**: e.g., $+4.25\%$ with 95% confidence intervals.*
> - * **Incremental Recovery GMV**: Value generated strictly above natural recovery.*
> - * **Contact Efficiency**: Net recovered rupees per synthetic contact sent.*
>
> *Notice our persistent mandatory disclaimer: All causal estimations are clearly labeled as simulated offline estimates, ensuring complete transparency."*

---

### Part 6: Test Verification, Code Quality & Conclusion (4:40 – 5:00)
**Screen**: Switch to Terminal. Run verification commands.

#### Terminal Command to Execute:
```powershell
python -m pytest; python -m ruff check .; npm --prefix web run test -- --run
```

> **Spoken Voiceover**:  
> *"Finally, let's run our comprehensive test suite:*
> - * **294 Backend Tests** passing across unit, integration, and scenario suites.*
> - * **100% Type-Safe** checked with Mypy and Ruff.*
> - * **16 Frontend Tests** verified with Vitest.*
>
> *ReTryPay delivers measured revenue recovery, strict compliance, and verifiable attribution for every Razorpay merchant.*
>
> *The complete source code is available on GitHub at `github.com/manish930s/retrypay`. Thank you!"*

---

## 📋 Quick Command Cheatsheet for Video Recording

| Timing | Demo Action | Command / URL |
| :--- | :--- | :--- |
| **0:00** | Open Dashboard Overview | `http://localhost:5173` |
| **0:50** | Show Policy Snapshot | `http://localhost:5173/settings` |
| **1:50** | Open Webhook Simulator | `http://localhost:5173/simulator` |
| **2:10** | Trigger Scenario 2 (Eligible Flow) | Click **Trigger Simulation Scenario** |
| **2:30** | Inspect Case & Send Reminder | Click **Send reminder** in Case Detail |
| **3:05** | Show Measured Batch Recovery | `http://localhost:5173/` (Top panel) |
| **4:05** | Show Causal Evaluation Report | `http://localhost:5173/evaluation` |
| **4:45** | Run Live Test Verification | `python -m pytest; npm --prefix web run test -- --run` |

---

## 💡 Speaker Tips for a High-Scoring Presentation

1. **Speak with Confidence on Safety**: Emphasize that ReTryPay **never touches real money or sends unconsented messages** in test mode.
2. **Highlight Track 03 Requirements**: Explicitly mention "Measured money recovered across a batch", "Two-Evidence reconciliation", and "Stopping rules".
3. **Keep the Pace Steady**: Spend ~1 minute on problem/policy, ~1.5 minutes on the live demo flow, ~1 minute on batch metrics, ~45s on causal evaluation, and ~15s on test verification.
