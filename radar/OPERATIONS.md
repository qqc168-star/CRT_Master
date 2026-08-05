# Operations

## Offline verification

```bash
./run_offline_tests.sh
./scripts/preflight_live_shadow.sh
```

## Required external Live Shadow

Use a persistent networked host with a persistent runtime volume:

```bash
CRT_RUNTIME_ROOT=/absolute/persistent/path ./scripts/run_live_shadow_24h.sh
CRT_RUNTIME_ROOT=/absolute/persistent/path ./scripts/verify_live_shadow.sh
```

The collector runs for 24 hours, performs one controlled restart around hour 12, archives every snapshot and appends a hash-chained Run Ledger.

## Acceptance

Only `live_shadow_summary.json` with decision `LIVE_SHADOW_PASS` may advance the system to P1-01 integration review. Any short run, corrupted archive, ledger mismatch, coverage below 0.95, blocked snapshot or missing restart remains `LIVE_SHADOW_NOT_YET_PASSED`.

## Authority

Read-only public market data only. No credentials, account connection, order placement, email, webhook or formal Radar scoring.
