from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.2"
FORMULA_VERSION = "CRT_DILUTED_MNAV_BTC_MARKET_VALUE_V1"
SEMANTIC_REF = "radar/RELEASE/CRT_DILUTED_MNAV_SEMANTIC_REVISION_20261013.md"
DENOMINATOR_BASIS = "BTC_HOLDINGS_MARKET_VALUE_USD"
FORMULA = "(diluted_shares * equity_price_usd) / (btc_holdings * btc_price_usd)"
VALIDATED_ALIGNMENT_STATE = "VALIDATED"
ISSUERS = {"MSTR": "CIK-0001050446", "ASST": "CIK-0001920406"}
COMPONENTS = ("diluted_shares", "equity_price_usd", "btc_holdings", "btc_price_usd")


def _is_positive_number(value: Any) -> bool:
    try:
        return (type(value) in (int, float) and math.isfinite(float(value))
                and float(value) > 0.0)
    except OverflowError:
        return False


def _finite_copy(value):
    # Invalid source numerics remain unknown in a JSON-safe blocked diagnostic;
    # their immutable original bytes are retained by the source archive.
    if isinstance(value, dict):
        return {k: _finite_copy(v) for k, v in value.items() if isinstance(k, str)}
    if isinstance(value, (list, tuple)):
        return [_finite_copy(v) for v in value]
    if type(value) is float:
        return value if math.isfinite(value) else None
    return value if value is None or type(value) in (str, int, bool) else None


def _component_reason(asset: str, values: dict, evidence: Any,
                      share_basis_ref: Any, as_of_ms: Any) -> str | None:
    if type(as_of_ms) is not int or as_of_ms <= 0:
        return "MNAV_EVALUATION_TIME_REQUIRED"
    if not isinstance(evidence, dict):
        return "MNAV_COMPONENT_EVIDENCE_REQUIRED"
    if not isinstance(share_basis_ref, str) or not share_basis_ref.strip():
        return "MNAV_DILUTION_BASIS_REQUIRED"
    effective = []
    for field, value in values.items():
        row = evidence.get(field)
        if not isinstance(row, dict):
            return "MNAV_COMPONENT_EVIDENCE_REQUIRED"
        if (row.get("verification_state") != "VALIDATED"
                or not isinstance(row.get("source_ref"), str) or not row["source_ref"].strip()):
            return "MNAV_COMPONENT_SOURCE_NOT_VALIDATED"
        if row.get("quality_state") in ("STALE", "BLOCKED", "PARTIAL", "INVALID"):
            return "MNAV_COMPONENT_SOURCE_NOT_QUALIFIED"
        if "valid_until_ms" in row and (type(row["valid_until_ms"]) is not int
                or as_of_ms >= row["valid_until_ms"]):
            return "MNAV_COMPONENT_SOURCE_EXPIRED"
        source_proof = row.get("source_evidence")
        raw_hash = row.get("raw_sha256", source_proof.get("raw_sha256")
                           if isinstance(source_proof, dict) else None)
        if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
            return "MNAV_COMPONENT_RAW_HASH_REQUIRED"
        expected_asset = "BTC" if field == "btc_price_usd" else asset
        if row.get("asset_id") != expected_asset:
            return "MNAV_COMPONENT_ASSET_MISMATCH"
        if field in ("diluted_shares", "btc_holdings") and row.get("issuer_id") != ISSUERS[asset]:
            return "MNAV_COMPONENT_ISSUER_MISMATCH"
        if field in ("equity_price_usd", "btc_price_usd") and row.get("currency") != "USD":
            return "MNAV_PRICE_CURRENCY_NOT_USD"
        if not _is_positive_number(row.get("value")) or not math.isclose(
                float(row["value"]), float(value), rel_tol=1e-12, abs_tol=0):
            return "MNAV_COMPONENT_VALUE_MISMATCH"
        clocks = [row.get(k) for k in ("effective_time", "disclosure_time", "first_seen_time", "retrieval_time")]
        if (any(type(t) is not int or t <= 0 for t in clocks)
                or clocks != sorted(clocks) or clocks[-1] > as_of_ms):
            return "MNAV_COMPONENT_TIME_NOT_QUALIFIED"
        effective.append(clocks[0])
    if len(set(effective)) != 1:
        return "MNAV_COMPONENT_EFFECTIVE_TIME_MISMATCH"
    shares = evidence["diluted_shares"]
    if (shares.get("basis_ref") != share_basis_ref
            or not isinstance(shares.get("dilution_scope"), str) or not shares["dilution_scope"].strip()
            or shares.get("coverage_state") != "COMPLETE"):
        return "MNAV_DILUTION_SCOPE_NOT_QUALIFIED"
    return None


