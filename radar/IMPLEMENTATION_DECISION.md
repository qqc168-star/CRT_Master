# Implementation Decision

## Decision

Continue by cumulative integration rather than issuing one ZIP per work order.

- V0.2, V0.3 and V0.4 are absorbed into this working tree.
- Intermediate artifacts remain internal staging evidence.
- The next user-facing checkpoint is deferred until a major milestone:
  - 24-hour Live Shadow evidence passes; or
  - an external deployment handoff must be delivered.

## Current state

`HARNESS_OFFLINE_PASS / READY_FOR_EXTERNAL_LIVE_SHADOW / LIVE_NOT_RUN`

This state does not authorize formal scoring, alerts, account access or trading.
