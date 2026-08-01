#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${CRT_RUNTIME_ROOT:-$ROOT/runtime_live_shadow}"
mkdir -p "$RUNTIME_ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m crt_radar.live_shadow_runner preflight \
  --registry "$ROOT/CONFIG/SOURCE_REGISTRY_V1.2.json" \
  --policy "$ROOT/CONFIG/LIVE_SHADOW_POLICY_V1.json" \
  --runtime-root "$RUNTIME_ROOT"
