#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "RADAR_SYSTEM_REGISTRY.csv"
SCHEMA = ROOT / "registry" / "REGISTRY_SCHEMA.json"


def validate(registry_path: Path = REGISTRY, schema_path: Path = SCHEMA) -> list[str]:
    errors: list[str] = []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    with registry_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    required = list(schema["required_columns"])
    if fields != required:
        errors.append("registry columns do not exactly match schema")
    if not rows:
        errors.append("registry has no rows")
        return errors

    ids = [row.get("id", "") for row in rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate module ID")
    if any(not value for value in ids):
        errors.append("blank module ID")

    orders: list[int] = []
    for row in rows:
        module_id = row.get("id", "UNKNOWN")
        try:
            orders.append(int(row.get("build_order", "")))
        except ValueError:
            errors.append(f"{module_id}: build_order invalid")
        if row.get("formal_parent") != schema["formal_parent"]:
            errors.append(f"{module_id}: formal_parent drift")
        if row.get("external_action_authority") != "NONE":
            errors.append(f"{module_id}: external action authority must be NONE")
        if not row.get("engineering_state"):
            errors.append(f"{module_id}: engineering_state missing")
        if not row.get("acceptance_gate"):
            errors.append(f"{module_id}: acceptance_gate missing")
        if not row.get("next_work_order"):
            errors.append(f"{module_id}: next_work_order missing")
        if "CANDIDATE" in row.get("governance_authority", "") and "FORMAL" in row.get("engineering_state", ""):
            errors.append(f"{module_id}: candidate cannot claim formal engineering state")

    if orders != list(range(1, len(rows) + 1)):
        errors.append("build_order must be contiguous from 1")

    known = set(ids)
    for row in rows:
        dependency = row.get("dependency", "").strip()
        if dependency in {"", "NONE"}:
            continue
        tokens = [part.strip() for part in dependency.replace("～", "-").replace("、", ",").split(",")]
        for token in tokens:
            if not token:
                continue
            if token in known:
                continue
            if token.startswith("P") and "-" in token:
                # Ranges and aggregate dependencies are documented prose; require at least one known prefix.
                prefix = token.split("-")[0]
                if any(item.startswith(prefix + "-") for item in known):
                    continue
            errors.append(f"{row['id']}: unresolved dependency token {token}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("RADAR_PROGRAM_REGISTRY_BLOCKED")
        for error in errors:
            print(error)
        return 1
    print("RADAR_PROGRAM_REGISTRY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
