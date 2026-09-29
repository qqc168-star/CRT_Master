from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import date, datetime, time
from typing import Any, Iterable
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "CRT_MSTR_ASST_FULL_DAY_MARKET_INTAKE_V0.1"
SUPPORTED_ASSETS = ("MSTR", "ASST")
NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DEFAULT_EARLY_CLOSE_DATES = frozenset({"2026-11-27", "2026-12-24"})


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _authority() -> dict[str, Any]:
    return {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _session_close_ms(
    session_date: str,
    *,
    early_close_dates: frozenset[str],
) -> int:
    parsed = date.fromisoformat(session_date)
    close_at = time(13, 0) if session_date in early_close_dates else time(16, 0)
    localized = datetime.combine(parsed, close_at, tzinfo=NEW_YORK)
    return int(localized.astimezone(UTC).timestamp() * 1000)


def _number(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"equity bar {key} must be numeric")
    return float(value)


def _normalize_bars(
    asset: str,
    rows: Any,
    *,
    generated_at_ms: int,
    early_close_dates: frozenset[str],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{asset} equity bars must be a list")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError(f"{asset} equity bar must be an object")
        session_date = raw.get("session_date")
        if not isinstance(session_date, str):
            raise ValueError(f"{asset} session_date must be an ISO date")
        if session_date in seen:
            raise ValueError(f"{asset} has duplicate session_date {session_date}")
        seen.add(session_date)

        close_ms = _session_close_ms(
            session_date,
            early_close_dates=early_close_dates,
        )
        normalized.append(
            {
                "session_date": session_date,
                "session_close_ms": close_ms,
                "session_state": (
                    "COMPLETE" if generated_at_ms >= close_ms else "INCOMPLETE"
                ),
                "open": _number(raw, "open"),
                "high": _number(raw, "high"),
                "low": _number(raw, "low"),
                "close": _number(raw, "close"),
                "volume": _number(raw, "volume"),
                "source_state": str(raw.get("source_state", "UNKNOWN")),
            }
        )

    normalized.sort(key=lambda row: row["session_date"])
    return normalized


def _returns(values: list[float], horizon: int) -> float | None:
    if len(values) <= horizon or values[-1 - horizon] == 0:
        return None
    return (values[-1] / values[-1 - horizon] - 1.0) * 100.0


def _rvol(values: list[float], index: int, window: int = 20) -> float | None:
    start = index - window
    if start < 0:
        return None
    baseline = values[start:index]
    average = sum(baseline) / len(baseline)
    if average == 0:
        return None
    return values[index] / average


def _btc_marks_by_close(rows: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("btc_close_marks must be a list")
    result: dict[int, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("BTC close mark must be an object")
        observed_at_ms = raw.get("observed_at_ms")
        price = raw.get("price_usd")
        if not isinstance(observed_at_ms, int):
            raise ValueError("BTC observed_at_ms must be an integer")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("BTC price_usd must be numeric")
        result[observed_at_ms] = {
            "observed_at_ms": observed_at_ms,
            "price_usd": float(price),
            "source_state": str(raw.get("source_state", "UNKNOWN")),
        }
    return result


def _asset_snapshot(
    asset: str,
    bars: list[dict[str, Any]],
    btc_marks: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    complete = [row for row in bars if row["session_state"] == "COMPLETE"]
    if not complete:
        return {
            "asset": asset,
            "state": "BLOCKED",
            "reason": "NO_COMPLETE_EQUITY_SESSION",
            "excluded_incomplete_sessions": sum(
                row["session_state"] == "INCOMPLETE" for row in bars
            ),
        }

    closes = [row["close"] for row in complete]
    volumes = [row["volume"] for row in complete]
    latest_index = len(complete) - 1
    latest = deepcopy(complete[-1])
    previous = deepcopy(complete[-2]) if len(complete) >= 2 else None
    latest_rvol = _rvol(volumes, latest_index)
    previous_rvol = _rvol(volumes, latest_index - 1) if latest_index >= 1 else None

    equity_returns = {
        "return_1d_pct": _returns(closes, 1),
        "return_5d_pct": _returns(closes, 5),
    }

    aligned_marks: list[dict[str, Any]] = []
    missing_closes: list[int] = []
    for row in complete:
        mark = btc_marks.get(row["session_close_ms"])
        if mark is None:
            missing_closes.append(row["session_close_ms"])
        else:
            aligned_marks.append(mark)

    latest_required_closes = {
        complete[-1]["session_close_ms"],
    }
    if len(complete) >= 2:
        latest_required_closes.add(complete[-2]["session_close_ms"])
    if len(complete) >= 6:
        latest_required_closes.add(complete[-6]["session_close_ms"])

    aligned_by_ms = {row["observed_at_ms"]: row for row in aligned_marks}
    alignment_ok = latest_required_closes.issubset(aligned_by_ms)
    btc_return_1d = None
    btc_return_5d = None
    if alignment_ok and len(complete) >= 2:
        latest_btc = aligned_by_ms[complete[-1]["session_close_ms"]]["price_usd"]
        prior_btc = aligned_by_ms[complete[-2]["session_close_ms"]]["price_usd"]
        if prior_btc != 0:
            btc_return_1d = (latest_btc / prior_btc - 1.0) * 100.0
        if len(complete) >= 6:
            five_day_btc = aligned_by_ms[complete[-6]["session_close_ms"]]["price_usd"]
            if five_day_btc != 0:
                btc_return_5d = (latest_btc / five_day_btc - 1.0) * 100.0

    relative = {
        "state": "VALID" if alignment_ok else "BLOCKED",
        "reason": (
            "SAME_CLOSE_CLOCK_CONFIRMED"
            if alignment_ok
            else "BTC_SAME_CLOSE_CLOCK_MARK_MISSING"
        ),
        "same_window": alignment_ok,
        "same_time_basis": alignment_ok,
        "btc_return_1d_pct": btc_return_1d,
        "btc_return_5d_pct": btc_return_5d,
        "btc_excess_return_1d_pct": (
            equity_returns["return_1d_pct"] - btc_return_1d
            if equity_returns["return_1d_pct"] is not None
            and btc_return_1d is not None
            else None
        ),
        "btc_excess_return_5d_pct": (
            equity_returns["return_5d_pct"] - btc_return_5d
            if equity_returns["return_5d_pct"] is not None
            and btc_return_5d is not None
            else None
        ),
        "missing_session_close_ms": sorted(
            latest_required_closes - set(aligned_by_ms)
        ),
    }

    return {
        "asset": asset,
        "state": "VALID",
        "latest_complete_session": latest,
        "previous_complete_session": previous,
        "complete_session_count": len(complete),
        "excluded_incomplete_sessions": sum(
            row["session_state"] == "INCOMPLETE" for row in bars
        ),
        "rvol20": latest_rvol,
        "previous_rvol20": previous_rvol,
        **equity_returns,
        "relative_btc": relative,
    }


def build_mstr_asst_full_day_market_intake(
    *,
    equity_bars: dict[str, list[dict[str, Any]]],
    btc_close_marks: list[dict[str, Any]],
    generated_at_ms: int,
    early_close_dates: Iterable[str] = DEFAULT_EARLY_CLOSE_DATES,
) -> dict[str, Any]:
    if not isinstance(equity_bars, dict):
        raise ValueError("equity_bars must be an object")
    if set(equity_bars) != set(SUPPORTED_ASSETS):
        raise ValueError("equity_bars must contain exactly MSTR and ASST")
    if not isinstance(generated_at_ms, int):
        raise ValueError("generated_at_ms must be an integer")

    early = frozenset(str(value) for value in early_close_dates)
    btc_marks = _btc_marks_by_close(btc_close_marks)
    assets = {
        asset: _asset_snapshot(
            asset,
            _normalize_bars(
                asset,
                equity_bars[asset],
                generated_at_ms=generated_at_ms,
                early_close_dates=early,
            ),
            btc_marks,
        )
        for asset in SUPPORTED_ASSETS
    }

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": (
            "VALID" if all(row["state"] == "VALID" for row in assets.values())
            else "BLOCKED"
        ),
        "generated_at_ms": generated_at_ms,
        "session_gate": "COMPLETE_SESSION_ONLY",
        "equity_clock": "AMERICA_NEW_YORK_OFFICIAL_CLOSE",
        "btc_alignment": "EXACT_EQUITY_SESSION_CLOSE",
        "assets": assets,
        **_authority(),
    }
    result["snapshot_hash"] = _canonical_hash(result)
    return result


def build_btc_convexity_research(*, equity_bars: dict, btc_close_marks: list,
                               generated_at_ms: int, source_window_contract: dict,
                               early_close_dates=DEFAULT_EARLY_CLOSE_DATES) -> dict:
    """Research sensitivity on the existing official-close clock, not health.

    The caller supplies an approved calendar/source/split-adjustment binding.
    Missing sessions/marks are not dropped to manufacture aligned returns.
    All returns are fractions. Rolling windows are fixed at 20 and 60 sessions.
    """
    out = {"research_state": "RESEARCH_ONLY", "assets": {}, "as_of": generated_at_ms,
           "company_health_authority": "NONE", "formal_price_target_authority": "NONE",
           "production": "NOT_APPROVED", "capital_decision_authority": "USER_ONLY",
           "machine_execution": "FORBIDDEN", **_authority()}
    try:
        contract = source_window_contract
        if (not isinstance(contract, dict) or contract.get("state") != "VALIDATED"
                or not contract.get("source_ref") or not contract.get("share_adjustment_basis")
                or type(contract.get("available_at_ms")) is not int
                or not 0 < contract["available_at_ms"] <= generated_at_ms):
            raise ValueError("APPROVED_SOURCE_WINDOW_AND_SHARE_BASIS_REQUIRED")
        expected = contract.get("expected_session_close_ms")
        if (not isinstance(expected, list) or len(expected) < 2
                or any(type(t) is not int or not 0 < t <= generated_at_ms for t in expected)
                or expected != sorted(set(expected))):
            raise ValueError("EXPLICIT_COMPLETED_SESSION_CALENDAR_REQUIRED")
        marks = _btc_marks_by_close(btc_close_marks)
        if len(marks) != len(btc_close_marks):
            raise ValueError("DUPLICATE_BTC_CLOSE_MARK")
        for t in expected:
            r = marks.get(t)
            if (r is None or not math.isfinite(r["price_usd"]) or r["price_usd"] <= 0
                    or r["source_state"] not in {"VALID_FRESH", "VALIDATED"}):
                raise ValueError("VERIFIED_EXACT_CLOSE_BTC_MARK_REQUIRED")
        for asset in SUPPORTED_ASSETS:
            try:
                bars = _normalize_bars(asset, equity_bars.get(asset), generated_at_ms=generated_at_ms,
                                       early_close_dates=frozenset(early_close_dates))
                rows = [r for r in bars if r["session_state"] == "COMPLETE"]
                if [r["session_close_ms"] for r in rows] != expected:
                    raise ValueError("EQUITY_SESSION_COVERAGE_MISMATCH")
                if any(not math.isfinite(r["close"]) or r["close"] <= 0
                       or r["source_state"] not in {"REALTIME", "VALIDATED"} for r in rows):
                    raise ValueError("VERIFIED_POSITIVE_EQUITY_CLOSE_REQUIRED")
                pairs = [{"at": b["session_close_ms"],
                          "equity_return": b["close"] / a["close"] - 1,
                          "btc_return": marks[b["session_close_ms"]]["price_usd"] /
                                        marks[a["session_close_ms"]]["price_usd"] - 1}
                         for a, b in zip(rows, rows[1:])]

                def stats(sample):
                    x = [r["btc_return"] for r in sample]
                    y = [r["equity_return"] for r in sample]
                    mx, my = sum(x)/len(x), sum(y)/len(y)
                    variance = sum((v-mx)**2 for v in x)
                    beta = sum((a-mx)*(b-my) for a, b in zip(x, y))/variance if variance else None
                    def capture(up):
                        selected = [(a, b) for a, b in zip(x, y) if (a > 0 if up else a < 0)]
                        denominator = math.prod(1+a for a, _ in selected)-1
                        return (math.prod(1+b for _, b in selected)-1)/denominator if denominator else None
                    values = {"rolling_btc_beta": beta, "upside_capture": capture(True),
                              "downside_capture": capture(False),
                              "relative_return_vs_btc": math.prod(1+v for v in y)-math.prod(1+v for v in x)}
                    if any(v is not None and not math.isfinite(v) for v in values.values()):
                        raise ValueError("NONFINITE_SENSITIVITY")
                    return {**values, "sample_count": len(sample),
                            "missing_evidence": [k for k, v in values.items() if v is None]}
                rolling = {str(w): [dict(start_at=pairs[i-w+1]["at"], end_at=pairs[i]["at"],
                                        **stats(pairs[i-w+1:i+1])) for i in range(w-1, len(pairs))]
                           for w in (20, 60)}
                out["assets"][asset] = {"state": "AVAILABLE", "sample_period": [expected[0], expected[-1]],
                    "full_sample": stats(pairs), "rolling": rolling,
                    "missing_windows": [w for w, values in rolling.items() if not values],
                    "limitation": "HISTORICAL_SENSITIVITY_NOT_HEALTH_OR_FIXED_LEVERAGE"}
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                out["assets"][asset] = {"state": "BLOCKED", "reason": str(exc)}
        out.update(state="AVAILABLE" if all(r["state"] == "AVAILABLE" for r in out["assets"].values()) else "PARTIAL",
                   source_window_contract=deepcopy(contract))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        out.update(state="BLOCKED", reason=str(exc))
    return out
