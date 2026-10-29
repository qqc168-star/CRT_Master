"""Read-only PRE/POST numeric presentation of existing evidence, not a model.

No collection, database write, forecast generation, health score or delivery.
Upstream source qualification is retained; a local hash is not source truth.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

from . import btc_etf_intake
from .btc_tactical_forecast import PRE, POST, _sources, content_hash, read_pre
from .btc_transition_replay_evidence import (
    _visible_completed_weekly_bars, build_long_horizon_50wma_context,
    build_long_horizon_200wma_context,
)
from .diluted_equity_mnav import (
    COMPONENTS, FORMULA, FORMULA_VERSION, SEMANTIC_REF, build_diluted_equity_mnav,
)
from .treasury_company_ct import (
    ISSUERS, _same_valuation_basis, validate_pit_replay, compact_treasury_valuation_context,
)
from .portfolio_allocation_context import build_common_equity_health

SCHEMA = "CRT_DAILY_QUANTITATIVE_REPORT_V0.1"
SECTIONS = ("BTC 市場", "週線／鏈上", "宏觀", "ETF／現貨", "槓桿",
            "Strategy", "MSTR 六維", "Strive ①", "Strive ②", "Strive ③", "Strive ④", "Strive ⑤", "ASST 六維", "結論")
DAY = 86_400_000
COMPARISON_WEEKS = (("quarter", 13), ("month", 4), ("week", 1))


def _number(v):
    return type(v) in (int, float) and math.isfinite(v)


def _iso(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).isoformat()


def _provenance(record):
    return {k: deepcopy(record.get(k)) for k in (
        "asset_id", "issuer_id", "source_id", "source_ref", "source_url", "evidence_hash", "source_evidence",
        "effective_time", "disclosure_time", "first_seen_time", "retrieval_time",
        "observed_at_ms", "available_at_ms", "retrieved_at_ms", "validated_at_ms",
        "quality_state", "basis_ref", "source_semantic", "share_basis", "currency",
        "unit", "source_as_of_date", "source_as_of_precision", "availability_semantics",
        "dilution_scope", "coverage_state", "raw_sha256", "evidence_authority",
        "share_settlement_scope", "economic_qualification", "field_conflicts",
        "initial_preferred_claims_scope", "verification_state", "valid_until_ms", "source_class",
        "period_start_date", "period_end_date", "execution_time", "ct_binding_state",
        "evidence_qualification", "qualification", "limitation")}


def _ct_visible(record, cutoff, *, asset_id, issuer_id):
    return (ISSUERS.get(asset_id) == issuer_id and isinstance(record, dict)
        and record.get("issuer_id") == issuer_id and record.get("asset_id") in (None, asset_id, "BTC")
        and record.get("quality_state") not in {"STALE", "INVALID", "BLOCKED"}
        and ("valid_until_ms" not in record or (type(record["valid_until_ms"]) is int
            and cutoff <= record["valid_until_ms"]))
        and validate_pit_replay(record, issuer_id=issuer_id, replay_at=cutoff,
            mode="AUDIT_REPLAY")["state"] == "AVAILABLE")


def _has_raw_hash(record):
    source=record.get("source_evidence")
    digest=record.get("raw_sha256") or (source.get("raw_sha256") if isinstance(source,dict) else None)
    return isinstance(digest,str) and len(digest)==64 and set(digest)<=set("0123456789abcdef")


def _fact(pack, kind, section=None, *, asset_id, issuer_id):
    if ISSUERS.get(asset_id) != issuer_id:
        raise ValueError("REPORT_ASSET_ISSUER_MISMATCH")
    rows = [r for r in pack.get("asset_facts", {}).get("items", [])
        if r.get("fact_type") == kind and r.get("issuer_id") == issuer_id
        and r.get("asset_id") in (None, asset_id)
        and (section is None or r.get("ct_section") == section)]
    if len(rows) > 1:
        raise ValueError("REPORT_DUPLICATE_ASSET_FACT")
    return rows[0].get("evidence", {}) if rows else {}


def _company_view(pack):
    """Recheck report inputs without changing the sealed pack or the CT model.

    Invalid records stay in the audit copy, not the calculation view. In
    particular, explicit stale evidence is not rescued by a successful PIT check.
    """
    view = deepcopy(pack)
    excluded = []
    items = []
    kinds = {"TREASURY_COMPANY_CT", "TREASURY_VALUATION_CONTEXT", "ISSUER_CT_SOURCE_BINDING"}
    for fact in pack.get("asset_facts", {}).get("items", []):
        if fact.get("fact_type") not in kinds:
            items.append(deepcopy(fact)); continue
        asset = fact.get("asset_id")
        if asset is None:
            asset = next((a for a,i in ISSUERS.items() if i == fact.get("issuer_id")), None)
        issuer = ISSUERS.get(asset)
        nested_asset = (fact.get("evidence") or {}).get("asset_id")
        if not issuer or fact.get("issuer_id") != issuer or nested_asset not in (None,asset):
            excluded.append(dict(asset_id=asset, issuer_id=fact.get("issuer_id"),
                reason="REPORT_COMPANY_FACT_IDENTITY_MISMATCH", fact=deepcopy(fact)))
            continue
        def clean(value):
            if isinstance(value, list):
                return [r for v in value if (r := clean(v)) is not None]
            if not isinstance(value, dict): return deepcopy(value)
            if "source_ref" in value and "issuer_id" in value and not _ct_visible(
                    value, pack["generated_at_ms"], asset_id=asset, issuer_id=issuer):
                excluded.append(dict(asset_id=asset, issuer_id=issuer,
                    reason="REPORT_COMPANY_RECORD_NOT_USABLE", evidence=_provenance(value)))
                return None
            return {k:clean(v) for k,v in value.items()}
        checked = deepcopy(fact)
        # Valuation contexts have an independent content hash. Validate before
        # filtering and leave that immutable receipt intact for its validator.
        if fact["fact_type"] == "TREASURY_VALUATION_CONTEXT":
            material = deepcopy(fact["evidence"]); digest = material.pop("context_hash", None)
            if digest != content_hash(material):
                raise ValueError("REPORT_VALUATION_CONTEXT_HASH_INVALID")
        elif fact["fact_type"] != "ISSUER_CT_SOURCE_BINDING":
            checked["evidence"] = clean(fact.get("evidence", {})) or {}
        items.append(checked)
    view["asset_facts"]["items"] = items
    return view, excluded


def _reference_date(at, days=0):
    d = datetime.fromtimestamp((at-days*DAY)/1000, timezone.utc)
    return d.date().isoformat()


def _exact_reference(rows, current, weeks):
    wanted = _reference_date(current["effective_time"], days=7*weeks)
    found = [r for r in rows if _reference_date(r["effective_time"]) == wanted]
    return found[0] if len(found) == 1 else None


def _weekly_rsi(closes):
    if len(closes) < 15:
        return None
    changes = [b-a for a,b in zip(closes,closes[1:])]
    gain = math.fsum(max(x,0) for x in changes[:14])/14
    loss = math.fsum(max(-x,0) for x in changes[:14])/14
    for change in changes[14:]:
        gain, loss = (13*gain+max(change,0))/14, (13*loss+max(-change,0))/14
    return 100-100/(1+gain/loss) if loss else 100 if gain else 50


def _frozen_forecast(record, original_pre, cutoff, generated):
    if not record:
        return {"state": "NOT_RUN", "reason": "NO_FROZEN_PRE_OR_POST"}
    def check(r):
        if (not isinstance(r, dict) or r.get("kind") not in (PRE, POST)
                or content_hash(r["content"]) != r.get("content_hash")
                or hashlib.sha256(r["content"]["original_text"].encode()).hexdigest()
                    != r["content"].get("original_text_hash")
                or r["recorded_at_ms"] < r["content"]["generated_at_ms"]
                or r["recorded_at_ms"] > generated
                or r["content"]["market_cutoff_ms"] > cutoff):
            raise ValueError("REPORT_FROZEN_FORECAST_INVALID")
        _sources(r["content"]["sources"], r["content"]["market_cutoff_ms"])
    check(record)
    if record["content"]["market_cutoff_ms"] != cutoff:
        raise ValueError("REPORT_FORECAST_CUTOFF_MISMATCH")
    if record["kind"] == POST:
        check(original_pre)
        if (original_pre["kind"] != PRE or record["content"]["pre_id"] != original_pre["content"]["id"]
                or record["content"]["pre_hash"] != original_pre["content_hash"]):
            raise ValueError("REPORT_POST_PRE_LINK_INVALID")
    return {"state": "RESEARCH_ONLY", "record": deepcopy(record),
        "original_pre": deepcopy(original_pre) if record["kind"] == POST else None}


def _company_valuation_rows(pack, context, cutoff, asset_id, add):
    issuer_id = ISSUERS[asset_id]
    section = "Strive ③" if asset_id == "ASST" else "Strategy"
    visible = lambda r: _ct_visible(r, cutoff, asset_id=asset_id, issuer_id=issuer_id)
    organs = {s:_fact(pack, "TREASURY_COMPANY_CT", s, asset_id=asset_id, issuer_id=issuer_id) for s in (
        "per_share_asset_engine", "capital_burden_resilience", "funding_engine", "capital_conversion")}
    binding = _fact(pack, "ISSUER_CT_SOURCE_BINDING", asset_id=asset_id, issuer_id=issuer_id)
    observations = [r for r in binding.get("observations",[]) if visible(r)]
    snapshots = [r for r in observations if r.get("claim") == "REPORTED_CAPITAL_STRUCTURE_SNAPSHOT" and not r.get("field_conflicts")]
    snapshots.sort(key=lambda r:r["effective_time"])
    assets = [r for r in organs["per_share_asset_engine"].get("observations",[]) if visible(r)]
    if not assets:
        assets = [{**r, **r.get("reported_fields",{}), "basis_ref":r.get("share_basis"),
            "btc_per_diluted_share": r["reported_fields"]["btc_holdings"]/r["reported_fields"]["diluted_shares"]}
            for r in snapshots if _number(r.get("reported_fields",{}).get("btc_holdings"))
            and _number(r.get("reported_fields",{}).get("diluted_shares")) and r["reported_fields"]["diluted_shares"]>0]
    current = assets[-1] if assets else {}
    add(section, "BTC / diluted share", current.get("btc_per_diluted_share"), "BTC/share",
        evidence=[current] if current else [], basis="公司截面；不與當日價格時鐘混合")
    for name, weeks in COMPARISON_WEEKS:
        prev = _exact_reference(assets,current,weeks) if current else None
        comparable = bool(prev and prev.get("basis_ref") == current.get("basis_ref") and current.get("basis_ref")
            and "UNRESOLVED" not in current["basis_ref"]
            and prev.get("share_settlement_scope") == current.get("share_settlement_scope")
            and _number(prev.get("btc_per_diluted_share")) and prev["btc_per_diluted_share"]>0)
        add(section, f"BTC/share {name} growth", (current["btc_per_diluted_share"]/prev["btc_per_diluted_share"]-1)*100 if comparable else None,
            "%", evidence=[r for r in (prev,current) if r], basis=f"{weeks}週={weeks*7}日；同稀釋／交割口徑；無插值",
            inputs={"weeks":weeks,"reference_date":_reference_date(current["effective_time"],days=weeks*7) if current else None},
            reason=None if comparable else "EXACT_COMPARABLE_COMPANY_SNAPSHOT_REQUIRED")

    valuation = _fact(pack,"TREASURY_VALUATION_CONTEXT", asset_id=asset_id, issuer_id=issuer_id)
    if valuation:
        copied = deepcopy(valuation); vh=copied.pop("context_hash",None)
        if content_hash(copied) != vh:
            raise ValueError("REPORT_VALUATION_CONTEXT_HASH_INVALID")
    history = [r for r in valuation.get("mnav_observations",[]) if r and visible(r)]
    current_mnav = valuation.get("current_observation") or {}
    if current_mnav and not visible(current_mnav):
        current_mnav = {}
    for name, weeks in COMPARISON_WEEKS:
        prior = _exact_reference(history,current_mnav,weeks) if current_mnav else None
        comparable = bool(prior and _same_valuation_basis(prior,current_mnav))
        add(section, f"historical mNAV {name}", prior["mnav"] if comparable else None, "",
            evidence=[prior] if prior else [], basis=f"{weeks}週={weeks*7}日公司歷史截面原值；不加X、不加%；不以當日價格重估",
            inputs={"weeks":weeks,"reference_date":_reference_date(current_mnav["effective_time"],days=weeks*7) if current_mnav else None},
            reason=None if comparable else "EXACT_COMPARABLE_MNAV_SNAPSHOT_REQUIRED")
    trial = (context.get("mnav_trials", {}).get(asset_id) or (context.get("mnav_trial") if asset_id == "ASST" else None)) or {k:current_mnav.get(k) for k in (
        "input_evidence","share_basis_ref","evidence_alignment_state")}
    trial["input_evidence"] = trial.get("input_evidence") or {}
    values = {k:trial.get("input_evidence",{}).get(k,{}).get("value") for k in COMPONENTS}
    checked = build_diluted_equity_mnav(asset_id=asset_id, **values, input_evidence=trial.get("input_evidence"),
        share_basis_ref=trial.get("share_basis_ref"), semantic_ref=SEMANTIC_REF,
        evidence_alignment_state=trial.get("evidence_alignment_state"), as_of_ms=cutoff)
    trial_sources = list(trial.get("input_evidence",{}).values())
    research = bool(len(trial_sources)==4 and all(_number(v) and v>0 for v in values.values())
        and all(visible(r) for r in trial_sources)
        and set(trial["input_evidence"]) == set(COMPONENTS)
        and all(r.get("asset_id")==("BTC" if k=="btc_price_usd" else asset_id)
            and (not k.endswith("price_usd") or r.get("currency")=="USD")
            and r.get("quality_state") not in {"BLOCKED","INVALID","PARTIAL"}
            and _has_raw_hash(r)
            for k,r in trial.get("input_evidence",{}).items()))
    fresh = all(type(trial.get("input_evidence",{}).get(k,{}).get("valid_until_ms")) is int
        and cutoff < trial["input_evidence"][k]["valid_until_ms"]
        and trial["input_evidence"][k].get("quality_state")!="STALE" for k in ("equity_price_usd","btc_price_usd"))
    if not fresh:
        checked={**checked,"state":"BLOCKED","reason":"REPORT_CURRENT_PRICE_FRESHNESS_UNPROVEN_OR_EXPIRED"}
    formal = compact_treasury_valuation_context(pack).get(asset_id,{}) if valuation else {}
    formal_bound = bool(research and checked["state"]=="AVAILABLE" and formal.get("formal_action_critical_state")=="AVAILABLE"
        and current_mnav.get("input_evidence")==trial["input_evidence"]
        and all(current_mnav.get(k)==values[k] for k in COMPONENTS)
        and all(r.get("quality_state")!="RESEARCH_ONLY" and r.get("source_class")!="RESEARCH_SECONDARY" for r in trial_sources))
    number = checked["mnav"] if research else None
    if number is None and research:
        # Display-only substitution of the SAME formal formula; never emit a
        # receipt or feed the trial back into CT, historical CDF or BUY gates.
        number = values["diluted_shares"]*values["equity_price_usd"]/(values["btc_holdings"]*values["btc_price_usd"])
    substitution = (f"({values['diluted_shares']} * {values['equity_price_usd']}) / ({values['btc_holdings']} * {values['btc_price_usd']})"
        if all(_number(v) for v in values.values()) else "NOT_RUN_MISSING_COMPONENTS")
    add(section, "current diluted mNAV", number, "", evidence=trial_sources,
        state="QUALIFIED" if formal_bound else "RESEARCH_ONLY" if research and fresh else "STALE" if research else "BLOCKED",
        reason=None if formal_bound else "FORMAL_CT_RECEIPT_NOT_BOUND_TO_THIS_TRIAL" if checked["state"]=="AVAILABLE" else checked.get("reason"),
        basis=FORMULA+" = "+substitution, inputs={"formula_version":FORMULA_VERSION, "substitution":substitution,
            "values":values, "formal_validation":checked, "buy_eligible":False})

    return organs, observations, snapshots, current


def _company_health_rows(pack, company_inputs, cutoff, add):
    # Use the existing six dimensions, not report-side health arithmetic.
    calculated = build_common_equity_health(pack)
    companies = {}
    for asset_id, issuer_id in ISSUERS.items():
        organs, observations, snapshots, _ = company_inputs[asset_id]
        row = calculated["assets"][asset_id]
        health = row["company_health"]
        windows = {}
        for name, section in organs.items():
            windows[name] = {label: _provenance(section[label]) if section.get(label) else None
                for label in ("previous", "current")}
        last_reported = max((r["effective_time"] for r in snapshots), default=None)
        compared = (organs["per_share_asset_engine"].get("current") or {}).get("effective_time")
        current_blockers = []
        if compared is None:
            current_blockers.append("QUALIFIED_CURRENT_COMPARISON_MISSING")
        if last_reported is not None and (compared is None or last_reported > compared):
            current_blockers.append("NEWER_REPORTED_SNAPSHOT_NOT_QUALIFIED_FOR_HEALTH_COMPARISON")
        for dimension, value in health["dimensions"].items():
            add(asset_id+" 六維", dimension, value["claims"], "existing claim units",
                evidence=[r for ref in value["supporting_evidence"]
                    for r in health.get("provenance",{}).get(ref,[])],
                state="RESEARCH_ONLY" if value["state"] != "BLOCKED" else "BLOCKED",
                reason=value["reason"], basis=value["claim_scope"]+"；方向="+value["direction"]
                    +"；比較結果不是當期公司放行；反證由分析者提出，不由程式捏造",
                inputs={"dimension":value, "comparison_windows":windows,
                    "current_health_blockers":current_blockers,
                    "counterevidence":health["capital_engine"]["contradictions"],
                    "analyst_counterevidence":"NOT_RUN"})
        add("結論", "company health contradictions", {"dimensions":{k:{f:v.get(f) for f in (
            "direction","reason","interpretation_state","missing_evidence")} for k,v in health["dimensions"].items()},
            "contradictions":health["capital_engine"]["contradictions"],
            "current_health_blockers":current_blockers},
            evidence=[r for records in health.get("provenance",{}).values() for r in records],
            basis=asset_id+"；重用六維；歷史與當期分線；沒有健康總分或自動配置", asset_id=asset_id)
        # The report's conclusion rows need explicit ownership too.
        companies[asset_id] = dict(asset_id=asset_id, issuer_id=issuer_id,
            comparison_windows=windows, latest_reported_effective_time=last_reported,
            current_comparison_effective_time=compared, current_health_blockers=current_blockers,
            current_health_state="BLOCKED" if current_blockers else "RESEARCH_COMPARISON_ONLY",
            health=deepcopy(row))
        if asset_id != "MSTR": continue
        # Strategy has its own capital facts. Never reuse Strive's initial
        # preference coverage or infer missing debt/claims from a BTC total.
        burden = organs["capital_burden_resilience"].get("current") or {}
        for field, unit in (("btc_holdings","BTC"),("diluted_shares","shares"),
                ("debt_principal_usd","USD"),("preferred_liquidation_claims_usd","USD"),
                ("annual_debt_interest_usd","USD/year"),("annual_preferred_distributions_usd","USD/year"),
                ("annual_carry_usd","USD/year"),("usd_cash_usd","USD"),("usd_reserve_usd","USD"),
                ("usable_liquidity_usd","USD"),("carry_coverage_years","years")):
            r = (organs["per_share_asset_engine"].get("current") or {}) if field in {"btc_holdings","diluted_shares"} else burden
            add("Strategy",field,r.get(field),unit,evidence=[r] if r else [],
                basis="MSTR原CT已驗證分項；現金與Reserve分列，未知不反推、不重複相加；靜態覆蓋非生存年限")
        add("Strategy","diluted share change",row.get("diluted_share_change"),"shares",
            evidence=[r for r in (organs["per_share_asset_engine"].get("previous"),
                organs["per_share_asset_engine"].get("current")) if r],
            basis="原CT可比股數差，不是普通股發行數或融資因果")
        funding = organs["funding_engine"]
        add("Strategy","ATM / other financing",funding.get("instruments") or None,"instrument units",
            evidence=funding.get("instruments",[]),basis="既有融資條款／承接／成本；額度不等於募集款")
        add("Strategy","period capital uses / STRC repurchases",organs["capital_conversion"].get("events") or None,
            "event component units",evidence=organs["capital_conversion"].get("events",[]),
            basis="逐事件來源與期間；execution_time可為null；不加總重疊用途，不推算消滅請求權或節省carry")
        binding = _fact(pack,"ISSUER_CT_SOURCE_BINDING",asset_id=asset_id,issuer_id=issuer_id)
        for reported in binding.get("observations",[]):
            if reported.get("claim")=="DATED_ADSO_RESEARCH_OBSERVATION" and reported.get("issuer_id") is None:
                add("Strategy","dated ADSO research (not CT)",
                    {k:reported.get(k) for k in ("previous","current","btc_per_diluted_share_change_pct",
                        "qualification","public_availability_state","dilution_scope_state","limitations")},
                    "source research units",evidence=[reported],state="BLOCKED",
                    reason="DATED_RESEARCH_NOT_CT_BOUND_PUBLIC_DISCLOSURE_UNPROVEN",
                    basis="原MSTR來源綁定內的研究資料，保留數值與原資格；未補issuer、揭露時間或正式稀釋；不進六維計算")
                continue
            if reported.get("issuer_id") != issuer_id: continue
            times=[reported.get(k) for k in ("disclosure_time","first_seen_time","retrieval_time")]
            visible=all(type(t) is int and 0<t<=cutoff for t in times) and times==sorted(times)
            # Period facts deliberately have no execution/effective instant.
            # Keep that existing narrow source qualification, never pass them
            # through the CT action/health calculation lane by inventing one.
            usable=visible and _has_raw_hash(reported) and (reported.get("evidence_qualification")=="VERIFIED_REPORTED_PERIOD_FACT"
                or _ct_visible(reported,cutoff,asset_id=asset_id,issuer_id=issuer_id))
            add("Strategy","source-bound reported fact",reported,"reported units",evidence=[reported],
                state="RESEARCH_ONLY" if usable else "BLOCKED",
                reason=None if usable else "REPORTED_RESEARCH_ONLY_NOT_CT_QUALIFIED",
                basis="保留原公告數字與資格；期間不是執行時點；reported date不是ADSO生效日；不推算索取權或carry")
        fixed=organs["capital_burden_resilience"].get("fixed_obligation_windows",{})
        add("Strategy","declared / confirmed payments",fixed.get("confirmed"),"USD by due date",
            evidence=fixed.get("confirmed") or [],basis="已確認付款，不含未行使權利或未宣告情境")
    return companies


def build_report(pack, *, context=None, forecast=None, original_pre=None, generated_at_ms):
    """Project a sealed pack plus explicitly hash-linked local research inputs.

    context.sources uses the existing PRE source-reference contract. Supplemental
    archives are local inputs, never fetched here and never written into a pack.
    Missing publication clocks remain null with a scope limitation.
    """
    material = deepcopy(pack)
    digest = material.pop("evidence_pack_hash", None)
    if digest != content_hash(material):
        raise ValueError("REPORT_EVIDENCE_PACK_HASH_INVALID")
    cutoff = pack["generated_at_ms"]
    if type(generated_at_ms) is not int or generated_at_ms < cutoff:
        raise ValueError("REPORT_GENERATION_BEFORE_CUTOFF")
    context = deepcopy(context or {})
    if context and context.get("evidence_pack_hash") != digest:
        raise ValueError("REPORT_CONTEXT_PACK_MISMATCH")
    rows = []
    def add(section, metric, value=None, unit="", *, evidence=(), basis="",
            state=None, reason=None, inputs=None, asset_id=None):
        if type(value) is float and not math.isfinite(value):
            value, reason = None, "NONFINITE_RESULT"
        if state is None:
            state = "RESEARCH_ONLY" if value is not None else "BLOCKED"
        if state == "STALE" and reason is None:
            reason = "ARCHIVE_STALE_AT_REPORT_CUTOFF"
        owner = asset_id or ("MSTR" if section in {"Strategy", "MSTR 六維"} else "ASST" if section.startswith("Strive") or section == "ASST 六維" else None)
        rows.append(dict(section=section, asset_id=owner, issuer_id=ISSUERS.get(owner), metric=metric, value=deepcopy(value), unit=unit,
            qualification=state, reason=reason if reason else None if value is not None else "REQUIRED_EVIDENCE_MISSING",
            basis=basis, evidence=[_provenance(r) for r in evidence], inputs=deepcopy(inputs)))

    # Display only values from the sealed pack, qualified by its existing source
    # identity AND the full PRE source clocks. A supplied source label alone is
    # never permission to introduce a new numeric observation.
    sources = context.get("sources") or []
    if sources:
        _sources(sources, cutoff)
    def metric_value(metric):
        candidates = [v for layer in pack.get("layers", {}).values()
            for k,v in layer.get("metrics", {}).items() if k == metric]
        if not candidates:
            candidates = [r for r in pack.get("asset_facts",{}).get("items",[])
                if r.get("fact_type")=="MACRO_REPORTED_LEVEL" and r.get("metric_id")==metric]
        if len(candidates) != 1:
            return None, [], "MISSING_OR_AMBIGUOUS_PACK_METRIC"
        v = candidates[0]
        refs = [s for s in sources if s.get("source_id") == v.get("source_id")
            and s.get("evidence_hash") == v.get("evidence_hash")
            and s.get("observed_at_ms") == v.get("as_of_ms")]
        if (len(refs) != 1 or not str(v.get("quality_state", "")).startswith("VALID")
                or refs[0]["quality_state"] not in {"VALID", "RESEARCH_ONLY"}):
            return None, refs, "PACK_METRIC_SOURCE_CLOCKS_OR_QUALIFICATION_UNPROVEN"
        ref = refs[0]
        if type(ref.get("valid_until_ms")) is not int or cutoff >= ref["valid_until_ms"]:
            return None, refs, "SOURCE_FRESHNESS_UNPROVEN_OR_EXPIRED"
        return v.get("value"), refs, None
    for section, metric, unit, meaning in (
        ("BTC 市場", "btc_spot_price_usd", "USD", "當期來源報價；不是可下單 Bid/Ask"),
        ("週線／鏈上", "mvrv", "", "市值／已實現市值；不等於 MVRV-Z"),
        ("宏觀", "effective_fed_funds_rate_pct", "%", "Fed有效基金利率；不是目標區間"),
        ("宏觀", "effective_fed_funds_change_bp", "bp", "相對上一筆已公布觀測，不假稱每日政策改變"),
        ("宏觀", "nominal_2y_yield_pct", "%", "美國2年期名目殖利率"),
        ("宏觀", "real_10y_yield_pct", "%", "美國10年期實質殖利率；不是名目10Y"),
        ("宏觀", "broad_usd_index", "index", "Nominal Broad US Dollar Index proxy；不是DXY"),
        ("ETF／現貨", "cvd_20d_share", "ratio", "主動成交差占成交額；負值不證明被動承接不存在"),
        ("ETF／現貨", "quote_volume_rvol20", "ratio", "當日成交額／前20個完整日平均成交額"),
        ("槓桿", "open_interest_notional_usd", "USD", "未平倉名目本金；不是新增現金流"),
        ("槓桿", "funding_rate", "rate/period", "每期多空支付率；不擅自年化"),
        ("槓桿", "liquidation_intensity_24h_pct", "%", "來源抽樣強平名目額／OI；非全市場完整成交"),
        ("槓桿", "liquidation_24h_total_usd", "USDT", "BTCUSDT來源觀測名目額；舊欄位名含USD不證明USDT/USD等價"),
    ):
        value, refs, reason = metric_value(metric)
        if metric in {"btc_spot_price_usd","open_interest_notional_usd"} and value is not None:
            currency = refs[0].get("currency")
            if currency not in {"USD","USDT"}:
                value, reason = None, "QUOTE_CURRENCY_UNPROVEN"
            else:
                unit = currency
        add(section, metric, value, unit, evidence=refs, reason=reason, basis=meaning)
    for section, metric, unit, reason in (
        ("週線／鏈上", "MVRV-Z", "", "NO_EXISTING_QUALIFIED_MVRV_Z_INPUT"),
        ("週線／鏈上", "SOPR", "", "NO_EXISTING_QUALIFIED_SOPR_INPUT"),
        ("宏觀", "10Y nominal yield", "%", "NO_EXISTING_QUALIFIED_NOMINAL_10Y_LEVEL"),
        ("宏觀", "DXY", "index", "BROAD_USD_PROXY_IS_NOT_DXY"),
        ("槓桿", "long / short account ratio", "ratio", "NO_EXISTING_QUALIFIED_ACCOUNT_RATIO_INPUT"),
    ):
        add(section, metric, unit=unit, reason=reason)
    # Weekly raw bytes use their acquisition clock, never today's replay clock.
    weekly = context.get("weekly_archive")
    if weekly:
        try:
            ref = weekly["source"]
            _sources([ref], cutoff)
            raw = weekly["raw_json"]
            if not isinstance(raw,str):
                raise ValueError("WEEKLY_RAW_JSON_REQUIRED")
            if hashlib.sha256(raw.encode()).hexdigest() != ref["evidence_hash"]:
                raise ValueError("WEEKLY_RAW_HASH_MISMATCH")
            if ref["quality_state"] not in {"VALID", "RESEARCH_ONLY"}:
                raise ValueError("WEEKLY_SOURCE_NOT_USABLE")
            currency=ref.get("currency")
            if currency not in {"USD","USDT"}:
                raise ValueError("WEEKLY_QUOTE_CURRENCY_REQUIRED")
            bars = json.loads(raw)
            if not isinstance(bars,list) or any(not isinstance(b,dict) for b in bars):
                raise ValueError("WEEKLY_NORMALIZED_BARS_REQUIRED")
            # Reuse the existing normalized weekly-bar contract and loader.
            captured = ref["retrieved_at_ms"]
            for b in bars:
                if b.get("is_complete") and (datetime.fromisoformat(b["week_closed_at"].replace("Z","+00:00")).timestamp()*1000 > captured
                        or datetime.fromisoformat(b["available_at"].replace("Z","+00:00")).timestamp()*1000 > captured):
                    raise ValueError("WEEKLY_COMPLETION_NOT_VISIBLE_AT_ACQUISITION")
            completed = _visible_completed_weekly_bars(bars, as_of=datetime.fromtimestamp(captured/1000,timezone.utc))
            if any((b["week_closed_at_dt"]-a["week_closed_at_dt"]).total_seconds()!=7*DAY/1000
                    for a,b in zip(completed,completed[1:])):
                raise ValueError("COMPLETED_WEEKLY_ARCHIVE_GAP")
            closes = [b["close"] for b in completed]
            latest_ms = int(datetime.fromisoformat(completed[-1]["week_closed_at"].replace("Z","+00:00")).timestamp()*1000)
            stale = cutoff-latest_ms > 7*DAY
            state = "STALE" if stale else "RESEARCH_ONLY"
            def weekly_comparison(name, latest, previous, unit, basis, inputs=None):
                details = dict(inputs or {}, latest_week_closed_at=completed[-1]["week_closed_at"],
                    previous_week_closed_at=completed[-2]["week_closed_at"] if len(completed)>1 else None,
                    previous_value=previous,
                    difference=latest-previous if latest is not None and previous is not None else None)
                for label, value in ((name,latest),(name+" previous completed week",previous),
                        (name+" weekly difference",details["difference"])):
                    add("週線／鏈上", label, value, unit, evidence=[ref], basis=basis,
                        state=state if value is not None else "BLOCKED", inputs=details)
            for n, fn in ((50,build_long_horizon_50wma_context),(200,build_long_horizon_200wma_context)):
                result = fn(bars, as_of=_iso(captured), provenance=ref["source_ref"])
                average = result.get(f"latest_completed_{n}wma")
                prior_bars = [{**{k:b[k] for k in ("week_closed_at","available_at","close")},
                    "is_complete":True} for b in completed[:-1]]
                prior = fn(prior_bars, as_of=_iso(captured), provenance=ref["source_ref"]).get(f"latest_completed_{n}wma")
                weekly_comparison(f"{n}WMA",average,prior,currency,
                    "同一封存完整週收盤算術平均；差額=本週−前週；非完整 KEY_WEEKLY_STRUCTURE",result)
                add("週線／鏈上", f"weekly close / {n}WMA deviation", (closes[-1]/average-1)*100 if average else None,
                    "%", evidence=[ref], basis="相同完整週線截止", state=state if average else "BLOCKED")
            add("週線／鏈上", "weekly close", closes[-1], currency, evidence=[ref], state=state)
            add("週線／鏈上", "weekly change", (closes[-1]/closes[-2]-1)*100 if len(closes)>1 else None,
                "%", evidence=[ref], state=state)
            weekly_comparison("RSI(14)",_weekly_rsi(closes),_weekly_rsi(closes[:-1]),"index points",
                "Wilder週線RSI；最初14筆變化均值初始化；差額為點數，非轉季分類器")
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            add("週線／鏈上", "weekly archive", reason=str(exc))
    else:
        for name in ("RSI(14)", "50WMA", "200WMA", "weekly change", "price deviation",
                "RSI(14) previous completed week", "RSI(14) weekly difference",
                "50WMA previous completed week", "50WMA weekly difference",
                "200WMA previous completed week", "200WMA weekly difference"):
            add("週線／鏈上", name, reason="COMPLETED_WEEKLY_ARCHIVE_NOT_SUPPLIED")

    etf = context.get("btc_etf_archive")
    if etf:
        try:
            if not any(f.get("source_id") == btc_etf_intake.SOURCE and f.get("evidence_hash") == etf.get("evidence_hash")
                    for f in pack.get("asset_facts",{}).get("items",[])):
                raise ValueError("ETF_ARCHIVE_NOT_BOUND_TO_PACK")
            windows = btc_etf_intake.trading_session_windows(etf, as_of_ms=cutoff)
            ref = windows["metadata"]
            for n, window in windows["windows"].items():
                add("ETF／現貨", f"ETF {n} completed sessions", window["value"], "USD", evidence=[ref],
                    basis=window["window_semantics"], state="RESEARCH_ONLY" if window["value"] is not None else "BLOCKED",
                    reason=window["reason"], inputs=window)
        except (ValueError, KeyError, TypeError) as exc:
            add("ETF／現貨", "ETF 5/20/60 sessions", reason=str(exc))
    else:
        for n in (5,20,60):
            add("ETF／現貨", f"ETF {n} completed sessions", unit="USD", reason="TFTC_ARCHIVE_NOT_SUPPLIED")

    # Same report boundary, original sealed pack retained for audit.
    company_pack, excluded_company_evidence = _company_view(pack)
    company_inputs = {}
    for asset_id in ISSUERS:
        company_inputs[asset_id] = _company_valuation_rows(company_pack, context, cutoff, asset_id, add)
    organs, observations, snapshots, current = company_inputs["ASST"]
    visible = lambda r: _ct_visible(r, cutoff, asset_id="ASST", issuer_id=ISSUERS["ASST"])
    burden = organs["capital_burden_resilience"].get("current") or {}
    if not visible(burden): burden={}
    reported = snapshots[-1] if snapshots else {}
    add("Strive ②", "reported cash and cash equivalents", reported.get("reported_fields",{}).get("cash_and_cash_equivalents_usd"),
        "USD", evidence=[reported] if reported else [], basis="來源截面歷史事實；不是目前可部署資本")
    for security in ("SATA","SATS"):
        field=security.lower()+"_shares"
        add("Strive ②",security+" reported outstanding shares",reported.get("reported_fields",{}).get(field),
            "shares",evidence=[reported] if reported else [],
            basis="各證券分列；股數不是已驗證清算索取額、初始優先額或可用現金")
    for field, unit in (("usd_cash_usd","USD"),("usd_reserve_usd","USD"),
                        ("annual_preferred_distributions_usd","USD/year"),("usable_liquidity_usd","USD"),
                        ("carry_coverage_years","years")):
        add("Strive ②", field, burden.get(field), unit, evidence=[burden] if burden else [],
            basis="原CT現金／Reserve用途與非重疊資格；靜態覆蓋不是生存年限")
    fixed = organs["capital_burden_resilience"].get("fixed_obligation_windows",{})
    confirmed = fixed.get("confirmed") if fixed else None
    add("Strive ②", "declared / confirmed payments", [{k:r.get(k) for k in ("payment_reference","due_at_ms","amount_usd","recognition")} for r in confirmed] if confirmed is not None else None,
        "USD by due date", evidence=confirmed or [], basis="已確認付款與未宣告年化條款分開；未知不填零")
    btc_price, btc_refs, _ = metric_value("btc_spot_price_usd")
    # Research asset coverage is NOT formal mNAV or dynamic solvency. Read each
    # component from independently source-bound CT facts; never substitute a
    # dynamic claim balance or silently degrade this metric to BTC-only.
    coverage_components = {}
    coverage_refs = list(btc_refs)
    coverage_sources = {"btc_price_usd":list(btc_refs),"btc_holdings":[current] if current else []}
    coverage_components["btc_price_usd"] = btc_price if btc_refs and btc_refs[0].get("currency")=="USD" else None
    coverage_components["btc_holdings"] = current.get("btc_holdings") if (_has_raw_hash(current)
        and current.get("quality_state") not in {"BLOCKED","STALE","INVALID","PARTIAL"}) else None
    if current: coverage_refs.append(current)
    for component, field in (("cash_usd","cash_and_cash_equivalents_usd"),
            ("strc_market_value_usd","strc_fair_value_usd"),
            ("initial_preferred_claims_usd","initial_preferred_claims_usd")):
        candidates = [r for r in observations if r.get("effective_time")==current.get("effective_time")
            and field in r.get("reported_fields",{}) and not r.get("field_conflicts")
            and _has_raw_hash(r) and r.get("quality_state") not in {"BLOCKED","STALE","INVALID","PARTIAL"}
            and (r.get("initial_preferred_claims_scope")=="COMPLETE_INITIAL_PREFERENCE"
                if component=="initial_preferred_claims_usd"
                else r.get("claim")=="REPORTED_CAPITAL_STRUCTURE_SNAPSHOT")]
        value = candidates[0]["reported_fields"][field] if len(candidates)==1 else None
        coverage_components[component] = value if _number(value) and value>=0 else None
        coverage_sources[component] = candidates
        coverage_refs.extend(candidates)
    btc = coverage_components["btc_holdings"]
    claims = coverage_components["initial_preferred_claims_usd"]
    cash_value = coverage_components["cash_usd"]
    strc_value = coverage_components["strc_market_value_usd"]
    complete = all(_number(v) and v>=0 for v in coverage_components.values()) and claims>0 and btc_price>0
    coverage = (btc_price*btc+cash_value+strc_value)/claims if complete else None
    coverage_basis = "(BTC持有量 × BTC價格 + 合格來源現金總額 + STRC市值) / 初始優先股索取額；Reserve不另加；非動態索取權、正式償付能力或mNAV"
    coverage_inputs = {"components":coverage_components,"reserve_added_usd":0,
        "component_evidence":{k:[_provenance(r) for r in refs] for k,refs in coverage_sources.items()},
        "cash_basis":"REPORTED_CASH_TOTAL_RESERVE_NOT_ADDED",
        "denominator_basis":"INITIAL_PREFERENCE_NOT_DYNAMIC_LIQUIDATION_CLAIMS",
        "missing_components":[k for k,v in coverage_components.items() if v is None],
        "substitution":f"({btc} * {btc_price} + {cash_value} + {strc_value}) / {claims}" if complete else None}
    add("Strive ①", "research asset coverage / initial preferred claims", coverage, "ratio", evidence=coverage_refs,
        basis=coverage_basis+(" = "+coverage_inputs["substitution"] if complete else "；缺項不得改為BTC-only"), inputs=coverage_inputs,
        reason=None if complete else "COMPLETE_SOURCE_BOUND_ASSET_AND_INITIAL_PREFERENCE_INPUTS_REQUIRED")
    add("Strive ①", "dynamic preferred liquidation claims", burden.get("preferred_liquidation_claims_usd"), "USD",
        evidence=[burden] if burden else [], basis="原CT當期動態索取權；不代替研究覆蓋的初始優先額")
    scenarios = context.get("btc_price_scenarios", [])
    if not isinstance(scenarios,list) or any(not isinstance(r,dict) or not _number(r.get("price_usd"))
            or r["price_usd"]<=0 or not isinstance(r.get("assumption_ref"),str) or not r["assumption_ref"].strip() for r in scenarios):
        raise ValueError("EXPLICIT_RESEARCH_PRICE_SCENARIO_REQUIRED")
    add("Strive ①", "BTC pressure comparison", [{**r,"coverage":(r["price_usd"]*btc+cash_value+strc_value)/claims} for r in scenarios]
        if scenarios and coverage is not None else None,
        "scenario", evidence=coverage_refs, inputs=coverage_inputs,
        state="RESEARCH_ONLY" if scenarios and coverage is not None else "BLOCKED" if scenarios else "NOT_RUN",
        reason=None if scenarios and coverage is not None else "QUALIFIED_COVERAGE_INPUTS_REQUIRED" if scenarios else "NO_EXPLICIT_RESEARCH_SCENARIO",
        basis=coverage_basis+"；僅代入明示價格假設，其他資產不變；不自創交易門檻")
    funding = organs["funding_engine"]
    for r in funding.get("reported_financing_facts",[]):
        if not visible(r): continue
        for field in ("commission_cap_pct", "authorized_capacity_usd"):
            if field in r:
                add("Strive ④", field, r[field], "%" if field.endswith("pct") else "USD capacity",
                    evidence=[r], basis="授權／費用上限條款；不是已募集款或實際費用")
        for field,value in r.get("reported_fields",{}).items():
            add("Strive ④", field, value, r.get("unit","USD"), evidence=[r],
                basis=f"{r.get('period_start_date')}~{r.get('period_end_date')}; 累計，不與其內含週期事件相加")
    events=funding.get("preferred_funding_attribution",{}).get("events",[])
    if not events:
        add("Strive ④", "financing net / cost / deployment", reason="QUALIFIED_FINANCING_EVENT_NOT_AVAILABLE")
    for event in events:
        terms=event.get("conditional_terms") or {}
        add("Strive ④", "reported offering stage", {"stage":event["funding_stage"],
            "instrument_id":event.get("instrument_id"), "security_id":event.get("security_id"),
            **{k:terms[k] for k in ("reported_closed_shares","conditional_gross_proceeds_usd","conditional_annual_dividends_usd") if k in terms}},
            "reported / conditional", evidence=[event], basis="條款與發行階段；不是已驗證淨額或當期完整索取權")
        add("Strive ④", "verified net proceeds", event.get("calculation_inputs",{}).get("verified_net_proceeds_usd"), "USD",
            evidence=[event], reason=None if event.get("realized_accounting_state")=="AVAILABLE" else "REALIZED_NET_ACCOUNTING_BLOCKED",
            basis=event["event_id"]+"; 不是毛募集額／ATM授權")
        add("Strive ④", "effective preferred funding cost", event.get("effective_preferred_funding_cost"), "ratio/year",
            evidence=[event], basis="既有年度優先股息／已驗證淨款，不是WACC")
        components=event.get("components",{})
        add("Strive ④", "funding component observations", components if any(v is not None for v in components.values()) else None, "component units",
            evidence=[event], reason=event.get("deployment_attribution_state"),
            basis=event.get("realized_accounting_state", "BLOCKED")+"; 分項事實不等於融資→購幣歸因；legacy不是交割證明，null仍未知")
    add("Strive ④", "market absorption", [r.get("absorption_comparison") for r in funding.get("instruments",[]) if r.get("absorption_comparison")] or None,
        "USD by comparable period", basis="既有公司健康市場承接；不以ATM額度或股價代替")
    add("Strive ⑤", "BTC price / whole-company acquisition cost", reason="MATCHED_TOTAL_ACQUISITION_COST_AND_HOLDINGS_REQUIRED",
        basis="不能以單次購幣成本冒充整體取得成本")
    if forecast and forecast.get("content", {}).get("evidence_pack_hash") not in (None, digest):
        raise ValueError("REPORT_FORECAST_PACK_MISMATCH")
    narrative = _frozen_forecast(forecast,original_pre,cutoff,generated_at_ms)
    text=narrative.get("record",{}).get("content",{})
    summary={k:text[k] for k in ("main_scenario","invalidation_line","strongest_counterevidence","change_conditions","reviews") if k in text}
    add("BTC 市場", "1–3 week scenario / original conditions", summary or None,
        state=narrative["state"], reason=narrative.get("reason"), basis="原文、錨、反證、改判與到期保持凍結；不產生新預測")
    add("結論", "market direction / invalidation / capital posture", summary or None,
        state=narrative["state"], reason=narrative.get("reason"), basis="分析者原判斷；無機器交易資格")
    companies = _company_health_rows(company_pack, company_inputs, cutoff, add)
    result=dict(schema_version=SCHEMA, evidence_pack_hash=digest, market_cutoff_ms=cutoff,
        generated_at_ms=generated_at_ms, context_hash=content_hash(context), rows=rows,
        report_state="PARTIAL_WITH_BLOCKERS" if any(r["qualification"] in {"BLOCKED","STALE","NOT_RUN"} for r in rows) else "RESEARCH_PRESENTATION_READY",
        upstream_pack_state=pack.get("pack_state"),
        companies=companies, excluded_company_evidence=excluded_company_evidence,
        company_source_audit=[deepcopy(f) for f in pack.get("asset_facts",{}).get("items",[])
            if f.get("fact_type") in {"TREASURY_COMPANY_CT","TREASURY_VALUATION_CONTEXT","ISSUER_CT_SOURCE_BINDING"}],
        forecast=narrative, execution_mode="FROZEN_RESEARCH_PRESENTATION" if forecast else "AUDIT_REPLAY_NOT_PROSPECTIVE",
        forecast_access="CALLER_RECORD_HASH_ONLY_NOT_DATABASE_READBACK" if forecast else "NOT_RUN",
        cloud_shared_access="BLOCKED", cloud_two_task_read_write="NOT_RUN", reasoning_state="NOT_YET_PROVEN",
        formal_season=None, action_output="NONE", machine_execution="FORBIDDEN",
        production="NOT_APPROVED", external_action_authority="NONE", capital_decision_authority="USER_ONLY")
    result["report_hash"]=content_hash(result)
    return result


def build_report_from_store(pack, store, *, pre_id, pre_hash, post_id=None, context=None, generated_at_ms):
    """Read back the existing immutable research events; never freeze or write."""
    pre=read_pre(store,pre_id,pre_hash)
    record=store.research_event(post_id,kind=POST) if post_id else pre
    if record is None:
        raise ValueError("REPORT_POST_NOT_FOUND")
    report=build_report(pack,context=context,forecast=record,original_pre=pre if post_id else None,
        generated_at_ms=generated_at_ms)
    report.pop("report_hash")
    report["forecast_access"]="OBSERVATION_STORE_READBACK"
    report["report_hash"]=content_hash(report)
    return report


def render_markdown(report):
    def cell(value):
        return str(value).replace("|","\\|").replace("\n"," ")
    def display(row):
        value=row["value"]
        if row["metric"].startswith("historical mNAV") and _number(value): return f"{value:.3f}"
        if isinstance(value,(dict,list)): return json.dumps(value,ensure_ascii=False,sort_keys=True)
        return "—" if value is None else str(value)
    lines=["# CRT 每日 PRE／POST 量化決策報告", "",
        f"市場截止：{_iso(report['market_cutoff_ms'])}；產生：{_iso(report['generated_at_ms'])}",
        f"報告狀態：{report['report_state']}；本機唯讀投影，非完整投資推理驗收。",
        f"Evidence Pack：`{report['evidence_pack_hash']}`；報告：`{report['report_hash']}`", "",
        "以下為投資人主報告；各項原始來源、時鐘、計算口徑及資格見後方詳細稽核附表。", ""]
    def table(selected):
        notes=[]
        lines.extend(["| 項目 | 數值 | 單位 | 解讀與資格 |", "|---|---|---|---|"])
        for row in selected:
            qualification=row["qualification"]+(":"+row["reason"] if row["reason"] else "")
            shown=display(row)
            if row["metric"]=="company health contradictions" and row["value"]:
                shown=(row.get("asset_id") or "")+"；"+"；".join(f"{k}: {v.get('direction')} / {v.get('reason')}" for k,v in row["value"]["dimensions"].items())
                shown+="；矛盾="+str(row["value"]["contradictions"])
            lines.append("| "+" | ".join(map(cell,(row["metric"],shown,row["unit"],qualification+"；"+row["basis"])))+" |")
            if row["metric"].startswith("ETF ") and row.get("inputs"):
                w=row["inputs"]
                notes.append(f"{row['metric']} 前期：{w.get('previous_value')} USD；變化：{w.get('change_usd')} USD；同範圍基金：{cell(w.get('scope_ids'))}。")
        lines.append("")
        lines.extend(note+"\n" for note in notes)
    def selected(*sections):
        return [r for r in report["rows"] if r["section"] in sections]
    lines.append("## 1. BTC 市場總覽及數值\n")
    table([r for r in selected("BTC 市場","宏觀") if r["metric"]!="1–3 week scenario / original conditions"])
    lines.append("## 2. 1～3 週戰術情境\n")
    table([r for r in report["rows"] if r["metric"]=="1–3 week scenario / original conditions"])
    original=report.get("forecast",{}).get("original_pre")
    if original:
        lines.append("原 PRE 主劇本："+cell(original["content"]["main_scenario"])+"\n")
    lines.append("## 3. 鏈上、RSI、50WMA、200WMA\n")
    table(selected("週線／鏈上"))
    lines.append("## 4. ETF 5／20／60 交易日與現貨需求\n")
    table(selected("ETF／現貨"))
    lines.append("## 5. 槓桿、Funding、強平及逐項解讀\n")
    table(selected("槓桿"))
    lines.append("## 6. 雙公司六維健康與 Strive 五項\n")
    def company_window(asset):
        company=report["companies"][asset]
        window=company["comparison_windows"]["per_share_asset_engine"]
        endpoints=[(window.get(k) or {}).get("effective_time") for k in ("previous","current")]
        shown=" → ".join(_iso(t) if type(t) is int else "UNKNOWN" for t in endpoints)
        lines.append(f"{asset} 已驗證每股比較窗口：{shown}；當期資格：{company['current_health_state']}；"
            +"限制："+cell(company["current_health_blockers"])+"。各維度另保留其原始比較窗口與反證。\n")
    lines.append("### Strategy（MSTR）｜六維健康與獨立資本事實\n")
    company_window("MSTR")
    table(selected("MSTR 六維", "Strategy"))
    lines.append("### Strive（ASST）｜六維健康\n")
    company_window("ASST")
    table(selected("ASST 六維"))
    for section,title in (("Strive ①","資產覆蓋與價格壓力"),("Strive ②","現金、股息與已宣告付款"),
            ("Strive ③","每股BTC與稀釋mNAV"),("Strive ④","融資、成本、市場承接與資本轉換"),
            ("Strive ⑤","BTC市價與整體取得成本")):
        lines.append(f"### {section}｜{title}\n")
        table(selected(section))
    lines.append("## 7. N.S. 市場與公司聯合裁決\n")
    lines.append("聯合裁決：NOT_RUN，須由 N.S. 根據證據形成；程式不捏造因果、方向、配置或交易建議。\n")
    table([r for r in selected("結論") if r["metric"]=="company health contradictions"])
    lines.append("## 8. PRE／POST 驗證與失效條件\n")
    forecast=report.get("forecast",{})
    if forecast.get("record"):
        record=forecast["record"];text=record["content"]
        lines.extend([f"原凍結分析者：{cell(text.get('analyst_ref'))}；存取：{report['forecast_access']}。",
            f"原文：{cell(text['original_text'])}",
            f"紀錄：{cell(text['id'])}；內容雜湊：`{record['content_hash']}`。",
            f"形成：{_iso(text['generated_at_ms'])}；提交：{_iso(record['recorded_at_ms'])}。"])
        for key in ("price_anchor","invalidation_line","strongest_counterevidence","change_conditions","claims","reviews","pre_id","pre_hash"):
            if key in text:
                lines.append(f"{key}：{cell(json.dumps(text[key],ensure_ascii=False,sort_keys=True))}")
        if original:
            lines.append("連結的原 PRE（原文、價格錨、到期與失效條件，未改寫）：")
            for key in ("original_text","price_anchor","claims","invalidation_line","strongest_counterevidence","change_conditions"):
                lines.append(f"{key}：{cell(json.dumps(original['content'][key],ensure_ascii=False,sort_keys=True))}")
    else:
        lines.append("NOT_RUN：沒有本次已凍結 PRE／POST；不產生預測、改判或核驗結論。")
    lines.extend(["", "## 詳細量化證據稽核附表", "",
        "| 區塊 | 指標 | 數值 | 單位 | 資格／限制 | 觀測／公開／首次取得／擷取／驗證 | 依據與來源 |",
        "|---|---|---|---|---|---|---|"])
    for section in SECTIONS:
        for row in (r for r in report["rows"] if r["section"]==section):
            value=display(row)
            if row["metric"].startswith("ETF ") and row.get("inputs",{}):
                funds=row["inputs"].get("by_fund",{})
                value=str(value)+"; "+"; ".join(f"{t}: {v['current_usd']} / 前期 {v['previous_usd']}" for t,v in sorted(funds.items()))
            refs="; ".join(str(r.get("source_ref") or r.get("source_url") or r.get("source_id")) for r in row["evidence"])
            clocks=[]
            for ref in row["evidence"]:
                t=[ref.get(a) or ref.get(b) for a,b in (("effective_time","observed_at_ms"),
                    ("disclosure_time","available_at_ms"),("first_seen_time","first_seen_time"),
                    ("retrieval_time","retrieved_at_ms"),("validated_at_ms","validated_at_ms"))]
                if "NOT_EXACT_PUBLICATION" in (ref.get("availability_semantics") or ""):
                    t[1]=None
                clocks.append(" / ".join(_iso(v) if type(v) is int else "UNKNOWN" for v in t))
                dated=ref.get("source_evidence") or {}
                day=dated.get("effective_date") if dated.get("effective_precision")=="DATE" else ref.get("source_as_of_date")
                if day:
                    clocks[-1]=day+" (DATE) / "+" / ".join(_iso(v) if type(v) is int else "UNKNOWN" for v in t[1:])
                if ref.get("availability_semantics"):
                    clocks[-1]+=" ("+ref["availability_semantics"]+")"
            lines.append("| "+" | ".join(map(cell,(section,row["metric"],value,row["unit"],
                row["qualification"]+(":"+row["reason"] if row["reason"] else ""),"; ".join(clocks),row["basis"]+" "+refs)))+" |")
    lines += ["", "跨雲端雙任務讀寫：BLOCKED／NOT_RUN。正式季節及交易權限沒有提升。", ""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-pack",required=True,type=Path)
    parser.add_argument("--context",type=Path)
    parser.add_argument("--forecast-record",type=Path)
    parser.add_argument("--original-pre",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--generated-at-ms",type=int)
    args=parser.parse_args()
    if args.output.suffix.lower()!=".json":
        raise ValueError("REPORT_JSON_OUTPUT_REQUIRED")
    load=lambda p: json.loads(p.read_text(encoding="utf-8")) if p else None
    report=build_report(load(args.evidence_pack),context=load(args.context),forecast=load(args.forecast_record),
        original_pre=load(args.original_pre),generated_at_ms=args.generated_at_ms or int(time.time()*1000))
    # Explicit new output only; never overwrite a frozen report or any input.
    if args.output.exists() or args.output.with_suffix(".md").exists():
        raise ValueError("REPORT_OUTPUT_EXISTS_NO_OVERWRITE")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    with args.output.with_suffix(".md").open("x",encoding="utf-8") as f: f.write(render_markdown(report))


if __name__ == "__main__":
    main()
