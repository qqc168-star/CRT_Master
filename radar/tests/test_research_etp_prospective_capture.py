from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
MODULE_PATH = RESEARCH / "prospective_capture.py"
CONTRACT_PATH = RESEARCH / "CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1.json"
ADAPTER_CONTRACT_PATH = RESEARCH / "CRT_ETP_ISSUER_ADAPTER_CONTRACT_V0.1.json"
ACQUISITION_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1.json"
AUTHORITY_PATH = RESEARCH / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
SOURCE_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
PROTOCOL_PATH = RESEARCH / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"
VECTORS_PATH = ROOT / "tests" / "fixtures" / "etp_issuer_adapter_vectors_v0.1.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(RESEARCH))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(RESEARCH))
    return module


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1_000)


class ResearchEtpProspectiveCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = _load_module("prospective_capture_tests", MODULE_PATH)
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.adapter_contract = json.loads(ADAPTER_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.acquisition_contract = json.loads(
            ACQUISITION_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        cls.source_contract = json.loads(SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
        cls.profiles = {
            item["ticker"]: item
            for item in cls.adapter_contract["issuer_profiles"]
        }
        cls.ready_tickers = tuple(cls.contract["capture_universe"]["ready_tickers"])

    def _fetcher(self, *, mutate=None, calls=None):
        def fetcher(*, ticker, url, timeout_s, max_bytes):
            if calls is not None:
                calls.append((ticker, url, timeout_s, max_bytes))
            raw = self.vectors["complete_visible_text"][ticker].encode("utf-8")
            if mutate is not None:
                raw = mutate(ticker, raw)
            return {
                "status_code": 200,
                "final_url": url,
                "content_type": "text/plain",
                "body": raw,
                "retrieved_at_ms": _ms("2026-08-11T00:30:00+00:00"),
            }

        return fetcher

    def _run(self, root: Path, *, now_ms=None, fetcher=None):
        current = _ms("2026-08-11T00:30:00+00:00") if now_ms is None else now_ms
        active_fetcher = self._fetcher() if fetcher is None else fetcher
        with patch.object(self.runner.time, "time", return_value=current / 1_000), patch.object(
            self.runner,
            "fetch_official_bytes",
            side_effect=active_fetcher,
        ):
            return self.runner.run_capture_cycle(
                root,
                capture_contract=self.contract,
                adapter_contract=self.adapter_contract,
                acquisition_contract=self.acquisition_contract,
                public_source_authority=self.authority,
                source_contract=self.source_contract,
                walk_forward_protocol=self.protocol,
            )

    def _replay(self, root: Path, receipt_relpath: str):
        return self.runner.replay_capture_receipt(
            root,
            receipt_relpath,
            capture_contract=self.contract,
            adapter_contract=self.adapter_contract,
            acquisition_contract=self.acquisition_contract,
            public_source_authority=self.authority,
            source_contract=self.source_contract,
            walk_forward_protocol=self.protocol,
        )

    def test_contract_is_hash_bound_shadow_only_and_preserves_all_parent_authority(self):
        self.assertEqual(
            self.runner.validate_capture_contract(
                self.contract,
                adapter_contract=self.adapter_contract,
                acquisition_contract=self.acquisition_contract,
                public_source_authority=self.authority,
                source_contract=self.source_contract,
                walk_forward_protocol=self.protocol,
            ),
            [],
        )
        self.assertEqual(
            self.contract["implementation_sha256"],
            hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            self.contract["acquisition_implementation_sha256"],
            hashlib.sha256((RESEARCH / "candidate_acquisition.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            self.runner._contract_semantic_hash(self.contract),
            self.runner.EXPECTED_CONTRACT_SEMANTIC_SHA256,
        )
        self.assertEqual(
            self.ready_tickers,
            ("IBIT", "BITB", "ARKB", "HODL", "GBTC", "BTC"),
        )
        self.assertEqual(
            set(self.contract["capture_universe"]["blocked_tickers"]),
            {"FBTC", "BTCO", "EZBC", "BRRR", "BTCW", "MSBT"},
        )
        self.assertEqual(self.contract["mode"], "SHADOW_ONLY")
        self.assertFalse(self.contract["historical_backfill_authority"])
        self.assertFalse(self.contract["dataset_readiness_granted"])
        self.assertEqual(self.contract["authority"]["formal_model"], "NOT_APPROVED")
        self.assertEqual(self.contract["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(self.contract["authority"]["external_action_authority"], "NONE")
        calendar = self.contract["market_calendar"]
        self.assertEqual(calendar["timezone"], "America/New_York")
        self.assertEqual(
            calendar["official_source_url"],
            "https://www.nyse.com/trade/hours-calendars",
        )
        self.assertEqual(calendar["valid_through"], "2028-12-31")
        self.assertIn("2026-09-07", calendar["full_close_dates"])
        self.assertIn("2027-01-18", calendar["full_close_dates"])
        self.assertIn("2028-12-25", calendar["full_close_dates"])

    def test_calendar_and_timezone_gate_weekends_holidays_early_runs_and_unknown_years(self):
        summer = self.runner.capture_decision(
            _ms("2026-08-11T00:30:00+00:00"), self.contract
        )
        winter = self.runner.capture_decision(
            _ms("2026-12-01T01:30:00+00:00"), self.contract
        )
        self.assertEqual(summer["expected_session_date"], "2026-08-10")
        self.assertEqual(winter["expected_session_date"], "2026-11-30")
        self.assertEqual(summer["state"], "CAPTURE_DUE")
        self.assertEqual(winter["state"], "CAPTURE_DUE")

        cases = (
            ("2026-08-10T23:00:00+00:00", "NOT_DUE"),
            ("2026-08-16T00:30:00+00:00", "MARKET_CLOSED"),
            ("2026-09-08T00:30:00+00:00", "MARKET_CLOSED"),
            ("2029-01-03T01:30:00+00:00", "CALENDAR_OUT_OF_RANGE"),
        )
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                decision = self.runner.capture_decision(_ms(timestamp), self.contract)
                self.assertEqual(decision["state"], expected)

        calls = []
        with tempfile.TemporaryDirectory() as td:
            report = self._run(
                Path(td),
                now_ms=_ms("2026-09-08T00:30:00+00:00"),
                fetcher=self._fetcher(calls=calls),
            )
        self.assertEqual(report["state"], "MARKET_CLOSED_NO_CAPTURE")
        self.assertEqual(calls, [])

    def test_six_ready_sources_capture_raw_first_and_emit_byte_verified_manifest(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original_parse = self.runner.issuer_adapters.parse_issuer_snapshot

            def assert_staged(ticker, raw_bytes, **kwargs):
                digest = hashlib.sha256(raw_bytes).hexdigest()
                relpath = f"artifacts/sha256/{digest[:2]}/{digest}"
                self.assertEqual((root / relpath).read_bytes(), raw_bytes)
                return original_parse(ticker, raw_bytes, **kwargs)

            with patch.object(
                self.runner.issuer_adapters,
                "parse_issuer_snapshot",
                side_effect=assert_staged,
            ):
                report = self._run(root, fetcher=self._fetcher(calls=calls))

            self.assertEqual(report["state"], "COMPLETE_SHADOW_CAPTURE")
            self.assertEqual(set(report["ticker_results"]), set(self.ready_tickers))
            self.assertEqual(len(calls), 6)
            self.assertEqual(report["captured_count"], 6)
            self.assertEqual(report["retry_required_count"], 0)
            self.assertEqual(report["blocked_count"], 0)
            self.assertEqual(report["mode"], "SHADOW_ONLY")
            self.assertEqual(report["formal_model"], "NOT_APPROVED")
            self.assertEqual(report["production"], "NOT_APPROVED")
            self.assertEqual(report["external_action_authority"], "NONE")
            self.assertFalse(report["historical_dataset_ready"])
            manifest_path = root / report["manifest"]["relpath"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["artifacts"]), 6)
            self.assertEqual(
                self.runner.candidate_acquisition.validate_dataset_manifest(
                    manifest,
                    archive_root=root,
                    required_source_contract_ids={"US_SPOT_BTC_ETP_POINT_IN_TIME"},
                ),
                [],
            )
            for ticker, result in report["ticker_results"].items():
                with self.subTest(ticker=ticker):
                    self.assertEqual(result["state"], "CAPTURED")
                    self.assertEqual(result["snapshot"]["observed_on"], "2026-08-10")
                    self.assertTrue(result["artifact"]["replay_eligible"])
                    self.assertEqual(
                        self._replay(root, result["receipt"]["relpath"]),
                        result["snapshot"],
                    )

    def test_stale_future_and_parser_failures_never_carry_previous_values_forward(self):
        def mutate_first(ticker, raw):
            if ticker == "IBIT":
                return raw.replace(b"Aug 10, 2026", b"Aug 07, 2026")
            return raw

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._run(root, fetcher=self._fetcher(mutate=mutate_first))
            ibit = report["ticker_results"]["IBIT"]
            self.assertEqual(ibit["state"], "STALE_SOURCE_RETRY_REQUIRED")
            self.assertNotIn("artifact", ibit)
            self.assertNotIn("receipt", ibit)
            self.assertTrue((root / ibit["staged_raw"]["relpath"]).is_file())
            self.assertEqual(report["state"], "PARTIAL_RETRY_REQUIRED")
            self.assertEqual(report["captured_count"], 5)
            self.assertEqual(report["retry_required_count"], 1)
            self.assertEqual(report["blocked_count"], 0)

        def mutate_future(ticker, raw):
            if ticker == "IBIT":
                return raw.replace(b"Aug 10, 2026", b"Aug 11, 2026")
            return raw

        with tempfile.TemporaryDirectory() as td:
            report = self._run(Path(td), fetcher=self._fetcher(mutate=mutate_future))
            self.assertEqual(
                report["ticker_results"]["IBIT"]["state"],
                "FUTURE_SOURCE_DATE_BLOCKED",
            )
            self.assertEqual(report["state"], "PARTIAL_BLOCKED")
            self.assertEqual(report["retry_required_count"], 0)
            self.assertEqual(report["blocked_count"], 1)

        def mutate_bad(ticker, raw):
            return b"<html>issuer maintenance</html>" if ticker == "IBIT" else raw

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._run(root, fetcher=self._fetcher(mutate=mutate_bad))
            ibit = report["ticker_results"]["IBIT"]
            self.assertEqual(ibit["state"], "PARSE_FAILED_RETRY_REQUIRED")
            self.assertTrue((root / ibit["staged_raw"]["relpath"]).is_file())
            self.assertNotIn("artifact", ibit)
            self.assertNotIn("snapshot", ibit)

    def test_identical_recapture_is_idempotent_and_reuses_original_first_seen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self._run(root)

            later_ms = _ms("2026-08-11T00:45:00+00:00")

            def later_fetcher(**kwargs):
                result = self._fetcher()(**kwargs)
                result["retrieved_at_ms"] = later_ms
                return result

            second = self._run(root, now_ms=later_ms, fetcher=later_fetcher)
            for ticker in self.ready_tickers:
                with self.subTest(ticker=ticker):
                    first_result = first["ticker_results"][ticker]
                    second_result = second["ticker_results"][ticker]
                    self.assertEqual(first_result["artifact"], second_result["artifact"])
                    self.assertEqual(first_result["snapshot"], second_result["snapshot"])
                    self.assertEqual(first_result["receipt"], second_result["receipt"])
                    self.assertEqual(
                        second_result["artifact"]["first_seen_at_ms"],
                        _ms("2026-08-11T00:30:00+00:00"),
                    )
            self.assertEqual(
                len(list(root.glob("capture_receipts/sha256/*/*.json"))),
                6,
            )

    def test_same_session_changed_bytes_form_revision_chain_and_both_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self._run(root)
            later_ms = _ms("2026-08-11T00:45:00+00:00")

            def revised(ticker, raw):
                return raw + b"\n" if ticker == "IBIT" else raw

            def revised_fetcher(**kwargs):
                result = self._fetcher(mutate=revised)(**kwargs)
                result["retrieved_at_ms"] = later_ms
                return result

            second = self._run(root, now_ms=later_ms, fetcher=revised_fetcher)
            old = first["ticker_results"]["IBIT"]
            new = second["ticker_results"]["IBIT"]
            self.assertNotEqual(old["artifact"]["sha256"], new["artifact"]["sha256"])
            self.assertEqual(
                new["artifact"]["revision_of_sha256"],
                old["artifact"]["sha256"],
            )
            self.assertEqual(self._replay(root, old["receipt"]["relpath"]), old["snapshot"])
            self.assertEqual(self._replay(root, new["receipt"]["relpath"]), new["snapshot"])

    def test_offline_replay_detects_raw_and_receipt_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._run(root)
            result = report["ticker_results"]["IBIT"]
            raw_path = root / result["artifact"]["archive_relpath"]
            raw_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(
                self.runner.ProspectiveCaptureError,
                "RAW_ARCHIVE_SHA256_MISMATCH",
            ):
                self._replay(root, result["receipt"]["relpath"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._run(root)
            receipt_path = root / report["ticker_results"]["IBIT"]["receipt"]["relpath"]
            receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
            with self.assertRaisesRegex(
                self.runner.ProspectiveCaptureError,
                "RECEIPT_FILE_SHA256_MISMATCH",
            ):
                self._replay(
                    root,
                    report["ticker_results"]["IBIT"]["receipt"]["relpath"],
                )

    def test_fetch_response_redirect_content_type_status_and_size_fail_closed(self):
        def bad_fetcher(kind):
            def fetcher(*, ticker, url, timeout_s, max_bytes):
                result = self._fetcher()(
                    ticker=ticker,
                    url=url,
                    timeout_s=timeout_s,
                    max_bytes=max_bytes,
                )
                if ticker == "IBIT":
                    if kind == "redirect":
                        result["final_url"] = "https://example.invalid/ibit"
                    elif kind == "content_type":
                        result["content_type"] = "application/json"
                    elif kind == "status":
                        result["status_code"] = 503
                    elif kind == "size":
                        result["body"] = b"x" * (max_bytes + 1)
                    elif kind == "clock":
                        result["retrieved_at_ms"] -= 300_001
                return result

            return fetcher

        for kind in ("redirect", "content_type", "status", "size", "clock"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                report = self._run(Path(td), fetcher=bad_fetcher(kind))
                result = report["ticker_results"]["IBIT"]
                self.assertEqual(result["state"], "FETCH_FAILED_RETRY_REQUIRED")
                self.assertNotIn("staged_raw", result)
                self.assertNotIn("artifact", result)

    def test_default_fetcher_is_direct_bounded_identity_encoded_get(self):
        class Headers:
            def get_content_type(self):
                return "text/html"

            def get(self, key):
                return {"Content-Length": "4", "Content-Encoding": "identity"}.get(key)

        class Response:
            status = 200
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return self.url

            def read(self, limit):
                self.limit = limit
                return b"page"

        response = Response()
        captured = {}

        class Opener:
            def open(self, request, timeout):
                captured["request"] = request
                captured["timeout"] = timeout
                response.url = request.full_url
                return response

        def build_opener(*handlers):
            captured["handlers"] = handlers
            return Opener()

        url = self.profiles["IBIT"]["official_product_url"]
        with patch.object(self.runner.urllib.request, "build_opener", side_effect=build_opener), patch.object(
            self.runner.ssl,
            "create_default_context",
            return_value=object(),
        ), patch.object(self.runner.time, "time", return_value=1_900_000_000):
            fetched = self.runner.fetch_official_bytes(
                ticker="IBIT",
                url=url,
                timeout_s=30,
                max_bytes=1024,
            )

        request = captured["request"]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(response.limit, 1025)
        proxy_handlers = [
            handler
            for handler in captured["handlers"]
            if isinstance(handler, self.runner.urllib.request.ProxyHandler)
        ]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})
        redirect = next(
            handler
            for handler in captured["handlers"]
            if isinstance(handler, self.runner._NoRedirect)
        )
        self.assertIsNone(redirect.redirect_request(None, None, 302, "", {}, url))
        self.assertEqual(fetched["body"], b"page")

    def test_replay_rejects_path_escape_and_noncanonical_receipt_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._run(root)
            receipt = report["ticker_results"]["IBIT"]["receipt"]
            with self.assertRaisesRegex(
                self.runner.ProspectiveCaptureError,
                "RECEIPT_PATH_INVALID",
            ):
                self._replay(root, "../../outside.json")

            canonical = root / receipt["relpath"]
            alias = root / "aliases" / canonical.name
            alias.parent.mkdir(parents=True)
            alias.write_bytes(canonical.read_bytes())
            with self.assertRaisesRegex(
                self.runner.ProspectiveCaptureError,
                "RECEIPT_PATH_NOT_CONTENT_ADDRESSED",
            ):
                self._replay(root, alias.relative_to(root).as_posix())

    def test_runner_surface_is_get_only_has_no_credentials_scheduler_or_runtime_wiring(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue({"urllib", "ssl"}.issubset(imports))
        self.assertTrue(
            {"requests", "httpx", "aiohttp", "socket", "subprocess", "webbrowser"}.isdisjoint(
                imports
            )
        )
        for forbidden in (
            "Authorization",
            "Cookie",
            "api_key",
            "password",
            "urlretrieve",
            "urlopen",
            "POST",
            "PUT",
            "DELETE",
            "candidate_model",
            "assess_walk_forward_readiness",
            "radar.src",
            "crt_radar",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('method="GET"', source)
        run_function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_capture_cycle"
        )
        run_parameters = {
            argument.arg
            for argument in run_function.args.args + run_function.args.kwonlyargs
        }
        self.assertNotIn("fetcher", run_parameters)
        self.assertNotIn("now_ms", run_parameters)
        runtime_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("prospective_capture", runtime_source)
        self.assertEqual(
            list((ROOT / "research").glob("*scheduler*")),
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
