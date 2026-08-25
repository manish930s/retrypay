# Security and Privacy

## Secrets
Use server-side environment variables for Razorpay Key Secret, webhook secret, LLM credentials, and database credentials. Commit only `.env.example` with placeholder names.

## Payment data
Never store or log PAN, CVV, OTP, UPI PIN, payment credentials, raw secrets, or full personally identifying contact data. Store monetary values in paise and redact logs.

## Webhooks
Validate the raw request body signature using a timing-safe comparison. Record verification result and payload hash. Reject invalid signature. Deduplicate provider event ID.

## Customer-contact safety
Consent/opt-out is a hard gate. No non-developer customer messaging in MVP. Mock channel adapters must clearly mark their output as simulated.

## Data separation
Hidden synthetic potential outcomes are evaluation-only. Keep them outside operational stores and dashboards.
