# CRT V1.10 Formal Seal Record

## Decision

- User approval: `GO`
- Approval time: `2026-08-05 19:09 +08:00`
- Formal release: `CRT V1.10`
- Integration vehicle: Pull Request `#1`
- Target branch: `main`
- Candidate branch: `radar/integrated-wip-20260801`

## Accepted technical evidence

- Integrated offline regression: `PASS`
- Legacy regression: `PASS`
- GitHub Actions: `PASS`
- 24-hour Live Shadow Gate: `LIVE_SHADOW_PASS`
- Accepted process run ID: `17cccceb-d819-4fca-aab0-45f6dc9275f1`
- P1-01 technical post-live review: `PASS`
- Live evidence archive: `PASS`
- External runtime ZIP SHA256: `a30c518317621c05e22f7705682169c4e7adf28f1025a8d7d5739d92060223e7`
- Runtime manifest SHA256: `a83f25ffb1e45fa2d8b299b75b00c98160703130d564ece9974d79553a6f7ce9`

## Preserved governance locks

- Constitution: unchanged
- Six-layer weights: `20 / 20 / 17 / 25 / 13 / 5`
- Light thresholds: `-60 / -35 / 35 / 60`
- Unqualified `mNAV`: `Diluted Equity mNAV` only
- Q4 semantic lock: `2026 Q4`
- Formal models, weights, thresholds and governance boundaries: unchanged
- External action authority: `NONE`

## Promotion boundary

Merging PR #1 promotes the accepted read-only decision-support integration to formal `CRT V1.10`.

This formal seal does not:

- approve Production;
- authorize trading, account access, email, webhook or notification;
- claim predictive maturity beyond the accepted evidence;
- complete the post-seal 20-run maturity observation;
- apply, overwrite or discard the parallel automation stash.

## Post-seal state

- Production: `NOT_APPROVED`
- Post-seal maturity observation: `0 / 20`
- Parallel automation work: `STASHED / NOT_APPLIED`
- External action authority: `NONE`

The 20-run observation is a post-seal maturity track and does not retroactively invalidate the accepted first Live Shadow Gate.
