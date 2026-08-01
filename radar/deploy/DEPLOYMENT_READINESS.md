# Live Shadow Deployment Readiness

## Current state

`HARNESS_OFFLINE_PASS / LIVE_NOT_RUN / NO_FORMAL_AUTHORITY`

## What is ready

- 24-hour collector command with one controlled restart.
- Hash-chained append-only Run Ledger.
- Immutable snapshot archive and hash verification.
- Coverage, stale, corruption and blocked-snapshot acceptance checks.
- Docker and systemd deployment templates.
- No account login, no trading, no notification and no formal scoring.

## What remains external

A persistent networked host must run `scripts/run_live_shadow_24h.sh` continuously. Chat sessions and ephemeral sandboxes are not acceptable evidence environments.

After the process exits, run `scripts/verify_live_shadow.sh`. Only a generated decision of `LIVE_SHADOW_PASS` may advance P1-01 to integration review.
