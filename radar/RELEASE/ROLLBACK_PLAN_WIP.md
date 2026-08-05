# CRT V1.10 Rollback Plan

## Protected baselines

- Pre-merge main: `6e624acc6e02892b4cdff99f8e177abbc388fd51`
- Release vehicle: Pull Request `#1`
- Release branch: `radar/integrated-wip-20260801`
- External action authority: `NONE`

## Rollback triggers

- Post-merge integrity or regression failure
- Evidence corruption
- Governance or lineage conflict
- Unauthorized external action
- A confirmed defect that violates the accepted read-only Safety Contract

## Rollback method

1. Preserve all accepted and failed evidence.
2. Record the defective commit and exact failing result.
3. Revert the V1.10 merge commit through a new reviewed commit.
4. Do not force-push or rewrite `main`.
5. Do not delete evidence to obtain a passing result.
6. Re-run offline regression and integrity checks before any replacement seal.
7. Production and external actions remain blocked throughout rollback.

The parallel automation stash is outside the V1.10 merge scope and must not be dropped or applied as part of rollback.
