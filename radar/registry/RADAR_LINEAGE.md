# CRT Radar Lineage

## Authority

- Formal SSOT: `CRT Master V1.9`.
- Historical engineering evidence: V1.3 Radar gap report and V0.2 Safety Contract repair.
- Architecture target only: V1.10-RC2／RC3 candidate lineage.
- This workspace is `CANDIDATE_UNMERGED`; it has no authority to change formal models, weights, thresholds or execute external actions.

## Retained implementation lineage

1. V0.2 Safety Contract: legacy 17-test fail-closed component.
2. V0.3 Source Gate migration: single registry and Binance Market-stream route.
3. V0.4 Persistent Liquidation Aggregator: append-only events, coverage and snapshots.
4. Integrated WIP: Run Ledger, Live Shadow evidence, AS-L4 adapter and deployment harness.
5. Evidence hardening V0.7-WIP: run-scoped acceptance, wall/monotonic duration cross-check, archive path confinement, registry hash lock, cadence and gap gates.

## Promotion rule

No candidate, shadow or local PASS changes formal authority. Promotion requires evidence Gate, explicit review and user approval.
