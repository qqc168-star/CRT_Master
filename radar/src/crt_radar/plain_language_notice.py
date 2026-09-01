from __future__ import annotations

import hashlib
import json
from copy import deepcopy
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
    raw_source_state = "TRANSITION_UNRESOLVED"
    control_transfer_loop_closed = False
    if pack.get("pack_state") == "BLOCKED":
        source_state = "BLOCKED"
        raw_source_state = source_state
        source_reason = "EVIDENCE_PACK_BLOCKED"
    else:
        overlay = pack.get("btc_bull_validation")
        if isinstance(overlay, dict):
            source_state = str(
                overlay.get("state", "TRANSITION_UNRESOLVED")
            )
            raw_source_state = str(
                overlay.get("raw_entry_transition_state", source_state)
            )
            control_transfer_loop_closed = bool(
                overlay.get("control_transfer_loop_closed")
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
                raw_source_state = source_state
                control_validation = entry.get("control_transfer_validation")
                if isinstance(control_validation, dict):
                    control_transfer_loop_closed = bool(
                        control_validation.get("control_transfer_loop_closed")
                    )
                source_reason = str(
                    entry.get("reason", "BTC_ENTRY_GATE_STATE")
                )
            else:
                source_state = "TRANSITION_UNRESOLVED"
                raw_source_state = source_state
                source_reason = "TRANSITION_EVIDENCE_NOT_AVAILABLE"

    if (
        source_state == "BULL_ACCEPTANCE_STRENGTHENED"
        and not control_transfer_loop_closed
    ):
        source_state = "BULL_ACCEPTANCE_DEVELOPING"
        source_reason = (
            "PRESENTATION_DOWNGRADED_UNTIL_CONTROL_TRANSFER_LOOP_CLOSES"
        )

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
            "\u4e0a\u653b\u8b49\u64da\u589e\u5f37\uff0c\u56de\u8e29\u3001\u66f4\u9ad8\u4f4e\u9ede\u8207\u518d\u653b\u5c1a\u672a\u5b8c\u6210\u9a57\u6536",
        ),
        "BULL_ACCEPTANCE_STRENGTHENED": (
            "GREEN",
            "\U0001f7e2",
            "\u7814\u7a76\u50f9\u683c\u7d50\u69cb\u9589\u74b0\u5df2\u9a57\u6536\uff0c\u4ecd\u975e\u6b63\u5f0f\u5b63\u7bc0\u5224\u5b9a",
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
        "schema_version": "CRT_BTC_TRANSITION_PRESENTATION_LIGHT_V0.2",
        "scope": "PRESENTATION_ONLY",
        "color": color,
        "symbol": symbol,
        "state": source_state,
        "raw_source_state": raw_source_state,
        "control_transfer_loop_closed": control_transfer_loop_closed,
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


def _market_health_events(pack: dict[str, Any]) -> list[str]:
    market_health = pack.get("mstr_asst_market_health")
    if not isinstance(market_health, dict):
        return []
    reasons = market_health.get("wake_reasons")
    if not isinstance(reasons, list):
        return []
    return [str(reason) for reason in reasons]


def build_plain_language_notice(pack: dict[str, Any]) -> dict[str, Any]:
    authority = pack.get("authority", {})
    if (
        authority.get("external_action_authority") != "NONE"
        or authority.get("external_action_performed") is not False
    ):
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

    dvol = pack.get("dvol_regime_watch")
    if not isinstance(dvol, dict):
        dvol = {
            "state": "BLOCKED",
            "reason": "DVOL_REGIME_NOT_AVAILABLE",
            "direction": "UNKNOWN",
        }

    requested = wake.get("state") == "REANALYSIS_REQUESTED"
    wake_reason = str(wake.get("reason", ""))
    market_health_events = _market_health_events(pack)
    market_health_requested = (
        requested
        and "MSTR_ASST_MARKET_HEALTH" in wake.get("wake_sources", [])
        and bool(market_health_events)
    )
    commander_observation = (
        requested
        and wake.get("input_family") == "COMMANDER_PLAN_OBSERVATION"
    )
    commander_event = wake.get("commander_event")
    if commander_observation and not isinstance(commander_event, dict):
        raise ValueError("Commander observation wake event is unavailable")
    commander_plan_context = "verified Commander Plan"
    if (
        isinstance(commander_event, dict)
        and commander_event.get("level_price_classification")
        == "SIMULATION_ONLY"
    ):
        commander_plan_context = "sealed simulated Commander Plan"

    dvol_state = str(dvol.get("state", "BLOCKED"))
    compression_alert = dvol_state == "COMPRESSION_EXTREME"

    percent_change = wake.get("percent_change")

    if market_health_requested:
        what_happened = (
            "MSTR／ASST 市場健康度事件已通過唯讀驗證："
            + "、".join(market_health_events)
            + "。這是 GPT 重新分析喚醒，不是使用者通知或交易指令。"
        )
        if commander_observation:
            assert isinstance(commander_event, dict)
            asset = str(commander_event.get("asset", "UNKNOWN_ASSET"))
            line_type = str(commander_event.get("line_type", "UNKNOWN_LINE"))
            event_type = str(commander_event.get("event_type", "UNKNOWN_EVENT"))
            level_price = commander_event.get("level_price")
            observed_price = commander_event.get("observed_price")
            what_happened += (
                f" {asset} {line_type} line also emitted {event_type}; "
                f"observed_price={observed_price}, level_price={level_price}. "
                "This remains an observation only."
            )
    elif commander_observation:
        assert isinstance(commander_event, dict)
        asset = str(commander_event.get("asset", "UNKNOWN_ASSET"))
        line_type = str(commander_event.get("line_type", "UNKNOWN_LINE"))
        event_type = str(commander_event.get("event_type", "UNKNOWN_EVENT"))
        level_price = commander_event.get("level_price")
        observed_price = commander_event.get("observed_price")
        what_happened = (
            f"{asset} {line_type} line emitted {event_type}; "
            f"observed_price={observed_price}, level_price={level_price}. "
            "This is an observation only; price reaching is not an action trigger."
        )
    elif requested and wake_reason == "DVOL_EXPANSION_ACTIVATED":
        current_dvol = dvol.get("current_dvol")
        rebound = dvol.get("rebound_from_30d_low_pct")
        if isinstance(current_dvol, (int, float)) and isinstance(
            rebound,
            (int, float),
        ):
            what_happened = (
                f"BTC DVOL ?????????????"
                f"?? DVOL ? {float(current_dvol):.2f}?"
                f"????????? {float(rebound):.2f}%?"
                "????????????????????????"
            )
        else:
            what_happened = (
                "BTC DVOL ?????????????"
                "????????????????????????"
            )
    elif requested and isinstance(percent_change, (int, float)):
        what_happened = (
            "BTC ??????????????????"
            f"??????? {float(percent_change):+.2f}%?"
        )
    elif requested:
        what_happened = (
            "BTC ??????????????????"
        )
    elif compression_alert:
        current_dvol = dvol.get("current_dvol")
        percentile = dvol.get("level_percentile_1y")
        if isinstance(current_dvol, (int, float)) and isinstance(
            percentile,
            (int, float),
        ):
            what_happened = (
                f"BTC DVOL ? {float(current_dvol):.2f}?"
                f"???????? {float(percentile):.1f} ????"
                "????????????????????"
                "?????????"
            )
        else:
            what_happened = (
                "BTC DVOL ????????"
                "??????????????"
            )
    else:
        what_happened = (
            "?????? BTC ?????????"
        )

    top_changes = _top_change_lines(pack)
    why_parts: list[str] = []

    if commander_observation:
        why_parts.append(
            f"A {commander_plan_context} observation changed state and requires "
            "contextual GPT review; it grants no trading authority."
        )

    if top_changes:
        why_parts.append(
            "??????????" + "?".join(top_changes) + "?"
        )

    if dvol_state in {
        "COMPRESSION_ELEVATED",
        "COMPRESSION_EXTREME",
        "EXPANSION_ACTIVATED",
    }:
        why_parts.append(
            "DVOL ?????????????????"
            "??????????????????"
        )

    why_it_matters = (
        " ".join(why_parts)
        if why_parts
        else "???????????????????"
    )

    blockers = pack.get("data_health", {}).get(
        "critical_blockers",
        [],
    )
    if not isinstance(blockers, list):
        blockers = []

    if market_health_requested:
        title = "MSTR／ASST 市場健康度觸發 GPT 重新分析"
        state = "GPT_REANALYSIS_REQUESTED"
        instruction = (
            "讀取最新 Evidence Pack、Capital State、未完成三段計畫、"
            "MSTR／ASST Market Health 與已核准 Three-Army Commander 線。"
            "依三軍統帥準則重新評估攻擊、第一防線、失效與收割位置；"
            "Wake 不等於 Notification，只有完成多空、BTC 傳導、衍生品、"
            "公司反身性與矛盾證據檢查後，才判斷是否值得通知使用者。"
        )
    elif commander_observation:
        title = "CRT Commander observation requires GPT reanalysis"
        state = "GPT_REANALYSIS_REQUESTED"
        instruction = (
            f"Re-read the latest Evidence Pack and {commander_plan_context} context, "
            "reassess the thesis, and advise the user only. Do not buy, sell, "
            "submit orders, alter positions, or move funds."
        )
    elif requested:
        title = "BTC ????????????"
        state = "GPT_REANALYSIS_REQUESTED"
        instruction = (
            "???????????????????"
            "???????????"
            "DVOL ??????????????????????"
        )
    elif compression_alert:
        title = "BTC ??????????????"
        state = "NO_WAKE"
        instruction = (
            "????????????? DVOL ?????????"
            "????? DVOL ???????????"
        )
    else:
        title = "CRT ?????????????"
        state = "NO_WAKE"
        instruction = (
            "??????????????????"
        )

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "title": title,
        "what_happened": what_happened,
        "why_it_matters": why_it_matters,
        "position_context": _position_line(pack.get("private_context")),
        "data_limits": blockers,
        "dvol_regime_watch": dvol,
        "mstr_asst_market_health": deepcopy(
            pack.get("mstr_asst_market_health")
        ),
        "btc_transition_light": build_btc_transition_light(pack),
        "instruction_for_gpt": instruction,
        "notification_state": "GPT_JUDGMENT_PENDING" if requested else "NO_NOTIFICATION",
        "notification_performed": False,
        "notification_authority": "NONE",
        "source_evidence_pack_hash": pack.get("evidence_pack_hash"),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    result["notice_hash"] = _canonical_hash(result)
    return result
