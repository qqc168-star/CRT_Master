# Work E — End-to-End Live Observation Acceptance

Date: 2026-09-20 Asia/Taipei (2026-09-19 UTC).

## Source and scope

GitHub `refs/heads/main` (independent `git ls-remote`) and local `origin/main`
both resolved to `b48b6336d4972db11df1b253de03fc81ea4517fd` before work.
The isolated `codex/work-e-live-observation` worktree started at that commit
and shares the original Local Git object database. Existing stashes were not
accessed or changed. A/B/D/C modules were reused without changes or new audits.

Only this report and `radar/tests/test_work_e_end_to_end_observation.py` change.
No six-layer weights, signal thresholds, mNAV semantics, Production approval,
External Action Authority, production code, or configuration changes.

## Permanent regression — PASS (offline, synthetic transport)

The new integration test reuses Work C's source fixture builders, which execute
IBKR capture normalization, `premarket_evidence_binding`, `premarket_battle_map`,
Work D asset readiness, `btc_transition_research_eval`, Work B posture, and Work C
source closure. It then executes the existing Commander operator, observation
monitor, SQLite journal, checkpoint, reanalysis wake, and GPT handoff.

Both MSTR and ASST are exercised. Assertions bind the source-main identity,
Evidence Pack hash, research evaluation, posture hash, readiness hash, judgment
hash, sealed plan, and validity window. Journal records are reopened and their
hash chain and checkpoint alignment verified. Handoffs are correlated to actual
observation event hashes and their local ledger must exist.

Negative cases cover upstream corruption (including forged readiness with valid
container seals), absent judgment, expired plans, changed main, all five authority
overrides, and journal corruption. These must reject before transport creation;
invalid closure inputs must also leave no runtime directory.

Fixed prices and GPT-shaped judgments are explicit test fixtures. No runtime
machine derives Commander lines. Synthetic transport results are never live
acceptance evidence. Fixture SHA `777...777` tests identity binding; it does not
claim to be the independently verified checkout SHA above.

Validation on Python 3.13:

| Check | Result |
| --- | --- |
| Focused permanent Work E integration | PASS, 5 tests |
| Related A/B/D/C, intake, battle-map, operator and journal regression | PASS, 111 tests |
| Full `python -m unittest discover -s tests -q` from `radar` | PASS, 796 tests |
| `python -m compileall -q src tests scripts` | PASS |
| `python scripts/validate_program_registry.py` | RADAR_PROGRAM_REGISTRY_PASS |
| `python scripts/assert_read_only_surface.py` | READ_ONLY_SURFACE_PASS |

Focused reproduction: from repository root, set `PYTHONPATH=radar/src` and run
`python -m unittest discover -s radar/tests -p test_work_e_end_to_end_observation.py -v`.
The existing full-regression CI discovers this test automatically.

## Real live read-only acceptance — BLOCKED, not PASS

The existing `inspect_ibkr_environment()` was invoked against the actual local
environment and repeated outside the network sandbox to rule out sandbox denial.
Both returned the same result:

```json
{
  "state": "BLOCKED",
  "host": "127.0.0.1",
  "ibapi_python_available": true,
  "ports": [
    {"port": 7497, "listening": false},
    {"port": 7496, "listening": false},
    {"port": 4002, "listening": false},
    {"port": 4001, "listening": false}
  ],
  "listening_ports": [],
  "blockers": ["TWS_OR_IB_GATEWAY_API_PORT_NOT_LISTENING"]
}
```

This is the sole observed live blocker. It is limited to the four standard local
TWS/Gateway endpoints; no claim is made about custom remote endpoints. No IBKR
session could be established, no market subscriptions were submitted, and zero
live observation cycles ran. No order, position, account, or funds API was called.
No fake feed was substituted for this acceptance. No live Commander judgment,
plan, observation journal, or reanalysis handoff was manufactured.

Live journal and live downstream lineage verification are **NOT RUN** because
the prerequisite session is unavailable. Offline journal validation is **PASS**.
The bounded live cycle remains outstanding until a real market-data session is
available; it must use fresh evidence and Work C judgment/validity validation.

All required locks remain:

```text
action_output = NONE
external_action_authority = NONE
capital_decision_authority = USER_ONLY
machine_execution = FORBIDDEN
production = NOT_APPROVED
```

## Delivery condition

Regression changes can be reviewed in a draft PR. Work E is not fully accepted.
The user's all-PASS prerequisite for merge is not satisfied, so no merge or
post-merge main update is performed. This is an environment blocker, not an
approval request. No additional authorization is required to continue the
already-authorized bounded acceptance once the prerequisite becomes available.
