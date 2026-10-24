from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .assumption_boundary_watch import (
    default_assumption_watch_context_path,
    load_assumption_watch_context,
)
from .btc_decision_support import (
    default_btc_entry_gate_context_path,
    load_btc_entry_gate_context,
    run_live_btc_entry_gate,
)
from .btc_transition_diagnostics import (
    blocked_transition_diagnostic,
    not_requested_transition_diagnostic,
    run_live_btc_transition_diagnostics,
)
from .btc_transition_replay_evidence import (
    build_btc_long_horizon_context,
)
from .dvol_regime_watch import (
    blocked_dvol_regime_watch,
    run_live_dvol_regime_watch,
)
from .evidence_pack import build_evidence_pack
from .gpt_handoff import run_gpt_handoff_gate
from .intraday_reanalysis_runner import run_intraday_reanalysis
from .liquidation_aggregator import SnapshotCorruption, load_verified_snapshot
from .maturity_tracker import record_maturity_attempt
from .observation_store import ObservationStore, extract_observations
from .plain_language_notice import build_plain_language_notice
from .private_profile import default_private_profile_path, load_private_profile
from .runtime_freshness import apply_runtime_checks, assess_file_freshness
from .season_transition_warning_overlay import (
    validate_season_transition_warning_overlay,
)
from .source_gate_runner import (
    FetchResult,
    default_liquidation_snapshot_path,
    default_registry_path,
    probe_liquidation_stream,
    run_source_gate,
)
from .source_registry import SourceRegistry, SourceSpec


def default_observation_db_path() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime" / "observations.sqlite3"


def default_evidence_pack_path() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime" / "evidence" / "latest.json"


SHADOW_VERSION = "CRT_LIQUIDATION_PAIRED_SHADOW_V0.2"
SHADOW_STUDY = "LIQUIDATION_SHADOW_STUDY"
SHADOW_PROTOCOL = "A_FROZEN_BEFORE_B_DISCLOSURE"


def _shadow_require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _shadow_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _shadow_now():
    return int(time.time() * 1000)


def _shadow_locks():
    return dict(research_only=True, formal_season=None, production="NOT_APPROVED",
                external_action_authority="NONE", external_action_performed=False,
                capital_decision_authority="USER_ONLY", machine_execution="FORBIDDEN",
                action_output="NONE", reasoning_state="NOT_YET_PROVEN")


def _shadow_check_clocks_and_authority(value, cutoff):
    """Reject future factual clocks and execution claims in shared research."""
    locks = {"external_action_authority": "NONE", "external_action_performed": False,
             "production": "NOT_APPROVED", "machine_execution": "FORBIDDEN",
             "action_output": "NONE", "capital_decision_authority": "USER_ONLY",
             "machine_may_confirm_bull_transition": False,
             "machine_may_output_trade_action": False, "formal_season": None}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in locks:
                expected = locks[key]
                valid = item is expected if expected is None or type(expected) is bool else item == expected
                _shadow_require(valid, "SHADOW_AUTHORITY_VIOLATION")
            if key.endswith("_ms") and item is not None and key not in {
                    "valid_until_ms", "expires_at_ms", "max_age_ms", "horizon_ms"}:
                _shadow_require(type(item) is int and 0 <= item <= cutoff,
                                "SHADOW_FUTURE_CONTEXT_OR_CLOCK_INVALID")
            _shadow_check_clocks_and_authority(item, cutoff)
    elif isinstance(value, list):
        for item in value:
            _shadow_check_clocks_and_authority(item, cutoff)


def _shadow_no_increment_in_a(value, incremental_ids):
    """A keeps aggregate L4, never the added event interpretation or Wake."""
    if isinstance(value, dict):
        _shadow_require(value.get("e") != "forceOrder", "SHADOW_A_ALREADY_CONTAINS_INCREMENT")
        for key, item in value.items():
            _shadow_require(not (key == "liquidation_research" and item),
                            "SHADOW_A_ALREADY_CONTAINS_INCREMENT")
            _shadow_no_increment_in_a(item, incremental_ids)
    elif isinstance(value, list):
        for item in value:
            _shadow_no_increment_in_a(item, incremental_ids)
    elif isinstance(value, str):
        _shadow_require(value != "LIQUIDATION_RESEARCH" and value not in incremental_ids,
                        "SHADOW_A_ALREADY_CONTAINS_INCREMENT")


def _shadow_validate_baseline(pack, gate, store, cutoff, control_transfer_evidence):
    from .evidence_pack import _group_layers, _data_health, _model_status
    from .change_engine import compute_changes
    from .v110_candidate import evaluate_v110_candidate
    from .btc_control_transfer_validation import evaluate_control_transfer_validation
    observations = extract_observations(gate, recorded_at_ms=cutoff)
    layers = _group_layers(observations)
    _shadow_require(pack.get("layers") == layers, "SHADOW_BASELINE_METRICS_MISMATCH")
    _shadow_require(pack.get("data_health") == _data_health(gate), "SHADOW_BASELINE_GATE_MISMATCH")
    _shadow_require(pack.get("changes") == compute_changes(store, observations),
                    "SHADOW_BASELINE_HISTORY_MISMATCH")
    formal = evaluate_v110_candidate(layers, store, evaluation_at_ms=cutoff)
    _shadow_require(pack.get("formal_candidate") == formal
                    and pack.get("model_status") == _model_status(layers, formal),
                    "SHADOW_BASELINE_MODEL_MISMATCH")
    q1 = evaluate_control_transfer_validation(control_transfer_evidence,
        observation_store=store, evaluated_at_ms=cutoff, require_observed_evidence=True)
    _shadow_require(pack.get("btc_control_transfer_validation") == q1,
                    "SHADOW_Q1_LINEAGE_OR_RESULT_MISMATCH")
    _shadow_check_clocks_and_authority(pack, cutoff)
    _shadow_require(all(item is None for item in pack.get("analyst_output", {}).values()),
                    "SHADOW_ANALYSIS_MUST_BE_FROZEN_SEPARATELY")


def _shadow_code_version():
    """Read actual evaluated code identity, without fetching or changing Git."""
    import subprocess
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], env=env).decode().strip()
    modules = ("daily_evidence_runner", "observation_store", "source_gate_runner", "reanalysis_wake",
               "btc_transition_diagnostics", "btc_decision_support", "btc_control_transfer_validation")
    return dict(git_sha=git("rev-parse", "HEAD"), working_tree_dirty=bool(git("status", "--porcelain")),
                module_sha256={name: hashlib.sha256((Path(__file__).parent / (name + ".py")).read_bytes()).hexdigest()
                               for name in modules}, absorption_semantics="CRT_SPOT_DEMAND_ABSORPTION_V0.2",
                pair_semantics=SHADOW_VERSION)


def start_liquidation_shadow(store, registry, *, mode="PROSPECTIVE"):
    """Explicit isolated-study enrollment; never starts a collector or scheduler."""
    prior = store.research_event(SHADOW_STUDY, kind=SHADOW_STUDY)
    if prior:
        _shadow_require(prior["schema_version"] == SHADOW_VERSION, "SHADOW_LEGACY_STUDY_REQUIRES_NEW_ISOLATED_STORE")
        _shadow_require(prior["mode"] == mode, "SHADOW_STUDY_MODE_CONFLICT")
        return prior
    _shadow_require(mode in {"PROSPECTIVE", "SYNTHETIC_TEST"}, "SHADOW_MODE_INVALID")
    version = _shadow_code_version()
    _shadow_require(mode == "SYNTHETIC_TEST" or not version["working_tree_dirty"], "SHADOW_CODE_NOT_SEALED")
    record = dict(schema_version=SHADOW_VERSION, mode=mode, started_at_ms=_shadow_now(),
                  registry=deepcopy(registry.with_l6_candidate_sources().payload), code_version=version,
                  selection="ALL_SUBMITTED_CLASSIFIED_CANDIDATES_IN_RECEIPT_ORDER",
                  stream_completeness="NOT_PROVEN_BINANCE_SAMPLED_SOURCE", **_shadow_locks())
    store.record_research_event(SHADOW_STUDY, SHADOW_STUDY, record)
    return record


class _ShadowWakePreview:
    """Buffer the existing Wake validator's writes until the pair intake commits."""
    def __init__(self, store):
        self.store, self.records = store, []

    def __getattr__(self, name):
        return getattr(self.store, name)

    def record_research_event(self, event_id, kind, payload):
        self.records.append((event_id, kind, deepcopy(payload)))
        return True


