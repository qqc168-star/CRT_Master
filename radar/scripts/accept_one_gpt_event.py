"""Observe the existing runtime and accept one newly published real event.

This operational acceptance runner does not collect data, alter wake conditions,
create events, or implement transport. It calls the deployed transport worker once
and verifies its ordinary duplicate replay. A pending real market event is required.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crt_radar.daily_evidence_runner import write_json_atomic
from crt_radar.gpt_transport_boundary import _read_json, ensure_pending_boundary_state
from crt_radar.gpt_transport_worker import deliver_event, send_response, validate_transport_payload
from crt_radar.openai_responses_adapter_contract import (
    API_KEY_ENV_VAR, SMOKE_MODEL, build_request_envelope, build_delivery_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--wait-seconds", type=int, default=86400)
    args = parser.parse_args()
    if not os.environ.get(API_KEY_ENV_VAR):
        raise SystemExit("Credential unavailable")
    root = args.runtime_root
    outbox, states = root / "gpt_bridge/outbox", root / "gpt_bridge/transport_boundary"
    baseline = {p.name for p in outbox.glob("*.json")}
    started_ms = int(time.time() * 1000)
    deadline = time.monotonic() + args.wait_seconds
    report = {"state": "WAITING_FOR_NEW_QUALIFIED_EVENT", "started_at_ms": started_ms,
              "baseline_event_count": len(baseline), "generation_attempts": 0}
    write_json_atomic(args.output, report)
    while time.monotonic() < deadline:
        for path in sorted(outbox.glob("*.json")):
            if path.name in baseline:
                continue
            try:
                payload = _read_json(path)
                event_id, payload_hash = validate_transport_payload(payload)
                envelope = build_request_envelope(payload, model=SMOKE_MODEL)
                current = _read_json(root / "evidence/latest.json")
                if (current.get("generated_at_ms", 0) < started_ms or
                    current.get("evidence_pack_hash") != payload["event"]["source_evidence_pack_hash"] or
                    current.get("reanalysis_wake", {}).get("state") != "REANALYSIS_REQUESTED"):
                    continue
                ensure_pending_boundary_state(states, payload)
                before = _read_json(states / path.name)
                if before["state"] != "PENDING":
                    continue
            except (ValueError, KeyError):
                # No repairs or rewriting of an incompatible published record.
                continue
            override = current.get("reanalysis_wake", {}).get("acceptance_override", {})
            report.update({
                "acceptance_override_used": override.get("acceptance_override_used", False),
                "acceptance_wake_operational_percentile": override.get("acceptance_wake_operational_percentile"),
                "production_wake_operational_percentile": override.get(
                    "production_wake_operational_percentile",
                    current.get("reanalysis_wake", {}).get("operational_percentile")),
                "persistent_configuration_changed": override.get("persistent_configuration_changed", False),
            })
            report.update(event_id=event_id, bridge_payload_hash=payload_hash,
                          request_hash=envelope["request_hash"],
                          input_utf8_bytes=len(envelope["request_body"]["input"].encode("utf-8")),
                          source_evidence_pack_hash=current["evidence_pack_hash"],
                          state="PENDING", transition_states=["PENDING"])
            write_json_atomic(args.output, report)

            def transport(request):
                state = _read_json(states / path.name)
                if state["state"] != "CLAIMED" or state["request_hash"] != request["request_hash"]:
                    raise ValueError("Claim/request binding unavailable")
                report.update(state="CLAIMED", generation_attempts=1)
                report["transition_states"].append("CLAIMED")
                write_json_atomic(args.output, report)
                return send_response(request)

            first = deliver_event(path, states, transport=transport)
            report["first_run"] = first
            if first["state"] != "DELIVERED":
                report["state"] = "LIVE_ACCEPTANCE_REQUIRES_ATTENTION"
                write_json_atomic(args.output, report)
                return 1
            stored = _read_json(states / path.name)
            evidence = _read_json(states / "responses" / path.name)
            expected = build_delivery_receipt(evidence["response"], event_id=event_id,
                                             bridge_payload_hash=payload_hash,
                                             request_hash=envelope["request_hash"])
            if stored["receipt"] != expected or evidence["request"] != envelope:
                raise ValueError("Persisted delivery evidence mismatch")
            replay = deliver_event(path, states)
            if replay != {"event_id": event_id, "transport_performed": False,
                          "notification_eligible": False, "state": "ALREADY_DELIVERED"}:
                raise ValueError("Duplicate replay acceptance failed")
            report.update(state="LIVE_ACCEPTANCE_PASS", replay=replay,
                          response_id=expected["response_id"], response_hash=expected["response_hash"],
                          receipt_hash=expected["receipt_hash"], completed_at_ms=int(time.time() * 1000))
            report["transition_states"].append("DELIVERED")
            write_json_atomic(args.output, report)
            return 0
        time.sleep(5)
    report["state"] = "NO_NEW_QUALIFIED_EVENT_WITHIN_WINDOW"
    write_json_atomic(args.output, report)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
