# Unattended GPT transport worker

Engineering baseline: GitHub main `b48b6336d4972db11df1b253de03fc81ea4517fd`,
verified with `git ls-remote` on 2026-09-21 (Asia/Taipei).

The worker reuses the durable bridge outbox, transport boundary transitions,
Responses envelope and delivery receipt. It adds no trading, account or funds API.
All formal weights, thresholds, mNAV and authority locks remain unchanged.
Item #7 is **NOT COMPLETE** until a real qualified event has a durable verified
receipt and its boundary is DELIVERED. Item #8 has not been accepted.

## Invocation and integration

From the deployed `radar` directory with `PYTHONPATH=src`:

```powershell
python -m crt_radar.gpt_transport_worker --outbox-dir <existing-outbox> --state-dir <existing-boundary> --event-id <existing-qualified-event-id>
```

The existing observation runner invokes the worker after boundary synchronization
only when the local process environment has `CRT_GPT_TRANSPORT_ENABLED=1`.
`OPENAI_API_KEY` must be supplied securely to that process. Never put the key in
source control, payloads, reports or command-line arguments. The endpoint is fixed
to `https://api.openai.com/v1/responses`; ambient proxies and redirects are disabled.
The existing fixed model, 16 KiB input ceiling, 1800 output token ceiling, one
attempt, `store=false`, `background=false` and no-tools contract are retained.
Do not enable a backlog sweep before inspecting compatibility and event freshness.

The live acceptance command must restrict delivery to one existing qualified event.
After successful delivery, repeat the identical command: expect ALREADY_DELIVERED
with `transport_performed=false` and `notification_eligible=false`.

## Persistence and recovery

Per-event OS locks serialize the entire claim/send/finalize operation. Filesystem
locks disappear on process death; lock files are deliberately not removed. State
transitions use fsync plus atomic replacement, retaining the existing four states.
An unexpired claim cannot be stolen. An expired claim abandoned before send can
be reclaimed. OS locking also prevents takeover while the original sender is alive,
even if its lease has expired.

The boundary stores `request_hash` before provider I/O. This durable send intent
prevents automatic duplicate requests after timeouts or death. Provider failure
uses RETRYABLE with a reconciliation reason, never DELIVERED. An expired lease
with a send intent and no saved response requires operator reconciliation; it is
not proof the provider did not receive the request. There is no assumed provider
exactly-once or idempotency-header guarantee, and no automatic resend override.

Validated completed responses and their existing request envelopes are stored at
`<boundary>/responses/<event_id>.json`, using no-clobber publication. The existing
Delivery Receipt is embedded in the atomically persisted DELIVERED boundary.
If death occurs after response persistence, the next eligible run reconstructs the
same receipt without a network call. Replays validate the saved request, response
and receipt binding before reporting ALREADY_DELIVERED.

`notification_eligible=true` identifies a newly finalized event only. This worker
does not send notifications and does not establish durable exactly-once downstream
notification delivery; that must be verified in #8 using the existing downstream
path. Provider output remains analysis, never machine execution authority.

## Initial live preflight findings (2026-09-21)

- No OPENAI_API_KEY is present in Process, User or Machine environment scopes.
- The actual `CRT-Observation-History` task uses the existing CRT_Runtime outbox.
- Seven historical outbox payloads fail the current worker's capital authority
  requirements; their canonical sizes are 40,615–48,183 bytes, above the existing
  16 KiB request contract. Do not rewrite their identities or silently relax the
  contract to force acceptance.
- The current evidence snapshot produces NO_HANDOFF under the current-main gate.
  No synthetic event or altered gate may be substituted for live acceptance.
- Deployment, real provider acceptance and notification acceptance remain pending.

These findings are separate from offline engineering test success. They do not
permit marking #7 COMPLETE, advancing to 8/8, or describing manual transport as
unattended transport.

## Offline verification

- Focused worker tests: 12 PASS, including actual cross-process OS-lock contention
  and release after forced process death.
- Related GPT regression: 74 PASS.
- Full regression: 803 PASS (Python 3.13.14, Windows).
- Compile, program registry, read-only surface and diff whitespace checks: PASS.
- No real provider request was made; no live receipt was created.

## Credential follow-up and actual qualified event

User-scope OPENAI_API_KEY presence is now verified. The existing agent process did
not inherit it, so a new local Python child process was started with the User value
passed through its environment; it confirmed presence without printing the secret.
Billing and disabled auto-reload are user-reported, not independently queried.

