# Next Gate｜External 24h Live Shadow

## Required environment

- Persistent networked Linux host or container runtime.
- Persistent writable volume for SQLite, raw JSONL, snapshots and Run Ledger.
- Python 3.13 and dependencies from `requirements.txt`.

## Gate sequence

1. Offline tests PASS.
2. Preflight returns `PREFLIGHT_PASS`.
3. Run 24 hours with one controlled restart.
4. Verify evidence.
5. Review any blocked snapshots, disconnect gaps or anomalies.
6. Only after `LIVE_SHADOW_PASS`, conduct P1-01 integration review.

No packaging or formal promotion occurs before this gate.
