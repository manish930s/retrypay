# Test Strategy

## Test pyramid
- Unit: policy rules, ROS contributions, state transitions, utility math, schema validation.
- Integration: webhook signature validation, deduplication, DB transactions, provider adapter fakes.
- Scenario/E2E: failed payment → case → link → captured payment; blocked/opt-out/risk paths.

## Mandatory regression scenarios
1. Duplicate webhook produces one case and one action.
2. Paid-before-worker creates no link or notification.
3. Opt-out, consent failure, cap, and quiet-hour rules suppress contact.
4. Risk/high-value/low-confidence cases route to review.
5. Invalid LLM JSON never produces an action.
6. Link creation timeout reconciles before retry.
7. Captured event closes active recovery case and cancels queued notification.
8. Changing hidden potential outcomes does not change action selection.
9. Policy block occurs before estimator invocation.
10. Same scenario seed, policy version, and assignment seed gives same aggregate evaluation.

## Completion gate
No feature is complete without tests for success, policy block, provider failure, and duplicate/retry behavior where applicable.