def capture_liquidation_shadow(store, registry, *, baseline_pack, captures, cutoff_ms, event_id=None,
                               candidate=None, liquidation_snapshot=None,
                               control_transfer_evidence=None):
    """Deliver only A's common input. No B candidate/slice is accepted here.

    captures preserves original UTF-8 bytes and actual archive clocks, alongside
    the existing FetchResult. Local integrity does not attest external truth.
    event_id is an opaque existing research identity supplied by the coordinator;
    its binding is checked only when B is submitted AFTER A is frozen.
    The caller must use an isolated ObservationStore; no Runtime/default path,
    fetch, broker, model, notification or external-action entry is invoked.
    """
    from .source_registry import sha256_hex
    study = store.research_event(SHADOW_STUDY, kind=SHADOW_STUDY)
    _shadow_require(study is not None, "SHADOW_NOT_ENROLLED")
    _shadow_require(candidate is None, "SHADOW_B_INPUT_BEFORE_A_FREEZE")
    _shadow_require(study["schema_version"] == SHADOW_VERSION, "SHADOW_LEGACY_INPUTS_NOT_STAGED")
    if event_id is None:
        return dict(state="NOT_RUN", reason="NO_CLASSIFIED_NATURAL_EVENT", **_shadow_locks())
    _shadow_require(isinstance(event_id, str) and len(event_id) == 64
                    and all(c in "0123456789abcdef" for c in event_id), "SHADOW_EVENT_TOKEN_INVALID")
    _shadow_require(isinstance(captures, dict)
                    and all(isinstance(v, dict) and isinstance(v.get("fetch"), FetchResult)
                            for v in captures.values()), "SHADOW_CAPTURE_FORMAT_INVALID")
    pair_id = "liquidation-shadow:" + event_id
    request = dict(baseline_pack=baseline_pack, event_id=event_id, snapshot=liquidation_snapshot,
                   control_transfer_evidence=control_transfer_evidence,
                   captures={k: {**{a: b for a, b in v.items() if a != "fetch"},
                                 "fetch": vars(v["fetch"])} for k, v in captures.items()}, cutoff_ms=cutoff_ms)
    request_hash = _shadow_hash(request)
    prior = store.research_event(pair_id, kind="LIQUIDATION_SHADOW_INPUTS")
    if prior:
        _shadow_require(prior["request_hash"] == request_hash, "SHADOW_FROZEN_INPUT_CONFLICT")
        return {k: deepcopy(v) for k, v in prior.items() if k != "source_archives"}
    now = _shadow_now()
    _shadow_require(type(cutoff_ms) is int and study["started_at_ms"] <= cutoff_ms <= now,
                    "SHADOW_CUTOFF_INVALID")
    _shadow_require(now - cutoff_ms <= registry.by_input_family("LIQUIDATION_AGGREGATES").max_age_seconds * 1000,
                    "SHADOW_HISTORICAL_REPLAY_FORBIDDEN")
    version = _shadow_code_version()
    _shadow_require(study["mode"] == "SYNTHETIC_TEST" or not version["working_tree_dirty"], "SHADOW_CODE_NOT_SEALED")
    _shadow_require(study["mode"] == "SYNTHETIC_TEST" or version == study["code_version"],
                    "SHADOW_STUDY_CODE_CHANGED")
    _shadow_require(registry.with_l6_candidate_sources().payload == study["registry"], "SHADOW_REGISTRY_CHANGED")
    overrides, sources = {}, {}
    for source_id, capture in captures.items():
        required = {"fetch", "raw_utf8", "sha256", "encoding", "first_seen_at_ms",
                    "retrieved_at_ms", "verified_at_ms", "available_at_ms",
                    "request_identity", "source_authority_hash", "evidence_class"}
        _shadow_require(isinstance(capture, dict) and required == set(capture),
                        "SHADOW_CAPTURE_METADATA_MISSING")
        fetched = capture["fetch"]
        spec = registry.with_l6_candidate_sources().get(source_id)
        _shadow_require(isinstance(fetched, FetchResult) and isinstance(capture["raw_utf8"], str)
                        and capture["encoding"] in {"JSON", "TEXT"}, "SHADOW_CAPTURE_FORMAT_INVALID")
        raw = capture["raw_utf8"].encode("utf-8")
        _shadow_require(sha256_hex(raw) == capture["sha256"], "SHADOW_ORIGINAL_BYTES_MISMATCH")
        payload = json.loads(raw) if capture["encoding"] == "JSON" else raw.decode("utf-8")
        _shadow_require(fetched.source_id == source_id and payload == fetched.payload, "SHADOW_PAYLOAD_MISMATCH")
        first, retrieved = capture["first_seen_at_ms"], capture["retrieved_at_ms"]
        verified, available = capture["verified_at_ms"], capture["available_at_ms"]
        _shadow_require(all(type(t) is int for t in (first, retrieved, verified, available))
                        and 0 < available <= first <= retrieved <= verified <= cutoff_ms,
                        "SHADOW_SOURCE_NOT_VISIBLE")
        expected_request = ("READ_LOCAL_PUBLIC_L4_SNAPSHOT:" + capture["sha256"]
            if spec.input_family == "LIQUIDATION_AGGREGATES" else
            "COMPOSE_REGISTERED_ENDPOINTS:" + _shadow_hash(spec.raw["endpoints"])
            if spec.raw.get("endpoints") else "GET " + str(spec.endpoint))
        _shadow_require(capture["request_identity"] == expected_request
                        and capture["source_authority_hash"] == registry.with_l6_candidate_sources().hash,
                        "SHADOW_SOURCE_IDENTITY_MISMATCH")
        _shadow_require(capture["evidence_class"] == (
            "SYNTHETIC_FIXTURE" if study["mode"] == "SYNTHETIC_TEST" else "CURRENT_FIRST_SEEN_CAPTURE"),
            "SHADOW_EVIDENCE_CLASS_MISMATCH")
        if spec.parser_id == "BINANCE_PRICE_STRUCTURE_PROXY_V1":
            # The staged archive has just been bound to original bytes and
            # first visibility. Reuse that evidence instead of the replay clock.
            from dataclasses import replace
            fetched = replace(fetched, captured_at_ms=first)
        overrides[source_id] = fetched
        sources[source_id] = {**{k: deepcopy(v) for k, v in capture.items() if k != "fetch"},
                              "source_definition": deepcopy(spec.raw)}
    gate = run_source_gate(registry, fetch_overrides=overrides,
                           liquidation_aggregate_payload=liquidation_snapshot, now_ms=cutoff_ms)
    _shadow_require(baseline_pack.get("evidence_pack_hash") == _shadow_hash(
        {k: v for k, v in baseline_pack.items() if k != "evidence_pack_hash"}), "SHADOW_BASE_PACK_HASH_INVALID")
    _shadow_require(baseline_pack["generated_at_ms"] == cutoff_ms
                    and baseline_pack["source_gate_idempotency_key"] == gate["idempotency_key"],
                    "SHADOW_BASELINE_SOURCE_OR_CLOCK_MISMATCH")
    _shadow_require(not baseline_pack.get("reanalysis_wake", {}).get("liquidation_research"),
                    "SHADOW_A_ALREADY_CONTAINS_INCREMENT")
    _shadow_no_increment_in_a(baseline_pack, {event_id})
    _shadow_no_increment_in_a(liquidation_snapshot, {event_id})
    preview = _ShadowWakePreview(store)
    _shadow_validate_baseline(baseline_pack, gate, preview, cutoff_ms, control_transfer_evidence)
    for e in gate["evidence"]:
        _shadow_require(e.get("as_of_ms") is None or e["as_of_ms"] <= cutoff_ms, "SHADOW_FUTURE_MARKET_OBSERVATION")
    # Original archives remain audit records, never the A analyst delivery view.
    common = dict(evidence_pack=deepcopy(baseline_pack), source_gate=gate,
                  sources={s: {k: v for k, v in capture.items() if k != "raw_utf8"}
                           for s, capture in sources.items()})
    prior_intake = store.latest_research_event("LIQUIDATION_SHADOW_INPUTS")
    _shadow_require(prior_intake is None or cutoff_ms >= prior_intake["cutoff_ms"], "SHADOW_INTAKE_ORDER_INVALID")
    evidence_ids = [e["evidence_hash"] for e in gate["evidence"] if e["quality_state"].startswith("VALID")]
    ready = _shadow_now()
    deadline = cutoff_ms + registry.by_input_family("LIQUIDATION_AGGREGATES").max_age_seconds * 1000
    _shadow_require(now <= ready <= deadline, "SHADOW_A_RELEASE_CLOCK_INVALID")
    record = dict(schema_version=SHADOW_VERSION, pair_id=pair_id, event_id=event_id, request_hash=request_hash,
                  protocol=SHADOW_PROTOCOL, source_archives=sources,
                  mode=study["mode"], cutoff_ms=cutoff_ms, captured_at_ms=now, code_version=version,
                  revalidated_at_ms=ready, judgment_deadline_ms=deadline,
                  source_qualification="EXISTING_GATE_REVALIDATED_LOCAL_CAPTURE",
                  external_source_authenticity="NOT_INDEPENDENTLY_ATTESTED",
                  common=common, common_hash=_shadow_hash(common), evidence_ids=evidence_ids,
                  A=dict(state="AVAILABLE_FOR_RESEARCH", input_hash=_shadow_hash(common), released_at_ms=ready),
                  analysis_execution={"A": "NOT_RUN", "B": "NOT_RUN"},
                  sample_state="A_INPUT_ONLY_B_NOT_RUN", **_shadow_locks())
    store.record_research_events(preview.records + [(pair_id, "LIQUIDATION_SHADOW_INPUTS", record)])
    return {k: deepcopy(v) for k, v in record.items() if k != "source_archives"}


