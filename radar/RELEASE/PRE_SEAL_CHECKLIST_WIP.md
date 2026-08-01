# CRT Radar Pre-Seal Checklist - WIP

## Authority

- Formal parent: `CRT Master V1.9`
- Branch: `radar/integrated-wip-20260801`
- Pull request: `#1 Draft / unmerged`
- External action authority: `NONE`
- This checklist does not authorize merge, seal or Production promotion.

## Required before P1-01 completion

- [ ] Live Shadow completed at least 24 wall-clock hours
- [ ] Controlled restart completed successfully
- [ ] Coverage ratio is at least 0.95
- [ ] Snapshot archive is complete and ordered
- [ ] Run Ledger hash chain is valid
- [ ] Registry and policy hashes match the active run
- [ ] Invalid, stale or blocked evidence remained blocked
- [ ] Final decision is `LIVE_SHADOW_PASS`
- [ ] P1-01 post-live review is completed
- [ ] No external action occurred

## Required before any merge or seal

- [ ] Current WIP state updated after final verification
- [ ] Final evidence index updated with accepted runtime evidence
- [ ] PR #1 file audit findings resolved or explicitly accepted
- [ ] Rollback point recorded
- [ ] Handoff document finalized
- [ ] GitHub Actions checks pass
- [ ] User gives explicit approval
- [ ] PR remains Draft until approval

## Explicitly blocked

- Production promotion
- Formal V1.10 promotion
- Trading or account access
- Email, webhook or notification
- Automatic PR merge
- Automatic final seal