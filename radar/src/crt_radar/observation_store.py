from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Observation:
    layer_id: str
    input_family: str
    metric: str
    as_of_ms: int
    value_num: float
    source_id: str
    quality_state: str
    evidence_hash: str
    registry_hash: str
    recorded_run_id: str
    recorded_at_ms: int


COMPARABLE_METRICS = {
    ("MACRO_CONTEXT", "core_inflation_acceleration"),
    ("MACRO_CONTEXT", "unemployment_deterioration"),
    ("MACRO_CONTEXT", "real_policy_rate"),
    ("DOLLAR_STRENGTH_PROXY", "broad_usd_proxy"),
    ("RATES_CONTEXT", "broad_usd_20d_log_change"),
    ("RATES_CONTEXT", "real_10y_yield_20d_change_bp"),
    ("RATES_CONTEXT", "nominal_2y_yield_20d_change_bp"),
    ("CREDIT_LIQUIDITY_CONTEXT", "stablecoin_supply_30d_log_change"),
    ("CREDIT_LIQUIDITY_CONTEXT", "high_yield_oas_20d_change_bp"),
    ("OPEN_INTEREST", "open_interest_contracts"),
    ("OPEN_INTEREST_NOTIONAL", "open_interest_notional_usd"),
    ("OPEN_INTEREST_NOTIONAL", "oi_to_market_cap_pct"),
    ("FUNDING_RATE", "funding_rate"),
    ("FUNDING_RATE", "abs_funding_3d_mean_bp"),
    ("LIQUIDATION_AGGREGATES", "liquidation_1h_total_usd"),
    ("LIQUIDATION_AGGREGATES", "liquidation_24h_total_usd"),
    ("LIQUIDATION_AGGREGATES", "liquidation_intensity_24h_pct"),
    ("LIQUIDATION_AGGREGATES", "short_minus_long_liquidation_share_24h"),
    ("ONCHAIN_VALUE", "mvrv"),
    ("ONCHAIN_VALUE", "nupl"),
    ("ONCHAIN_VALUE", "realized_cap_30d_log_change"),
    ("PRICE_STRUCTURE_CONTEXT", "close_minus_sma200_over_atr20"),
    ("PRICE_STRUCTURE_CONTEXT", "sma50_minus_sma200_over_atr20"),
    ("PRICE_STRUCTURE_CONTEXT", "return_20d_over_atr_vol"),
    ("PRICE_STRUCTURE_CONTEXT", "cvd_20d_share"),
}


def _finite(value: Any) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError("numeric observation missing or invalid")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("numeric observation must be finite")
    return number


