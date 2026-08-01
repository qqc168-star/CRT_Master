# CRT Radar Integrated Workspace

- Workspace: `CRT-RADAR-INTEGRATED-WORKSPACE-WIP-20260801`
- Version: `0.9.0-wip`
- Status: `OFFLINE_INTEGRATION_PASS / LIVE_NOT_RUN / CANDIDATE_UNMERGED`
- Formal parent: `CRT Master V1.9`
- Architecture target: V1.10-RC2／RC3 candidate lineage
- External action authority: `NONE`

## Absorbed work

1. V0.2 Production Safety Contract repair.
2. V0.3 Source Registry and Binance liquidation route migration.
3. V0.4 Persistent Liquidation Aggregator.
4. Hash-chained Run Ledger, immutable snapshot archive and deployment harness.
5. Run-scoped Live Shadow acceptance hardening.
6. 32-system Radar Program Registry and validator.
7. Coin Metrics transparent MVRV/NUPL input parser.
8. AS-L2 / AS-L4 / AS-L5 no-score multi-layer bridge.

## Current verification

- `88/88` integrated tests PASS.
- Program Registry PASS.
- Read-only surface PASS.
- Live Shadow preflight PASS.

## Current truth

The system is ready for an isolated 24-hour Live Shadow on a persistent networked host. That run has not occurred. AS-L1, AS-L3 and AS-L6 remain unimplemented. No formal score or trade action is authorized.

## Commands

```bash
./run_offline_tests.sh
./scripts/preflight_live_shadow.sh
./scripts/run_live_shadow_24h.sh
./scripts/verify_live_shadow.sh
```
