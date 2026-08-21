from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA_VERSION = "CRT_CODEX_NOTICE_V1"


METRIC_LABELS = {
    "btc_spot_price_usd": "BTC \u73fe\u8ca8\u50f9\u683c",
    "funding_rate": "\u6c38\u7e8c\u5408\u7d04\u8cc7\u91d1\u8cbb\u7387",
    "open_interest_contracts": "\u672a\u5e73\u5009\u5408\u7d04",
    "broad_usd_20d_log_change": "\u5ee3\u7fa9\u7f8e\u5143\u4e8c\u5341\u65e5\u8b8a\u5316",
    "stablecoin_supply_30d_log_change": "\u6838\u5fc3\u7a69\u5b9a\u5e63\u4e09\u5341\u65e5\u4f9b\u7d66\u8b8a\u5316",
    "mvrv": "MVRV \u5e02\u503c\u5be6\u73fe\u50f9\u503c\u6bd4",
}


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()



def build_btc_transition_light(pack: dict[str, Any]) -> dict[str, Any]:
    if pack.get("pack_state") == "BLOCKED":
        source_state = "BLOCKED"
        source_reason = "EVIDENCE_PACK_BLOCKED"
    else:
        overlay = pack.get("btc_bull_validation")
        if isinstance(overlay, dict):
            source_state = str(
                overlay.get("state", "TRANSITION_UNRESOLVED")
            )
            source_reason = str(
                overlay.get("reason", "OVERLAY_STATE")
            )
        else:
            entry = pack.get("btc_entry_gate")
            if isinstance(entry, dict):
                if entry.get("state") == "BLOCKED":
                    source_state = "BLOCKED"
                else:
                    source_state = str(
                        entry.get(
                            "transition_state",
                            "TRANSITION_UNRESOLVED",
                        )
                    )
                source_reason = str(
                    entry.get("reason", "BTC_ENTRY_GATE_STATE")
                )
            else:
                source_state = "TRANSITION_UNRESOLVED"
                source_reason = "TRANSITION_EVIDENCE_NOT_AVAILABLE"

    mapping = {
        "BLOCKED": (
            "GRAY",
            "\u26aa",
            "\u8cc7\u6599\u4e0d\u8db3\uff0c\u4e0d\u80fd\u53ef\u9760\u5224\u8b80",
        ),
        "BEAR_REJECTION_STRENGTHENED": (
            "RED",
            "\U0001f534",
            "\u504f\u718a\u62d2\u7d55\u8b49\u64da\u660e\u986f\u589e\u5f37",
        ),
        "BEAR_REJECTION_PLAUSIBLE": (
            "YELLOW",
            "\U0001f7e1",
            "\u51fa\u73fe\u504f\u718a\u8b66\u8a0a\uff0c\u4f46\u6a5f\u5236\u4ecd\u672a\u5b8c\u6574",
        ),
        "TRANSITION_UNRESOLVED": (
            "YELLOW",
            "\U0001f7e1",
            "\u718a\u725b\u8f49\u63db\u4ecd\u672a\u89e3\u6c7a",
        ),
        "BULL_ACCEPTANCE_DEVELOPING": (
            "YELLOW",
            "\U0001f7e1",
            "\u8f49\u725b\u63a5\u53d7\u5ea6\u8b49\u64da\u6b63\u5728\u767c\u5c55",
        ),
        "BULL_ACCEPTANCE_STRENGTHENED": (
            "GREEN",
            "\U0001f7e2",
            "\u8f49\u725b\u63a5\u53d7\u5ea6\u8b49\u64da\u660e\u986f\u589e\u5f37",
        ),
    }

    color, symbol, meaning = mapping.get(
        source_state,
        (
            "GRAY",
            "\u26aa",
            "\u72c0\u614b\u7121\u6cd5\u53ef\u9760\u8f49\u8b6f",
        ),
    )

    return {
        "schema_version": "CRT_BTC_TRANSITION_PRESENTATION_LIGHT_V0.1",
        "scope": "PRESENTATION_ONLY",
        "color": color,
        "symbol": symbol,
        "state": source_state,
        "meaning": meaning,
        "source_reason": source_reason,
        "formal_model_authority": "NONE",
        "formal_threshold_authority": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }


def _top_change_lines(pack: dict[str, Any], limit: int = 3) -> list[str]:
    rows = pack.get("distillation", {}).get("top_changes", [])
    result: list[str] = []
    for row in rows[:limit] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        metric = str(row.get("metric"))
        label = METRIC_LABELS.get(metric, metric)
        direction = "\u4e0a\u5347" if row.get("direction") == "UP" else "\u4e0b\u964d"
        percent = row.get("percent_change")
        if isinstance(percent, (int, float)):
            result.append(f"{label}{direction} {abs(float(percent)):.2f}%")
        else:
            result.append(f"{label}{direction}")
    return result

