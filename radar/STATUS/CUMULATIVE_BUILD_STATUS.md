# CRT Radar Cumulative Build Status

## Retained stages

| Stage | Result retained | Current authority |
|---|---|---|
| V0.2 Safety Contract | 17/17 legacy regression PASS | Safety component only |
| V0.3 Source Gate migration | Market route + single Source Registry | Candidate / unmerged |
| V0.4 Persistent Aggregator | append-only events, coverage, snapshots | Ready for Live Shadow |
| Evidence hardening V0.7-WIP | run-scoped duration, cadence, hash/path locks | Offline PASS |
| Program Registry | 32-system inventory + validator | Local candidate |
| L5 transparent inputs | Coin Metrics parser + MVRV/NUPL formulas | Input only; no score |
| Multi-layer bridge | AS-L2 / AS-L4 / AS-L5 adapters | Observation only |

## Current executable result

- Integrated suite: **88/88 PASS**.
- Program Registry validator: **PASS**.
- Read-only surface scan: **PASS**.
- Live Shadow preflight: **PASS**.
- Python compile / JSON / shell syntax: **PASS** through `run_offline_tests.sh`.

## Current blocking facts

1. The required external 24-hour networked Live Shadow has not run.
2. Current sandbox cannot resolve external DNS, so it cannot perform a trustworthy live smoke test.
3. GitHub isolated branch remains blocked until Codex quota/write path becomes available.
4. AS-L1, AS-L3 and AS-L6 source families are not yet implemented.

## Authority

`CANDIDATE_UNMERGED / LIVE_NOT_RUN / EXTERNAL_ACTION_AUTHORITY_NONE`