def build_diluted_equity_mnav(
    *, asset_id: str,
    diluted_equity_market_cap_usd: float | None = None,
    asset_nav_usd: float | None = None,
    semantic_ref: str | None = None,
    evidence_alignment_state: str | None = None,
    diluted_shares: float | None = None,
    equity_price_usd: float | None = None,
    btc_holdings: float | None = None,
    btc_price_usd: float | None = None,
    share_basis_ref: str | None = None,
    input_evidence: dict | None = None,
    as_of_ms: int | None = None,
) -> dict[str, Any]:
    """The single formal formula; reported aggregates never define its NAV.

    Consume qualified normalized source facts; raw capture/authority validation
    stays with the existing source pipeline. Hashes are provenance references,
    not evidence that a caller's self-signed source is trustworthy. Original
    dilution scope and each source clock remain available for revalidation.
    """
    asset = str(asset_id).strip().upper()
    if asset not in ISSUERS:
        raise ValueError("diluted mNAV is only enabled for MSTR or ASST")
    values = dict(diluted_shares=diluted_shares, equity_price_usd=equity_price_usd,
                  btc_holdings=btc_holdings, btc_price_usd=btc_price_usd)
    result = dict(schema_version=SCHEMA_VERSION, asset_id=asset, state="BLOCKED", mnav=None,
        semantic_ref=semantic_ref, formula_version=FORMULA_VERSION,
        denominator_basis=DENOMINATOR_BASIS, formula=FORMULA,
        evidence_alignment_state=evidence_alignment_state, **values,
        share_basis_ref=share_basis_ref, input_evidence=deepcopy(input_evidence), as_of_ms=as_of_ms,
        effective_time=None, diluted_equity_market_cap_usd=None,
        btc_market_value_usd=None, asset_nav_usd=None,
        action_output="NONE", external_action_authority="NONE", external_action_performed=False)

    def blocked(reason):
        result["reason"] = reason
        return _finite_copy(result)

    if not isinstance(semantic_ref, str) or not semantic_ref.strip():
        return blocked("FORMAL_MNAV_SEMANTIC_REF_REQUIRED")
    if semantic_ref != SEMANTIC_REF:
        return blocked("FORMAL_MNAV_SEMANTIC_VERSION_MISMATCH")
    if evidence_alignment_state != VALIDATED_ALIGNMENT_STATE:
        return blocked("MNAV_EVIDENCE_ALIGNMENT_NOT_VALIDATED")
    if any(v is None for v in values.values()):
        return blocked("MNAV_COMPONENT_INPUT_MISSING")
    if any(not _is_positive_number(v) for v in values.values()):
        return blocked("MNAV_COMPONENT_INPUT_INVALID")
    reason = _component_reason(asset, values, input_evidence, share_basis_ref, as_of_ms)
    if reason:
        return blocked(reason)
    cap = float(diluted_shares) * float(equity_price_usd)
    btc_value = float(btc_holdings) * float(btc_price_usd)
    if not _is_positive_number(cap) or not _is_positive_number(btc_value):
        return blocked("MNAV_PRODUCT_NONFINITE")
    # Backward field names are checked aliases, never alternative formulas.
    for supplied, computed in ((diluted_equity_market_cap_usd, cap), (asset_nav_usd, btc_value)):
        if supplied is not None and (not _is_positive_number(supplied)
                or not math.isclose(float(supplied), computed, rel_tol=1e-12, abs_tol=0)):
            return blocked("MNAV_REPORTED_AGGREGATE_MISMATCH")
    ratio = cap / btc_value
    if not _is_positive_number(ratio):
        return blocked("MNAV_RESULT_NONFINITE")
    result.update(state="AVAILABLE", mnav=ratio, diluted_equity_market_cap_usd=cap,
        btc_market_value_usd=btc_value, asset_nav_usd=btc_value,
        effective_time=input_evidence["diluted_shares"]["effective_time"],
        reason="QUALIFIED_DILUTED_MARKET_CAP_OVER_BTC_MARKET_VALUE")
    return result


