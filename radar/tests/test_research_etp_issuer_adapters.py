from __future__ import annotations

import ast
import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
MODULE_PATH = RESEARCH / "issuer_adapters.py"
ACQUISITION_MODULE_PATH = RESEARCH / "candidate_acquisition.py"
AUTHORITY_PATH = RESEARCH / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
FEASIBILITY_PATH = RESEARCH / "CRT_ETP_PUBLIC_REPLAY_FEASIBILITY_V0.1.json"
ACQUISITION_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1.json"
ADAPTER_CONTRACT_PATH = RESEARCH / "CRT_ETP_ISSUER_ADAPTER_CONTRACT_V0.1.json"
VECTORS_PATH = ROOT / "tests" / "fixtures" / "etp_issuer_adapter_vectors_v0.1.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResearchEtpIssuerAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapters = _load_module("issuer_adapters_tests", MODULE_PATH)
        cls.acquisition = _load_module(
            "candidate_acquisition_adapter_tests",
            ACQUISITION_MODULE_PATH,
        )
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        cls.feasibility = json.loads(FEASIBILITY_PATH.read_text(encoding="utf-8"))
        cls.acquisition_contract = json.loads(
            ACQUISITION_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        cls.contract = json.loads(ADAPTER_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
        cls.profiles = {
            item["ticker"]: item for item in cls.contract["issuer_profiles"]
        }

    def _parse(
        self,
        ticker: str,
        text: str,
        *,
        evidence_class: str = "SYNTHETIC_FIXTURE",
    ) -> dict:
        return self.adapters.parse_issuer_snapshot(
            ticker,
            text.encode("utf-8"),
            source_url=self.profiles[ticker]["official_product_url"],
            content_type="text/plain",
            first_seen_at_ms=1_900_000_000_000,
            evidence_class=evidence_class,
            contract=self.contract,
        )

    def test_contract_binds_all_twelve_authority_members_and_sec_identities(self):
        self.assertEqual(
            self.adapters.validate_adapter_contract(
                self.contract,
                public_source_authority=self.authority,
                etp_feasibility=self.feasibility,
                acquisition_contract=self.acquisition_contract,
            ),
            [],
        )
        authority_members = {
            item["ticker"]: item
            for item in self.authority["decisions"]["US_SPOT_BTC_ETP_POINT_IN_TIME"][
                "universe"
            ]["members"]
        }
        self.assertEqual(set(self.profiles), set(authority_members))
        self.assertEqual(len(self.profiles), 12)
        for ticker, profile in self.profiles.items():
            with self.subTest(ticker=ticker):
                member = authority_members[ticker]
                self.assertEqual(profile["issuer_label"], member["issuer_label"])
                self.assertEqual(
                    profile["membership_effective_from"],
                    member["membership_effective_from"],
                )
                self.assertEqual(
                    profile["official_product_url"],
                    member["official_product_url"],
                )
                identity = profile["sec_identity"]
                self.assertRegex(identity["cik"], r"^\d{10}$")
                self.assertRegex(identity["accession"], r"^\d{18}$")
                self.assertIn(identity["cik"].lstrip("0"), identity["url"])
                self.assertIn(identity["accession"], identity["url"])

        surface = self.contract["surface_probe_result"]
        self.assertEqual(len(surface["proven_tickers"]), 6)
        self.assertEqual(set(surface["blocked_tickers"]), set(self.vectors["observed_surface_blockers"]))
        self.assertEqual(self.contract["network_fetch_implemented"], False)
        self.assertEqual(self.contract["raw_dataset_acquired"], False)
        self.assertEqual(self.contract["dataset_readiness_granted"], False)

    def test_all_twelve_profiles_parse_complete_synthetic_shapes_without_derivation(self):
        expected = self.vectors["common_expected"]
        for ticker, text in self.vectors["complete_visible_text"].items():
            with self.subTest(ticker=ticker):
                snapshot = self._parse(ticker, text)
                self.assertEqual(snapshot["fund_id"], ticker)
                self.assertEqual(snapshot["observed_on"], expected["observed_on"])
                self.assertEqual(snapshot["observed_at_ms"], expected["observed_at_ms"])
                self.assertEqual(snapshot["nav_per_share"], expected["nav_per_share"])
                self.assertEqual(
                    snapshot["raw_nav_per_share"],
                    expected["nav_per_share"],
                )
                self.assertEqual(snapshot["net_assets"], expected["net_assets"])
                self.assertEqual(
                    snapshot["raw_shares_outstanding"],
                    expected["raw_shares_outstanding"],
                )
                self.assertEqual(
                    snapshot["adjusted_shares_outstanding"],
                    expected["raw_shares_outstanding"],
                )
                self.assertEqual(snapshot["published_at_ms"], snapshot["first_seen_at_ms"])
                self.assertEqual(snapshot["availability_proof_type"], "LOCAL_FIRST_SEEN_CAPTURE")
                self.assertEqual(snapshot["historical_backfill_authority"], "NONE")
                self.assertEqual(snapshot["evidence_class"], "SYNTHETIC_FIXTURE")
                self.assertFalse(snapshot["replay_eligible"])
                self.assertEqual(
                    snapshot["snapshot_sha256"],
                    self.adapters.snapshot_hash(snapshot),
                )
                self.assertEqual(
                    set(snapshot["field_evidence"]),
                    {"nav_per_share", "net_assets", "raw_shares_outstanding"},
                )

    def test_six_observed_surface_gaps_fail_closed_with_precise_codes(self):
        for ticker, item in self.vectors["observed_surface_blockers"].items():
            with self.subTest(ticker=ticker):
                with self.assertRaisesRegex(
                    self.adapters.IssuerAdapterError,
                    item["expected_error"],
                ):
                    self._parse(ticker, item["visible_text"])

        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "CURRENT_SURFACE_NOT_PROVEN",
        ):
            self._parse(
                "BTCW",
                self.vectors["complete_visible_text"]["BTCW"],
                evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
            )

        current = self._parse(
            "IBIT",
            self.vectors["complete_visible_text"]["IBIT"],
            evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
        )
        self.assertTrue(current["replay_eligible"])

    def test_abbreviated_net_assets_are_rejected_even_when_arithmetic_looks_plausible(self):
        text = self.vectors["complete_visible_text"]["IBIT"].replace(
            "$250,000,000",
            "$250.00M",
        )
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "NET_ASSETS_ABBREVIATED_FORBIDDEN",
        ):
            self._parse("IBIT", text)

    def test_source_url_identity_date_and_ambiguous_values_fail_closed(self):
        text = self.vectors["complete_visible_text"]["IBIT"]
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "SOURCE_URL_NOT_LOCKED",
        ):
            self.adapters.parse_issuer_snapshot(
                "IBIT",
                text.encode("utf-8"),
                source_url="https://example.invalid/ibit",
                content_type="text/plain",
                first_seen_at_ms=1_900_000_000_000,
                evidence_class="SYNTHETIC_FIXTURE",
                contract=self.contract,
            )

        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "ISSUER_IDENTITY_MISMATCH",
        ):
            self._parse("IBIT", text.replace("IBIT", "WRONG"))

        cross_dated = text.replace(
            "Shares Outstanding\n10,000,000\nas of Aug 10, 2026",
            "Shares Outstanding\n10,000,000\nas of Aug 07, 2026",
        )
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "FIELD_DATE_MISMATCH",
        ):
            self._parse("IBIT", cross_dated)

        ambiguous = text + "\nNet Assets of Fund\n$251,000,000\nas of Aug 10, 2026"
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "NET_ASSETS_AMBIGUOUS",
        ):
            self._parse("IBIT", ambiguous)

    def test_weekend_and_cross_panel_dates_fail_closed(self):
        ibit = self.vectors["complete_visible_text"]["IBIT"]
        weekend = ibit.replace("Aug 10, 2026", "Aug 09, 2026")
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "OBSERVATION_DATE_NOT_WEEKDAY",
        ):
            self._parse("IBIT", weekend)

        for ticker, old, new in (
            ("HODL", "ETF Statistics as of 08/10/2026", "ETF Statistics as of 08/07/2026"),
            ("BTCW", "Net Asset Value As of 8/10/2026", "Net Asset Value As of 8/7/2026"),
        ):
            with self.subTest(ticker=ticker):
                text = self.vectors["complete_visible_text"][ticker].replace(old, new)
                with self.assertRaisesRegex(
                    self.adapters.IssuerAdapterError,
                    "SNAPSHOT_DATE_AMBIGUOUS",
                ):
                    self._parse(ticker, text)

    def test_html_visible_text_ignores_script_decoys(self):
        plain = self.vectors["complete_visible_text"]["IBIT"]
        html = (
            "<html><body>"
            + plain.replace("\n", "<br>")
            + "<script>Net Assets of Fund $999,000,000 as of Aug 10, 2026</script>"
            + "</body></html>"
        )
        snapshot = self.adapters.parse_issuer_snapshot(
            "IBIT",
            html.encode("utf-8"),
            source_url=self.profiles["IBIT"]["official_product_url"],
            content_type="text/html",
            first_seen_at_ms=1_900_000_000_000,
            evidence_class="SYNTHETIC_FIXTURE",
            contract=self.contract,
        )
        self.assertEqual(snapshot["net_assets"], 250_000_000)

    def test_btc_reverse_split_normalizes_pre_split_shares_and_nav_reciprocally(self):
        before = (
            "Grayscale Bitcoin Mini Trust ETF BTC\n"
            "AS OF 10/31/2024\n"
            "ASSETS UNDER MANAGEMENT (NON-GAAP) $2,500,000,000\n"
            "SHARES OUTSTANDING 500,000,000\n"
            "NET ASSET VALUE (NAV) PER SHARE $5.00"
        )
        snapshot = self._parse("BTC", before)
        self.assertEqual(snapshot["raw_nav_per_share"], 5)
        self.assertEqual(snapshot["nav_per_share"], 25)
        self.assertEqual(snapshot["raw_shares_outstanding"], 500_000_000)
        self.assertEqual(snapshot["adjusted_shares_outstanding"], 100_000_000)
        self.assertEqual(
            snapshot["raw_nav_per_share"] * snapshot["raw_shares_outstanding"],
            snapshot["nav_per_share"] * snapshot["adjusted_shares_outstanding"],
        )
        self.assertEqual(
            snapshot["split_adjustments_applied"],
            [
                {
                    "effective_on": "2024-11-19",
                    "numerator": 1,
                    "denominator": 5,
                    "event": "1_FOR_5_REVERSE_SPLIT",
                }
            ],
        )

        after = self._parse("BTC", self.vectors["complete_visible_text"]["BTC"])
        self.assertEqual(after["raw_nav_per_share"], 25)
        self.assertEqual(after["nav_per_share"], 25)
        self.assertEqual(after["raw_shares_outstanding"], 10_000_000)
        self.assertEqual(after["adjusted_shares_outstanding"], 10_000_000)
        self.assertEqual(after["split_adjustments_applied"], [])

    def test_acquisition_metadata_is_first_seen_only_and_synthetic_never_eligible(self):
        snapshot = self._parse("IBIT", self.vectors["complete_visible_text"]["IBIT"])
        metadata = self.adapters.build_acquisition_metadata(
            snapshot,
            public_source_authority_hash=self.contract["public_source_authority_hash"],
            content_type="text/plain",
        )
        self.assertEqual(
            metadata["available_at_coverage_start_ms"],
            snapshot["first_seen_at_ms"],
        )
        self.assertEqual(
            metadata["available_at_coverage_end_ms"],
            snapshot["first_seen_at_ms"],
        )
        self.assertEqual(metadata["evidence_class"], "SYNTHETIC_FIXTURE")
        self.assertFalse(metadata["replay_eligible"])

        raw = self.vectors["complete_visible_text"]["IBIT"].encode("utf-8")
        with tempfile.TemporaryDirectory() as td:
            artifact = self.acquisition.archive_artifact(Path(td), raw, **metadata)
            self.assertEqual(artifact["evidence_class"], "SYNTHETIC_FIXTURE")
            self.assertFalse(artifact["replay_eligible"])
            self.assertEqual(artifact["sha256"], snapshot["raw_snapshot_sha256"])
            self.assertEqual(
                (Path(td) / artifact["archive_relpath"]).read_bytes(),
                raw,
            )
            self.assertEqual(
                snapshot["adapter_contract_hash"],
                self.adapters.canonical_hash(self.contract),
            )

    def test_contract_or_implementation_drift_is_rejected(self):
        changed = deepcopy(self.contract)
        changed["issuer_profiles"][0]["sec_identity"]["cik"] = "0000000000"
        errors = self.adapters.validate_adapter_contract(
            changed,
            public_source_authority=self.authority,
            etp_feasibility=self.feasibility,
            acquisition_contract=self.acquisition_contract,
        )
        self.assertIn("adapter contract profile IBIT SEC identity drift", errors)
        self.assertIn("adapter contract semantic hash mismatch", errors)
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "ADAPTER_CONTRACT_SEMANTIC_HASH_MISMATCH",
        ):
            self.adapters.parse_issuer_snapshot(
                "IBIT",
                self.vectors["complete_visible_text"]["IBIT"].encode("utf-8"),
                source_url=self.profiles["IBIT"]["official_product_url"],
                content_type="text/plain",
                first_seen_at_ms=1_900_000_000_000,
                evidence_class="SYNTHETIC_FIXTURE",
                contract=changed,
            )

        changed = deepcopy(self.contract)
        changed["surface_probe_result"]["proven_tickers"].append("FBTC")
        errors = self.adapters.validate_adapter_contract(
            changed,
            public_source_authority=self.authority,
            etp_feasibility=self.feasibility,
            acquisition_contract=self.acquisition_contract,
        )
        self.assertIn("adapter contract surface partition invalid", errors)

        changed = deepcopy(self.contract)
        changed["implementation_sha256"] = "0" * 64
        errors = self.adapters.validate_adapter_contract(
            changed,
            public_source_authority=self.authority,
            etp_feasibility=self.feasibility,
            acquisition_contract=self.acquisition_contract,
        )
        self.assertIn("adapter contract implementation hash mismatch", errors)

    def test_acquisition_metadata_rejects_snapshot_contract_or_authority_drift(self):
        snapshot = self._parse(
            "IBIT",
            self.vectors["complete_visible_text"]["IBIT"],
        )
        snapshot["adapter_contract_hash"] = "0" * 64
        snapshot["snapshot_sha256"] = self.adapters.snapshot_hash(snapshot)
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "SNAPSHOT_ADAPTER_CONTRACT_HASH_MISMATCH",
        ):
            self.adapters.build_acquisition_metadata(
                snapshot,
                public_source_authority_hash=self.contract[
                    "public_source_authority_hash"
                ],
                content_type="text/plain",
            )

        snapshot = self._parse(
            "IBIT",
            self.vectors["complete_visible_text"]["IBIT"],
        )
        snapshot["external_action_authority"] = "ORDER_EXECUTION"
        snapshot["snapshot_sha256"] = self.adapters.snapshot_hash(snapshot)
        with self.assertRaisesRegex(
            self.adapters.IssuerAdapterError,
            "SNAPSHOT_AUTHORITY_INVALID",
        ):
            self.adapters.build_acquisition_metadata(
                snapshot,
                public_source_authority_hash=self.contract[
                    "public_source_authority_hash"
                ],
                content_type="text/plain",
            )

    def test_adapter_module_has_no_network_subprocess_write_or_external_action_surface(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            imported_roots.isdisjoint(
                {"requests", "urllib", "http", "socket", "subprocess", "webbrowser"}
            )
        )
        forbidden_calls = {
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "system",
            "popen",
            "urlopen",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(called.isdisjoint(forbidden_calls))

        runtime_source = "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("issuer_adapters", runtime_source)
        self.assertNotIn("CRT_ETP_ISSUER_ADAPTER_CONTRACT", runtime_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
