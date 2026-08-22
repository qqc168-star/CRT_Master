# CRT Radar Cumulative Build Status

## Retained formal milestones

| Milestone | Result | Formal authority |
|---|---:|---|
| V0.2 Safety Contract | 17/17 legacy regression PASS | Integrated in CRT V1.10 |
| V0.3 Source Gate migration | PASS | Integrated in CRT V1.10 |
| V0.4 Persistent Aggregator | PASS | Integrated in CRT V1.10 |
| Evidence hardening | PASS | Integrated in CRT V1.10 |
| Program Registry | PASS | Integrated in CRT V1.10 |
| Transparent L5 inputs | PASS | Input only; no independent score |
| Multi-layer bridge | PASS | Observation only |
| 24-hour Live Shadow | PASS | Accepted first Live-run Gate |
| P1-01 post-live review | PASS | Technical integration accepted |

## Current engineering snapshot

- State reconciliation lineage: `PR #36`
- Reconciliation basis main SHA: `1426b56a7877d3c6357f76b9ecdda632ff1e50a3`
- Reconciliation verified candidate: `dfe2738cd4a7fb57a3d34f0c73613985efac1feb`
- Reconciliation merge SHA: `e3aadc64f39b709fc9a5d1cf3ff31136c7cabc14`
- Snapshot freshness rule: semantic state change, not ordinary repository HEAD movement
- Formal version: `CRT V1.10`
- Last verified full regression: `366/366 PASS` via `radar/run_offline_tests.sh`
- Program Registry: `PASS`
- Read-only surface: `PASS`
- Live Shadow: `LIVE_SHADOW_PASS`
- Production: `NOT_APPROVED`
- External action authority: `NONE`
- BTC Season output: `BLOCKED / null`

## Source and season distinction

Engineering source namespaces are present for:

`AS-L1 / AS-L2 / AS-L3 / AS-L4 / AS-L5 / AS-L6`

This does not mean formal BTC Season inputs are bound.

The BTC Season Formal Input Envelope remains:

- Required families: `12`
- Formally bound families: `0`
- State: `UNBOUND_BLOCKED`
- Runtime binding: `NOT_APPROVED`

## Open maturity work

1. Post-seal maturity target remains `0 / 20` qualified runs.
2. Qualified-run accumulation is currently blocked because the BTC Season Router is not `VALID_VERIFIED_EXECUTABLE`.
3. Formal BTC Season input binding remains the principal structural blocker.
4. L4 OI point-in-time revision selection is deterministic, but historical availability and coverage sufficiency are not certified.
5. Parallel automation stash remains outside the formal seal.

The formal seal establishes accepted implementation and evidence lineage.
Post-seal engineering additions do not imply Production approval or broad predictive maturity.
