# Agent Organization (Autopilot)

This repo is owned by BE Agent under Orchestrator control.

## BE Responsibilities
- API contracts and schema compatibility
- execution engine reliability/performance
- evidence/failure-code standardization
- async job orchestration (queue/poll/progress)
- final test sheet correctness (csv/xlsx)

## BE Hard Rules
- No API breaking change without API_SPEC update.
- No "PASS" without deterministic evidence.
- All new endpoints must include smoke call examples.

## Required handoff fields
- Scope
- Files changed
- API changes
- Validation output
- Rollback plan