def _position_line(private_context: dict[str, Any] | None) -> str:
    if not isinstance(private_context, dict) or private_context.get("state") != "AVAILABLE":
        return "\u672c\u6a5f\u79c1\u4eba\u6301\u5009\u8a2d\u5b9a\u5c1a\u4e0d\u53ef\u7528\uff0c\u672c\u6b21\u4e0d\u505a\u500b\u4eba\u6301\u5009\u5c0d\u7167\u3002"
    profile = private_context.get("profile", {})
    strc = profile.get("strc", {})
    derived = profile.get("derived", {})
    shares = strc.get("shares")
    rate = strc.get("current_annual_distribution_rate")
    six_month_cash = derived.get("six_month_cash_usd")
    minimum = derived.get("minimum_shares_for_target")
    return (
        f"\u672c\u6a5f\u8a2d\u5b9a\u70ba STRC {shares} \u80a1\u3001\u76ee\u524d\u52d5\u614b\u914d\u606f\u7387 {float(rate) * 100:.2f}%\uff1b"
        f"\u4f30\u7b97\u672a\u6263\u7a05\u534a\u5e74\u73fe\u91d1\u70ba ${float(six_month_cash):,.2f}\uff0c\u76ee\u6a19\u6240\u9700\u81f3\u5c11 {minimum} \u80a1\u3002"
    )


def build_plain_language_notice(pack: dict[str, Any]) -> dict[str, Any]:
    authority = pack.get("authority", {})
    if authority.get("external_action_authority") != "NONE" or authority.get("external_action_performed") is not False:
        raise ValueError("evidence pack external action boundary is invalid")
    wake = pack.get("reanalysis_wake")
    if not isinstance(wake, dict):
        wake = {
            "state": "NO_WAKE",
            "reason": "WAKE_NOT_EVALUATED",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
    requested = wake.get("state") == "REANALYSIS_REQUESTED"
    percent_change = wake.get("percent_change")
    if requested and isinstance(percent_change, (int, float)):
        what_happened = f"BTC \u51fa\u73fe\u76f8\u5c0d\u6b77\u53f2\u6ce2\u52d5\u5c6c\u65bc\u91cd\u5927\u7b49\u7d1a\u7684\u8b8a\u5316\uff0c\u6700\u65b0\u4e00\u6bb5\u8b8a\u5316\u7d04 {float(percent_change):+.2f}%\u3002"
    elif requested:
        what_happened = "BTC \u51fa\u73fe\u76f8\u5c0d\u6b77\u53f2\u6ce2\u52d5\u5c6c\u65bc\u91cd\u5927\u7b49\u7d1a\u7684\u8b8a\u5316\u3002"
    else:
        what_happened = "\u76ee\u524d\u6c92\u6709\u89f8\u767c BTC \u91cd\u5927\u7570\u52d5\u91cd\u65b0\u5224\u8b80\u3002"

    top_changes = _top_change_lines(pack)
    why_it_matters = (
        "\u540c\u6642\u503c\u5f97\u6ce8\u610f\u7684\u8b49\u64da\uff1a" + "\uff1b".join(top_changes) + "\u3002"
        if top_changes
        else "\u76ee\u524d\u6c92\u6709\u5176\u4ed6\u8db3\u4ee5\u5217\u5165\u91cd\u9ede\u7684\u53ef\u6bd4\u8f03\u8b8a\u5316\u3002"
    )
    blockers = pack.get("data_health", {}).get("critical_blockers", [])
    if not isinstance(blockers, list):
        blockers = []
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": "GPT_REANALYSIS_REQUESTED" if requested else "NO_WAKE",
        "title": "BTC \u6709\u91cd\u5927\u7570\u52d5\uff0c\u9700\u8981\u91cd\u65b0\u5224\u8b80" if requested else "CRT \u96f7\u9054\u6b63\u5e38\u503c\u73ed\uff0c\u6c92\u6709\u91cd\u5927\u7570\u52d5",
        "what_happened": what_happened,
        "why_it_matters": why_it_matters,
        "position_context": _position_line(pack.get("private_context")),
        "data_limits": blockers,
        "btc_transition_light": build_btc_transition_light(pack),
        "instruction_for_gpt": (
            "\u8acb\u7528\u7e41\u9ad4\u4e2d\u6587\u89e3\u91cb\u767c\u751f\u4ec0\u9ebc\u3001\u70ba\u4ec0\u9ebc\u91cd\u8981\u3001\u76ee\u524d\u6301\u5009\u662f\u5426\u9700\u8981\u91cd\u770b\uff1b\u4e0d\u5f97\u4ee3\u66ff\u4f7f\u7528\u8005\u4e0b\u55ae\u3002"
            if requested
            else "\u7121\u9808\u4e3b\u52d5\u63d0\u51fa\u4ea4\u6613\u5efa\u8b70\uff1b\u7dad\u6301\u96f7\u9054\u503c\u73ed\u3002"
        ),
        "source_evidence_pack_hash": pack.get("evidence_pack_hash"),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    result["notice_hash"] = _canonical_hash(result)
    return result
