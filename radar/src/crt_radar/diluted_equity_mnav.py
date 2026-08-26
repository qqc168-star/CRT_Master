from __future__ import annotations

import math
from typing import Any

SCHEMA_VERSION = "CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.1"
VALIDATED_ALIGNMENT_STATE = "VALIDATED"


def _is_positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def _blocked(
    *,
    asset_id: str,
    semantic_ref: str | None,
    evidence_alignment_state: str | None,
    diluted_equity_market_cap_usd: float | None,
    asset_nav_usd: float | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_id": asset_id,
        "state": "BLOCKED",
        "mnav": None,
        "semantic_ref": semantic_ref,
        "evidence_alignment_state": evidence_alignment_state,
        "diluted_equity_market_cap_usd": diluted_equity_market_cap_usd,
        "asset_nav_usd": asset_nav_usd,
        "reason": reason,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def build_diluted_equity_mnav(
    *,
    asset_id: str,
    diluted_equity_market_cap_usd: float | None,
    asset_nav_usd: float | None,
    semantic_ref: str | None,
    evidence_alignment_state: str | None,
) -> dict[str, Any]:
    """Calculate only the ratio after upstream evidence and semantics are closed.

    This module deliberately does not define what belongs in ``asset_nav_usd``.
    NAV composition remains owned by the existing formal CRT mNAV semantics.
    """

    normalized_asset = str(asset_id).strip().upper()
    if normalized_asset not in {"MSTR", "ASST"}:
        raise ValueError("diluted equity mNAV is only enabled for MSTR or ASST")

    normalized_semantic = (
        str(semantic_ref).strip() if isinstance(semantic_ref, str) else None
    )
    if not normalized_semantic:
        return _blocked(
            asset_id=normalized_asset,
            semantic_ref=None,
            evidence_alignment_state=evidence_alignment_state,
            diluted_equity_market_cap_usd=diluted_equity_market_cap_usd,
            asset_nav_usd=asset_nav_usd,
            reason="FORMAL_MNAV_SEMANTIC_REF_REQUIRED",
        )

    if evidence_alignment_state != VALIDATED_ALIGNMENT_STATE:
        return _blocked(
            asset_id=normalized_asset,
            semantic_ref=normalized_semantic,
            evidence_alignment_state=evidence_alignment_state,
            diluted_equity_market_cap_usd=diluted_equity_market_cap_usd,
            asset_nav_usd=asset_nav_usd,
            reason="MNAV_EVIDENCE_ALIGNMENT_NOT_VALIDATED",
        )

    if diluted_equity_market_cap_usd is None or asset_nav_usd is None:
        return _blocked(
            asset_id=normalized_asset,
            semantic_ref=normalized_semantic,
            evidence_alignment_state=evidence_alignment_state,
            diluted_equity_market_cap_usd=diluted_equity_market_cap_usd,
            asset_nav_usd=asset_nav_usd,
            reason="MNAV_INPUT_MISSING",
        )

    if not _is_positive_number(diluted_equity_market_cap_usd):
        raise ValueError("diluted_equity_market_cap_usd must be a positive finite number")
    if not _is_positive_number(asset_nav_usd):
        raise ValueError("asset_nav_usd must be a positive finite number")

    market_cap = float(diluted_equity_market_cap_usd)
    nav = float(asset_nav_usd)
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_id": normalized_asset,
        "state": "AVAILABLE",
        "mnav": market_cap / nav,
        "semantic_ref": normalized_semantic,
        "evidence_alignment_state": VALIDATED_ALIGNMENT_STATE,
        "diluted_equity_market_cap_usd": market_cap,
        "asset_nav_usd": nav,
        "reason": "FORMAL_SEMANTICS_AND_EVIDENCE_VALIDATED_UPSTREAM",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }