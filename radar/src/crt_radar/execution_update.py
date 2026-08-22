from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .private_profile import (
    PrivateProfileError,
    default_private_profile_path,
    validate_private_profile,
)


EXECUTION_UPDATE_SCHEMA_VERSION = "CRT_EXECUTION_UPDATE_V0.1"
EXECUTION_CONFIRMATION = "USER_CONFIRMED"
EXECUTABLE_SIDES = {"BUY", "SELL"}


class ExecutionUpdateError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionUpdateError(
            f"{field} must be a non-empty string"
        )
    return value.strip()


def _number(
    value: Any,
    field: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if value is None or isinstance(value, bool):
        raise ExecutionUpdateError(
            f"{field} missing or invalid"
        )

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionUpdateError(
            f"{field} must be numeric"
        ) from exc

    if not math.isfinite(number):
        raise ExecutionUpdateError(
            f"{field} must be finite"
        )

    if positive and number <= 0:
        raise ExecutionUpdateError(
            f"{field} must be positive"
        )

    if nonnegative and number < 0:
        raise ExecutionUpdateError(
            f"{field} must be nonnegative"
        )

    return number


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    candidate = (
        text[:-1] + "+00:00"
        if text.endswith("Z")
        else text
    )

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ExecutionUpdateError(
            f"{field} must be ISO-8601"
        ) from exc

    if parsed.tzinfo is None:
        raise ExecutionUpdateError(
            f"{field} must include timezone"
        )

    return text


def _asset(value: Any, field: str) -> str:
    symbol = _text(value, field).upper()

    if any(char.isspace() for char in symbol):
        raise ExecutionUpdateError(
            f"{field} must not contain whitespace"
        )

    return symbol


def _same_number(left: float, right: float) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def validate_execution_update(
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExecutionUpdateError(
            "execution update must be an object"
        )

    if (
        payload.get("schema_version")
        != EXECUTION_UPDATE_SCHEMA_VERSION
    ):
        raise ExecutionUpdateError(
            "execution update schema_version invalid"
        )

    if payload.get("confirmation") != EXECUTION_CONFIRMATION:
        raise ExecutionUpdateError(
            "execution update requires USER_CONFIRMED"
        )

    if payload.get("cash_exact_confirmed") is not True:
        raise ExecutionUpdateError(
            "exact post-execution cash confirmation required"
        )

    side = _text(
        payload.get("side"),
        "side",
    ).upper()

    if side not in EXECUTABLE_SIDES:
        raise ExecutionUpdateError(
            "side must be BUY or SELL"
        )

    normalized = json.loads(json.dumps(payload))

    normalized["execution_id"] = _text(
        payload.get("execution_id"),
        "execution_id",
    )
    normalized["executed_at"] = _timestamp(
        payload.get("executed_at"),
        "executed_at",
    )
    normalized["plan_id"] = _text(
        payload.get("plan_id"),
        "plan_id",
    )
    normalized["tranche_id"] = _text(
        payload.get("tranche_id"),
        "tranche_id",
    )
    normalized["asset"] = _asset(
        payload.get("asset"),
        "asset",
    )
    normalized["side"] = side

    normalized["executed_quantity"] = _number(
        payload.get("executed_quantity"),
        "executed_quantity",
        positive=True,
    )
    normalized["execution_price_usd"] = _number(
        payload.get("execution_price_usd"),
        "execution_price_usd",
        positive=True,
    )

    for field in (
        "expected_holding_quantity_before",
        "holding_quantity_after",
        "expected_available_cash_usd_before",
        "available_cash_usd_after",
        "expected_reserved_cash_usd_before",
        "reserved_cash_usd_after",
    ):
        normalized[field] = _number(
            payload.get(field),
            field,
            nonnegative=True,
        )

    normalized["cash_exact_confirmed"] = True
    normalized["confirmation"] = EXECUTION_CONFIRMATION

    return normalized


def apply_user_confirmed_execution(
    profile: dict[str, Any],
    update_payload: dict[str, Any],
) -> dict[str, Any]:
    current = validate_private_profile(profile)
    update = validate_execution_update(update_payload)

    if current.get("external_action_authority") != "NONE":
        raise ExecutionUpdateError(
            "external_action_authority must remain NONE"
        )

    if current.get("action_output") != "NONE":
        raise ExecutionUpdateError(
            "action_output must remain NONE"
        )

    for existing_plan in current.get("plans", []):
        for existing_tranche in existing_plan.get(
            "tranches",
            [],
        ):
            execution = existing_tranche.get("execution")

            if (
                isinstance(execution, dict)
                and execution.get("execution_id")
                == update["execution_id"]
            ):
                raise ExecutionUpdateError(
                    "execution_id already applied"
                )

    matching_plans = [
        plan
        for plan in current.get("plans", [])
        if plan.get("plan_id") == update["plan_id"]
    ]

    if len(matching_plans) != 1:
        raise ExecutionUpdateError(
            "exactly one matching plan required"
        )

    plan = matching_plans[0]

    if plan.get("status") != "ACTIVE":
        raise ExecutionUpdateError(
            "plan must be ACTIVE"
        )

    if plan.get("side") == "WAIT":
        raise ExecutionUpdateError(
            "WAIT plan cannot be marked executed"
        )

    if plan.get("side") != update["side"]:
        raise ExecutionUpdateError(
            "execution side does not match plan"
        )

    if plan.get("asset") != update["asset"]:
        raise ExecutionUpdateError(
            "execution asset does not match plan"
        )

    matching_tranches = [
        tranche
        for tranche in plan.get("tranches", [])
        if tranche.get("tranche_id")
        == update["tranche_id"]
    ]

    if len(matching_tranches) != 1:
        raise ExecutionUpdateError(
            "exactly one matching tranche required"
        )

    tranche = matching_tranches[0]

    if tranche.get("status") != "PENDING":
        raise ExecutionUpdateError(
            "tranche must be PENDING"
        )

    holding_before = 0.0

    for holding in current.get("holdings", []):
        if holding.get("asset") == update["asset"]:
            holding_before = float(
                holding.get("quantity", 0.0)
            )
            break

    cash = current.get("cash")

    if not isinstance(cash, dict):
        raise ExecutionUpdateError(
            "current cash state unavailable"
        )

    available_before = float(
        cash.get("available_usd", 0.0)
    )
    reserved_before = float(
        cash.get("reserved_usd", 0.0)
    )

    if not _same_number(
        holding_before,
        update["expected_holding_quantity_before"],
    ):
        raise ExecutionUpdateError(
            "holding precondition mismatch"
        )

    if not _same_number(
        available_before,
        update["expected_available_cash_usd_before"],
    ):
        raise ExecutionUpdateError(
            "available cash precondition mismatch"
        )

    if not _same_number(
        reserved_before,
        update["expected_reserved_cash_usd_before"],
    ):
        raise ExecutionUpdateError(
            "reserved cash precondition mismatch"
        )

    if update["side"] == "BUY":
        expected_after = (
            holding_before
            + update["executed_quantity"]
        )
    else:
        expected_after = (
            holding_before
            - update["executed_quantity"]
        )

        if expected_after < -1e-9:
            raise ExecutionUpdateError(
                "SELL execution exceeds current holding"
            )

    if not _same_number(
        expected_after,
        update["holding_quantity_after"],
    ):
        raise ExecutionUpdateError(
            "holding postcondition mismatch"
        )

    candidate = json.loads(json.dumps(profile))

    candidate_holdings = candidate.get("holdings")

    if not isinstance(candidate_holdings, list):
        raise ExecutionUpdateError(
            "candidate holdings unavailable"
        )

    target_holding = None

    for holding in candidate_holdings:
        if (
            isinstance(holding, dict)
            and str(
                holding.get("asset", "")
            ).upper()
            == update["asset"]
        ):
            target_holding = holding
            break

    if target_holding is None:
        target_holding = {
            "asset": update["asset"],
            "quantity": 0.0,
        }
        candidate_holdings.append(target_holding)

    target_holding["asset"] = update["asset"]
    target_holding["quantity"] = (
        update["holding_quantity_after"]
    )

    if update["asset"] == "STRC":
        strc = candidate.get("strc")

        if not isinstance(strc, dict):
            raise ExecutionUpdateError(
                "legacy STRC state unavailable"
            )

        strc["shares"] = update[
            "holding_quantity_after"
        ]

    candidate_cash = candidate.get("cash")

    if not isinstance(candidate_cash, dict):
        raise ExecutionUpdateError(
            "candidate cash state unavailable"
        )

    candidate_cash["available_usd"] = update[
        "available_cash_usd_after"
    ]
    candidate_cash["reserved_usd"] = update[
        "reserved_cash_usd_after"
    ]
    candidate_cash["exact_amount_confirmed"] = True
    candidate_cash["exact_amount_source"] = (
        "USER_CONFIRMED_EXECUTION_UPDATE"
    )
    candidate_cash["exact_amount_observed_at"] = update[
        "executed_at"
    ]

    capital_state = candidate.get("capital_state")

    if not isinstance(capital_state, dict):
        raise ExecutionUpdateError(
            "candidate capital_state unavailable"
        )

    capital_state["as_of"] = update["executed_at"]

    candidate_plans = candidate.get("plans")

    if not isinstance(candidate_plans, list):
        raise ExecutionUpdateError(
            "candidate plans unavailable"
        )

    candidate_plan = next(
        (
            item
            for item in candidate_plans
            if isinstance(item, dict)
            and item.get("plan_id")
            == update["plan_id"]
        ),
        None,
    )

    if candidate_plan is None:
        raise ExecutionUpdateError(
            "candidate plan unavailable"
        )

    candidate_tranche = next(
        (
            item
            for item in candidate_plan.get(
                "tranches",
                [],
            )
            if isinstance(item, dict)
            and item.get("tranche_id")
            == update["tranche_id"]
        ),
        None,
    )

    if candidate_tranche is None:
        raise ExecutionUpdateError(
            "candidate tranche unavailable"
        )

    candidate_tranche["status"] = (
        "USER_CONFIRMED_EXECUTED"
    )
    candidate_tranche["execution"] = {
        "schema_version": (
            EXECUTION_UPDATE_SCHEMA_VERSION
        ),
        "execution_id": update["execution_id"],
        "confirmation": EXECUTION_CONFIRMATION,
        "executed_at": update["executed_at"],
        "asset": update["asset"],
        "side": update["side"],
        "executed_quantity": update[
            "executed_quantity"
        ],
        "execution_price_usd": update[
            "execution_price_usd"
        ],
        "holding_quantity_before": holding_before,
        "holding_quantity_after": update[
            "holding_quantity_after"
        ],
        "available_cash_usd_before": (
            available_before
        ),
        "available_cash_usd_after": update[
            "available_cash_usd_after"
        ],
        "reserved_cash_usd_before": (
            reserved_before
        ),
        "reserved_cash_usd_after": update[
            "reserved_cash_usd_after"
        ],
    }

    tranche_statuses = [
        item.get("status")
        for item in candidate_plan.get(
            "tranches",
            [],
        )
        if isinstance(item, dict)
    ]

    if (
        len(tranche_statuses) == 3
        and all(
            status == "USER_CONFIRMED_EXECUTED"
            for status in tranche_statuses
        )
    ):
        candidate_plan["status"] = "COMPLETED"

    validated = validate_private_profile(candidate)

    if validated.get(
        "external_action_authority"
    ) != "NONE":
        raise ExecutionUpdateError(
            "external_action_authority changed"
        )

    if validated.get("action_output") != "NONE":
        raise ExecutionUpdateError(
            "action_output changed"
        )

    return candidate


def _atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_name, path)

    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def apply_execution_update_file(
    profile_path: str | Path,
    update_payload: dict[str, Any],
) -> dict[str, Any]:
    target = Path(profile_path)

    if not target.exists():
        raise ExecutionUpdateError(
            "private profile file missing"
        )

    try:
        raw_profile = json.loads(
            target.read_text(
                encoding="utf-8-sig",
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionUpdateError(
            "private profile file unreadable"
        ) from exc

    update = validate_execution_update(
        update_payload
    )

    candidate = apply_user_confirmed_execution(
        raw_profile,
        update,
    )

    safe_id = "".join(
        char
        if (
            char.isalnum()
            or char in {"-", "_", "."}
        )
        else "_"
        for char in update["execution_id"]
    )

    backup = target.with_name(
        f"{target.stem}.before_execution."
        f"{safe_id}{target.suffix}"
    )

    if backup.exists():
        raise ExecutionUpdateError(
            "execution backup already exists"
        )

    shutil.copy2(target, backup)

    _atomic_write_json(
        target,
        candidate,
    )

    try:
        persisted = json.loads(
            target.read_text(
                encoding="utf-8",
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionUpdateError(
            "persisted profile unreadable"
        ) from exc

    validated = validate_private_profile(
        persisted
    )

    plan = next(
        item
        for item in validated["plans"]
        if item["plan_id"] == update["plan_id"]
    )

    tranche = next(
        item
        for item in plan["tranches"]
        if item["tranche_id"]
        == update["tranche_id"]
    )

    if (
        tranche["status"]
        != "USER_CONFIRMED_EXECUTED"
    ):
        raise ExecutionUpdateError(
            "persisted tranche state invalid"
        )

    return {
        "state": "EXECUTION_UPDATE_APPLIED",
        "execution_id": update["execution_id"],
        "plan_id": update["plan_id"],
        "tranche_id": update["tranche_id"],
        "asset": update["asset"],
        "side": update["side"],
        "backup_path": str(backup),
        "external_action_authority": (
            validated[
                "external_action_authority"
            ]
        ),
        "action_output": validated[
            "action_output"
        ],
        "capital_state_status": validated[
            "capital_state_status"
        ],
    }


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply one user-confirmed CRT "
            "capital execution update."
        )
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=default_private_profile_path(),
    )
    parser.add_argument(
        "--update",
        type=Path,
        required=True,
    )

    args = parser.parse_args(argv)

    try:
        update = json.loads(
            args.update.read_text(
                encoding="utf-8-sig",
            )
        )

        result = apply_execution_update_file(
            args.profile,
            update,
        )

    except (
        ExecutionUpdateError,
        PrivateProfileError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"EXECUTION_UPDATE_BLOCKED: {exc}"
        )
        return 2

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
