# CRT L6 Formal Source Binding V0.1

Base: `9119c174eae5bf4559aa756f62901d670de8afa4`.

This binds two locked research sources to candidate evidence. It does not approve
the formal model, production, the Season Router, or capital action. The authority
remains `formal_model=NOT_APPROVED`, `production=NOT_APPROVED`,
`external_action_authority=NONE`, `action_output=NONE`, and
`capital_decision_authority=USER_ONLY`.

## Integration

`SourceRegistry.with_l6_candidate_sources()` applies
`radar/CONFIG/L6_SOURCE_BINDING_OVERLAY_V0.1.json` inside `run_source_gate`.
The sealed base registry stays byte-for-byte unchanged: its hash is a dependency
of the L4 OI revision policy. The gate records both base and effective hashes.
No L3 or L4 source implementation or contract changes.

The gate reports `l6_candidate_state` and `l6_candidate_blocked_reasons`
separately from the legacy first-slice transport state. A missing L6 source
blocks L6 qualification and V110, without invalidating independently valid L4
evidence. An `OBSERVATION_ONLY` transport state is not complete candidate evidence.

| Family | Source ID | Metrics |
|---|---|---|
| BTC_SPOT_COMPOSITE_OHLCV | CRT-CONN-BTC-SPOT-THREE-VENUE-COMPOSITE-001 | close_minus_sma200_over_atr20; sma50_minus_sma200_over_atr20; return_20d_over_atr_vol |
| BTC_SPOT_AGGRESSOR_DAILY | CRT-CONN-BTC-SPOT-AGGRESSOR-BINANCE-001 | cvd_20d_share |

The four existing research calculations are shared, without formula changes, in
`l6_calculations.py`. Research delegates to that same implementation. Runtime does
not import the research acquisition or model modules. The research source lock
and V110 feature bindings are unchanged and verified before intake.

The Binance directional proxy remains registered, retains
`formal_composite_authority=NONE`, and is still collected independently. Qualified
formal observations take precedence regardless of observation order. An absent
formal source never promotes the proxy: V110 continues rejecting its identity.

## Read-only archive intake

Set `CRT_L6_SOURCE_ROOT` to a local archive directory (default:
`radar/runtime/l6_sources`). No downloader, scheduler, live runtime mutation, or
automatic source substitution is introduced. The source gate reads archived
provider responses and derives measurements itself; a supplied metric or
precomputed daily aggregate is not sufficient.

The directory contains one manifest per family, named `<input_family>.json`:

```json
{
  "schema_version": "CRT_L6_SOURCE_ARCHIVES_V0.1",
  "input_family": "BTC_SPOT_COMPOSITE_OHLCV",
  "source_id": "CRT-CONN-BTC-SPOT-THREE-VENUE-COMPOSITE-001",
  "source_authority_hash": "b090665891e84fc8ddbccd0e07d81e3b6abc9013e76bc43f4baab5c2406261fb",
  "window_end_ms": 1788134400000,
  "artifacts": []
}
```

This empty example is blocked, not live evidence. Each artifact requires
`sha256`, `size_bytes`, `request_identity` (`GET https://...`),
`first_seen_at_ms`, `retrieved_at_ms`, `evidence_class`,
`license_classification`, and `source_authority_hash`. Bytes reside at
`artifacts/sha256/<first-two-hash-characters>/<sha256>` and must match the hash
and length. Timestamps must be ordered and visible at evaluation. Synthetic
evidence classes are rejected. Intake writes neither manifests nor artifacts.

### Composite

Require 201 consecutive completed daily bars ending at the explicitly requested
UTC `window_end_ms`, with every locked venue present on every day. Do not select
an older intersection to conceal a missing day. Record coordinate-wise medians,
per-field dispersion in basis points, summed base volume as quality metadata,
venue count, retrieval availability, and original artifact provenance.

Each artifact declares the exact locked `venue_id`, `product`, and `transport`:

- Coinbase BTC-USD: original candle JSON from the official Exchange candles
  endpoint with `granularity=86400`.
- Bitstamp btcusd: original OHLC JSON from the official endpoint with
  `step=86400`, including pair identity BTC/USD.
- Kraken XBT/USD: official OHLCVT ZIP, `archive_member` naming
  `XBTUSD_1440.csv`, plus an `official_link_artifact` containing the archived
  locked Kraken documentation page linking the exact archive URL. The nested
  documentation artifact has the same byte/provenance requirements. Complete
  quarterly ZIPs can supply consecutive non-overlapping history; a split ZIP
  part is not a complete archive and cannot qualify by itself.

Malformed OHLC, duplicate days, missing venue days, insufficient history, stale
windows and unavailable bytes block the source. Incomplete/future API extras
are excluded and cannot fill required completed days. There is no forward fill
or single-venue fallback. The same composite close remains the only
forward-return target; this intake does not introduce a new target.

### Aggressor

Require original Binance Spot BTCUSDT daily aggTrades ZIPs, their exact provider
`.CHECKSUM` responses, and 22 consecutive files: the 20 measurement days plus
one completed neighboring day on each side for boundary audit. Each artifact
declares `symbol=BTCUSDT`, UTC `day_start_ms`, and a nested `checksum_artifact`
with the same provenance requirements. The ZIP/CSV names and request URL must
match the declared day and locked archive pattern.

Use documented timestamp units (milliseconds before 2025; microseconds from
2025), unique contiguous aggregate/trade IDs, ordered timestamps, and the locked
buyer-maker mapping. Quote volume is price times quantity. Unknown sides,
partial/out-of-day records, missing daily files, checksum failures and boundary
gaps block. Empty days require an actual verified complete archive; absent files
are never zero. The adjacent-day requirement can delay the eligible window by a
day; the existing 172800-second source freshness limit still applies.

## Availability and validation boundary

Mechanics tests use temporary synthetic provider-shaped archives only. They
demonstrate qualification behavior, not live history readiness. No local live
archive population is performed by this change. Missing archives, the Kraken
quarterly publication lag, and candidate normalization-history requirements may
remain blockers after code integration. Do not replace Kraken archives with its
REST endpoint without a source-doctrine ruling.

Provider format references:
[Coinbase candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles),
[Kraken OHLCVT](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data),
[Bitstamp OHLC](https://www.bitstamp.net/api/#ohlc_data),
[Binance public archives](https://github.com/binance/binance-public-data).