def release_liquidation_shadow_b(store, registry, pair_id, *, candidate, liquidation_snapshot):
    """Only after A submission, validate and disclose B against the frozen cutoff."""
    from .reanalysis_wake import apply_liquidation_research_wake
    inputs = store.research_event(pair_id, kind="LIQUIDATION_SHADOW_INPUTS")
    a = store.research_event(pair_id + ":A", kind="LIQUIDATION_SHADOW_ARM_JUDGMENT")
    _shadow_require(inputs is not None and inputs.get("protocol") == SHADOW_PROTOCOL,
                    "SHADOW_STAGED_INPUTS_REQUIRED")
    _shadow_require(a is not None, "SHADOW_A_NOT_FROZEN")
    _shadow_require(a["inputs_hash"] == _shadow_hash(inputs) and a["comparison_eligible"],
                    "SHADOW_A_EXPOSURE_OR_PROVENANCE_BLOCKED")
    _shadow_require(isinstance(candidate, dict), "SHADOW_CANDIDATE_INVALID")
    identity = {key: candidate.get(key) for key in ("source_id", "symbol", "direction", "anchor_evidence_id")}
    _shadow_require(_shadow_hash(identity) == inputs["event_id"], "SHADOW_EVENT_IDENTITY_MISMATCH")
    request_hash = _shadow_hash([candidate, liquidation_snapshot])
    prior = store.research_event(pair_id + ":B-input", kind="LIQUIDATION_SHADOW_B_INPUTS")
    if prior:
        _shadow_require(prior["request_hash"] == request_hash, "SHADOW_FROZEN_INPUT_CONFLICT")
        return prior
    now, cutoff = _shadow_now(), inputs["cutoff_ms"]
    _shadow_require(a["submitted_at_ms"] <= now <= inputs["judgment_deadline_ms"], "SHADOW_B_RELEASE_CLOCK_INVALID")
    _shadow_require(inputs["mode"] == "SYNTHETIC_TEST" or _shadow_code_version() == inputs["code_version"],
                    "SHADOW_STUDY_CODE_CHANGED")
    study = store.research_event(SHADOW_STUDY, kind=SHADOW_STUDY)
    _shadow_require(registry.with_l6_candidate_sources().payload == study["registry"], "SHADOW_REGISTRY_CHANGED")
    _shadow_check_clocks_and_authority(candidate, cutoff)
    _shadow_check_clocks_and_authority(liquidation_snapshot, cutoff)
    _shadow_no_increment_in_a(inputs["common"], {inputs["event_id"], *candidate.get("supporting_evidence_ids", [])})
    aggregate = registry.by_input_family("LIQUIDATION_AGGREGATES")
    capture = inputs["source_archives"].get(aggregate.source_id)
    _shadow_require(capture is not None and json.loads(capture["raw_utf8"]) == liquidation_snapshot,
                    "SHADOW_SNAPSHOT_ARCHIVE_CLOCK_MISSING")
    baseline = inputs["common"]["evidence_pack"]
    base_wake = baseline.get("reanalysis_wake") or dict(state="NO_WAKE", reason="BASELINE_NO_WAKE",
        action_output="NONE", external_action_authority="NONE", external_action_performed=False)
    preview = _ShadowWakePreview(store)
    wake = apply_liquidation_research_wake(base_wake, store=preview, candidate=candidate,
        source_gate=inputs["common"]["source_gate"], snapshot=liquidation_snapshot, registry=registry, at_ms=cutoff)
    b = wake["liquidation_research"]
    if b["state"] == "REANALYSIS_REQUESTED":
        from .liquidation_aggregator import normalize_force_order
        from .reanalysis_wake import liquidation_evidence_identity
        anchor = next(normalize_force_order(row["raw_payload"], received_ms=row["received_ms"])
                      for row in candidate["event_records"] if liquidation_evidence_identity(
                          normalize_force_order(row["raw_payload"], received_ms=row["received_ms"]),
                          candidate["source_id"]) == candidate["anchor_evidence_id"])
        if min(anchor.received_ms, anchor.event_time_ms, candidate["formed_at_ms"]) < study["started_at_ms"]:
            b = dict(state="BLOCKED", reason="SHADOW_PRE_ENROLLMENT_EVENT")
    qualified = b["state"] == "REANALYSIS_REQUESTED"
    increment = dict(candidate=deepcopy(candidate), snapshot=deepcopy(liquidation_snapshot), wake=wake) if qualified else None
    ready = _shadow_now()
    _shadow_require(now <= ready <= inputs["judgment_deadline_ms"], "SHADOW_B_RELEASE_CLOCK_INVALID")
    record = dict(schema_version=SHADOW_VERSION, protocol=SHADOW_PROTOCOL, pair_id=pair_id,
        request_hash=request_hash, common=deepcopy(inputs["common"]), cutoff_ms=cutoff,
        a_judgment_hash=_shadow_hash(a), released_at_ms=ready, increment=increment,
        state="AVAILABLE_FOR_RESEARCH" if qualified else "BLOCKED", reason=b.get("reason"),
        evidence_ids=b["evidence_ids"] if qualified else [],
        input_hash=_shadow_hash([inputs["common_hash"], increment]), **_shadow_locks())
    store.record_research_events((preview.records if qualified else []) +
        [(pair_id + ":B-input", "LIQUIDATION_SHADOW_B_INPUTS", record)])
    return record


def freeze_liquidation_shadow_judgments(store, pair_id, judgments):
    """Submit exactly one arm; simultaneous A/B submission is forbidden."""
    inputs = store.research_event(pair_id, kind="LIQUIDATION_SHADOW_INPUTS")
    _shadow_require(inputs is not None and inputs.get("protocol") == SHADOW_PROTOCOL, "SHADOW_INPUTS_NOT_FROZEN")
    _shadow_require(set(judgments) in ({"A"}, {"B"}), "SHADOW_ONE_ARM_PER_SUBMISSION_REQUIRED")
    arm = next(iter(judgments))
    a = store.research_event(pair_id + ":A", kind="LIQUIDATION_SHADOW_ARM_JUDGMENT")
    b_inputs = store.research_event(pair_id + ":B-input", kind="LIQUIDATION_SHADOW_B_INPUTS")
    if arm == "B":
        _shadow_require(a is not None, "SHADOW_A_NOT_FROZEN")
        _shadow_require(b_inputs is not None and b_inputs["state"] == "AVAILABLE_FOR_RESEARCH",
                        "SHADOW_B_NOT_RELEASED_OR_BLOCKED")
    freeze_id = pair_id + ":" + arm
    prior = store.research_event(freeze_id, kind="LIQUIDATION_SHADOW_ARM_JUDGMENT")
    if prior:
        _shadow_require(prior["judgments"] == judgments and prior["inputs_hash"] == _shadow_hash(inputs),
                        "SHADOW_FROZEN_JUDGMENT_CONFLICT")
        return complete_liquidation_shadow_pair(store, pair_id) if arm == "B" else prior
    fields = {"input_hash", "cutoff_ms", "formed_at_ms", "analyst_provenance", "research_hypothesis", "competing_hypotheses",
              "supporting_evidence_ids", "strongest_counterevidence", "capital_posture_research",
              "invalidation_conditions", "next_trigger_conditions", "difference_reason", "analysis_process"}
    now = _shadow_now()
    _shadow_require(now <= inputs["judgment_deadline_ms"], "SHADOW_JUDGMENTS_TOO_LATE")
    version = _shadow_code_version()
    _shadow_require(inputs["mode"] == "SYNTHETIC_TEST" or version == inputs["code_version"],
                    "SHADOW_JUDGMENT_CODE_CHANGED")
    for arm, judgment in judgments.items():
        arm_input = inputs["A"] if arm == "A" else b_inputs
        delivered = inputs["A"]["released_at_ms"] if arm == "A" else b_inputs["released_at_ms"]
        _shadow_require(set(judgment) == fields, "SHADOW_JUDGMENT_FIELDS_INVALID")
        _shadow_require(judgment["input_hash"] == arm_input["input_hash"]
                        and judgment["cutoff_ms"] == inputs["cutoff_ms"], "SHADOW_JUDGMENT_INPUT_MISMATCH")
        formed = judgment["formed_at_ms"]
        _shadow_require(type(formed) is int and delivered <= formed <= now,
                        "SHADOW_JUDGMENT_CLOCK_INVALID")
        for key in ("analyst_provenance", "research_hypothesis", "difference_reason"):
            _shadow_require(isinstance(judgment[key], str) and bool(judgment[key].strip()), "SHADOW_JUDGMENT_TEXT_MISSING")
        for key in ("competing_hypotheses", "invalidation_conditions", "next_trigger_conditions"):
            values = judgment[key]
            _shadow_require(isinstance(values, list) and len(values) >= (2 if key == "competing_hypotheses" else 1)
                            and all(isinstance(v, str) and v.strip() for v in values), "SHADOW_REASONING_FIELDS_MISSING")
        allowed = set(inputs["evidence_ids"] + [inputs["common"]["evidence_pack"]["evidence_pack_hash"]]
                      + (b_inputs["evidence_ids"] if arm == "B" else []))
        counter = judgment["strongest_counterevidence"]
        _shadow_require(set(counter) == {"statement", "evidence_ids"} and bool(counter["statement"]), "SHADOW_COUNTEREVIDENCE_MISSING")
        for refs in (judgment["supporting_evidence_ids"], counter["evidence_ids"]):
            _shadow_require(isinstance(refs, list) and bool(refs) and set(refs) <= allowed, "SHADOW_EVIDENCE_REFERENCE_INVALID")
        posture = judgment["capital_posture_research"]
        _shadow_require(set(posture) == {"state", "btc_capital_question", "conditional_direction", "limitations"}
                        and posture["state"] in {"CONDITIONAL_RESEARCH", "BLOCKED", "NOT_RUN"}
                        and all(isinstance(posture[k], str) and posture[k].strip()
                                for k in ("btc_capital_question", "conditional_direction", "limitations")),
                        "SHADOW_CAPITAL_LINK_MISSING")
        _shadow_check_clocks_and_authority(judgment, now)
        process = judgment["analysis_process"]
        process_fields = {"actor_id", "session_id", "method", "provenance_ref", "input_manifest_hash",
                          "analysis_started_at_ms", "market_information_cutoff_ms", "b_information_exposure",
                          "external_context_used", "input_access_log"}
        _shadow_require(isinstance(process, dict) and set(process) == process_fields,
                        "SHADOW_ANALYSIS_PROCESS_MISSING")
        _shadow_require(all(isinstance(process[k], str) and process[k].strip()
                            for k in ("actor_id", "session_id", "method", "provenance_ref")),
                        "SHADOW_ANALYSIS_PROVENANCE_MISSING")
        _shadow_require(process["input_manifest_hash"] == arm_input["input_hash"]
                        and process["market_information_cutoff_ms"] == inputs["cutoff_ms"],
                        "SHADOW_ANALYSIS_INPUT_OR_CUTOFF_MISMATCH")
        started = process["analysis_started_at_ms"]
        _shadow_require(type(started) is int and delivered <= started <= formed,
                        "SHADOW_ANALYSIS_START_BEFORE_DISCLOSURE")
        accesses = process["input_access_log"]
        _shadow_require(isinstance(accesses, list) and bool(accesses), "SHADOW_INPUT_ACCESS_LOG_MISSING")
        for access in accesses:
            _shadow_require(isinstance(access, dict) and set(access) == {"input_hash", "accessed_at_ms"}
                and access["input_hash"] == arm_input["input_hash"]
                and type(access["accessed_at_ms"]) is int and delivered <= access["accessed_at_ms"] <= formed,
                "SHADOW_UNAUTHORIZED_INPUT_ACCESS")
        _shadow_require(min(v["accessed_at_ms"] for v in accesses) <= started,
                        "SHADOW_ANALYSIS_START_BEFORE_DISCLOSURE")
        _shadow_require(type(process["external_context_used"]) is bool and process["b_information_exposure"] in (
            {"NOT_EXPOSED_DECLARED", "EXPOSED", "UNKNOWN"} if arm == "A" else {"B_STAGE_AUTHORIZED"}),
            "SHADOW_EXPOSURE_DECLARATION_INVALID")
        eligible = (not process["external_context_used"] and
                    (arm == "B" or process["b_information_exposure"] == "NOT_EXPOSED_DECLARED"))
    result = dict(schema_version=SHADOW_VERSION, pair_id=pair_id, inputs_hash=_shadow_hash(inputs),
                  protocol=SHADOW_PROTOCOL, arm=arm, input_hash=arm_input["input_hash"],
                  delivered_at_ms=delivered, submitted_at_ms=now, frozen_at_ms=now,
                  judgments=deepcopy(judgments), code_version=version, paired=False,
                  comparison_eligible=eligible,
                  sample_state=arm + "_FROZEN" if eligible else "COMPARISON_BLOCKED_DECLARED_EXPOSURE",
                  judgment_quality="ANALYST_DECLARED_NOT_MACHINE_PROVEN", **_shadow_locks())
    store.record_research_event(freeze_id, "LIQUIDATION_SHADOW_ARM_JUDGMENT", result)
    return complete_liquidation_shadow_pair(store, pair_id) if arm == "B" else result


