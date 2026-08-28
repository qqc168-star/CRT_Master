# CRT × IBKR Live Market Data Intake V0.1

## Scope

This intake is market-data only. It requests:

- streaming Level 1 watchlist data with `reqMktData`;
- RTVolume timestamps through generic tick `233`;
- 5-second `TRADES` bars with `reqRealTimeBars`;
- MSTR, ASST, STRC, and SATA as US stocks routed through SMART in USD.

The implementation contains no order placement, order cancellation, account, position, or fund-movement request. Regulatory snapshots are disabled. Its fixed governance boundary is:

- `external_action_authority = NONE`
- `capital_decision_authority = USER_ONLY`
- `machine_may_execute_trade = false`

## Required local setup

1. Install and sign in to TWS or IB Gateway.
2. In API settings, enable socket clients and keep **Read-Only API** enabled.
3. Select the matching socket port. Typical defaults are TWS paper `7497`, TWS live `7496`, IB Gateway paper `4002`, and IB Gateway live `4001`; the configured application value is authoritative.
4. Install the Python package supplied with the official IBKR TWS API so `import ibapi` succeeds.
5. Confirm that the IBKR username has the relevant US equity market-data permissions. The collector refuses delayed data.

The API does not expose a trustworthy query for the TWS **Read-Only API** checkbox. Live collection therefore requires the operator to verify it and pass an explicit confirmation flag.

## Preflight

From `radar`:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m crt_radar.ibkr_live_market_data_intake --preflight-only --port 7497
```

Preflight checks the local Python API package and the selected loopback port. `READY_FOR_OPERATOR_CONFIRMATION` means the machine checks passed but the TWS read-only checkbox still needs human confirmation.

## Capture and CRT integration

Run during the US premarket session. The collector fails closed if a symbol has no timestamped premarket trade, if IBKR returns delayed/frozen data, or if any provider/source/hash boundary is invalid.

```powershell
python -m crt_radar.ibkr_live_market_data_intake `
  --confirm-tws-read-only `
  --port 7497 `
  --client-id 168 `
  --duration-seconds 12
```

Default outputs are ignored runtime artifacts:

- `runtime/equity/premarket/latest.json`
- `runtime/equity/premarket/handoff.json`
- `runtime/equity/premarket/battle_map.json`

To attach the verified handoff and Battle Map to an existing CRT Evidence Pack without overwriting the input:

```powershell
python -m crt_radar.ibkr_live_market_data_intake `
  --confirm-tws-read-only `
  --evidence-pack-input runtime/evidence/latest.json `
  --evidence-pack-output runtime/evidence/latest_with_ibkr.json
```

The output Evidence Pack is re-hashed after the additive `premarket_market_data` surface is validated. Analyst-owned lights, entry/exit conditions, and share deltas remain empty.

The runtime registry is built additively from `CONFIG/SOURCE_REGISTRY_V1.2.json` and `CONFIG/IBKR_EQUITY_SOURCE_V0.1.json`. The base registry is not edited or re-sealed; its hash is recorded in the composite runtime registry before the provider overlay is bound.

## Operational notes

- Use a client ID not used by another API client.
- Keep capture bursts small. IBKR counts real-time bars against both Level 1 market-data lines and historical small-bar pacing limits.
- A live subscription and trading permissions are required for live market data. This collector never falls back to delayed data.
- Outside US premarket, use `--preflight-only`; the evidence collector will not relabel regular-hours or stale trades as premarket evidence.
- If one asset is unavailable, the machine-verified four-asset snapshot is not emitted. Resolve the subscription/contract issue or leave the affected claim blocked.

Official references:

- [IBKR TWS API documentation](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/)
- [Streaming market data](https://interactivebrokers.github.io/tws-api/market_data.html)
- [5-second real-time bars](https://interactivebrokers.github.io/tws-api/realtime_bars.html)