def validate_diluted_mnav_evidence(raw: Any, *, as_of_ms: int, asset_id: str | None = None) -> dict:
    """Independently rederive an existing receipt; a version label is not proof."""
    fields = {k: raw.get(k) for k in COMPONENTS} if isinstance(raw, dict) else {}
    invalid = dict(state="BLOCKED", mnav=None, reason="FORMAL_MNAV_EVIDENCE_NOT_VALIDATED")
    if (not isinstance(raw, dict) or raw.get("asset_id") not in tuple(ISSUERS)
            or (asset_id is not None and raw["asset_id"] != asset_id)
            or raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("formula_version") != FORMULA_VERSION
            or raw.get("denominator_basis") != DENOMINATOR_BASIS
            or raw.get("state") != "AVAILABLE" or raw.get("action_output") != "NONE"
            or raw.get("external_action_authority") != "NONE"
            or raw.get("external_action_performed") is not False):
        return invalid
    result = build_diluted_equity_mnav(asset_id=raw["asset_id"], **fields,
        semantic_ref=raw.get("semantic_ref"), evidence_alignment_state=raw.get("evidence_alignment_state"),
        diluted_equity_market_cap_usd=raw.get("diluted_equity_market_cap_usd"),
        asset_nav_usd=raw.get("asset_nav_usd"), share_basis_ref=raw.get("share_basis_ref"),
        input_evidence=raw.get("input_evidence"), as_of_ms=as_of_ms)
    if result["state"] != "AVAILABLE":
        return result
    if (not _is_positive_number(raw.get("mnav"))
            or not _is_positive_number(raw.get("btc_market_value_usd"))
            or not math.isclose(float(raw["mnav"]), result["mnav"], rel_tol=1e-12, abs_tol=0)
            or not math.isclose(float(raw["btc_market_value_usd"]), result["btc_market_value_usd"], rel_tol=1e-12, abs_tol=0)
            or raw.get("effective_time") != result["effective_time"]):
        return {**invalid, "reason": "MNAV_UPSTREAM_RESULT_MISMATCH"}
    return result


def validate_compact_mnav_evidence(row: Any, *, asset_id: str, as_of_ms: int) -> dict:
    """Recheck the existing compact valuation projection, not its state label."""
    invalid = dict(state="BLOCKED", mnav=None, reason="FORMAL_MNAV_EVIDENCE_NOT_VALIDATED")
    if not isinstance(row, dict):
        return invalid
    semantic = row.get("source_semantic")
    identity = semantic.get("identity") if isinstance(semantic, dict) else semantic
    if (identity != "CRT_FORMAL_DILUTED_EQUITY_MNAV"
            or row.get("evidence_authority") != "FORMAL_ACTION_CRITICAL"
            or row.get("formal_action_critical_state") != "AVAILABLE"):
        return invalid
    inputs = row.get("mnav_calculation_inputs")
    if not isinstance(inputs, dict):
        return invalid
    # These fixed read-only flags describe the projection interface, not an
    # invented market fact. All economic components and clocks stay literal.
    receipt = dict(asset_id=asset_id, schema_version=row.get("mnav_schema_version"),
        formula_version=row.get("formula_version"), denominator_basis=row.get("denominator_basis"),
        semantic_ref=row.get("semantic_ref"), evidence_alignment_state=row.get("mnav_evidence_alignment_state"),
        state="AVAILABLE", action_output="NONE", external_action_authority="NONE",
        external_action_performed=False, mnav=row.get("diluted_mnav"),
        share_basis_ref=row.get("share_basis_ref"), input_evidence=row.get("mnav_input_evidence"),
        effective_time=row.get("mnav_as_of"),
        **{key: inputs.get(key) for key in (*COMPONENTS, "diluted_equity_market_cap_usd", "btc_market_value_usd")},
        asset_nav_usd=inputs.get("btc_market_value_usd"))
    return validate_diluted_mnav_evidence(receipt, as_of_ms=as_of_ms, asset_id=asset_id)
