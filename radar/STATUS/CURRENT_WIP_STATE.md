# CRT Radar Current Formal State

- Formal SSOT: `CRT V1.10`
- State reconciliation lineage: `PR #36`
- Reconciliation basis main SHA: `1426b56a7877d3c6357f76b9ecdda632ff1e50a3`
- Reconciliation merge SHA: `e3aadc64f39b709fc9a5d1cf3ff31136c7cabc14`
- Snapshot freshness rule: semantic state change, not ordinary repository HEAD movement
- Formal seal approval: `2026-08-05 19:09 +08:00`
- 24-hour Live Shadow Gate: `PASS`
- P1-01 technical post-live review: `PASS`
- Live evidence archive: `PASS`
- Last verified full regression: `366/366 PASS`
- Production: `NOT_APPROVED`
- BTC Season output: `BLOCKED / null`
- Formal BTC Season input bindings: `0 / 12`, `UNBOUND_BLOCKED`
- Post-seal maturity observation: `0 / 20 qualified`
- Qualified-run blocker: `BTC_SEASON_ROUTER_NOT_VERIFIED`
- External action authority: `NONE`
- Parallel automation stash: `PRESERVED / NOT_APPLIED`

## Active objective（目前主動目標）

- Active Baton（主動接力棒）: `radar/STATUS/CRT_ACTIVE_BATON.md`
- Mission（任務）: `CRT Live Action Loop V0.1`
- Progress（進度）: see `radar/STATUS/CRT_ACTIVE_BATON.md`
- Active item（目前唯一進行中項目）: see `radar/STATUS/CRT_ACTIVE_BATON.md`
- Priority（優先順序）: `依 CRT_ACTIVE_BATON.md 的 2026-10-11 七項新排序 Q1 -> Q7`
- BTC 正式季節恢復已獲使用者重新排序批准，列為 Q1；原第八項端到端驗收保留原定義並列為 Q6。
## Current engineering distinction

Engineering sources now exist across `AS-L1` through `AS-L6`.
This does not constitute complete formal BTC Season source authority.

The current formal input envelope remains fail-closed until all required
formal source, transform, freshness, window and clock bindings are recovered
and approved under the existing governance boundary.

## Preserved locks

- Six-layer weights: `20 / 20 / 17 / 25 / 13 / 5`
- Light thresholds: `-60 / -35 / 35 / 60`
- Unqualified `mNAV`: `Diluted mNAV`（稀釋後資產淨值倍數）; see the current semantic revision below
- Q4: `2026 Q4`
- Production approval: unchanged
- External action authority: `NONE`
- Constitution and governance boundaries: unchanged

## Current mNAV semantic revision（目前資產淨值倍數語義修訂）

The later explicit user approval on `2026-10-13` supersedes only the current
mNAV interpretation of the preserved `2026-08-05` seal. The original seal and
the reconciliation/test snapshots above remain historical records, not newly
performed validation. Current authority is
`radar/RELEASE/CRT_DILUTED_MNAV_SEMANTIC_REVISION_20261013.md`:
`(diluted_shares * equity_price_usd) / (btc_holdings * btc_price_usd)`.
Current formula version: `CRT_DILUTED_MNAV_BTC_MARKET_VALUE_V1`.
Legacy unknown/different-denominator values remain labeled research evidence;
they do not enter the current formal historical distribution. No formal Season,
production, external action, allocation or capital-execution approval is added.
