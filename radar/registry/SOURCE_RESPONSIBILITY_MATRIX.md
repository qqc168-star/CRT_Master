# Source Responsibility Matrix

This matrix is generated from `CONFIG/SOURCE_REGISTRY_V1.2.json` (registry payload version `1.3-wip`). It is an engineering registry, not formal scoring authority.

Current implemented families:

- AS-L2: Nominal Broad U.S. Dollar Index proxy (must never be labelled DXY).
- AS-L4: BTCUSDT OI, funding, liquidation connectivity and persistent liquidation aggregates.
- AS-L5: Coin Metrics market-cap and realized-cap inputs with transparent MVRV/NUPL formulas.

Current missing families:

- AS-L1 official macro release engine.
- AS-L3 ETF / stablecoin / credit-liquidity engine.
- AS-L6 price / volume / averages / ATR / CVD engine.

No source in this matrix has account, order, email, webhook or fund-movement authority.
