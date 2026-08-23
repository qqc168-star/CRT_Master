from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.gpt_bridge_outbox import (
    BRIDGE_PRIVACY_CONTRACT_VERSION,
    BRIDGE_SCHEMA_VERSION,
    enqueue_bridge_payload,
)
from crt_radar.gpt_transport_boundary import (
    PENDING_REASON,
    build_pending_state,
    claim_delivery,
    ensure_pending_boundary_state,
    mark_delivered,
    mark_retryable,
    sync_transport_boundary,
)


def canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bridge_payload(
    *,
    event_id: str = "a" * 64,
    marker: str = "A",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "privacy_contract_version": BRIDGE_PRIVACY_CONTRACT_VERSION,
        "state": "BRIDGE_PAYLOAD_READY_LOCAL_ONLY",
        "event": {"event_id": event_id},
        "analysis": {"marker": marker},
        "authority": {
            "production": "NOT_APPROVED",
            "trading_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "transport_authority": "NONE",
            "transport_performed": False,
            "action_output": "NONE",
        },
        "privacy": {
            "mode": "MINIMIZED_ALLOWLIST_ONLY",
            "raw_private_context_included": False,
            "full_private_profile_included": False,
            "filesystem_paths_included": False,
            "broker_or_account_identifiers_included": False,
            "credentials_or_secrets_included": False,
            "transport_selected": False,
        },
    }
    payload["bridge_payload_hash"] = canonical_hash(payload)
    return payload


class TransportBoundaryTests(unittest.TestCase):
    def test_sync_creates_pending_boundary_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outbox = root / "outbox"
            state_dir = root / "boundary"

            payload = bridge_payload()
            enqueue_bridge_payload(outbox, payload)
            result = sync_transport_boundary(outbox, state_dir)

            self.assertEqual(result["created"], 1)
            self.assertEqual(result["existing"], 0)
            self.assertFalse(result["transport_configured"])
            self.assertFalse(result["transport_performed"])

            state_path = state_dir / f"{payload['event']['event_id']}.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "PENDING")
            self.assertEqual(state["reason"], PENDING_REASON)
            self.assertFalse(state["adapter_selected"])
            self.assertEqual(state["production"], "NOT_APPROVED")
            self.assertEqual(state["external_action_authority"], "NONE")
            self.assertEqual(state["action_output"], "NONE")

    def test_sync_is_idempotent_for_same_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outbox = root / "outbox"
            state_dir = root / "boundary"

            payload = bridge_payload()
            enqueue_bridge_payload(outbox, payload)
            first = sync_transport_boundary(outbox, state_dir)
            second = sync_transport_boundary(outbox, state_dir)

            self.assertEqual(first["created"], 1)
            self.assertEqual(second["created"], 0)
            self.assertEqual(second["existing"], 1)
            self.assertEqual(len(list(state_dir.glob("*.json"))), 1)

    def test_same_event_different_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "boundary"
            first = bridge_payload(event_id="a" * 64, marker="A")
            second = bridge_payload(event_id="a" * 64, marker="B")
            ensure_pending_boundary_state(state_dir, first)
            with self.assertRaises(ValueError):
                ensure_pending_boundary_state(state_dir, second)

    def test_outbox_filename_must_match_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outbox = root / "outbox"
            state_dir = root / "boundary"
            outbox.mkdir(parents=True)

            payload = bridge_payload()
            wrong = outbox / f"{'b' * 64}.json"
            wrong.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                sync_transport_boundary(outbox, state_dir)

    def test_claim_requires_selected_adapter(self) -> None:
        pending = build_pending_state(bridge_payload())
        with self.assertRaises(ValueError):
            claim_delivery(
                pending,
                adapter_id="synthetic-adapter",
                now_ms=1000,
                lease_ms=500,
                adapter_selected=False,
            )

    def test_live_claim_blocks_duplicate_until_expiry(self) -> None:
        pending = build_pending_state(bridge_payload())
        claimed = claim_delivery(
            pending,
            adapter_id="synthetic-adapter",
            now_ms=1000,
            lease_ms=500,
            adapter_selected=True,
        )
        self.assertEqual(claimed["state"], "CLAIMED")
        self.assertEqual(claimed["attempt_count"], 1)

        with self.assertRaises(ValueError):
            claim_delivery(
                claimed,
                adapter_id="synthetic-adapter",
                now_ms=1200,
                lease_ms=500,
                adapter_selected=True,
            )

        reclaimed = claim_delivery(
            claimed,
            adapter_id="synthetic-adapter",
            now_ms=1500,
            lease_ms=500,
            adapter_selected=True,
        )
        self.assertEqual(reclaimed["state"], "CLAIMED")
        self.assertEqual(reclaimed["attempt_count"], 2)
        self.assertNotEqual(
            claimed["claim"]["claim_token"],
            reclaimed["claim"]["claim_token"],
        )

    def test_retryable_requires_matching_claim_token(self) -> None:
        claimed = claim_delivery(
            build_pending_state(bridge_payload()),
            adapter_id="synthetic-adapter",
            now_ms=1000,
            lease_ms=500,
            adapter_selected=True,
        )

        with self.assertRaises(ValueError):
            mark_retryable(
                claimed,
                claim_token="wrong",
                reason="synthetic failure",
            )

        retryable = mark_retryable(
            claimed,
            claim_token=claimed["claim"]["claim_token"],
            reason="synthetic failure",
        )
        self.assertEqual(retryable["state"], "RETRYABLE")
        self.assertIsNone(retryable["claim"])
        self.assertFalse(retryable["adapter_selected"])

    def test_delivery_requires_matching_token_and_receipt(self) -> None:
        claimed = claim_delivery(
            build_pending_state(bridge_payload()),
            adapter_id="synthetic-adapter",
            now_ms=1000,
            lease_ms=500,
            adapter_selected=True,
        )

        with self.assertRaises(ValueError):
            mark_delivered(
                claimed,
                claim_token="wrong",
                receipt={"id": "receipt-1"},
            )

        with self.assertRaises(ValueError):
            mark_delivered(
                claimed,
                claim_token=claimed["claim"]["claim_token"],
                receipt={},
            )

        delivered = mark_delivered(
            claimed,
            claim_token=claimed["claim"]["claim_token"],
            receipt={"id": "receipt-1", "kind": "synthetic"},
        )
        self.assertEqual(delivered["state"], "DELIVERED")
        self.assertIsNone(delivered["claim"])
        self.assertEqual(delivered["receipt"]["id"], "receipt-1")

        with self.assertRaises(ValueError):
            claim_delivery(
                delivered,
                adapter_id="synthetic-adapter",
                now_ms=2000,
                lease_ms=500,
                adapter_selected=True,
            )

    def test_tampered_boundary_hash_fails_closed(self) -> None:
        pending = build_pending_state(bridge_payload())
        pending["attempt_count"] = 99
        with self.assertRaises(ValueError):
            claim_delivery(
                pending,
                adapter_id="synthetic-adapter",
                now_ms=1000,
                lease_ms=500,
                adapter_selected=True,
            )


if __name__ == "__main__":
    unittest.main()
