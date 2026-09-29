"""Local-only Gold research extensions over current CRT evidence contracts.

No collector, independent Evidence Pack, score, season or capital decision.
Input numbers are normalized verified observations or explicitly frozen scenarios.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .assumption_boundary_watch import evaluate_external_research_assumptions
from .btc_transition_replay_evidence import build_forward_200wma_context
from .mstr_asst_full_day_market_intake import build_btc_convexity_research
from .treasury_company_ct import ISSUERS, validate_pit_replay

DAY = 86_400_000
HORIZONS_WEEKS = (4, 8, 12, 26)
COHORTS = {"2013": (2013, 2013), "2017": (2017, 2017), "2020_2021": (2020, 2021),
           "2024_2026": (2024, 2026), "FULL_SAMPLE": (1, 9999)}
ETF_METRICS = ("BTC_ETF_BALANCE_BTC", "BTC_ETF_NET_FLOW_USD", "BTC_ETF_FLOW_BREADTH")
HOLDING_METRICS = (ETF_METRICS[0], "PUBLIC_COMPANY_BTC_HOLDINGS", "SOVEREIGN_OFFICIAL_BTC_HOLDINGS")
CADENCE = {"M2": {"collection": "MONTHLY", "calculation": "ON_RELEASE", "surface": "MONTHLY"},
           "TGA": {"collection": "WEEKLY", "calculation": "ON_RELEASE", "surface": "WEEKLY"},
           "RRP": {"collection": "DAILY", "calculation": "COMPLETED_WEEK", "surface": "WEEKLY"},
           "PMI": {"collection": "MONTHLY", "calculation": "ON_RELEASE", "surface": "MONTHLY"},
           "ETF": {"collection": "DAILY", "calculation": "ON_NEW_EVIDENCE", "surface": "EVENT_DRIVEN"},
           "HOLDINGS": {"collection": "OFFICIAL_DISCLOSURE", "calculation": "ON_NEW_EVIDENCE", "surface": "EVENT_DRIVEN"}}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _authority():
    return {"research_state": "RESEARCH_ONLY", "action_output": "NONE", "external_action_authority": "NONE",
            "external_action_performed": False, "capital_decision_authority": "USER_ONLY",
            "machine_execution": "FORBIDDEN", "production": "NOT_APPROVED",
            "formal_price_target_authority": "NONE", "machine_may_determine_btc_season": False}


def _blocked(reason):
    return {"state": "BLOCKED", "reason": reason, "value": None, **_authority()}


def _attempt(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError) as exc:
        return _blocked(str(exc))


def _num(value, *, positive=False, nonnegative=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or positive and value <= 0 or nonnegative and value < 0):
        raise ValueError("FINITE_NUMERIC_EVIDENCE_REQUIRED")
    return float(value)


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("EXPLICIT_BASIS_OR_SOURCE_REQUIRED")
    return value


def _date(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc)


def _series(rows, entity, as_of, metric=None):
    if not isinstance(rows, list) or not rows:
        raise ValueError("NORMALIZED_HISTORY_MISSING")
    visible = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("OBSERVATION_NOT_OBJECT")
        if type(raw.get("disclosure_time")) is int and raw["disclosure_time"] > as_of:
            continue
        result = validate_pit_replay(raw, issuer_id=entity, replay_at=as_of, mode="AUDIT_REPLAY")
        if result["state"] != "AVAILABLE":
            raise ValueError("PIT_OR_PROVENANCE_NOT_VALIDATED")
        for field in ("basis_ref", "scope_ref", "limitation", "invalidation"):
            _text(raw.get(field))
        if (raw.get("source_class") not in {"OFFICIAL", "SEC", "ISSUER", "VERIFIED_PROCESSED"}
                or raw.get("coverage_state") not in {"COMPLETE", "PARTIAL"}
                or metric is not None and raw.get("metric_id") != metric):
            raise ValueError("SOURCE_COVERAGE_OR_METRIC_NOT_BOUND")
        unit = ("BTC" if metric in (*HOLDING_METRICS, "BTC_CIRCULATING_SUPPLY") else
                "USD" if metric in ("M2", "TGA", "RRP", "BTC_PRICE_USD", "BTC_ETF_NET_FLOW_USD") else None)
        if unit is not None and raw.get("unit") != unit:
            raise ValueError("NORMALIZED_METRIC_UNIT_REQUIRED")
        visible.append(deepcopy(raw))
    if not visible:
        raise ValueError("NO_VISIBLE_OBSERVATIONS")
    visible.sort(key=lambda r: r["effective_time"])
    if len({r["effective_time"] for r in visible}) != len(visible):
        raise ValueError("DUPLICATE_OR_REVISED_OBSERVATIONS_REQUIRE_VINTAGE_SELECTION")
    first = visible[0]
    if any((r["basis_ref"], r["scope_ref"], r["source_semantic"]["identity"], r["source_semantic"]["version"])
           != (first["basis_ref"], first["scope_ref"], first["source_semantic"]["identity"], first["source_semantic"]["version"])
           for r in visible):
        raise ValueError("COMPARABLE_SCOPE_AND_SEMANTIC_REQUIRED")
    return visible


def _scenario(raw, as_of):
    if (not isinstance(raw, dict) or raw.get("scenario_only") is not True
            or type(raw.get("frozen_at")) is not int or not 0 < raw["frozen_at"] <= as_of):
        raise ValueError("FROZEN_LABELED_SCENARIO_REQUIRED")
    for k in ("scenario_id", "source_ref", "limitation", "invalidation"):
        _text(raw.get(k))
    return deepcopy(raw)


def btc_gold_valuation(raw, *, as_of):
    row = _scenario(raw, as_of)
    supply_basis = _text(row.get("btc_supply_basis"))
    supply = _num(row.get("btc_supply_quantity"), positive=True)
    cap = _num(row.get("gold_market_cap_usd"), positive=True) * _num(row.get("btc_gold_ratio"), positive=True)
    price = _num(cap/supply, positive=True)
    return {"state": "AVAILABLE", "scenario": row, "as_of": as_of, "btc_supply_basis": supply_basis,
            "implied_btc_market_cap_usd": cap, "scenario_btc_price_usd": price,
            "limitation": "NO_AVERAGING_WITH_200WMA_OR_FORMAL_PRICE_TARGET", **_authority()}


def liquidity_components(inputs, *, as_of):
    def component(name):
        rows = _series(inputs.get(name), "US", as_of, name)
        if any(r["source_class"] != "OFFICIAL" for r in rows):
            raise ValueError("OFFICIAL_NORMALIZED_MACRO_SOURCE_REQUIRED")
        for row in rows:
            _num(row.get("value"), nonnegative=True)
            if row.get("unit") != "USD":
                raise ValueError("NORMALIZED_USD_UNIT_REQUIRED")
        result = {"state": "AVAILABLE", "observations": rows, "cadence": CADENCE[name],
                  "current": rows[-1], "delta": None, "missing_evidence": [], **_authority()}
        if name in {"M2", "TGA"}:
            if len(rows) < 2:
                result["missing_evidence"].append("PRIOR_COMPARABLE_PERIOD")
            else:
                a, b = rows[-2:]
                if name == "M2":
                    ap = datetime.strptime(a.get("period", ""), "%Y-%m")
                    bp = datetime.strptime(b.get("period", ""), "%Y-%m")
                    consecutive = (bp.year-ap.year)*12+bp.month-ap.month == 1
                else:
                    consecutive = b["effective_time"]-a["effective_time"] == 7*DAY
                if consecutive:
                    result["delta"] = b["value"]-a["value"]
                else:
                    result["missing_evidence"].append("CONSECUTIVE_NATIVE_PERIODS_REQUIRED")
        else:
            calendar = inputs.get("RRP_calendar", {})
            expected = calendar.get("expected_dates")
            if calendar.get("state") != "VALIDATED" or not calendar.get("source_ref") or not isinstance(expected, list) or not expected:
                raise ValueError("RRP_PUBLISHED_BUSINESS_DAY_CALENDAR_REQUIRED")
            dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in expected]
            if len(set(dates)) != len(dates):
                raise ValueError("DUPLICATE_CALENDAR_DATE")
            groups = defaultdict(list)
            by_date = {_date(r["effective_time"]).date(): r for r in rows}
            if len(by_date) != len(rows):
                raise ValueError("DUPLICATE_RRP_DAY")
            for d in dates:
                groups[d-timedelta(days=d.weekday())].append(d)
            weeks = []
            for monday, days in sorted(groups.items()):
                end = datetime.combine(monday+timedelta(days=7), datetime.min.time(), timezone.utc)
                complete = end.timestamp()*1000 <= as_of and all(d in by_date for d in days)
                weeks.append({"week_start": monday.isoformat(), "state": "AVAILABLE" if complete else "BLOCKED",
                              "mean_daily_rrp_usd": sum(by_date[d]["value"] for d in days)/len(days) if complete else None,
                              "expected_dates": [d.isoformat() for d in days],
                              "source_refs": [by_date[d]["source_ref"] for d in days if d in by_date]})
            result.update(weekly=weeks, aggregation="MEAN_DAILY_STOCK_NOT_SUM_OF_STOCKS", calendar=calendar)
        return result
    return {name: _attempt(component, name) for name in ("M2", "TGA", "RRP")}


def liquidity_transmission_replay(inputs, *, as_of):
    metric = inputs.get("metric_id")
    if metric not in {"M2", "TGA", "RRP"}:
        raise ValueError("DECLARED_LIQUIDITY_COMPONENT_REQUIRED")
    liquidity = _series(inputs.get("liquidity"), "US", as_of, metric)
    prices = _series(inputs.get("btc_prices"), "BTC", as_of, "BTC_PRICE_USD")
    by_time = {r["effective_time"]: r for r in prices}
    results = {}
    for horizon in HORIZONS_WEEKS:
        pairs, omitted = [], []
        for previous, current in zip(liquidity, liquidity[1:]):
            # Economic period is not its release clock. Trade/replay origin is
            # the first locally visible instant, never revised history's period.
            origin = current["retrieval_time"]
            if previous["retrieval_time"] >= origin:
                omitted.append({"origin": origin, "reason": "ORIGINAL_VINTAGE_SEQUENCE_REQUIRED"})
                continue
            end = origin+horizon*7*DAY
            start_price, end_price = by_time.get(origin), by_time.get(end)
            if (end > as_of or start_price is None or end_price is None
                    or start_price["retrieval_time"] > origin or end_price["retrieval_time"] > end):
                omitted.append({"origin": origin, "reason": "EXACT_VISIBLE_PRICE_ENDPOINTS_REQUIRED"})
                continue
            change = math.log(_num(current.get("value"), positive=True)) - math.log(_num(previous.get("value"), positive=True))
            future_return = _num(end_price.get("value"), positive=True)/_num(start_price.get("value"), positive=True)-1
            pairs.append({"origin": origin, "end": end, "delta_log_liquidity": change,
                          "future_btc_return": future_return,
                          "source_refs": [r["source_ref"] for r in (previous, current, start_price, end_price)]})
        cohorts = {}
        for label, (first, last) in COHORTS.items():
            sample = [p for p in pairs if first <= _date(p["origin"]).year <= last]
            value, reason = None, "AT_LEAST_THREE_PAIRED_OBSERVATIONS_REQUIRED"
            if len(sample) >= 3:
                x = [p["delta_log_liquidity"] for p in sample]
                y = [p["future_btc_return"] for p in sample]
                mx, my = sum(x)/len(x), sum(y)/len(y)
                denominator = math.sqrt(sum((v-mx)**2 for v in x)*sum((v-my)**2 for v in y))
                if denominator:
                    value, reason = sum((a-mx)*(b-my) for a, b in zip(x, y))/denominator, "DESCRIPTIVE_CORRELATION_ONLY"
                else:
                    reason = "ZERO_SAMPLE_VARIANCE"
            cohorts[label] = {"state": "AVAILABLE" if value is not None else "BLOCKED",
                              "correlation": value, "sample_count": len(sample), "reason": reason}
        results[str(horizon)] = {"cohorts": cohorts, "pairs": pairs, "omitted": omitted}
    return {"state": "AVAILABLE", "as_of": as_of, "metric_id": metric, "horizons_weeks": list(HORIZONS_WEEKS),
            "results": results, "provenance": {"liquidity": liquidity, "btc_prices": prices},
            "limitation": "FIXED_GRID_OVERLAPPING_HORIZONS_NO_CAUSAL_OR_STATISTICAL_SIGNIFICANCE_CLAIM",
            "promotion_state": "NOT_ELIGIBLE_FOR_FORMAL_THRESHOLD", **_authority()}


def institutional_absorption(records, *, as_of, supply=None):
    """Extend External Structural Demand metric IDs, not its warehouse or light."""
    components = {}
    for metric in HOLDING_METRICS:
        def history():
            rows = _series([r for r in records if r.get("metric_id") == metric], "BTC", as_of, metric)
            for r in rows:
                _num(r.get("value"), nonnegative=True)
                scopes = r.get("holding_scope_ids")
                if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or not s for s in scopes) or len(set(scopes)) != len(scopes):
                    raise ValueError("EXPLICIT_NONOVERLAPPING_HOLDER_SCOPE_REQUIRED")
            latest = rows[-1]
            changes = {}
            for days in (7, 30):
                prior = next((r for r in rows if r["effective_time"] == latest["effective_time"]-days*DAY), None)
                comparable = prior is not None and set(prior["holding_scope_ids"]) == set(latest["holding_scope_ids"])
                changes[str(days)+"D"] = {"state": "AVAILABLE" if comparable else "BLOCKED",
                                        "change_btc": latest["value"]-prior["value"] if comparable else None}
            return {"state": "AVAILABLE", "current": latest, "changes": changes, "observations": rows}
        components[metric] = _attempt(history)
    total = _blocked("ALL_THREE_DISJOINT_ALIGNED_TRACKED_SCOPES_REQUIRED")
    if all(r["state"] == "AVAILABLE" for r in components.values()):
        latest = [r["current"] for r in components.values()]
        scope_ids = [s for r in latest for s in r["holding_scope_ids"]]
        if len(set(scope_ids)) == len(scope_ids) and len({r["effective_time"] for r in latest}) == 1:
            total = {"state": "AVAILABLE", "tracked_btc_holdings": sum(r["value"] for r in latest),
                     "as_of": latest[0]["effective_time"], "tracked_scope_ids": scope_ids,
                     "coverage_state": "COMPLETE" if all(r["coverage_state"] == "COMPLETE" for r in latest) else "PARTIAL",
                     "limitation": "DECLARED_TRACKED_UNIVERSE_NOT_GLOBAL_INSTITUTIONAL_TOTAL"}
    share = _blocked("CIRCULATING_SUPPLY_BASIS_REQUIRED")
    if total["state"] == "AVAILABLE" and supply is not None:
        def supply_share():
            row = _series([supply], "BTC", as_of, "BTC_CIRCULATING_SUPPLY")[0]
            if row["effective_time"] != total["as_of"]:
                raise ValueError("SUPPLY_TIME_ALIGNMENT_REQUIRED")
            return {"state": "AVAILABLE", "fraction": total["tracked_btc_holdings"]/_num(row.get("value"), positive=True),
                    "supply_provenance": row}
        share = _attempt(supply_share)
    existing = {}
    for metric in ETF_METRICS[1:]:
        existing[metric] = _attempt(_series, [r for r in records if r.get("metric_id") == metric], "BTC", as_of, metric)
    return {"state": "AVAILABLE" if any(r["state"] == "AVAILABLE" for r in components.values()) else "BLOCKED",
            "components": components, "tracked_total": total, "share_of_circulating_supply": share,
            "existing_flow_and_breadth": existing,
            "contract_ref": "CRT-EXTERNAL-STRUCTURAL-DEMAND-EVIDENCE-V0.1",
            "cadence": {"ETF": CADENCE["ETF"], "HOLDINGS": CADENCE["HOLDINGS"]}, **_authority()}


def etf_stickiness_episode(episode, records, *, as_of):
    """Episode facts, with exact scoped endpoints and separately blocked claims."""
    _text(episode.get("episode_id"))
    _text(episode.get("boundary_source_ref"))
    start, trough, end = [episode.get(k) for k in ("start_time", "trough_time", "end_time")]
    if any(type(t) is not int for t in (start, trough, end)) or not 0 < start < trough <= end <= as_of:
        raise ValueError("VISIBLE_ORDERED_EPISODE_BOUNDARIES_REQUIRED")
    def inventory():
        rows = _series([r for r in records if r.get("metric_id") == ETF_METRICS[0]], "BTC", as_of, ETF_METRICS[0])
        by_time = {r["effective_time"]: r for r in rows}
        selected = [by_time[t] for t in (start, trough, end)]
        if any(set(r.get("holding_scope_ids", [])) != set(selected[0].get("holding_scope_ids", []))
               for r in selected) or not selected[0].get("holding_scope_ids"):
            raise ValueError("EPISODE_HOLDER_SCOPE_CHANGED_OR_UNKNOWN")
        a, b, c = [_num(r.get("value"), positive=True) for r in selected]
        return {"state": "AVAILABLE", "start_btc": a, "trough_btc": b, "end_btc": c,
                "drawdown_inventory_change_fraction": b/a-1, "recovery_inventory_change_fraction": c/b-1,
                "episode_inventory_change_fraction": c/a-1, "provenance": selected}
    def price():
        if episode.get("market_window_lock_state") != "APPROVED" or not episode.get("market_window_lock_ref"):
            raise ValueError("EXISTING_MARKET_SOURCE_WINDOW_APPROVAL_REQUIRED")
        rows = _series(episode.get("btc_prices"), "BTC", as_of, "BTC_PRICE_USD")
        selected = {r["effective_time"]: r for r in rows}
        a, b, c = [_num(selected[t].get("value"), positive=True) for t in (start, trough, end)]
        if b > a:
            raise ValueError("DECLARED_TROUGH_IS_NOT_BELOW_START")
        return {"state": "AVAILABLE", "btc_drawdown_fraction": b/a-1,
                "recovery_return_fraction": c/b-1, "end_vs_start_fraction": c/a-1,
                "provenance": rows, "limitation": "DECLARED_EPISODE_ENDPOINTS_NOT_AUTOMATIC_PEAK_DETECTION"}
    def flows():
        rows = _series([r for r in records if r.get("metric_id") == ETF_METRICS[1]], "BTC", as_of, ETF_METRICS[1])
        expected = episode.get("flow_observation_times")
        if (not isinstance(expected, list) or not expected or expected != sorted(set(expected))
                or any(type(t) is not int or not start < t <= end for t in expected)
                or episode.get("flow_calendar_state") != "VALIDATED" or not episode.get("flow_calendar_ref")):
            raise ValueError("COMPLETE_EPISODE_FLOW_CALENDAR_REQUIRED")
        sample = [r for r in rows if start < r["effective_time"] <= end]
        if [r["effective_time"] for r in sample] != expected or any(r["coverage_state"] != "COMPLETE" for r in sample):
            raise ValueError("EPISODE_FLOW_COVERAGE_INCOMPLETE")
        return {"state": "AVAILABLE", "net_flow_usd": sum(_num(r.get("value")) for r in sample), "provenance": sample}
    def breadth():
        rows = _series([r for r in records if r.get("metric_id") == ETF_METRICS[2]], "BTC", as_of, ETF_METRICS[2])
        sample = [r for r in rows if start < r["effective_time"] <= end]
        if not sample:
            raise ValueError("EPISODE_BREADTH_MISSING")
        for r in sample:
            for field in ("positive_fund_count", "negative_fund_count"):
                if type(r.get(field)) is not int or r[field] < 0:
                    raise ValueError("VERIFIED_FUND_COUNTS_REQUIRED")
        return {"state": "AVAILABLE", "observations": sample,
                "limitation": "OBSERVED_BREADTH_ONLY_NOT_COMPLETE_EPISODE_UNLESS_COVERAGE_PROVEN"}
    return {"state": "AVAILABLE", "episode_id": episode["episode_id"], "boundaries": deepcopy(episode),
            "price": _attempt(price), "inventory": _attempt(inventory), "flow": _attempt(flows),
            "breadth": _attempt(breadth), "cadence": "EVENT_DRIVEN",
            "limitation": "EPISODE_FACTS_NOT_STICKINESS_SCORE_OR_CAUSAL_DEMAND_CONFIRMATION", **_authority()}


def pmi_cycle_maturity(inputs, *, as_of):
    def metric(name):
        rows = _series(inputs.get(name), "US", as_of, name)
        periods = [datetime.strptime(r.get("period", ""), "%Y-%m") for r in rows]
        if any(r["source_class"] != "OFFICIAL" for r in rows):
            raise ValueError("OFFICIAL_NORMALIZED_PMI_SOURCE_REQUIRED")
        if any(not 0 <= _num(r.get("value")) <= 100 for r in rows):
            raise ValueError("PMI_INDEX_RANGE_INVALID")
        values = [r["value"] for r in rows]
        def consecutive(n):
            return len(periods) > n and all((b.year-a.year)*12+b.month-a.month == 1
                                           for a, b in zip(periods[-n-1:], periods[-n:]))
        one = values[-1]-values[-2] if consecutive(1) else None
        three = (values[-1]-values[-4])/3 if consecutive(3) else None
        return {"state": "AVAILABLE", "level": values[-1], "change_1m": one,
                "slope_3m_index_points_per_month": three, "distance_from_declared_sample_high": values[-1]-max(values),
                "rollover_observation": "BLOCKED" if one is None else "FALLING" if one < 0 else "RISING" if one > 0 else "FLAT",
                "missing_evidence": [k for k, v in (("CONSECUTIVE_1M", one), ("CONSECUTIVE_3M", three)) if v is None],
                "sample_period": [rows[0]["period"], rows[-1]["period"]], "provenance": rows}
    return {"state": "AVAILABLE", "metrics": {k: _attempt(metric, k) for k in ("PMI", "PMI_NEW_ORDERS")},
            "cadence": CADENCE["PMI"], "limitation": "CYCLE_MATURITY_EVIDENCE_NOT_PEAK_OR_SELL_TRIGGER", **_authority()}


def historical_gross_multiple_distribution(inputs, *, asset, as_of):
    """Gross BTC-asset ratio = equity price / (BTC price * diluted BTC/share).

    This is explicitly not CRT formal Diluted Equity mNAV. Sample completeness
    and usable-period selection must be evidenced, not inferred from surviving rows.
    """
    if asset not in ISSUERS:
        raise ValueError("SUPPORTED_TREASURY_ASSET_REQUIRED")
    entity = ISSUERS[asset]
    rows = _series(inputs.get("observations"), entity, as_of, "HISTORICAL_GROSS_BTC_ASSET_MULTIPLE")
    definition = _series([inputs.get("sample_definition")], entity, as_of, "GROSS_MULTIPLE_SAMPLE")[0]
    scope = "ALL_AVAILABLE_HISTORY" if asset == "MSTR" else "POST_STRATEGY_POST_MERGER"
    if definition.get("sample_scope") != scope or definition["coverage_state"] != "COMPLETE":
        raise ValueError("COMPLETE_ISSUER_SPECIFIC_SAMPLE_DEFINITION_REQUIRED")
    start, end = definition.get("sample_start"), definition.get("sample_end")
    if type(start) is not int or type(end) is not int or not 0 < start < end <= as_of:
        raise ValueError("VISIBLE_SAMPLE_PERIOD_REQUIRED")
    rows = [r for r in rows if start <= r["effective_time"] <= end]
    expected = definition.get("expected_observation_times")
    if (not isinstance(expected, list) or len(expected) < 2
            or expected != sorted(set(expected)) or [r["effective_time"] for r in rows] != expected):
        raise ValueError("HISTORICAL_DISTRIBUTION_COVERAGE_INCOMPLETE")
    observations = []
    for r in rows:
        if (r.get("market_alignment_state") != "EXACT_CLOSE" or not r.get("market_window_lock_ref")
                or not r.get("share_basis_ref") or r["coverage_state"] != "COMPLETE"):
            raise ValueError("EXACT_CLOSE_AND_DILUTED_SHARE_BASIS_REQUIRED")
        denominator = _num(r.get("btc_price_usd"), positive=True)*_num(r.get("btc_per_diluted_share"), positive=True)
        value = _num(_num(r.get("equity_price_usd"), positive=True)/denominator, positive=True)
        observations.append({"as_of": r["effective_time"], "gross_btc_asset_multiple": value, "provenance": r})
    if len({r["provenance"]["share_basis_ref"] for r in observations}) != 1:
        raise ValueError("COMPARABLE_HISTORICAL_SHARE_BASIS_REQUIRED")

    def distribution(sample):
        if len(sample) < 2:
            raise ValueError("AT_LEAST_TWO_ACTUAL_HISTORICAL_OBSERVATIONS_REQUIRED")
        values = sorted(r["gross_btc_asset_multiple"] for r in sample)
        def percentile(p):
            rank = (len(values)-1)*p
            lo, hi = math.floor(rank), math.ceil(rank)
            return values[lo]+(values[hi]-values[lo])*(rank-lo)
        return {"state": "AVAILABLE", "median": percentile(.5), "P75": percentile(.75), "P90": percentile(.9),
                "sample_count": len(values), "sample_period": [sample[0]["as_of"], sample[-1]["as_of"]],
                "quantile_method": "LINEAR_INTERPOLATION_N_MINUS_ONE", "sample_scope": scope}

    def bull_sample():
        binding = _series([inputs.get("bull_window_binding")], entity, as_of, "BULL_WINDOW_RESEARCH_BINDING")[0]
        a, b = binding.get("window_start"), binding.get("window_end")
        if (type(a) is not int or type(b) is not int or not start <= a < b <= end
                or binding["retrieval_time"] > a or not binding.get("classification_basis_ref")):
            raise ValueError("PIT_FROZEN_BULL_WINDOW_BINDING_REQUIRED")
        return {**distribution([r for r in observations if a <= r["as_of"] <= b]),
                "window_binding": binding, "limitation": "LABELED_RESEARCH_WINDOW_NOT_FORMAL_SEASON"}
    return {"state": "AVAILABLE", "asset": asset, "valuation_lane": "HISTORICAL_GROSS_BTC_ASSET_MULTIPLE",
            "distribution": distribution(observations), "bull_window": _attempt(bull_sample),
            "observations": observations, "sample_definition": definition,
            "confidence": "LOWER_CONFIDENCE_SHORT_ISSUER_HISTORY" if asset == "ASST" else "DESCRIPTIVE_SAMPLE_ONLY",
            "limitation": "GROSS_BTC_ASSETS_EXCLUDE_CASH_SENIOR_CLAIMS_AND_CARRY_NOT_FORMAL_MNAV", **_authority()}


def next_cycle_valuation(inputs, *, asset, treasury_context, as_of):
    if asset not in ISSUERS or not isinstance(treasury_context, dict):
        raise ValueError("EXISTING_TREASURY_VALUATION_CONTEXT_REQUIRED")
    content = {k: v for k, v in treasury_context.items() if k != "context_hash"}
    if _hash(content) != treasury_context.get("context_hash"):
        raise ValueError("EXISTING_TREASURY_CONTEXT_HASH_MISMATCH")
    if treasury_context.get("asset_id") != asset or treasury_context.get("as_of", as_of+1) > as_of:
        raise ValueError("TREASURY_ASSET_OR_AS_OF_MISMATCH")
    current = treasury_context.get("btc_per_diluted_share", {}).get("current")
    if validate_pit_replay(current, issuer_id=ISSUERS[asset], replay_at=as_of, mode="AUDIT_REPLAY")["state"] != "AVAILABLE":
        raise ValueError("CURRENT_VERIFIED_DILUTED_BTC_PER_SHARE_REQUIRED")
    bps = _num(current.get("btc_per_diluted_share"), positive=True)
    distribution = _attempt(historical_gross_multiple_distribution, inputs.get("history", {}), asset=asset, as_of=as_of)
    def envelope(raw):
        row = _scenario(raw, as_of)
        future_btc = _num(row.get("future_btc_price_usd"), positive=True)
        factor = _num(row.get("btc_per_share_factor"), positive=True)
        kind = row.get("multiple_kind")
        if kind == "RESEARCH_SCENARIO_CANDIDATE":
            multiple = _num(row.get("gross_btc_asset_multiple"), positive=True)
            sample_period = None
        elif kind == "HISTORICAL_DISTRIBUTION":
            selected = row.get("distribution", "distribution")
            if selected not in {"distribution", "bull_window"}:
                raise ValueError("EXPLICIT_HISTORICAL_DISTRIBUTION_REQUIRED")
            history = distribution.get(selected, {})
            quantile = row.get("quantile")
            if history.get("state") != "AVAILABLE" or quantile not in {"median", "P75", "P90"}:
                raise ValueError("ACTUAL_HISTORICAL_DISTRIBUTION_REQUIRED_NOT_CANDIDATE_MEDIAN")
            multiple, sample_period = history[quantile], history["sample_period"]
        else:
            raise ValueError("EXPLICIT_GROSS_RESEARCH_MULTIPLE_LANE_REQUIRED")
        future_bps = _num(bps*factor, positive=True)
        value = _num(future_btc*future_bps*multiple, positive=True)
        return {"state": "AVAILABLE", "scenario": row, "current_btc_per_diluted_share": bps,
                "btc_per_share_factor": factor, "future_btc_per_diluted_share": future_bps,
                "future_btc_price_usd": future_btc, "gross_btc_asset_multiple": multiple,
                "scenario_equity_price_usd": value, "multiple_kind": kind, "sample_period": sample_period,
                "source": {"current_btc_per_share": current, "historical_context": distribution.get("sample_definition")},
                "as_of": as_of, "confidence": "LOWER_CONFIDENCE" if asset == "ASST" else "SCENARIO_CONDITIONAL",
                "limitation": "GROSS_ASSET_RESEARCH_ENVELOPE_NOT_EQUITY_FAIR_VALUE_OR_FORMAL_MNAV"}
    scenarios = inputs.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("SCENARIO_ARRAY_REQUIRED")
    envelopes = [_attempt(envelope, r) for r in scenarios]
    return {"state": "AVAILABLE" if any(r["state"] == "AVAILABLE" for r in envelopes) else "BLOCKED",
            "asset": asset, "historical_gross_multiple": distribution, "scenarios": envelopes,
            "formal_diluted_equity_mnav_lane": {"value": treasury_context.get("diluted_mnav"),
                "state": treasury_context.get("formal_action_critical_state"),
                "context_hash": treasury_context["context_hash"], "authority": "EXISTING_TREASURY_VALUATION_CONTEXT"},
            "legacy_multiple_candidates": [1.5, 2.0, 2.5] if asset == "MSTR" else [1.5, 2.32, 3.14],
            "legacy_candidate_label": "RESEARCH_SCENARIO_CANDIDATE_NOT_HISTORICAL_MEDIAN", **_authority()}


def model_dependency_map():
    dependencies = {
        "forward_200wma": ["HISTORICAL_BTC_PRICE", "FUTURE_BTC_PRICE_SCENARIO"],
        "btc_gold": ["GOLD_MARKET_CAP_SCENARIO", "BTC_GOLD_RATIO_SCENARIO", "BTC_SUPPLY_BASIS"],
        "liquidity_transmission": ["LIQUIDITY_VINTAGES", "HISTORICAL_BTC_PRICE"],
        "institutional_absorption": ["ETF_INVENTORY", "OFFICIAL_HOLDER_DISCLOSURES", "BTC_SUPPLY_BASIS"],
        "etf_stickiness": ["ETF_INVENTORY", "ETF_FLOWS", "HISTORICAL_BTC_PRICE"],
        "treasury_convexity": ["HISTORICAL_EQUITY_PRICE", "HISTORICAL_BTC_PRICE"],
        "next_cycle_valuation": ["FUTURE_BTC_PRICE_SCENARIO", "DILUTED_BTC_PER_SHARE", "HISTORICAL_EQUITY_PRICE", "HISTORICAL_BTC_PRICE"],
        "external_price_assumptions": ["LIQUIDITY_NARRATIVE", "INSTITUTIONAL_DEMAND_NARRATIVE", "FUTURE_BTC_PRICE_SCENARIO"],
    }
    return {"dependencies": dependencies, "state": "RESEARCH_ONLY",
            "limitation": "SHARED_INPUTS_AND_NARRATIVES_ARE_NOT_INDEPENDENT_VOTES_NO_PRICE_AVERAGING"}


def build_gold_research_context(inputs: dict, evidence_pack: dict) -> dict:
    """Pure local sidecar; the parent pack and its GPT bridge are not modified."""
    if not isinstance(inputs, dict) or not isinstance(evidence_pack, dict):
        raise ValueError("LOCAL_INPUT_AND_EXISTING_EVIDENCE_PACK_REQUIRED")
    if _hash({k: v for k, v in evidence_pack.items() if k != "evidence_pack_hash"}) != evidence_pack.get("evidence_pack_hash"):
        raise ValueError("PARENT_EVIDENCE_PACK_HASH_MISMATCH")
    as_of = inputs.get("as_of_ms")
    if type(as_of) is not int or as_of <= 0 or evidence_pack.get("generated_at_ms", as_of+1) > as_of:
        raise ValueError("RESEARCH_AS_OF_OR_PARENT_VISIBILITY_INVALID")
    facts = evidence_pack.get("asset_facts", {}).get("items", [])
    if not isinstance(facts, list) or any(not isinstance(r, dict) for r in facts):
        raise ValueError("PARENT_ASSET_FACTS_INVALID")
    demand = [r for r in facts if r.get("metric_id") in set(HOLDING_METRICS) | set(ETF_METRICS)]
    def treasury(asset):
        rows = [r for r in facts if r.get("fact_type") == "TREASURY_VALUATION_CONTEXT" and r.get("asset_id") == asset]
        if len(rows) != 1:
            raise ValueError("UNIQUE_EXISTING_TREASURY_VALUATION_FACT_REQUIRED")
        return next_cycle_valuation(inputs.get("next_cycle", {}).get(asset, {}), asset=asset,
                                    treasury_context=rows[0].get("evidence"), as_of=as_of)
    long_horizon = inputs.get("forward_200wma", {})
    cutoff = _date(as_of).isoformat()
    market = inputs.get("convexity", {})
    result = {"schema_version": "CRT_GOLD_RESEARCH_CONTEXT_V0.1", "storage": "LOCAL_ONLY",
        "as_of_ms": as_of, "parent_evidence_pack_hash": evidence_pack["evidence_pack_hash"],
        "forward_200wma": _attempt(build_forward_200wma_context, long_horizon.get("weekly_bars"),
            as_of=cutoff, provenance=long_horizon.get("provenance"), scenario=long_horizon.get("scenario")),
        "btc_gold": _attempt(btc_gold_valuation, inputs.get("btc_gold"), as_of=as_of),
        "liquidity_components": _attempt(liquidity_components, inputs.get("liquidity", {}), as_of=as_of),
        "liquidity_transmission": _attempt(liquidity_transmission_replay, inputs.get("liquidity_replay", {}), as_of=as_of),
        "institutional_absorption": institutional_absorption(demand, as_of=as_of, supply=inputs.get("btc_circulating_supply")),
        "etf_stickiness": [_attempt(etf_stickiness_episode, e, demand, as_of=as_of) for e in inputs.get("etf_episodes", [])],
        "pmi_cycle_maturity": _attempt(pmi_cycle_maturity, inputs.get("pmi", {}), as_of=as_of),
        "treasury_convexity": _attempt(build_btc_convexity_research,
            equity_bars=market.get("equity_bars", {}), btc_close_marks=market.get("btc_close_marks", []),
            generated_at_ms=as_of, source_window_contract=market.get("source_window_contract")),
        "next_cycle_valuation": {asset: _attempt(treasury, asset) for asset in ISSUERS},
        "model_dependency_map": model_dependency_map(),
        "assumption_watch": evaluate_external_research_assumptions(inputs.get("assumptions"), as_of_ms=as_of),
        "existing_context_refs": {k: _hash(evidence_pack[k]) for k in (
            "layers", "btc_long_horizon_context", "season_transition_warning_overlay", "btc_control_transfer_validation",
            "common_equity_health", "mstr_asst_market_health") if k in evidence_pack},
        "bridge_policy": "LOCAL_ONLY_NO_BRIDGE_BYTES_ADDED", **_authority()}
    result["context_hash"] = _hash(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evidence-pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() in {args.input.resolve(), args.evidence_pack.resolve()}:
        parser.error("research sidecar output must not overwrite its inputs or Evidence Pack")
    result = build_gold_research_context(json.loads(args.input.read_text(encoding="utf-8-sig")),
                                         json.loads(args.evidence_pack.read_text(encoding="utf-8-sig")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