The actual runtime now reports GPT_HANDOFF_READY for event
`d0fee5d059cb90ac37cd100a3d9707292a51aec0a958792d49e7a7b34636feba`.
The existing BTC intraday threshold triggered MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY.
NO_HANDOFF is no longer the active blocker. The Evidence Pack remains BLOCKED for
other recorded data-quality gaps; these were neither hidden nor promoted.

Rebuilding this event in memory with the unchanged current-main bridge builder
produces **49,231 UTF-8 bytes**, already canonically serialized without whitespace.
Its market_context is 43,834 bytes; changes alone are 20,767 bytes. The unchanged
request contract rejects it above 16,384 bytes. There is no existing size-bounded
projection in the current builder. Its older deployed outbox record was not
rewritten, re-identified, or replaced. No alternate outbox was created.

Actual public HTTPS provenance also exposed a worker regex false positive: the
last character of `https:` was matched as a Windows drive letter. The drive-path
pattern now requires a preceding non-alphanumeric boundary. A focused regression
test permits public HTTPS provenance while retaining local-path rejection.
All 13 focused worker tests and targeted compile/diff checks PASS. The previously
valid 803-test run was not repeated locally.

See UNATTENDED_GPT_LIVE_PREFLIGHT.json for sanitized event/hash/size evidence.
There have been **zero provider requests** and no live Delivery Receipt. #7 remains
incomplete. Further delivery requires a genuine event whose unchanged builder
output fits the existing ceiling, or an explicitly scoped change to the existing
bridge minimization policy before a new event is published. Raising the ceiling,
truncating this record, changing its identity or faking a wake is not a remedy.

## Authorized bounded-detail projection

The user authorized a minimal amendment to the existing bridge builder. For an
oversized payload only, the builder now projects research detail before computing
the new payload hash. Capital State, analysis contract, event lineage, privacy and
authority are unchanged. All current layer metric values, observation timestamps,
quality states and missing-required-metric lists remain. Formal model state,
weights and thresholds remain. Asset strategy and premarket sections remain intact.

The payload explicitly lists omitted detail and binds the original market context
by hash: per-metric provenance and redundant required lists; historical change
tables/rankings; candidate scoring hashes; non-trigger DVOL research detail;
transition 30-minute windows, duplicate prompts and machine causal hypotheses;
bull-validation check values. Data-health gaps and all bull check-status lists are
retained. Transition impulse/prior-60m/recent-60m observations remain available for
GPT's own causal analysis. Omitted detail must not be interpreted as absent evidence.

The actual snapshot previously measuring 49,231 bytes now measures 16,131 bytes
under this projection and passes the unchanged envelope size validation. This is
an in-memory verification only, not a replacement of its existing outbox record.
If mandatory content still exceeds 16 KiB, the existing request builder rejects it;
there is no arbitrary byte truncation, rounded numeric data or raised limit.

## Post-merge deployment and one-event watch

PR #103 merged as `9b1b0cb61b4c5e04b358e48d2be0ad7e083e2b1d` and the actual
observation runtime was fast-forwarded to that commit. Deployed compile, registry
and read-only checks PASS. The PR-triggered CI for head `38a30d5` passed all 806
tests. Its parallel push CI hit two existing collector timing failures; a local
targeted check also exceeded the 250 ms wall-clock assertion. Collector code and
thresholds were not changed; the CI discrepancy is retained rather than hidden.

A new process successfully authenticated a read-only model metadata GET for the
fixed `gpt-5.6-luna` model (HTTP 200). There were no generation requests. The next
actual observation remained NO_WAKE / CHANGE_WITHIN_INTRADAY_HISTORY (approximately
0.0695% change, historical percentile 21.93 against 90). It wrote its evidence,
wake and handoff records, then failed printing a Unicode status symbol under cp950.
The observation launcher now explicitly uses UTF-8 for Python output.

`scripts/accept_one_gpt_event.py` is an operational one-event acceptance observer.
It does not collect or generate events and does not change the hourly task or wake
criteria. It ignores every preexisting outbox filename, waits up to 24 hours for a
new actual event linked to current evidence, validates the existing envelope and
calls the deployed worker. It records PENDING/CLAIMED/DELIVERED and performs the
ordinary duplicate replay, then exits after that single attempted delivery.
Any ambiguous provider failure stops acceptance without retry. The acceptance
report is not a second receipt or transport state store; the existing boundary and
its response evidence remain authoritative. Six targeted runner/launcher tests PASS.

No live PASS or item #7 completion may be recorded while this observer is waiting.