def complete_liquidation_shadow_pair(store, pair_id):
    """Receipt only after both immutable submissions and A-before-B disclosure."""
    inputs = store.research_event(pair_id, kind="LIQUIDATION_SHADOW_INPUTS")
    a, b = (store.research_event(pair_id + ":" + arm, kind="LIQUIDATION_SHADOW_ARM_JUDGMENT") for arm in ("A", "B"))
    b_inputs = store.research_event(pair_id + ":B-input", kind="LIQUIDATION_SHADOW_B_INPUTS")
    _shadow_require(inputs is not None and a is not None and b is not None and b_inputs is not None,
                    "SHADOW_BOTH_FROZEN_ARMS_REQUIRED")
    _shadow_require(all(v.get("protocol") == SHADOW_PROTOCOL for v in (inputs, a, b, b_inputs)),
                    "SHADOW_LEGACY_INPUTS_NOT_STAGED")
    _shadow_require(a["code_version"] == b["code_version"] == inputs["code_version"],
                    "SHADOW_JUDGMENT_CODE_CHANGED")
    _shadow_require(a["comparison_eligible"] and b["comparison_eligible"], "SHADOW_DECLARED_CONTAMINATION")
    _shadow_require(a["inputs_hash"] == b["inputs_hash"] == _shadow_hash(inputs)
                    and b_inputs["a_judgment_hash"] == _shadow_hash(a)
                    and a["input_hash"] == inputs["A"]["input_hash"]
                    and b["input_hash"] == b_inputs["input_hash"]
                    and b_inputs["common"] == inputs["common"]
                    and b_inputs["cutoff_ms"] == inputs["cutoff_ms"]
                    and b_inputs["state"] == "AVAILABLE_FOR_RESEARCH"
                    and b_inputs["input_hash"] == _shadow_hash([inputs["common_hash"], b_inputs["increment"]]),
                    "SHADOW_ARM_CHAIN_MISMATCH")
    _shadow_require(a["delivered_at_ms"] == inputs["A"]["released_at_ms"]
                    and b["delivered_at_ms"] == b_inputs["released_at_ms"]
                    and a["delivered_at_ms"] <= a["judgments"]["A"]["formed_at_ms"]
                    <= a["submitted_at_ms"] <= b_inputs["released_at_ms"]
                    <= b["judgments"]["B"]["formed_at_ms"] <= b["submitted_at_ms"]
                    <= inputs["judgment_deadline_ms"], "SHADOW_SUBMISSION_ORDER_INVALID")
    _shadow_require(all(j["cutoff_ms"] == inputs["cutoff_ms"] for j in
                        (a["judgments"]["A"], b["judgments"]["B"])), "SHADOW_JUDGMENT_INPUT_MISMATCH")
    judgments = {**a["judgments"], **b["judgments"]}
    result = dict(schema_version=SHADOW_VERSION, protocol=SHADOW_PROTOCOL, pair_id=pair_id,
        inputs_hash=_shadow_hash(inputs), a_judgment_hash=_shadow_hash(a), b_judgment_hash=_shadow_hash(b),
        b_input_hash=_shadow_hash(b_inputs), judgments=judgments, frozen_at_ms=b["submitted_at_ms"],
        paired=True, sample_state="PROSPECTIVE_PAIR_FROZEN" if inputs["mode"] == "PROSPECTIVE" else "SYNTHETIC_PAIR_ONLY",
        independence_state="DECLARED_INPUT_ISOLATION_COGNITIVE_BLINDNESS_NOT_PROVEN",
        judgment_quality="ANALYST_DECLARED_NOT_MACHINE_PROVEN", code_version=b["code_version"], **_shadow_locks())
    result["judgment_differences"] = {
        key: {"A": judgments["A"][key], "B": judgments["B"][key]}
        for key in judgments["A"].keys() - {"input_hash", "cutoff_ms", "formed_at_ms", "analyst_provenance", "analysis_process"}
        if judgments["A"][key] != judgments["B"][key]
    }
    store.record_research_event(pair_id + ":judgments", "LIQUIDATION_SHADOW_JUDGMENTS", result)
    return result


def record_liquidation_shadow_followup(store, pair_id, *, archive_root, artifact, window_start_ms,
                                       window_end_ms, interpretation):
    """Only after paired freezing, read GO4's existing verified research archive."""
    from .source_gate_runner import verified_price_structure_archive, parse_price_structure, _assert_fresh
    frozen = store.research_event(pair_id + ":judgments", kind="LIQUIDATION_SHADOW_JUDGMENTS")
    _shadow_require(frozen is not None and frozen["paired"] and frozen.get("protocol") == SHADOW_PROTOCOL,
                    "SHADOW_PAIRED_JUDGMENTS_REQUIRED")
    inputs = store.research_event(pair_id, kind="LIQUIDATION_SHADOW_INPUTS")
    _shadow_require(inputs is not None and _shadow_hash(inputs) == frozen["inputs_hash"],
                    "SHADOW_FROZEN_INPUT_CHAIN_MISMATCH")
    now = _shadow_now()
    _shadow_require(type(window_start_ms) is int and type(window_end_ms) is int
                    and frozen["frozen_at_ms"] < window_start_ms <= window_end_ms < now,
                    "SHADOW_FOLLOWUP_WINDOW_NOT_LATER")
    _shadow_require(frozen["frozen_at_ms"] < artifact["first_seen_at_ms"] <= now,
                    "SHADOW_FOLLOWUP_ALREADY_VISIBLE_AT_FREEZE")
    _shadow_require(artifact["first_seen_at_ms"] > window_end_ms,
                    "SHADOW_FOLLOWUP_NOT_YET_AVAILABLE")
    payload = verified_price_structure_archive(Path(archive_root), artifact, now)
    registry = SourceRegistry(store.research_event(SHADOW_STUDY, kind=SHADOW_STUDY)["registry"])
    spec = registry.by_input_family("PRICE_STRUCTURE_CONTEXT")
    parsed = parse_price_structure(payload, captured_at_ms=artifact["first_seen_at_ms"], now_ms=now)
    _assert_fresh(parsed["as_of_ms"], now_ms=now, max_age_seconds=spec.max_age_seconds)
    bars = [row for row in payload if window_start_ms <= row[0] and row[6] <= window_end_ms]
    _shadow_require(bool(bars) and all(row[0] > frozen["frozen_at_ms"] and row[6] < now for row in bars),
                    "SHADOW_FOLLOWUP_BARS_INVALID")
    _shadow_require(isinstance(interpretation, str) and bool(interpretation.strip()), "SHADOW_FOLLOWUP_INTERPRETATION_MISSING")
    identity = [pair_id, spec.source_id, "BTCUSDT", window_start_ms, window_end_ms]
    event_id = "shadow-followup:" + _shadow_hash(identity)
    material = dict(identity=identity, bars=bars, interpretation=interpretation)
    prior = store.research_event(event_id, kind="LIQUIDATION_SHADOW_FOLLOWUP")
    if prior:
        _shadow_require(prior["material"] == material, "SHADOW_FROZEN_OUTCOME_CONFLICT")
        return prior
    result = dict(schema_version=SHADOW_VERSION, material=material, artifact=deepcopy(artifact), recorded_at_ms=now,
                  paired_judgments_hash=_shadow_hash(frozen), inputs_hash=_shadow_hash(inputs),
                  market_outcome_not_decision_quality_proof=True, code_version=_shadow_code_version(),
                  **_shadow_locks())
    store.record_research_event(event_id, "LIQUIDATION_SHADOW_FOLLOWUP", result)
    return result


