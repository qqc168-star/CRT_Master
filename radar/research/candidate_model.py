#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from crt_radar.candidate_engine import (
    CandidateModelError,
    aggregate_feature_scores,
    evaluate_candidate as _evaluate_candidate,
    load_registry as _load_registry,
    score_feature,
    validate_registry,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return _load_registry(path)


def evaluate_candidate(
    observations: dict[str, Any],
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _evaluate_candidate(observations, registry if registry is not None else load_registry())
