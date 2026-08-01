# CRT Radar Rollback Plan - WIP

## Purpose

Provide a reversible recovery path without altering the formal parent or current Production authority.

## Protected baseline

- Formal parent: `CRT Master V1.9`
- Working branch: `radar/integrated-wip-20260801`
- Pull request: `#1 Draft / unmerged`
- External action authority: `NONE`

## Rollback triggers

- Live Shadow verification fails
- Coverage is below 0.95
- Run Ledger verification fails
- Snapshot archive is incomplete or corrupted
- Registry or policy hash mismatch
- Critical blocked evidence was accepted
- Unauthorized external action is detected
- Governance or lineage conflict remains unresolved

## Rollback method

1. Keep PR #1 in Draft state.
2. Do not merge into `main`.
3. Preserve failed evidence and logs.
4. Record the failing commit and verification result.
5. Return the branch to the last verified checkpoint only after explicit approval.
6. Re-run offline regression and preflight before another Live Shadow attempt.
7. Never delete failed evidence merely to obtain a passing result.

## Safe rollback boundary

Rollback may affect only the isolated WIP branch.

It must not:

- rewrite `main`
- alter CRT Master V1.9
- authorize Production
- change formal models, weights or thresholds
- trigger trading, account access, email, webhook or notification