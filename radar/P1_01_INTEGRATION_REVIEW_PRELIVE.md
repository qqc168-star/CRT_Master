# P1-01 Integration Review｜Pre-Live Checkpoint

## Decision

`INTERFACE_OFFLINE_PASS / LIVE_SHADOW_REQUIRED / NO_FORMAL_AUTHORITY`

## What is now wired

1. Source Registry → Source Gate → AS-L4 E2E Adapter.
2. OI, Funding and persistent Liquidation Aggregates are required as one fail-closed AS-L4 set.
3. The Adapter emits dated evidence, registry hash, payload/evidence hashes and deterministic layer input hash.
4. The Adapter does not calculate the locked six-layer score and does not alter weights or thresholds.
5. V1.10 semantic locks are preserved:
   - `mnav = diluted_equity_mnav`
   - `q4_window = 2026-Q4`
6. External action authority remains `NONE`.

## What is not claimed

- No 24-hour networked Live Shadow has passed.
- No complete AS-L1～AS-L6 score is produced by this workspace.
- The recovered V1.10 E2E engine is not reconstructed from memory.
- No Production or formal V1.10 promotion is claimed.

## Next gate

1. Deploy the existing Live Shadow harness to a persistent networked host.
2. Run 24 hours with one controlled restart.
3. Verify immutable evidence and coverage.
4. Feed the verified AS-L4 layer to the preserved V1.10 E2E engine or a separately verified replacement.
5. Run SG-02 and SG-05 with real scheduled evidence.
