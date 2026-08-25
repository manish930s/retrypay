# Implementation Plan

## Milestone 0 — Repository baseline
Create project structure, environment template, local services, formatter/linter/type checker, test runner, CI, and this documentation pack.

## Milestone 1 — Event truth
Implement order/payment fixtures, webhook endpoint, signature validation, event table, deduplication, and reconciliation. Demonstrate duplicate and out-of-order event handling.

## Milestone 2 — Recovery domain
Implement recovery-case state machine, audit log, hard policy engine, consent/cap/quiet-hour configuration, and dashboard case list.

## Milestone 3 — Decisioning
Implement deterministic ROS, diagnosis adapter with schema fallback, `SimulationEstimator`, action utility, `NO_ACTION` baseline, and budget manager.

## Milestone 4 — Execution loop
Implement Razorpay Test Mode Payment Link adapter, notification mock, captured-event closure, and case timeline.

## Milestone 5 — Evaluation and demo
Implement synthetic generator, separate evaluator, three-strategy reports, dashboard metrics, seeded demo scenarios, and a five-minute walkthrough.

## Definition of done
A clean clone can run seed data, trigger every mandatory scenario, show audit traces, run tests, and reproduce synthetic evaluation using documented commands.
