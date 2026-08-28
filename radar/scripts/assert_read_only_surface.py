#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CALL_NAMES = {
    "place_order",
    "placeOrder",
    "submit_order",
    "create_order",
    "cancel_order",
    "cancelOrder",
    "reqGlobalCancel",
    "exerciseOptions",
    "replaceFA",
    "send_email",
    "transfer_funds",
    "withdraw",
}
AUTHORITY_KEYS = {"external_action_authority", "external_operation_authority"}
PERFORMED_KEYS = {"external_action_performed"}


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def scan_python(path: Path) -> list[str]:
    errors: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in FORBIDDEN_CALL_NAMES:
                label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
                errors.append(f"{label}:{node.lineno}: forbidden call {name}")
    return errors


def scan_json_value(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in AUTHORITY_KEYS and child != "NONE":
                errors.append(f"{child_path}: authority must be NONE")
            if key in PERFORMED_KEYS and child is not False:
                errors.append(f"{child_path}: performed flag must be false")
            scan_json_value(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_json_value(child, f"{path}[{index}]", errors)


def scan_json(path: Path) -> list[str]:
    errors: list[str] = []
    value = json.loads(path.read_text(encoding="utf-8"))
    label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    scan_json_value(value, str(label), errors)
    return errors


def main() -> int:
    errors: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        errors.extend(scan_python(path))
    for path in sorted((ROOT / "CONFIG").rglob("*.json")):
        errors.extend(scan_json(path))
    if errors:
        print("READ_ONLY_SURFACE_BLOCKED")
        for error in errors:
            print(error)
        return 1
    print("READ_ONLY_SURFACE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
