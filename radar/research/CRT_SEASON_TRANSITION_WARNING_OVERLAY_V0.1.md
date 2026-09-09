# CRT Season Transition Warning Overlay V0.1

`SEASON_TRANSITION_WARNING_OVERLAY` is a research and decision-support surface.
It is not a Formal Season router, a production approval, or a trade-action
generator.

## Governing principle

> Radar gets time; Formal Season keeps discipline.

The overlay exposes five lights and one future-market scenario through
`Gate + Core + VETO`. Weights express responsibility order; the result is not
selected by counting green lights. A decisive veto blocks an upgrade.

## Existing signals reused

- Price structure: the three existing L6 price feature scores, using their
  existing internal weights renormalized only after intentionally excluding
  CVD from this light. The CVD feature is not duplicated here.
- Spot demand: direct reuse of `L6_CVD_20D_SHARE`, with spot buy share, spot
  CVD proxy, and 30-minute-to-30-minute persistence as diagnostic evidence.
- Institutional flow: direct reuse of
  `L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM`. Optional 1D, 5D, 20D, 60D, and 120D
  research windows use `100 * flow_usd / starting_aum_usd`; absolute USD flow
  is display-only. The 1D pulse and 120D context never score the light.
- Leverage quality: direct reuse of the existing L4 layer score. Raw display
  includes OI 24-hour/3-day changes, latest/3-day funding, and long/short
  liquidation values.
- Conflict/veto: categorical only: `NO_DECISIVE_VETO`, `CONFLICT_PRESENT`, or
  `DECISIVE_VETO`. It is a fuse, not a fifth vote, and has no numeric score.

## Locked boundaries

- Existing Radar thresholds remain exactly `[-60, -35, 35, 60]` with buckets
  `C0_VERY_UNSUPPORTIVE` through `C4_VERY_SUPPORTIVE`.
- Existing six-layer weights remain `20/20/17/25/13/5`.
- Event research coordinates 82K-83K attack and 80K-82K retest/defense are
  display-only and carry no formal-threshold authority.
- `formal_season` remains null and
  `score_may_determine_btc_season` remains false.
- Production and external-action authority remain `NOT_APPROVED` and `NONE`.
- No BUY or SELL output is permitted.

## Scenario vocabulary

- `情境 1｜春季證據強升級`
- `情境 2｜春芽存在、仍在拉扯`
- `情境 3｜假春風險升高`

Future paths are scenarios. A historical replay may use a historical case ID.
Replay output preserves the joint objective
`DETECTION_LATENCY_X_FALSE_POSITIVE`; missing ground truth stays explicit and
is never imputed.

## Institutional context status

The current registered live source does not yet provide complete point-in-time
1D/5D/20D/60D/120D ETP history. Those windows therefore enter only through an
optional, research-only context until a separately governed source integration
exists. Missing windows remain `NOT_AVAILABLE`; the overlay does not fabricate
or forward-fill them.
