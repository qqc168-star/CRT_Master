# CRT Radar Final Evidence Index - WIP

## Authority

- Formal parent: `CRT Master V1.9`
- Branch: `radar/integrated-wip-20260801`
- Pull request: `#1 Draft / unmerged`
- External action authority: `NONE`
- Current gate: `RUNNING / LIVE_GATE_NOT_YET_PASSED`

## Current authoritative state

- `STATUS/CURRENT_WIP_STATE.md`
- `VALIDATION/PR1_FILE_AUDIT_20260801.md`
- `STATUS/LIVE_SHADOW_RUN_20260801.md`

## Offline verification evidence

- `VALIDATION/INTEGRATED_COMPILE_REPORT.txt`
- `VALIDATION/INTEGRATED_TEST_LOG.txt`
- `VALIDATION/LEGACY_V0.2_RERUN_LOG.txt`
- `VALIDATION/PREFLIGHT_SAMPLE.json`
- `VALIDATION/PREFLIGHT_V0.9.json`
- `VALIDATION/READ_ONLY_SURFACE_V0.9.txt`
- `VALIDATION/WORKSPACE_FILE_HASHES.txt`

## Governance and registry evidence

- `CONFIG/SOURCE_REGISTRY_V1.2.json`
- `CONFIG/LIVE_SHADOW_POLICY_V1.json`
- `registry/RADAR_SYSTEM_REGISTRY.csv`
- `registry/RADAR_DEPENDENCY_GRAPH.md`
- `registry/RADAR_LINEAGE.md`
- `registry/SOURCE_RESPONSIBILITY_MATRIX.md`
- `registry/SOURCE_RESPONSIBILITY_MATRIX.csv`

## Live Shadow controls

- `scripts/windows/start_live_shadow_24h_windows.ps1`
- `scripts/windows/live_shadow_status_windows.ps1`
- `scripts/windows/verify_live_shadow_windows.ps1`
- `scripts/windows/live_shadow_gate_windows.ps1`
- `../CRT_LIVE_STATUS.cmd`
- `../CRT_LIVE_VERIFY.cmd`

## Live Shadow runtime evidence expected after completion

Runtime evidence is generated under `runtime_live_shadow/` and is not yet accepted.

Required evidence:

- `runtime_live_shadow/evidence/live_shadow_summary.json`
- `runtime_live_shadow/live_shadow.pid`
- `runtime_live_shadow/snapshots/`
- `runtime_live_shadow/run_ledger/`
- runtime logs
- duration evidence
- controlled restart evidence
- coverage ratio
- immutable snapshot verification
- Run Ledger hash-chain verification

Only a verified decision of `LIVE_SHADOW_PASS` may advance P1-01.

## Post-Live review and maturity evidence

- `P1_01_INTEGRATION_REVIEW_PRELIVE.md`
- `P1_01_POST_LIVE_REVIEW_TEMPLATE.md`
- `POST_SEAL_20_RUN_MATURITY_PLAN.md`
- `STATUS/POST_SEAL_20_RUN_TRACKER.csv`

## Historical checkpoint evidence

The following versioned groups are retained as historical evidence and are not current operational truth:

- Integrated compile reports: current, V0.6 and V0.9
- Integrated test logs: current, V0.6 and V0.9
- Legacy V0.2 rerun logs: current and V0.6
- Workspace hash lists: current, handoff and V0.9
- `LINEAGE/V0.4_CHECKPOINT/`
- `LINEAGE/CRT-RADAR-SOURCE-GATE-LIQ-MIGRATION_V0.3-RC1_20260801.zip`

## Waiting evidence

- Completed 24-hour duration
- Controlled restart completion
- Final coverage ratio at least 0.95
- Final immutable archive verification
- Final Run Ledger verification
- Final decision `LIVE_SHADOW_PASS`
- Completed P1-01 post-live review

## Blocked claims

Until all required evidence is verified:

- No Production promotion
- No formal V1.10 promotion
- No PR merge
- No final seal
- No trading, account access, email, webhook or notification