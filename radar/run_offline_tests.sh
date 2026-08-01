#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PYTHONWARNINGS=error::ResourceWarning PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m json.tool CONFIG/SOURCE_REGISTRY_V1.2.json >/dev/null
python -m json.tool CONFIG/LIVE_SHADOW_POLICY_V1.json >/dev/null
bash -n scripts/*.sh
PYTHONPATH=src:. python scripts/validate_program_registry.py