def _resolve_wake_operational_percentile(
    dvol_regime_watch: dict[str, Any],
    acceptance_override: float | None,
) -> tuple[float, dict[str, Any] | None]:
    """Resolve the ordinary wake sensitivity plus an explicit one-shot acceptance override.

    The override is transport-acceptance-only.  It does not alter the DVOL regime
    recommendation, formal CRT thresholds, investment thresholds, or persisted
    production configuration.
    """
    recommended = dvol_regime_watch.get(
        "recommended_wake_operational_percentile",
        95.0,
    )
    try:
        recommended = float(recommended)
    except (TypeError, ValueError):
        recommended = 95.0
    if not (0.0 < recommended <= 100.0):
        recommended = 95.0

    if acceptance_override is None:
        return recommended, None

    override = float(acceptance_override)
    if not (0.0 < override <= 100.0):
        raise ValueError(
            "acceptance wake percentile must be in (0, 100]"
        )

    return override, {
        "scope": "ONE_SHOT_TRANSPORT_ACCEPTANCE_ONLY",
        "acceptance_override_used": True,
        "production_wake_operational_percentile": recommended,
        "acceptance_wake_operational_percentile": override,
        "persistent_configuration_changed": False,
        "formal_threshold_authority": "NONE",
        "investment_threshold_authority": "NONE",
        "external_action_authority": "NONE",
        "action_output": "NONE",
    }


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run_daily_evidence(
    registry: SourceRegistry,
    *,
    observation_db: str | Path,
    reflexivity_input: dict[str, Any] | None = None,
    treasury_valuation_inputs: dict[str, Any] | None = None,
    treasury_company_ct_inputs: dict[str, Any] | None = None,
    issuer_ct_archive: str | Path | None = None,
    btc_long_horizon_inputs: dict[str, Any] | None = None,
    portfolio_allocation_inputs: dict[str, Any] | None = None,
    fixed_income_inputs: dict[str, Any] | None = None,
    btc_etf_archive: dict[str, Any] | None = None,
    fetch_overrides: dict[str, FetchResult] | None = None,
    liquidation_aggregate_payload: dict[str, Any] | None = None,
    probe_fetcher: Callable[[SourceSpec], FetchResult] | None = None,
    runtime_checks: list[dict[str, Any]] | None = None,
    now_ms: int | None = None,
    generated_at_ms: int | None = None,
    private_context: dict[str, Any] | None = None,
    broker_capital_observation: dict[str, Any] | None = None,
    user_capital_intent: dict[str, Any] | None = None,
    full_decision_intent: dict[str, Any] | None = None,
    previous_capital_reconciliation: dict[str, Any] | None = None,
    previous_capital_at_ms: int | None = None,
    previous_full_decision_intent: dict[str, Any] | None = None,
    dvol_regime_runner: Callable[..., dict[str, Any]] | None = None,
    transition_diagnostic_runner: Callable[..., dict[str, Any]] | None = None,
    btc_entry_gate_context: dict[str, Any] | None = None,
    btc_entry_gate_runner: Callable[..., dict[str, Any]] | None = None,
    assumption_watch_context: dict[str, Any] | None = None,
    mstr_asst_market_health: dict[str, Any] | None = None,
    qualified_equity_daily_source: dict[str, Any] | None = None,
    issuer_ratio_observation: dict[str, Any] | None = None,
    issuer_announcement_wake: dict[str, Any] | None = None,
    institutional_flow_context: dict[str, Any] | None = None,
    previous_season_transition_overlay: dict[str, Any] | None = None,
    season_transition_replay_context: dict[str, Any] | None = None,
    btc_control_transfer_validation_evidence: dict[str, Any] | None = None,
    acceptance_wake_operational_percentile: float | None = None,
    liquidation_research_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if issuer_ct_archive is not None:
        if treasury_company_ct_inputs is not None:
            raise ValueError("Supply retained issuer archive or normalized CT inputs, not both")
        from .issuer_ratio_market_health_source import build_archived_issuer_ct_inputs
        treasury_company_ct_inputs = build_archived_issuer_ct_inputs(
            issuer_ct_archive, as_of_ms=generated_at_ms if generated_at_ms is not None else (now_ms if now_ms is not None else int(time.time() * 1000)))
    source_gate = run_source_gate(
        registry,
        fetch_overrides=fetch_overrides,
        liquidation_aggregate_payload=liquidation_aggregate_payload,
        probe_fetcher=probe_fetcher,
        now_ms=now_ms,
    )
    source_gate = apply_runtime_checks(source_gate, runtime_checks)
    # One evaluation clock and one captured account snapshot serve the wake,
    # reconciliation, Evidence Pack and later capital-source binding.
    if generated_at_ms is None:
        generated_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    retained = ((private_context or {}).get("profile", {}).get("capital_reconciliation") or {})
    current_capital = None
    if broker_capital_observation is not None or user_capital_intent is not None or retained:
        from .broker_capital_observation import adapt_capital_intent, reconcile_capital
        from .private_profile import apply_broker_capital_state
        broker_capital_observation = (broker_capital_observation if broker_capital_observation is not None
                                      else retained.get("broker_observed"))
        user_capital_intent = (user_capital_intent if user_capital_intent is not None
                               else retained.get("user_confirmed"))
        intent_adapter = adapt_capital_intent(user_capital_intent, full_decision_intent)
        full_decision_intent = intent_adapter["full_decision_intent"]
        current_capital = reconcile_capital(broker_capital_observation, user_capital_intent, at_ms=generated_at_ms)
        private_context = apply_broker_capital_state(private_context, current_capital)
        private_context["profile"]["full_decision_intent"] = full_decision_intent
    recorded_at_ms = int(generated_at_ms) if generated_at_ms is not None else None
    current_observations = extract_observations(source_gate, recorded_at_ms=recorded_at_ms)

    dvol_now_ms = generated_at_ms if generated_at_ms is not None else now_ms
    if dvol_regime_runner is None:
        dvol_regime_watch = blocked_dvol_regime_watch(
            "DVOL_REGIME_RUNNER_NOT_CONFIGURED"
        )
    else:
        try:
            dvol_regime_watch = dvol_regime_runner(now_ms=dvol_now_ms)
        except Exception as exc:
            dvol_regime_watch = blocked_dvol_regime_watch(
                "DVOL_REGIME_RUNNER_FAILED",
                error=f"{type(exc).__name__}:{exc}",
            )

    (
        wake_operational_percentile,
        acceptance_override_metadata,
    ) = _resolve_wake_operational_percentile(
        dvol_regime_watch,
        acceptance_wake_operational_percentile,
    )

    btc_rows = [
        row
        for row in current_observations
        if row.input_family == "BTC_SPOT_PRICE" and row.metric == "btc_spot_price_usd"
    ]
    if btc_rows:
        current_btc = max(btc_rows, key=lambda row: row.as_of_ms)
        with ObservationStore(observation_db) as store:
            reanalysis_wake = run_intraday_reanalysis(
                store,
                current_btc,
                operational_percentile=wake_operational_percentile,
            )
    else:
        reanalysis_wake = {
            "state": "NO_WAKE",
            "reason": "BTC_SPOT_OBSERVATION_UNAVAILABLE",
            "metric": "btc_spot_price_usd",
            "input_family": "BTC_SPOT_PRICE",
            "current_value": None,
            "previous_value": None,
            "percent_change": None,
            "historical_percentile": None,
            "baseline_count": 0,
            "operational_percentile": wake_operational_percentile,
            "analyst_reanalysis_requested": False,
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
    if (
        dvol_regime_watch.get("state") == "EXPANSION_ACTIVATED"
        and reanalysis_wake.get("state") != "REANALYSIS_REQUESTED"
    ):
        reanalysis_wake = {
            "state": "REANALYSIS_REQUESTED",
            "reason": "DVOL_EXPANSION_ACTIVATED",
            "metric": "btc_dvol",
            "input_family": "BTC_DVOL_RESEARCH",
            "current_value": dvol_regime_watch.get("current_dvol"),
            "previous_value": dvol_regime_watch.get("dvol_30d_low"),
            "percent_change": dvol_regime_watch.get(
                "rebound_from_30d_low_pct"
            ),
            "historical_percentile": dvol_regime_watch.get(
                "level_percentile_1y"
            ),
            "baseline_count": dvol_regime_watch.get(
                "baseline_count",
                0,
            ),
            "operational_percentile": wake_operational_percentile,
            "analyst_reanalysis_requested": True,
            "direction": "UNKNOWN",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }

    if acceptance_override_metadata is not None:
        reanalysis_wake["acceptance_override"] = (
            acceptance_override_metadata
        )

    if current_capital is not None:
        from .reanalysis_wake import apply_capital_reanalysis_wake
        reanalysis_wake = apply_capital_reanalysis_wake(
            reanalysis_wake, current_capital, at_ms=generated_at_ms,
            previous_reconciliation=previous_capital_reconciliation,
            previous_at_ms=previous_capital_at_ms,
            decision_intent=full_decision_intent,
            previous_decision_intent=previous_full_decision_intent,
        )

    if liquidation_research_candidate is not None:
        from .reanalysis_wake import apply_liquidation_research_wake
        with ObservationStore(observation_db) as store:
            reanalysis_wake = apply_liquidation_research_wake(
                reanalysis_wake, store=store, candidate=liquidation_research_candidate,
                source_gate=source_gate, snapshot=liquidation_aggregate_payload,
                registry=registry, at_ms=generated_at_ms,
            )

    if reanalysis_wake["state"] == "REANALYSIS_REQUESTED":
        if transition_diagnostic_runner is None:
            transition_diagnostic = blocked_transition_diagnostic(
                "DIAGNOSTIC_RUNNER_NOT_CONFIGURED"
            )
        else:
            transition_diagnostic = transition_diagnostic_runner(
                wake=reanalysis_wake,
                liquidation_snapshot=liquidation_aggregate_payload,
                now_ms=generated_at_ms if generated_at_ms is not None else now_ms,
            )
    else:
        transition_diagnostic = not_requested_transition_diagnostic(
            "REANALYSIS_WAKE_NOT_REQUESTED"
        )

    btc_entry_gate = None
    if btc_entry_gate_runner is not None:
        btc_entry_gate = btc_entry_gate_runner(
            transition_diagnostic=transition_diagnostic,
            research_context=btc_entry_gate_context or {
                "state": "BLOCKED",
                "reason": "BTC_ENTRY_GATE_RESEARCH_CONTEXT_NOT_SUPPLIED",
            },
            now_ms=generated_at_ms if generated_at_ms is not None else now_ms,
        )

    btc_long_horizon_context = (
        build_btc_long_horizon_context(
            btc_long_horizon_inputs
        )
        if btc_long_horizon_inputs is not None
        else None
    )

    return build_evidence_pack(
        source_gate,
        observation_db=observation_db,
        generated_at_ms=generated_at_ms,
        reflexivity_input=reflexivity_input,
        treasury_valuation_inputs=treasury_valuation_inputs if treasury_valuation_inputs is not None else {},
        treasury_company_ct_inputs=treasury_company_ct_inputs,
        btc_long_horizon_context=btc_long_horizon_context,
        portfolio_allocation_inputs=portfolio_allocation_inputs,
        fixed_income_inputs=fixed_income_inputs,
        btc_etf_archive=btc_etf_archive,
        dvol_regime_watch=dvol_regime_watch,
        reanalysis_wake=reanalysis_wake,
        transition_diagnostic=transition_diagnostic,
        btc_entry_gate=btc_entry_gate,
        assumption_watch_context=assumption_watch_context,
        private_context=private_context,
        broker_capital_observation=broker_capital_observation,
        user_capital_intent=user_capital_intent,
        mstr_asst_market_health=mstr_asst_market_health,
        qualified_equity_daily_source=qualified_equity_daily_source,
        issuer_ratio_observation=issuer_ratio_observation,
        issuer_announcement_wake=issuer_announcement_wake,
        institutional_flow_context=institutional_flow_context,
        previous_season_transition_overlay=previous_season_transition_overlay,
        season_transition_replay_context=season_transition_replay_context,
        btc_control_transfer_validation_evidence=(
            btc_control_transfer_validation_evidence
        ),
    )


def _load_liquidation_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return load_verified_snapshot(path)
    except SnapshotCorruption:
        return None


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} cannot be loaded: {type(exc).__name__}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _load_previous_evidence_pack(path: Path) -> dict[str, Any] | None:
    """Use the previous authenticated pack as a historical comparison only."""
    if not path.exists():
        return None
    try:
        pack = _load_json_object(path, label="Previous Evidence Pack")
        from .capital_decision_closure import digest
        if pack.get("evidence_pack_hash") != digest({k: v for k, v in pack.items() if k != "evidence_pack_hash"}):
            return None
        return pack
    except (ValueError, TypeError):
        return None


def _daily_capital_posture(pack, inputs, *, at_ms):
    """Compose from original records; never rebind an old context or user rail."""
    from . import capital_decision_closure as c
    from .capital_posture_context import build_capital_posture_context, seasonal_capital_rail
    from .commander_plan_adapter import CommanderPlanBlocked
    context = None
    try:
        c.require(not ("posture_inputs" in inputs and "posture_context" in inputs),
                  "DAILY_POSTURE_INPUTS_AMBIGUOUS")
        if "posture_inputs" in inputs:
            raw = inputs["posture_inputs"]
            c.require(isinstance(raw, dict) and raw.get("as_of_ms") == at_ms,
                      "DAILY_POSTURE_CLOCK_MISMATCH")
            context = build_capital_posture_context(raw, pack)
        else:
            context = inputs.get("posture_context")
        if context is None:
            return None, {"state": "BLOCKED", "reason": "DAILY_POSTURE_INPUTS_NOT_SUPPLIED"}
        c.require(isinstance(context, dict)
                  and context.get("parent_evidence_pack_hash") == pack["evidence_pack_hash"]
                  and context.get("as_of_ms") == at_ms
                  and context.get("context_hash") == c.digest({k: v for k, v in context.items() if k != "context_hash"}),
                  "DAILY_POSTURE_LINEAGE_OR_CLOCK_INVALID")
        c.require(context.get("schema_version") == "CRT_CAPITAL_POSTURE_CONTEXT_V0.1"
                  and context.get("storage") == "LOCAL_ONLY"
                  and all(context.get(key) == value for key, value in c.LOCKS.items()),
                  "DAILY_POSTURE_AUTHORITY_INVALID")
        supporting = context.get("supporting_evidence", {})
        c.require(supporting.get("company_health") == pack.get("common_equity_health", {})
                  and supporting.get("portfolio_allocation_source_hash") == c.digest(pack.get("portfolio_allocation_context", {})),
                  "DAILY_POSTURE_SUPPORTING_EVIDENCE_MISMATCH")
        rail = context.get("current_strategic_capital_posture", {})
        proof = rail.get("provenance", {})
        c.require(rail.get("state") == "READY_FOR_ANALYST"
                  and proof.get("recorded_by") == "USER"
                  and proof.get("parent_evidence_pack_hash") == pack["evidence_pack_hash"]
                  and proof.get("cycle_id") == context.get("cycle_id"),
                  "DAILY_POSTURE_CONFIRMED_CURRENT_RAIL_REQUIRED")
        c.require(rail == seasonal_capital_rail(proof, as_of=at_ms, parent_hash=pack["evidence_pack_hash"]),
                  "DAILY_POSTURE_RAIL_PROOF_INVALID")
        c.require(type(proof.get("valid_until_ms")) is int and at_ms < proof["valid_until_ms"],
                  "DAILY_POSTURE_EXPIRED")
        return context, {"state": "READY_FOR_ANALYST", "context_hash": context["context_hash"],
                         "parent_evidence_pack_hash": pack["evidence_pack_hash"]}
    except (ValueError, KeyError, TypeError, AttributeError, CommanderPlanBlocked) as exc:
        return None, {"state": "BLOCKED", "reason": str(exc), "context": context}


def build_daily_capital_source(
    pack: dict[str, Any], payload: dict[str, Any], *,
    handoff: dict[str, Any],
    broker_observation: dict[str, Any] | None,
    user_capital_intent: dict[str, Any] | None,
    decision_inputs: dict[str, Any], source_main_sha: str, at_ms: int,
) -> dict[str, Any]:
    """Bind one day's existing source assembler to the same local account proof.

    This local wrapper adds provenance, not a second capital engine. Missing
    fee/instrument/cash permissions remain absent facts in the existing source;
    each affected claim is blocked by the existing deterministic validator.
    """
    from . import capital_decision_closure as c
    from .broker_capital_observation import MAX_AGE_MS, adapt_capital_intent, reconcile_capital
    result = {"state": "BLOCKED", "storage": "LOCAL_ONLY", "source": None,
              "blockers": [], "production": "NOT_APPROVED", "external_action_authority": "NONE",
              "capital_decision_authority": "USER_ONLY", "machine_execution": "FORBIDDEN"}
    try:
        c.require(type(at_ms) is int and pack.get("generated_at_ms") == at_ms, "DAILY_SOURCE_CLOCK_MISMATCH")
        c.require(pack.get("evidence_pack_hash") == c.digest({k: v for k, v in pack.items() if k != "evidence_pack_hash"}),
                  "DAILY_EVIDENCE_HASH_INVALID")
        c.require(payload.get("event", {}).get("source_evidence_pack_hash") == pack["evidence_pack_hash"],
                  "DAILY_BRIDGE_EVIDENCE_MISMATCH")
        expected = reconcile_capital(broker_observation, user_capital_intent, at_ms=at_ms)
        supplied = pack.get("private_context", {}).get("profile", {}).get("capital_reconciliation")
        c.require(supplied == expected, "DAILY_RECONCILIATION_IDENTITY_MISMATCH")
        from .gpt_handoff import _bridge_capital_state
        c.require(payload.get("capital_state") == _bridge_capital_state(pack.get("private_context"), generated_at_ms=at_ms),
                  "DAILY_BRIDGE_CAPITAL_MISMATCH")
        from .gpt_handoff import build_full_decision_bridge_payload
        c.require(payload == build_full_decision_bridge_payload(pack, handoff), "DAILY_BRIDGE_PROJECTION_MISMATCH")
        c.require(isinstance(decision_inputs, dict), "FULL_DECISION_INPUTS_REQUIRED")
        c.require(set(decision_inputs) <= {"user_intent", "qualification", "instruments", "fees", "task",
                                         "evidence_validity", "posture_context", "posture_inputs"}, "FULL_DECISION_INPUTS_FIELDS_INVALID")
        c.require("task" in decision_inputs and "evidence_validity" in decision_inputs, "FULL_DECISION_TASK_AND_VALIDITY_REQUIRED")
        adapter = adapt_capital_intent(user_capital_intent, decision_inputs.get("user_intent"))
        c.require("CAPITAL_INTENT_IDENTITY_MISMATCH" not in adapter["blockers"], "CAPITAL_INTENT_IDENTITY_MISMATCH")
        q = decision_inputs.get("qualification")
        if q is not None:
            c.require(q.get("observation_hash") == (expected.get("broker_observed") or {}).get("observation_hash"),
                      "QUALIFICATION_SNAPSHOT_MISMATCH")
        c.fresh(decision_inputs["evidence_validity"], at_ms)
        posture, posture_binding = _daily_capital_posture(pack, decision_inputs, at_ms=at_ms)
        result["posture_binding"] = posture_binding
        source = c.build_source(payload=payload, source_main_sha=source_main_sha,
            broker_observation=expected.get("broker_observed"), user_intent=adapter["full_decision_intent"],
            qualification=q, instruments=decision_inputs.get("instruments", []), fees=decision_inputs.get("fees", []),
            task=decision_inputs["task"], evidence_validity=decision_inputs["evidence_validity"],
            posture_context=posture, at_ms=at_ms)
        projection = c.build_projection(payload, source, at_ms=at_ms)
        clocks = [source["task"]["valid_until_ms"], source["evidence_validity"]["valid_until_ms"]]
        if posture is not None:
            clocks.append(posture["current_strategic_capital_posture"]["provenance"]["valid_until_ms"])
        broker = source["broker_observation"]
        if broker is not None:
            clocks.append(broker["observed_at_ms"] + MAX_AGE_MS)
        if q is not None:
            clocks.append(q["valid_until_ms"])
        result.update(state="SOURCE_BOUND", source=source, source_hash=c.source_hash(source),
            binding={"evidence_pack_hash": pack["evidence_pack_hash"], "bridge_payload_hash": payload["bridge_payload_hash"],
                     "broker_observation_hash": (broker or {}).get("observation_hash"),
                     "reconciliation_hash": c.digest(expected), "as_of_ms": at_ms, "valid_until_ms": min(clocks)},
            claim_states={"spending_cap": projection["spending_cap"]}, blockers=adapter["blockers"])
        if posture_binding["state"] == "BLOCKED":
            result["blockers"].append(posture_binding["reason"])
        if projection["spending_cap"]["state"] == "BLOCKED":
            result["blockers"].append(projection["spending_cap"]["reason"])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        result["blockers"] = [str(exc)]
    return result


def _load_previous_season_transition_overlay(
    evidence_pack_path: Path,
) -> dict[str, Any] | None:
    if not evidence_pack_path.exists():
        return None
    try:
        payload = _load_json_object(
            evidence_pack_path,
            label="Previous Evidence Pack",
        )
    except ValueError:
        return None
    supplied_hash = payload.get("evidence_pack_hash")
    material = dict(payload)
    material.pop("evidence_pack_hash", None)
    calculated_hash = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if supplied_hash != calculated_hash:
        return None
    overlay = payload.get("season_transition_warning_overlay")
    if not isinstance(overlay, dict):
        return None
    return (
        overlay
        if not validate_season_transition_warning_overlay(overlay)
        else None
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the first lean CRT Evidence Pack from the existing Source Gate.")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("--liquidation-snapshot", type=Path, default=default_liquidation_snapshot_path())
    parser.add_argument("--observation-db", type=Path, default=default_observation_db_path())
    parser.add_argument("--output", type=Path, default=default_evidence_pack_path())
    parser.add_argument("--private-profile", type=Path, default=default_private_profile_path())
    capital_source = parser.add_mutually_exclusive_group()
    capital_source.add_argument("--broker-capital-observation", type=Path,
                                help="Retained, hash-bound broker observation; its original clock is preserved.")
    capital_source.add_argument("--observe-broker-capital", action="store_true",
                                help="Read current capital from existing local TWS, without order authority.")
    parser.add_argument("--user-capital-intent", type=Path,
                        help="Private USER_CONFIRMED reserve and cancellation facts; never infer from old plans.")
    parser.add_argument("--capital-decision-inputs", type=Path,
                        help="LOCAL_ONLY explicit full-decision intent, qualifications, fees, task and validity; no inferred facts.")
    parser.add_argument("--capital-source-output", type=Path,
                        help="LOCAL_ONLY source binding status; per-event sources are immutable beside this file.")
    parser.add_argument("--source-main-sha", type=str,
                        help="Verified engineering source commit for full-decision source binding.")
    parser.add_argument("--treasury-valuation-inputs", type=Path, default=None,
        help="Local verified CT histories for MSTR/ASST; absent claims remain BLOCKED.")
    parser.add_argument("--btc-etf-archive", type=Path, default=None,
        help="Exact TFTC JSON retrieval envelope; research-only flow evidence.")
    parser.add_argument("--treasury-company-ct-inputs", type=Path, default=None,
        help="Local verified CT organs keyed by MSTR/ASST; company health evidence only.")
    parser.add_argument("--fixed-income-inputs", type=Path, default=None,
                        help="Read-only sourced dividend ledger, entitlements, tax, goal and forecast assumptions")
    parser.add_argument("--portfolio-allocation-inputs", type=Path, default=None,
        help="Local season/allocation/side-job context; no trade or Season Router authority.")
    parser.add_argument(
        "--btc-long-horizon-inputs",
        type=Path,
        default=None,
        help=(
            "Optional local research-only BTC weekly/cycle "
            "context; no formal price-target or trade authority."
        ),
    )
    parser.add_argument(
        "--btc-entry-context",
        type=Path,
        default=default_btc_entry_gate_context_path(),
        help="Research-only event-scoped BTC transition corridor. Never a formal threshold.",
    )
    parser.add_argument(
        "--assumption-context",
        type=Path,
        default=default_assumption_watch_context_path(),
        help="Local/private research assumptions and invalidation rules. Never formal model authority.",
    )
    parser.add_argument("--wake-output", type=Path, default=None)
    parser.add_argument("--notice-output", type=Path, default=None)
    parser.add_argument("--handoff-output", type=Path, default=None)
    parser.add_argument("--handoff-ledger", type=Path, default=None)
    parser.add_argument("--bridge-outbox-dir", type=Path, default=None)
    parser.add_argument(
        "--acceptance-wake-percentile",
        type=float,
        default=None,
        help=(
            "One-shot transport-acceptance-only BTC wake percentile. "
            "Does not change persisted production wake policy."
        ),
    )
    parser.add_argument(
        "--confirm-acceptance-wake-override",
        action="store_true",
        help=(
            "Required acknowledgement for --acceptance-wake-percentile."
        ),
    )
    parser.add_argument(
        "--mstr-asst-market-health",
        type=Path,
        default=None,
        help=(
            "Optional local-only validated MSTR/ASST Market Health V0.1 "
            "snapshot to fuse into Evidence Pack and GPT Wake."
        ),
    )
    parser.add_argument("--qualified-equity-daily-source", type=Path, default=None,
        help="Read-only retained IBKR daily close proof; original source clocks are preserved.")
    parser.add_argument(
        "--season-transition-flow-context",
        type=Path,
        default=None,
        help=(
            "Optional research-only 1D/5D/20D/60D/120D institutional "
            "flow context; no formal threshold authority."
        ),
    )
    parser.add_argument(
        "--season-transition-replay-context",
        type=Path,
        default=None,
        help=(
            "Optional historical replay ground truth for detection-latency "
            "and false-positive evaluation."
        ),
    )
    parser.add_argument(
        "--btc-control-transfer-validation-evidence",
        type=Path,
        default=None,
        help=(
            "Optional research-only post-candidate control-transfer "
            "validation evidence."
        ),
    )
    parser.add_argument("--maturity-ledger", type=Path, default=None)
    parser.add_argument("--maturity-status", type=Path, default=None)
    parser.add_argument(
        "--phone-l4-freshness-path",
        type=Path,
        default=None,
        help="Optional Mobile L4 handoff file whose local mtime is checked before the Evidence Pack is built.",
    )
    parser.add_argument(
        "--phone-l4-max-age-seconds",
        type=int,
        default=300,
        help="Transport-only freshness limit for --phone-l4-freshness-path. Source-level freshness remains authoritative.",
    )
    parser.add_argument("--issuer-ratio-proof", type=Path, default=None,
        help="Existing sealed issuer proof; independent reported observation lane, no Commander requirement.")
    parser.add_argument(
        "--issuer-announcement-wake",
        type=Path,
        default=None,
        help="Fresh official issuer-announcement radar output for Evidence/Wake fusion.",
    )
    parser.add_argument("--issuer-ct-archive", type=Path, default=None,
        help="Read-only retained official SEC archive; four-clock CT binding, no collection.")
    args = parser.parse_args(argv)

    if (
        args.acceptance_wake_percentile is not None
        and not args.confirm_acceptance_wake_override
    ):
        raise ValueError(
            "--acceptance-wake-percentile requires "
            "--confirm-acceptance-wake-override"
        )

    if (
        (args.handoff_output is None)
        != (args.handoff_ledger is None)
    ):
        raise ValueError(
            "--handoff-output and --handoff-ledger "
            "must be supplied together"
        )

    if (
        args.bridge_outbox_dir is not None
        and args.handoff_output is None
    ):
        raise ValueError(
            "--bridge-outbox-dir requires "
            "--handoff-output and --handoff-ledger"
        )

    if args.capital_decision_inputs is not None and (
        args.capital_source_output is None or args.source_main_sha is None or args.bridge_outbox_dir is None
    ):
        raise ValueError("--capital-decision-inputs requires --capital-source-output, --source-main-sha and --bridge-outbox-dir")

    registry = SourceRegistry.load(args.registry)
    liquidation_payload = _load_liquidation_snapshot(args.liquidation_snapshot)
    runtime_checks: list[dict[str, Any]] = []
    if args.phone_l4_freshness_path is not None:
        runtime_checks.append(
            assess_file_freshness(
                args.phone_l4_freshness_path,
                max_age_seconds=args.phone_l4_max_age_seconds,
                reason_prefix="PHONE_L4",
            )
        )

    private_context = load_private_profile(args.private_profile,
        include_capital_sidecars=not (args.observe_broker_capital or args.broker_capital_observation is not None
                                     or args.user_capital_intent is not None))
    broker_observation = None
    if args.observe_broker_capital:
        from .broker_capital_observation import BLOCKED_BROKER_REASONS, capture_ibkr_capital
        try:
            broker_observation = capture_ibkr_capital()
        except Exception as exc:
            # Preserve the capital failure without suppressing unrelated market analysis.
            reason = ("BROKER_SDK_UNAVAILABLE" if isinstance(exc, ImportError) else
                      "BROKER_CONNECT_UNAVAILABLE" if isinstance(exc, (OSError, TimeoutError)) else
                      str(exc) if str(exc) in BLOCKED_BROKER_REASONS else "BROKER_OBSERVATION_INVALID")
            broker_observation = {"capture_failed": True, "reason": reason}
    elif args.broker_capital_observation is not None:
        broker_observation = _load_json_object(args.broker_capital_observation, label="Broker capital observation")
    capital_intent = (_load_json_object(args.user_capital_intent, label="User capital intent")
                      if args.user_capital_intent is not None else None)
    decision_inputs = (_load_json_object(args.capital_decision_inputs, label="Full capital decision inputs")
                       if args.capital_decision_inputs is not None else None)
    previous_pack = _load_previous_evidence_pack(args.output)
    previous_profile = (previous_pack or {}).get("private_context", {}).get("profile", {})
    btc_entry_gate_context = load_btc_entry_gate_context(args.btc_entry_context)
    assumption_watch_context = load_assumption_watch_context(args.assumption_context)
    mstr_asst_market_health = (
        _load_json_object(
            args.mstr_asst_market_health,
            label="MSTR/ASST Market Health",
        )
        if args.mstr_asst_market_health is not None
        else None
    )
    qualified_equity_daily_source = (
        _load_json_object(args.qualified_equity_daily_source, label="Qualified equity daily source")
        if args.qualified_equity_daily_source is not None else None
    )
    institutional_flow_context = (
        _load_json_object(
            args.season_transition_flow_context,
            label="Season Transition Institutional Flow Context",
        )
        if args.season_transition_flow_context is not None
        else None
    )
    season_transition_replay_context = (
        _load_json_object(
            args.season_transition_replay_context,
            label="Season Transition Historical Replay Context",
        )
        if args.season_transition_replay_context is not None
        else None
    )
    btc_control_transfer_validation_evidence = (
        _load_json_object(
            args.btc_control_transfer_validation_evidence,
            label="BTC Control Transfer Validation Evidence",
        )
        if args.btc_control_transfer_validation_evidence is not None
        else None
    )
    previous_season_transition_overlay = (
        _load_previous_season_transition_overlay(args.output)
    )
    issuer_observation = None
    if args.issuer_ratio_proof is not None:
        from .mstr_asst_market_health import build_issuer_ratio_observation
        issuer_observation = build_issuer_ratio_observation(
            _load_json_object(args.issuer_ratio_proof, label="Issuer ratio source proof"),
            generated_at_ms=int(time.time() * 1000),
        )
    issuer_announcement = (
        _load_json_object(
            args.issuer_announcement_wake,
            label="Issuer announcement wake",
        )
        if args.issuer_announcement_wake is not None
        else None
    )
    pack = run_daily_evidence(
        registry,
        observation_db=args.observation_db,
        liquidation_aggregate_payload=liquidation_payload,
        probe_fetcher=probe_liquidation_stream,
        runtime_checks=runtime_checks,
        private_context=private_context,
        broker_capital_observation=broker_observation,
        user_capital_intent=capital_intent,
        full_decision_intent=(decision_inputs or {}).get("user_intent"),
        previous_capital_reconciliation=previous_profile.get("capital_reconciliation"),
        previous_capital_at_ms=(previous_pack or {}).get("generated_at_ms"),
        previous_full_decision_intent=previous_profile.get("full_decision_intent"),
        treasury_valuation_inputs=(
            _load_json_object(args.treasury_valuation_inputs, label="Treasury valuation inputs")
            if args.treasury_valuation_inputs is not None else {}
        ),
        issuer_ct_archive=args.issuer_ct_archive,
        treasury_company_ct_inputs=(
            _load_json_object(args.treasury_company_ct_inputs, label="Treasury Company CT inputs")
            if args.treasury_company_ct_inputs is not None else None
        ),
        btc_etf_archive=(_load_json_object(args.btc_etf_archive, label="BTC ETF archive")
            if args.btc_etf_archive is not None else None),
        fixed_income_inputs=(
            _load_json_object(args.fixed_income_inputs, label="Fixed income inputs")
            if args.fixed_income_inputs is not None else None
        ),
        portfolio_allocation_inputs=(
            _load_json_object(args.portfolio_allocation_inputs, label="Portfolio allocation inputs")
            if args.portfolio_allocation_inputs is not None else None
        ),
        btc_long_horizon_inputs=(
            _load_json_object(
                args.btc_long_horizon_inputs,
                label="BTC long-horizon inputs",
            )
            if args.btc_long_horizon_inputs is not None
            else None
        ),
        dvol_regime_runner=run_live_dvol_regime_watch,
        transition_diagnostic_runner=run_live_btc_transition_diagnostics,
        btc_entry_gate_context=btc_entry_gate_context,
        btc_entry_gate_runner=run_live_btc_entry_gate,
        assumption_watch_context=assumption_watch_context,
        mstr_asst_market_health=mstr_asst_market_health,
        qualified_equity_daily_source=qualified_equity_daily_source,
        issuer_ratio_observation=issuer_observation,
        issuer_announcement_wake=issuer_announcement,
        institutional_flow_context=institutional_flow_context,
        previous_season_transition_overlay=(
            previous_season_transition_overlay
        ),
        season_transition_replay_context=(
            season_transition_replay_context
        ),
        btc_control_transfer_validation_evidence=(
            btc_control_transfer_validation_evidence
        ),
        acceptance_wake_operational_percentile=(
            args.acceptance_wake_percentile
        ),
    )
    write_json_atomic(args.output, pack)
    if args.wake_output is not None:
        write_json_atomic(args.wake_output, pack["reanalysis_wake"])

    notice = None
    if (
        args.notice_output is not None
        or args.handoff_output is not None
    ):
        notice = build_plain_language_notice(pack)

    if args.notice_output is not None:
        assert notice is not None
        write_json_atomic(
            args.notice_output,
            notice,
        )

    handoff = None
    if args.handoff_output is not None:
        assert notice is not None
        assert args.handoff_ledger is not None

        handoff = run_gpt_handoff_gate(
            pack,
            notice,
            ledger_path=args.handoff_ledger,
            bridge_outbox_dir=args.bridge_outbox_dir,
            full_decision=decision_inputs is not None,
        )

        write_json_atomic(
            args.handoff_output,
            handoff,
        )

    if args.capital_source_output is not None:
        bound = {"state": "BLOCKED", "storage": "LOCAL_ONLY", "source": None,
                 "blockers": ["FULL_DECISION_INPUTS_NOT_SUPPLIED"], "production": "NOT_APPROVED",
                 "external_action_authority": "NONE", "capital_decision_authority": "USER_ONLY",
                 "machine_execution": "FORBIDDEN"}
        if decision_inputs is not None:
            if handoff is None or handoff.get("append_status") != "APPENDED":
                bound["blockers"] = ["NO_NEW_FULL_DECISION_EVENT_SOURCE_NOT_REBOUND"]
            else:
                event_id = handoff["event_id"]
                payload = _load_json_object(args.bridge_outbox_dir / f"{event_id}.json", label="Current full decision bridge")
                bound = build_daily_capital_source(pack, payload, broker_observation=broker_observation,
                    handoff=handoff,
                    user_capital_intent=capital_intent, decision_inputs=decision_inputs,
                    source_main_sha=args.source_main_sha, at_ms=pack["generated_at_ms"])
                if bound["source"] is not None:
                    target = args.capital_source_output.parent / "sources" / f"{event_id}.json"
                    if target.exists():
                        if _load_json_object(target, label="Existing capital source") != bound["source"]:
                            raise ValueError("Existing event capital source must not be rebound")
                    else:
                        write_json_atomic(target, bound["source"])
                    bound["event_id"] = event_id
                    bound["source_path"] = str(target)
        write_json_atomic(args.capital_source_output, bound)

    if (args.maturity_ledger is None) != (args.maturity_status is None):
        raise ValueError("--maturity-ledger and --maturity-status must be supplied together")
    if args.maturity_ledger is not None and args.maturity_status is not None:
        record_maturity_attempt(args.maturity_ledger, args.maturity_status, pack)
    print(json.dumps(pack, ensure_ascii=False, indent=2))

    return 0 if pack.get("pack_state") in {"READY_FOR_ANALYST", "PARTIAL_FOR_ANALYST", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
