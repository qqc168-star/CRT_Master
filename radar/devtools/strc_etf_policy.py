from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any


FUNDS = ("PFF", "PFFA", "PFXF")

VALID_IDENTITY_METHODS = {
    "EXACT_TICKER",
    "CUSIP",
    "ISIN",
    "EXACT_SECURITY_DESCRIPTION",
}


@dataclass(frozen=True)
class RadarDecision:
    status: str
    notify: bool
    aggregate_allowed: bool
    reasons: tuple[str, ...]


def load_policy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_policy(policy: dict[str, Any]) -> None:
    schedule = policy["schedule"]

    if schedule["etf_hourly_polling_enabled"] is not False:
        raise ValueError("ETF hourly polling must remain disabled")

    if (
        schedule["strategy_strive_company_event_interval_hours"]
        != 4
    ):
        raise ValueError("Company-event cadence must be four hours")

    if schedule["etf_primary_scan"]["time"] != "08:30":
        raise ValueError("ETF primary scan must be 08:30")

    if schedule["etf_retry_scan"]["time"] != "13:00":
        raise ValueError("ETF retry scan must be 13:00")

    if (
        schedule["etf_retry_scan"]["condition"]
        != "PRIMARY_SCAN_HAS_NO_NEW_USABLE_TRADE_DATE_DATA"
    ):
        raise ValueError("ETF retry must be conditional")

    if policy["external_action_authority"] != "NONE":
        raise ValueError("External action authority must remain NONE")

    if policy["production_approved"] is not False:
        raise ValueError("Candidate policy cannot claim Production approval")


def schedule_action(
    now_taipei: datetime,
    *,
    is_us_trading_day: bool,
    primary_scan_has_new_usable_data: bool,
) -> str:
    if not is_us_trading_day:
        return "SKIP_NON_TRADING_DAY"

    current = now_taipei.time().replace(
        second=0,
        microsecond=0,
    )

    if current == time(8, 30):
        return "RUN_PRIMARY"

    if current == time(13, 0):
        if primary_scan_has_new_usable_data:
            return "SKIP_RETRY_ALREADY_COMPLETE"

        return "RUN_CONDITIONAL_RETRY"

    return "NOT_DUE"


def assess_snapshot(
    snapshot: dict[str, Any],
    *,
    stale_after_us_trading_days: int = 2,
) -> RadarDecision:
    reasons: list[str] = []
    as_of_dates: set[str] = set()

    for fund in FUNDS:
        record = snapshot.get("funds", {}).get(fund)

        if not isinstance(record, dict):
            reasons.append(f"{fund}:MISSING_RECORD")
            continue

        as_of_date = str(record.get("as_of_date", "")).strip()
        usable_sources = int(
            record.get("usable_source_count", 0)
        )
        trading_day_lag = int(
            record.get("trading_day_lag", 0)
        )
        identity_method = str(
            record.get("identity_method", "")
        ).upper()
        same_date_conflict = bool(
            record.get("same_date_source_conflict", False)
        )

        if as_of_date:
            as_of_dates.add(as_of_date)

        if (
            usable_sources == 0
            and trading_day_lag > stale_after_us_trading_days
        ):
            reasons.append(
                f"{fund}:NO_USABLE_DATA_OVER_STALE_WINDOW"
            )

        if identity_method not in VALID_IDENTITY_METHODS:
            reasons.append(
                f"{fund}:AMBIGUOUS_STRC_IDENTITY"
            )

        if same_date_conflict:
            reasons.append(
                f"{fund}:SAME_DATE_SOURCE_CONFLICT"
            )

    aggregate_requested = bool(
        snapshot.get("aggregate_requested", False)
    )

    aggregate_allowed = (
        bool(as_of_dates)
        and len(as_of_dates) == 1
    )

    if aggregate_requested and not aggregate_allowed:
        reasons.append("CROSS_DATE_AGGREGATION_BLOCKED")

    blocked = any(
        reason.endswith("NO_USABLE_DATA_OVER_STALE_WINDOW")
        or reason.endswith("AMBIGUOUS_STRC_IDENTITY")
        or reason.endswith("SAME_DATE_SOURCE_CONFLICT")
        or reason == "CROSS_DATE_AGGREGATION_BLOCKED"
        for reason in reasons
    )

    if blocked:
        return RadarDecision(
            status="BLOCKED_ALERT",
            notify=True,
            aggregate_allowed=False,
            reasons=tuple(reasons),
        )

    material_change = bool(
        snapshot.get("new_material_change", False)
    )

    if material_change:
        return RadarDecision(
            status="MATERIAL_CHANGE",
            notify=True,
            aggregate_allowed=aggregate_allowed,
            reasons=tuple(reasons),
        )

    return RadarDecision(
        status="NO_ALERT",
        notify=False,
        aggregate_allowed=aggregate_allowed,
        reasons=tuple(reasons),
    )
