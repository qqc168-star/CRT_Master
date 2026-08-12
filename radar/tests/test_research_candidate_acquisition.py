from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
ACQUISITION_MODULE_PATH = RESEARCH / "candidate_acquisition.py"
CANDIDATE_DATA_MODULE_PATH = RESEARCH / "candidate_data.py"
MODEL_REGISTRY_PATH = RESEARCH / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"
AUTHORITY_PATH = RESEARCH / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
FEASIBILITY_PATH = RESEARCH / "CRT_ETP_PUBLIC_REPLAY_FEASIBILITY_V0.1.json"
ACQUISITION_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1.json"
SOURCE_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
PROTOCOL_PATH = RESEARCH / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


candidate_data = _load_module("candidate_data_acquisition_tests", CANDIDATE_DATA_MODULE_PATH)


class ResearchCandidateAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.acquisition = _load_module("candidate_acquisition_tests", ACQUISITION_MODULE_PATH)
        cls.model_registry = json.loads(MODEL_REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        cls.feasibility = json.loads(FEASIBILITY_PATH.read_text(encoding="utf-8"))
        cls.acquisition_contract = json.loads(
            ACQUISITION_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        cls.source_contract = json.loads(SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    def _metadata(self, *, evidence_class: str = "CURRENT_FIRST_SEEN_CAPTURE") -> dict:
        first_seen_at_ms = 1_900_000_000_000
        is_current = evidence_class == "CURRENT_FIRST_SEEN_CAPTURE"
        return {
            "source_contract_id": "US_SPOT_BTC_ETP_POINT_IN_TIME",
            "request_identity": "GET https://issuer.example/ibit/snapshot",
            "retrieved_at_ms": first_seen_at_ms + 1_000,
            "first_seen_at_ms": first_seen_at_ms,
            "available_at_coverage_start_ms": (
                first_seen_at_ms if is_current else first_seen_at_ms - 86_400_000
            ),
            "available_at_coverage_end_ms": first_seen_at_ms,
            "integrity_proof_type": (
                "LOCAL_FIRST_SEEN_SHA256" if is_current else "PROVIDER_ARCHIVE_CHECKSUM"
            ),
            "provider_checksum": None if is_current else "a" * 64,
            "license_classification": "LOCAL_RESEARCH_ONLY",
            "source_authority_hash": candidate_data.canonical_hash(self.authority),
            "evidence_class": evidence_class,
            "replay_eligible": evidence_class != "SYNTHETIC_FIXTURE",
            "content_type": "application/json",
            "availability_proof_type": (
                "LOCAL_FIRST_SEEN_CAPTURE" if is_current else "IMMUTABLE_PROVIDER_ARCHIVE"
            ),
            "revision_of_sha256": None,
        }

    def test_etp_replay_probe_covers_three_hard_product_shapes_and_stays_blocked(self):
        self.assertEqual(
            candidate_data.validate_etp_replay_feasibility(
                self.feasibility,
                self.authority,
            ),
            [],
        )
        cases = {item["case_type"]: item for item in self.feasibility["representative_cases"]}
        self.assertEqual(
            set(cases),
            {"NEW_LAUNCH", "CONVERTED_TRUST", "LATE_LAUNCH_DISTRIBUTION_AND_SPLIT"},
        )
        self.assertEqual(cases["NEW_LAUNCH"]["ticker"], "IBIT")
        self.assertEqual(cases["NEW_LAUNCH"]["sec_cik"], "0001980994")
        self.assertEqual(cases["CONVERTED_TRUST"]["ticker"], "GBTC")
        self.assertEqual(cases["CONVERTED_TRUST"]["sec_cik"], "0001588489")
        self.assertEqual(cases["LATE_LAUNCH_DISTRIBUTION_AND_SPLIT"]["ticker"], "BTC")
        self.assertEqual(cases["LATE_LAUNCH_DISTRIBUTION_AND_SPLIT"]["sec_cik"], "0002015034")
        self.assertTrue(
            all(item["daily_historical_replay_state"] == "NOT_PROVEN_BLOCKED" for item in cases.values())
        )
        self.assertEqual(
            self.feasibility["result"]["historical_backfill_state"],
            "BLOCKED_NOT_PROVEN",
        )
        self.assertEqual(
            self.feasibility["result"]["prospective_capture_state"],
            "CONTRACT_READY_ADAPTERS_NOT_IMPLEMENTED",
        )

    def test_acquisition_contract_is_hash_bound_research_only_and_does_not_claim_data(self):
        self.assertEqual(
            candidate_data.validate_acquisition_contract(
                self.acquisition_contract,
                self.model_registry,
                self.authority,
                self.feasibility,
            ),
            [],
        )
        self.assertEqual(
            self.acquisition_contract["status"],
            "PROOF_SLICE_IMPLEMENTED_DATA_NOT_ACQUIRED",
        )
        self.assertEqual(self.acquisition_contract["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(
            self.acquisition_contract["authority"]["external_action_authority"],
            "NONE",
        )
        self.assertFalse(self.acquisition_contract["network_fetch_implemented"])
        self.assertFalse(self.acquisition_contract["dataset_readiness_granted"])

    def test_content_addressed_archive_is_idempotent_and_never_overwrites(self):
        raw = b'{"ticker":"IBIT","shares":1}'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self.acquisition.archive_artifact(root, raw, **self._metadata())
            second = self.acquisition.archive_artifact(root, raw, **self._metadata())
            path = root / first["archive_relpath"]

            self.assertEqual(first, second)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(first["sha256"], self.acquisition.sha256_bytes(raw))
            self.assertEqual(first["size_bytes"], len(raw))
            self.assertEqual(
                first["archive_relpath"],
                f'artifacts/sha256/{first["sha256"][:2]}/{first["sha256"]}',
            )

            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(
                self.acquisition.AcquisitionError,
                "ARCHIVE_EXISTING_BYTES_HASH_MISMATCH",
            ):
                self.acquisition.archive_artifact(root, raw, **self._metadata())

    def test_identical_source_bytes_cannot_rewrite_first_seen_history(self):
        raw = b'{"ticker":"IBIT","shares":1}'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self._metadata()
            self.acquisition.archive_artifact(root, raw, **first)

            replay = self._metadata()
            replay["retrieved_at_ms"] += 10_000
            same = self.acquisition.archive_artifact(root, raw, **replay)
            self.assertEqual(same["retrieved_at_ms"], first["retrieved_at_ms"])
            self.assertEqual(same["first_seen_at_ms"], first["first_seen_at_ms"])

            rewritten = self._metadata()
            rewritten["retrieved_at_ms"] += 10_000
            rewritten["first_seen_at_ms"] += 1_000
            rewritten["available_at_coverage_start_ms"] += 1_000
            rewritten["available_at_coverage_end_ms"] += 1_000
            with self.assertRaisesRegex(
                self.acquisition.AcquisitionError,
                "FIRST_SEEN_METADATA_CONFLICT",
            ):
                self.acquisition.archive_artifact(root, raw, **rewritten)

    def test_current_capture_cannot_be_backdated_and_fixture_cannot_be_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            backdated = self._metadata()
            backdated["available_at_coverage_start_ms"] -= 1
            with self.assertRaisesRegex(
                self.acquisition.AcquisitionError,
                "CURRENT_CAPTURE_CANNOT_PROVE_EARLIER_AVAILABILITY",
            ):
                self.acquisition.archive_artifact(Path(td), b"current", **backdated)

            fixture = self._metadata(evidence_class="SYNTHETIC_FIXTURE")
            fixture["replay_eligible"] = True
            with self.assertRaisesRegex(
                self.acquisition.AcquisitionError,
                "SYNTHETIC_FIXTURE_CANNOT_BE_REPLAY_ELIGIBLE",
            ):
                self.acquisition.archive_artifact(Path(td), b"fixture", **fixture)

    def test_manifest_is_deterministic_hash_bound_and_verifies_archive_bytes(self):
        raw = b'{"ticker":"IBIT","as_of":"2026-08-11"}'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = self.acquisition.archive_artifact(root, raw, **self._metadata())
            manifest = self.acquisition.build_dataset_manifest(
                [artifact],
                candidate_registry_hash=candidate_data.canonical_hash(self.model_registry),
                public_source_authority_hash=candidate_data.canonical_hash(self.authority),
                acquisition_contract_hash=candidate_data.canonical_hash(self.acquisition_contract),
                source_contract_hash=candidate_data.canonical_hash(self.source_contract),
                created_at_ms=1_900_000_001_000,
            )
            reversed_manifest = self.acquisition.build_dataset_manifest(
                list(reversed([artifact])),
                candidate_registry_hash=candidate_data.canonical_hash(self.model_registry),
                public_source_authority_hash=candidate_data.canonical_hash(self.authority),
                acquisition_contract_hash=candidate_data.canonical_hash(self.acquisition_contract),
                source_contract_hash=candidate_data.canonical_hash(self.source_contract),
                created_at_ms=1_900_000_001_000,
            )

            self.assertEqual(manifest, reversed_manifest)
            self.assertEqual(
                manifest["manifest_sha256"],
                self.acquisition.manifest_hash(manifest),
            )
            self.assertEqual(
                self.acquisition.validate_dataset_manifest(
                    manifest,
                    archive_root=root,
                    required_source_contract_ids={"US_SPOT_BTC_ETP_POINT_IN_TIME"},
                ),
                [],
            )

            (root / artifact["archive_relpath"]).write_bytes(b"tampered")
            errors = self.acquisition.validate_dataset_manifest(
                manifest,
                archive_root=root,
                required_source_contract_ids={"US_SPOT_BTC_ETP_POINT_IN_TIME"},
            )
            self.assertIn("artifact 0 archive sha256 mismatch", errors)

    def test_synthetic_manifest_entry_never_satisfies_source_presence(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._metadata(evidence_class="SYNTHETIC_FIXTURE")
            fixture["replay_eligible"] = False
            artifact = self.acquisition.archive_artifact(Path(td), b"fixture", **fixture)
            manifest = self.acquisition.build_dataset_manifest(
                [artifact],
                candidate_registry_hash=candidate_data.canonical_hash(self.model_registry),
                public_source_authority_hash=candidate_data.canonical_hash(self.authority),
                acquisition_contract_hash=candidate_data.canonical_hash(self.acquisition_contract),
                source_contract_hash=candidate_data.canonical_hash(self.source_contract),
                created_at_ms=1_900_000_001_000,
            )
            result = candidate_data.assess_walk_forward_readiness(
                self.source_contract,
                self.protocol,
                dataset_manifest=manifest,
                dataset_root=Path(td),
                public_source_authority=self.authority,
                acquisition_contract=self.acquisition_contract,
                etp_feasibility=self.feasibility,
            )
            self.assertEqual(result["state"], "BLOCKED")
            self.assertIn(
                "US_SPOT_BTC_ETP_POINT_IN_TIME_ARTIFACT_MISSING",
                result["blocked_reasons"],
            )
            self.assertIn(
                "POINT_IN_TIME_DATASET_ARTIFACT_0_NOT_REPLAY_ELIGIBLE",
                result["blocked_reasons"],
            )

    def test_manifest_without_archive_root_is_never_ready(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = self.acquisition.archive_artifact(Path(td), b"raw", **self._metadata())
            manifest = self.acquisition.build_dataset_manifest(
                [artifact],
                candidate_registry_hash=candidate_data.canonical_hash(self.model_registry),
                public_source_authority_hash=candidate_data.canonical_hash(self.authority),
                acquisition_contract_hash=candidate_data.canonical_hash(self.acquisition_contract),
                source_contract_hash=candidate_data.canonical_hash(self.source_contract),
                created_at_ms=1_900_000_001_000,
            )
            result = candidate_data.assess_walk_forward_readiness(
                self.source_contract,
                self.protocol,
                dataset_manifest=manifest,
                dataset_root=None,
                public_source_authority=self.authority,
                acquisition_contract=self.acquisition_contract,
                etp_feasibility=self.feasibility,
            )
            self.assertEqual(result["state"], "BLOCKED")
            self.assertIn(
                "POINT_IN_TIME_DATASET_ARCHIVE_ROOT_MISSING",
                result["blocked_reasons"],
            )

    def test_manifest_archive_path_escape_is_rejected_before_file_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = self.acquisition.archive_artifact(root, b"raw", **self._metadata())
            manifest = self.acquisition.build_dataset_manifest(
                [artifact],
                candidate_registry_hash=candidate_data.canonical_hash(self.model_registry),
                public_source_authority_hash=candidate_data.canonical_hash(self.authority),
                acquisition_contract_hash=candidate_data.canonical_hash(self.acquisition_contract),
                source_contract_hash=candidate_data.canonical_hash(self.source_contract),
                created_at_ms=1_900_000_001_000,
            )
            manifest["artifacts"][0]["archive_relpath"] = "../../outside"
            manifest["manifest_sha256"] = self.acquisition.manifest_hash(manifest)

            errors = self.acquisition.validate_dataset_manifest(
                manifest,
                archive_root=root,
                required_source_contract_ids={"US_SPOT_BTC_ETP_POINT_IN_TIME"},
            )
            self.assertIn("artifact 0 archive path invalid", errors)
            self.assertIn(
                "source contract US_SPOT_BTC_ETP_POINT_IN_TIME missing replay-eligible artifact",
                errors,
            )

    def test_forged_provider_archive_without_checksum_cannot_satisfy_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = self.acquisition.archive_artifact(root, b"raw", **self._metadata())
            artifact["evidence_class"] = "IMMUTABLE_PROVIDER_ARCHIVE"
            artifact["availability_proof_type"] = "IMMUTABLE_PROVIDER_ARCHIVE"
            artifact["provider_checksum"] = None
            artifact["available_at_coverage_start_ms"] -= 86_400_000
            manifest = self.acquisition.build_dataset_manifest(
                [artifact],
                candidate_registry_hash=candidate_data.canonical_hash(self.model_registry),
                public_source_authority_hash=candidate_data.canonical_hash(self.authority),
                acquisition_contract_hash=candidate_data.canonical_hash(self.acquisition_contract),
                source_contract_hash=candidate_data.canonical_hash(self.source_contract),
                created_at_ms=1_900_000_001_000,
            )
            errors = self.acquisition.validate_dataset_manifest(
                manifest,
                archive_root=root,
                required_source_contract_ids={"US_SPOT_BTC_ETP_POINT_IN_TIME"},
            )
            self.assertIn("artifact 0 provider archive checksum missing", errors)

            result = candidate_data.assess_walk_forward_readiness(
                self.source_contract,
                self.protocol,
                dataset_manifest=manifest,
                dataset_root=root,
                public_source_authority=self.authority,
                acquisition_contract=self.acquisition_contract,
                etp_feasibility=self.feasibility,
            )
            self.assertIn(
                "POINT_IN_TIME_DATASET_ARTIFACT_0_PROVIDER_CHECKSUM_MISSING",
                result["blocked_reasons"],
            )
            self.assertIn(
                "US_SPOT_BTC_ETP_POINT_IN_TIME_ARTIFACT_MISSING",
                result["blocked_reasons"],
            )

    def test_hash_drift_and_runtime_imports_fail_closed(self):
        changed = deepcopy(self.feasibility)
        changed["result"]["historical_backfill_state"] = "READY"
        errors = candidate_data.validate_acquisition_contract(
            self.acquisition_contract,
            self.model_registry,
            self.authority,
            changed,
        )
        self.assertIn("acquisition contract ETP feasibility hash mismatch", errors)

        runtime_files = list((ROOT / "src").rglob("*.py"))
        runtime_source = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
        self.assertNotIn("candidate_acquisition", runtime_source)
        self.assertNotIn("CRT_CANDIDATE_ACQUISITION_CONTRACT", runtime_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
