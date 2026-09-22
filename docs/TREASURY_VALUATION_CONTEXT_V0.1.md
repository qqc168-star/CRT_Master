# Treasury Valuation Context V0.1

Engineering baseline: GitHub main `74b9b0baa91a13452ee779c3f322ba94b6dabd40`.
This extends Treasury Company CT, reuses its four-clock metadata validation,
BTC/diluted-share calculation and formal `diluted_equity_mnav` adapter. It adds
no second NAV formula, issuer fact database, season router or trading engine.

## Local input and evidence

`build_treasury_valuation_context(asset_id, as_of_ms, ...)` accepts MSTR or ASST.
Issuer identifiers are respectively CIK-0001050446 and CIK-0001920406. Input
records use CT's source reference, VALIDATED verification, versioned semantic,
effective/disclosure/first-seen/retrieval clocks and explicit basis reference.
All four clocks must be ordered, and retrieval must be no later than evaluation.
Unknown numbers remain null. Invalid current observations never fall back to an
older valid level. Duplicate effective times are blocked, not double-counted.

`mnav_history` contains ONE semantic/basis series, with `asset_id`, `basis_ref`
and `mnav`. Formal observations additionally require the existing mNAV builder
output, validated cap/NAV inputs and a source class ISSUER, SEC or
VERIFIED_DETERMINISTIC. The unqualified formal mNAV definition is unchanged.
StrategyTracker observations always retain RESEARCH_SECONDARY_EVIDENCE, for
both issuers; a claimed authority on the input cannot override that assignment.
Without official inputs `formal_action_critical_state=BLOCKED`, while research
levels remain available for qualitative comparison.

New imports use STRATEGYTRACKER_DILUTED_MNAV_RESEARCH. Legacy
SAYLORTRACKER_DILUTED_MNAV_RESEARCH records remain valid and the old callable
import/admission names remain aliases. Legacy and corrected historical series
are not silently pooled. STRATEGY_ISSUER_MNAV is not diluted-equity mNAV.

`asset_history` reuses CT's holdings/shares/basis algorithm, additionally requiring
official source class and locally visible four clocks. It preserves current,
previous, direction, observation span, holdings, diluted shares and basis.
BTC holdings growth alone never implies per-share accretion. Source-specific
share exclusions (for example ASST traditional warrants) belong in `basis_ref`.
This does not modify BTC_PER_DILUTED_SHARE_DECREASED or any existing Wake path.

## Historical comparisons

Own-history CDF = `100 * count(previous value <= current value) / count`.
The current observation is excluded from the baseline. At least 20 distinct
prior observations are required; this is a research availability minimum, not
a trading or Wake threshold. Comparison requires identical issuer, semantic
identity AND version, and basis. Baseline count, start/end, current value,
calculation version, semantic and complete baseline remain in local evidence.

Regime rank is BLOCKED/PIT_REGIME_BINDING_UNAVAILABLE: current main has candidate
weather, but no reliable PIT binding between that history and issuer mNAV.
No bull/bear classification is inferred. Benchmark input must explicitly name
`identity`, `asset_id` and `history`; it must meet the same semantic/version/basis,
PIT, sample count and prior-observation requirements. No benchmark is selected
implicitly. Different issuer observations can only compare on a documented
shared valuation basis, never merely because their field is named mNAV.

Five-week change selects the nearest comparable observation to 35 days before
the current effective time, within +/-3 calendar days. Ties select the earlier
observation; no interpolation or substitution outside this window. Source
observations and actual span are retained. All change_pct values are fractions
(0.1 means 10%); empirical_cdf_pct is 0..100.

A retrospective web history retrieved today does NOT prove the original
disclosure/first-seen clocks or revision lineage. Retain its raw bytes locally,
but do not fabricate historical metadata. `history_coverage` records that limit;
unverified history cannot populate percentiles or five-week comparisons.

## Preferred funding attribution

`preferred_funding_events` are independent research-only events, using CT
metadata, official sources, unique event IDs, active calculation flags and an
explicit consequence basis. Components: ASSET_ACTION (BTC), CLAIM_ACTION (USD),
CARRY (USD annual run-rate), RESERVE_ACTION (USD realized liquidity), and
SHARE_DENOMINATOR (shares). No cross-event summation hides overlapping scopes.

`effective_preferred_funding_cost` is current annual preferred distributions /
verified net proceeds, a fractional annual rate. Both cost and net-proceeds
bases and VALIDATED proceeds are mandatory. Authorization, ATM ceiling, unused
capacity and gross issuance are never proceeds substitutes.
`claim_adjusted_reserve_delta_usd` = verified realized liquidity delta minus
verified current senior-claim delta, only for REALIZED_VERIFIED reserve changes.
Future carry/distributions are never deducted; annual run-rate is context,
not a currently accrued liability. Missing components remain independently
blocked. Source refs, four clocks, basis refs and calculation inputs remain local.

## Pack, runtime and bridge

`build_evidence_pack(..., treasury_valuation_inputs={"MSTR": {...}, "ASST": {...}})`
adds two TREASURY_VALUATION_CONTEXT facts to existing asset_facts. It does not
create a parallel pack. Each full context has a canonical SHA-256; the enclosing
Evidence Pack also hashes it. The existing daily runner always attaches both
issuers, explicitly BLOCKED when absent. `--treasury-valuation-inputs` supplies
normalized local CT evidence; the Windows runner reads
`<RuntimeRoot>/treasury/valuation-inputs.json` when present. This is an input
artifact, not a new issuer store or automated web crawler.

GPT receives only levels, ranks/counts, five-week and BTC/share changes, source
identity, basis/time, authority, research attribution summary, blockers, quality
and full-context hashes. Growth-acceleration blockers (an unrelated CT claim)
remain local. Full raw history, baselines and provenance are never sent.
Both the local bridge and unchanged provider adapter enforce 16,384 bytes; the
Treasury path rejects >=16,384 bytes without truncation or number rounding.

When needed, the bridge reuses existing detail projections, then losslessly
shares equal facts and uses explicit field/string dictionaries and Treasury
column records or common fields. `@N` keys expand through `field_names`;
`text_ref` expands through `literal_strings`; `record` arrays follow `columns`;
asset fields inherit `common`, with additional blockers appended.
`same_as` paths refer to expanded field names; `authority_same_as=authority`
inherits matching authority locks. All dictionaries accompany the payload.
Supporting schema/doctrine labels may be omitted with their original hash
binding; values, precision, decision claims and unavailable states remain.
No additional provider request is needed for this deployment acceptance.

Battle Map first_screen and analyst-owned fields are unchanged. Six weights
20/20/17/25/13/5, light thresholds -60/-35/35/60, formal Wake 90/95,
production NOT_APPROVED, external_action_authority NONE,
capital_decision_authority USER_ONLY, machine_execution FORBIDDEN and
action_output NONE remain locked. #7 remains COMPLETE, 7/8=87.5%; #8 is not run.

## Validation

Deterministic tests cover formal MSTR/ASST, research authority, semantic/basis
mismatches, PIT exclusion, CDF ties/counts, regime/benchmark blockers, comparable
five-week selection, accretion/dilution, net proceeds, future carry, duplicate
events, hashes, compact projection and 2,100-day histories remaining local.
Targeted Treasury/mNAV/Evidence/Market Health/Handoff/transport/Battle Map tests,
full unittest discovery, compileall, registry and read-only surface checks are
required. Live acceptance records distinguish valid unavailable claims from
engineering failure; they never fill missing official inputs for a prettier pass.
