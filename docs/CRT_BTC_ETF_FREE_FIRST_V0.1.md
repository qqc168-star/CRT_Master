# BTC ETF free-first evidence

N.S. source-role dispatch on base `98197494f81291f00ca074f1858ac4a616dc3262`
authorizes TFTC open JSON for processed flow and breadth research. It does not
qualify formal L3 inputs, alter scores, or authorize capital actions.

The source-role SSOT and deferred paid policy are in
`radar/research/CRT_EXTERNAL_STRUCTURAL_DEMAND_SOURCE_REGISTRY_V0.1.json`.
TFTC is PRIMARY_PROCESSED_FLOW_SOURCE; Farside remains a non-blocking,
LOCAL_FETCH_BLOCKED cross-check. No discrepancy is invented when it cannot be
retrieved. Glassnode is deferred secondary research/audit; CoinGlass is a deferred
paid candidate, with no runtime dependency or credential requirement.

## Existing daily Evidence Pack path

From `radar`, with `src` on PYTHONPATH:

```powershell
python -m crt_radar.btc_etf_intake --capture C:\Users\maxwe\CRT_Runtime\btc_etf_free_first\unique_retrieval.json
python -m crt_radar.daily_evidence_runner --btc-etf-archive C:\Users\maxwe\CRT_Runtime\btc_etf_free_first\unique_retrieval.json
```

Use a new archive filename each retrieval. Capture preserves exact UTF-8 JSON,
actual retrieval time and SHA-256; it never overwrites earlier evidence. The
optional daily input is explicit: this change does not install a scheduler or
replace existing runtime files. Without this argument existing behavior stays
unchanged. Run dry/offline replay against separate output/observation paths.

Intake checks the locked URL, USD units, CC BY 4.0, attribution, upstream source
disclosure, unique dates, finite numbers, and complete-session visibility.
`days[].perEtfUsd` is the calculation input; provider `netFlowUsd`, AUM and BTC
price are not substitutes for missing per-fund values or BTC holdings.

The existing Source Authority Lock defines effective-dated basket membership; the existing capture
calendar defines expected trading sessions. Historical provider funds outside
the requested window do not expand CRT's basket. Unexpected funds within the
current window block intake for review. Null/absent data never becomes zero.
Numeric 0.0 is reported zero flow and contributes to the zero count.

1D is the latest completed session. 7D and 30D sum daily flows in the inclusive
calendar windows ending that session (latest minus 6/29 calendar days), using
existing CRT horizon constants. Each window has a constant, explicitly listed
fund scope. Missing fund history reduces that whole window's comparable scope;
PARTIAL means a disclosed basket, never a full-universe total. A missing session
blocks that window, independently of valid shorter windows. No weekend/holiday
rows are synthesized. The latest session must match the latest calendar session
before the evaluation UTC date; stale values are not carried forward.

Source dates have DATE precision. A current download is a retrieval vintage,
not proof of what was published on historical dates. Archives retrieved after a
replay cutoff are rejected. No historical publication time is fabricated.

Flow/breadth append to `asset_facts.items`; coverage and balance gaps append to
`blockers.items` before the Evidence Pack hash. No new pack section is created.
`BTC_ETF_BALANCE_BTC` current/7D/30D remain BLOCKED until reliable free BTC-unit
history exists; valid flow evidence remains available. The existing compact GPT
market context carries facts, provenance, scope, coverage and balance warning.
The existing wake gate still controls automatic handoff; evidence alone does not
invent a wake or a capital decision. A user-requested local replay may exercise
that handoff with an explicitly labelled replay request and a separate ledger.

## Deferred paid upgrade

**No subscription without decision value.** The registry permanently records
three candidate triggers: a real capital judgment is materially weakened by
missing balance 7D/30D; a future approved action-critical input exceeds free
coverage/history/provenance; or observed maintenance cost exceeds demonstrated
paid integration savings. A trigger only reports to N.S. Central. Activation
requires decision-value proof, N.S. architecture review and explicit user
approval together. No automatic subscription is authorized.

## Construction acceptance: real session 2026-09-29

The actual open-JSON GET returned HTTP 200/application/json, USD units,
CC BY 4.0 and 697 daily records. Retrieval `1790800542924` has raw SHA-256
`b19b8a25ff929308245d3daf030d3fb32edc236f0251f58970bdf00a87440741`.
The 12-member comparable basket yielded USD 66,194,702.40 (1D),
769,353,764.43 (7D, five reported sessions), and 3,013,388,531.15 (30D,
21 reported sessions). Breadth: two positive, one negative, nine reported zero.
All flow windows and breadth were COMPLETE; BTC balance remained BLOCKED.

An isolated replay added this archive to a copy of the real runtime Evidence
Pack and exercised the existing handoff/compact bridge with an explicitly
user-requested local replay event. The bridge was 16,035 bytes and retained all
three values, breadth, basket, provenance and balance warning. Formal layers,
candidate, model status, authority and pack state were unchanged. The live
runtime's NO_WAKE was not changed. No fixture was used as live evidence and no
remote GPT call or notification was sent. Local audit artifacts are under
`CRT_Runtime/btc_etf_free_first/`: `tftc_20260930_retrieval.json`,
`replay_pack.json`, `replay_handoff.json`, and `replay_bridge.json`.
