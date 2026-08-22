# CRT Radar - Post-Seal 20-Run Maturity Plan

## Governance boundary

- The 24-hour scene-based Live Shadow was the pre-seal acceptance gate and is `PASS`.
- The 20-run sequence is post-seal maturity observation.
- The 20-run sequence does not reopen or invalidate the accepted Live Shadow Gate.
- Completion does not automatically approve Production.
- External action authority remains `NONE`.

## Qualification dependency

The current maturity tracker counts only qualified Evidence Pack runs.

A qualified run requires the existing qualification contract, including:

- Evidence Pack state `READY_FOR_ANALYST`
- six-layer evidence state `COMPLETE_DIRECTIONAL`
- locked formal scoring state `VALID_VERIFIED_EXECUTABLE`
- BTC Season Router state `VALID_VERIFIED_EXECUTABLE`
- external action boundary unchanged

The current BTC Season Formal Input Envelope remains `12 / 12 UNBOUND_BLOCKED`.
Therefore the BTC Season Router is not yet `VALID_VERIFIED_EXECUTABLE`, and
qualified-run accumulation cannot currently advance.

Fail-closed or blocked attempts may still be recorded for audit, but they do
not increase the qualified-run count.

## Observation record for each run

- Run ID
- Start and end time
- Registry hash
- Runtime policy hash
- Run Ledger head hash
- Snapshot count
- Coverage ratio
- Controlled restart result
- Final verification decision
- Blocked evidence and anomalies

## Restrictions

- No changes to formal models, weights or thresholds.
- No trading, account access, email, webhook or notification.
- Failed or blocked runs remain visible in the evidence history.
- Any promotion requires separate explicit approval.

## Current status

`NOT_STARTED / QUALIFIED_RUN_ACCUMULATION_BLOCKED`

Current qualified runs: `0 / 20`

Current blocker: `BTC_SEASON_ROUTER_NOT_VERIFIED`

The prior `WAITING_FOR_INITIAL_LIVE_GATE` wording is obsolete because the
initial Live Shadow Gate and P1-01 post-live review are already `PASS`.