def _family_evidence(source_gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = source_gate.get("evidence")
    if not isinstance(rows, list):
        raise ValueError("source_gate.evidence must be a list")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        family = raw.get("input_family")
        if not isinstance(family, str) or not family:
            continue
        if family in result:
            raise ValueError(f"duplicate evidence family: {family}")
        result[family] = raw
    return result


def _metric_rows(family: str, parsed: dict[str, Any]) -> list[tuple[str, float]]:
    if family == "MACRO_CONTEXT":
        return [
            ("core_inflation_acceleration", _finite(parsed.get("core_inflation_acceleration"))),
            ("unemployment_deterioration", _finite(parsed.get("unemployment_deterioration"))),
            ("real_policy_rate", _finite(parsed.get("real_policy_rate"))),
        ]
    if family == "DOLLAR_STRENGTH_PROXY":
        return [("broad_usd_proxy", _finite(parsed.get("value")))]
    if family == "RATES_CONTEXT":
        return [
            ("broad_usd_20d_log_change", _finite(parsed.get("broad_usd_20d_log_change"))),
            ("real_10y_yield_20d_change_bp", _finite(parsed.get("real_10y_yield_20d_change_bp"))),
            ("nominal_2y_yield_20d_change_bp", _finite(parsed.get("nominal_2y_yield_20d_change_bp"))),
        ]
    if family == "CREDIT_LIQUIDITY_CONTEXT":
        rows = [
            ("stablecoin_supply_30d_log_change", _finite(parsed.get("stablecoin_supply_30d_log_change"))),
            ("high_yield_oas_20d_change_bp", _finite(parsed.get("high_yield_oas_20d_change_bp"))),
        ]
        if parsed.get("spot_btc_etp_flow_20d_pct_aum") is not None:
            rows.append(("spot_btc_etp_flow_20d_pct_aum", _finite(parsed.get("spot_btc_etp_flow_20d_pct_aum"))))
        return rows
    if family == "OPEN_INTEREST":
        return [("open_interest_contracts", _finite(parsed.get("open_interest_contracts")))]
    if family == "OPEN_INTEREST_NOTIONAL":
        rows = [("open_interest_notional_usd", _finite(parsed.get("open_interest_notional_usd")))]
        if parsed.get("oi_to_market_cap_pct") is not None:
            rows.append(("oi_to_market_cap_pct", _finite(parsed.get("oi_to_market_cap_pct"))))
        return rows
    if family == "FUNDING_RATE":
        rows = [
            ("funding_rate", _finite(parsed.get("funding_rate"))),
            ("mark_price", _finite(parsed.get("mark_price"))),
        ]
        if parsed.get("abs_funding_3d_mean_bp") is not None:
            rows.append(("abs_funding_3d_mean_bp", _finite(parsed.get("abs_funding_3d_mean_bp"))))
        return rows
    if family == "BTC_SPOT_PRICE":
        return [
            ("btc_spot_price_usd", _finite(parsed.get("spot_price_usd"))),
        ]
    if family == "LIQUIDATION_AGGREGATES":
        windows = parsed.get("windows")
        if not isinstance(windows, dict):
            raise ValueError("LIQUIDATION_AGGREGATES.windows missing")
        rows: list[tuple[str, float]] = [("liquidation_coverage_ratio", _finite(parsed.get("coverage_ratio")))]
        for label in ("1h", "24h"):
            bucket = windows.get(label)
            if not isinstance(bucket, dict):
                raise ValueError(f"LIQUIDATION_AGGREGATES.windows.{label} missing")
            rows.extend(
                [
                    (f"liquidation_{label}_long_usd", _finite(bucket.get("long_liquidation_usd"))),
                    (f"liquidation_{label}_short_usd", _finite(bucket.get("short_liquidation_usd"))),
                    (f"liquidation_{label}_total_usd", _finite(bucket.get("total_liquidation_usd"))),
                    (f"liquidation_{label}_event_count", _finite(bucket.get("event_count"))),
                ]
            )
        if parsed.get("liquidation_intensity_24h_pct") is not None:
            rows.append(("liquidation_intensity_24h_pct", _finite(parsed.get("liquidation_intensity_24h_pct"))))
        if parsed.get("short_minus_long_liquidation_share_24h") is not None:
            rows.append(
                (
                    "short_minus_long_liquidation_share_24h",
                    _finite(parsed.get("short_minus_long_liquidation_share_24h")),
                )
            )
        return rows
    if family == "ONCHAIN_VALUE":
        rows = [
            ("mvrv", _finite(parsed.get("mvrv"))),
            ("nupl", _finite(parsed.get("nupl"))),
        ]
        for metric in ("market_cap_usd", "realized_cap_usd", "realized_cap_30d_log_change"):
            if parsed.get(metric) is not None:
                rows.append((metric, _finite(parsed.get(metric))))
        return rows
    if family == "PRICE_STRUCTURE_CONTEXT":
        rows = [
            ("close_minus_sma200_over_atr20", _finite(parsed.get("close_minus_sma200_over_atr20"))),
            ("sma50_minus_sma200_over_atr20", _finite(parsed.get("sma50_minus_sma200_over_atr20"))),
            ("return_20d_over_atr_vol", _finite(parsed.get("return_20d_over_atr_vol"))),
            ("cvd_20d_share", _finite(parsed.get("cvd_20d_share"))),
        ]
        for metric in (
            "quote_volume_rvol20",
            "taker_buy_quote_share_1d",
        ):
            if parsed.get(metric) is not None:
                rows.append((metric, _finite(parsed.get(metric))))
        return rows
    return []


def extract_observations(source_gate: dict[str, Any], *, recorded_at_ms: int | None = None) -> list[Observation]:
    if not isinstance(source_gate, dict):
        raise ValueError("source_gate must be an object")
    run_id = source_gate.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("source_gate.run_id missing")
    registry_hash = source_gate.get("source_registry_hash")
    if not isinstance(registry_hash, str) or len(registry_hash) != 64:
        raise ValueError("source_registry_hash invalid")
    parsed_all = source_gate.get("parsed")
    if not isinstance(parsed_all, dict):
        raise ValueError("source_gate.parsed must be an object")
    evidence_by_family = _family_evidence(source_gate)
    recorded_at = int(time.time() * 1000) if recorded_at_ms is None else int(recorded_at_ms)

    result: list[Observation] = []
    for family, parsed in parsed_all.items():
        if not isinstance(family, str) or not isinstance(parsed, dict):
            continue
        evidence = evidence_by_family.get(family)
        if evidence is None:
            continue
        evidence_hash = evidence.get("evidence_hash")
        source_id = evidence.get("source_id")
        namespace = evidence.get("namespace")
        quality_state = evidence.get("quality_state")
        as_of_ms = parsed.get("as_of_ms")
        if not isinstance(evidence_hash, str) or len(evidence_hash) != 64:
            raise ValueError(f"{family} evidence_hash invalid")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError(f"{family} source_id missing")
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(f"{family} namespace missing")
        if not isinstance(quality_state, str) or not quality_state.startswith("VALID"):
            continue
        try:
            as_of = int(as_of_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{family}.as_of_ms invalid") from exc
        for metric, value in _metric_rows(family, parsed):
            result.append(
                Observation(
                    layer_id=namespace,
                    input_family=family,
                    metric=metric,
                    as_of_ms=as_of,
                    value_num=value,
                    source_id=source_id,
                    quality_state=quality_state,
                    evidence_hash=evidence_hash,
                    registry_hash=registry_hash,
                    recorded_run_id=run_id,
                    recorded_at_ms=recorded_at,
                )
            )
    return result


class ObservationStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer_id TEXT NOT NULL,
                input_family TEXT NOT NULL,
                metric TEXT NOT NULL,
                as_of_ms INTEGER NOT NULL,
                value_num REAL NOT NULL,
                source_id TEXT NOT NULL,
                quality_state TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,
                registry_hash TEXT NOT NULL,
                recorded_run_id TEXT NOT NULL,
                recorded_at_ms INTEGER NOT NULL,
                UNIQUE(evidence_hash, metric)
            );
            CREATE INDEX IF NOT EXISTS idx_observations_metric_time
            ON observations(input_family, metric, as_of_ms);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ObservationStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def record(self, observations: Iterable[Observation]) -> int:
        before = self.conn.total_changes
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO observations (
                layer_id, input_family, metric, as_of_ms, value_num,
                source_id, quality_state, evidence_hash, registry_hash,
                recorded_run_id, recorded_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    o.layer_id,
                    o.input_family,
                    o.metric,
                    o.as_of_ms,
                    o.value_num,
                    o.source_id,
                    o.quality_state,
                    o.evidence_hash,
                    o.registry_hash,
                    o.recorded_run_id,
                    o.recorded_at_ms,
                )
                for o in observations
            ],
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def latest_at_or_before(
        self,
        input_family: str,
        metric: str,
        target_ms: int,
        *,
        max_gap_ms: int,
    ) -> Observation | None:
        row = self.conn.execute(
            """
            SELECT * FROM observations
            WHERE input_family = ? AND metric = ? AND as_of_ms <= ?
            ORDER BY as_of_ms DESC
            LIMIT 1
            """,
            (input_family, metric, int(target_ms)),
        ).fetchone()
        if row is None:
            return None
        if int(target_ms) - int(row["as_of_ms"]) > int(max_gap_ms):
            return None
        return Observation(
            layer_id=row["layer_id"],
            input_family=row["input_family"],
            metric=row["metric"],
            as_of_ms=int(row["as_of_ms"]),
            value_num=float(row["value_num"]),
            source_id=row["source_id"],
            quality_state=row["quality_state"],
            evidence_hash=row["evidence_hash"],
            registry_hash=row["registry_hash"],
            recorded_run_id=row["recorded_run_id"],
            recorded_at_ms=int(row["recorded_at_ms"]),
        )

    def series(self, input_family: str, metric: str) -> list[Observation]:
        rows = self.conn.execute(
            """
            SELECT * FROM observations
            WHERE input_family = ? AND metric = ?
            ORDER BY as_of_ms ASC
            """,
            (input_family, metric),
        ).fetchall()
        return [
            Observation(
                layer_id=row["layer_id"],
                input_family=row["input_family"],
                metric=row["metric"],
                as_of_ms=int(row["as_of_ms"]),
                value_num=float(row["value_num"]),
                source_id=row["source_id"],
                quality_state=row["quality_state"],
                evidence_hash=row["evidence_hash"],
                registry_hash=row["registry_hash"],
                recorded_run_id=row["recorded_run_id"],
                recorded_at_ms=int(row["recorded_at_ms"]),
            )
            for row in rows
        ]
