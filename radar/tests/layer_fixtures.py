from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crt_radar.source_gate_runner import FetchResult


DAY_MS = 86_400_000


def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _fred_csv(series: str, rows: list[tuple[int, float]]) -> str:
    return "DATE," + series + "\n" + "".join(f"{_date(ms)},{value}\n" for ms, value in rows)


def _daily_rows(now_ms: int, count: int, start: float, step: float) -> list[tuple[int, float]]:
    latest = (now_ms // DAY_MS) * DAY_MS
    return [(latest - (count - 1 - index) * DAY_MS, start + index * step) for index in range(count)]


def _monthly_rows(now_ms: int, count: int, start: float, step: float) -> list[tuple[int, float]]:
    current = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    result: list[tuple[int, float]] = []
    for reverse_index in range(count - 1, -1, -1):
        month_index = current.year * 12 + current.month - 1 - reverse_index
        year, zero_month = divmod(month_index, 12)
        observed = datetime(year, zero_month + 1, 1, tzinfo=timezone.utc)
        result.append((int(observed.timestamp() * 1000), start + (count - 1 - reverse_index) * step))
    return result


def _stablecoin_rows(now_ms: int, start: float, step: float) -> list[dict]:
    rows = _daily_rows(now_ms, 31, start, step)
    return [
        {
            "date": str(observed_ms // 1000),
            "totalCirculatingUSD": {"peggedUSD": value},
        }
        for observed_ms, value in rows
    ]


def _price_rows(now_ms: int) -> list[list]:
    latest_open = (now_ms // DAY_MS) * DAY_MS - DAY_MS
    result: list[list] = []
    for index in range(205):
        open_ms = latest_open - (204 - index) * DAY_MS
        close_ms = open_ms + DAY_MS - 1
        open_value = 50_000.0 + index * 20.0
        close = open_value + 10.0
        quote_volume = 100_000_000.0 + index * 1_000.0
        taker_buy = quote_volume * 0.51
        result.append(
            [
                open_ms,
                str(open_value),
                str(open_value + 100.0),
                str(open_value - 100.0),
                str(close),
                "1000",
                close_ms,
                str(quote_volume),
                1000,
                "510",
                str(taker_buy),
                "0",
            ]
        )
    return result


def supplemental_overrides(registry, now_ms: int) -> dict[str, FetchResult]:
    macro = registry.by_input_family("MACRO_CONTEXT")
    rates = registry.by_input_family("RATES_CONTEXT")
    credit = registry.by_input_family("CREDIT_LIQUIDITY_CONTEXT")
    oi_notional = registry.by_input_family("OPEN_INTEREST_NOTIONAL")
    price = registry.by_input_family("PRICE_STRUCTURE_CONTEXT")
    macro_payload = {
        "core_cpi": _fred_csv("CPILFESL", _monthly_rows(now_ms, 13, 100.0, 0.25)),
        "unemployment": _fred_csv("UNRATE", _monthly_rows(now_ms, 15, 4.0, 0.01)),
        "effr": _fred_csv("EFFR", _daily_rows(now_ms, 3, 4.5, 0.0)),
        "core_pce": _fred_csv("PCEPILFE", _monthly_rows(now_ms, 13, 100.0, 0.2)),
    }
    rates_payload = {
        "broad_usd": _fred_csv("DTWEXBGS", _daily_rows(now_ms, 21, 118.0, 0.05)),
        "real_10y": _fred_csv("DFII10", _daily_rows(now_ms, 21, 1.8, 0.001)),
        "nominal_2y": _fred_csv("DGS2", _daily_rows(now_ms, 21, 3.5, 0.001)),
    }
    credit_payload = {
        "usdt": _stablecoin_rows(now_ms, 160_000_000_000.0, 20_000_000.0),
        "usdc": _stablecoin_rows(now_ms, 70_000_000_000.0, 10_000_000.0),
        "high_yield_oas": _fred_csv("BAMLH0A0HYM2", _daily_rows(now_ms, 21, 3.0, 0.001)),
    }
    return {
        macro.source_id: FetchResult(macro.source_id, "OK", payload=macro_payload),
        rates.source_id: FetchResult(rates.source_id, "OK", payload=rates_payload),
        credit.source_id: FetchResult(credit.source_id, "OK", payload=credit_payload),
        oi_notional.source_id: FetchResult(
            oi_notional.source_id,
            "OK",
            payload=[
                {
                    "symbol": "BTCUSDT",
                    "sumOpenInterestValue": "7000000000",
                    "timestamp": now_ms - 30_000,
                }
            ],
        ),
        price.source_id: FetchResult(price.source_id, "OK", payload=_price_rows(now_ms)),
    }
