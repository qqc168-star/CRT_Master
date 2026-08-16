from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.issuer_announcement_runner import (
    IssuerAnnouncementError,
    load_registry,
    parse_q4_press_feed,
    parse_sec_submissions,
    parse_strategy_press_archive,
    run_issuer_announcement_cycle,
)


REGISTRY_PATH = ROOT / "CONFIG" / "ISSUER_ANNOUNCEMENT_REGISTRY_V1.json"
NOW_MS = 1_786_885_000_000


def sec_payload(cik: str, name: str, rows: list[dict]) -> dict:
    fields = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "act",
        "form",
        "fileNumber",
        "filmNumber",
        "items",
        "size",
        "isXBRL",
        "isInlineXBRL",
        "primaryDocument",
        "primaryDocDescription",
    )
    recent = {field: [row.get(field, "") for row in rows] for field in fields}
    return {"cik": int(cik), "name": name, "filings": {"recent": recent}}


def filing(accession: str, form: str, *, items: str = "8.01", document: str = "issuer.htm") -> dict:
    return {
        "accessionNumber": accession,
        "filingDate": "2026-08-15",
        "reportDate": "2026-08-15",
        "acceptanceDateTime": "2026-08-1512:00:00.000Z",
        "act": "34",
        "form": form,
        "fileNumber": "001-00000",
        "filmNumber": "26000000",
        "items": items,
        "size": 1000,
        "isXBRL": 1,
        "isInlineXBRL": 1,
        "primaryDocument": document,
        "primaryDocDescription": "Current report",
    }


class IssuerAnnouncementRunnerTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(REGISTRY_PATH)
        self.strategy = next(row for row in self.registry["issuers"] if row["issuer_id"] == "STRATEGY_INC")
        self.strive = next(row for row in self.registry["issuers"] if row["issuer_id"] == "STRIVE_INC")
        self.strategy_payload = sec_payload(
            self.strategy["cik"],
            "STRATEGY INC",
            [filing("0001193125-26-100001", "8-K", document="mstr.htm")],
        )
        self.strive_payload = sec_payload(
            self.strive["cik"],
            "STRIVE, INC.",
            [filing("0001628280-26-100001", "10-Q", items="", document="asst.htm")],
        )
        self.press_html = b"""
            <html><body>
              <a href="/press/strategy-initiates-strc-repurchases_07-27-2026">
                Strategy Initiates STRC Repurchases and Announces Ongoing Buyback Policy
              </a>
            </body></html>
        """
        self.strive_press_payload = {
            "GetPressReleaseListResult": [
                {
                    "PressReleaseId": 1755,
                    "PressReleaseDate": "08/10/2026 07:00:00",
                    "Headline": "Strive, Inc. Announces Second Quarter 2026 Financial Results",
                    "LinkToDetailPage": "/news-events/news-releases/news-details/2026/Strive-Inc--Announces-Second-Quarter-2026-Financial-Results/default.aspx",
                },
                {
                    "PressReleaseId": 1729,
                    "PressReleaseDate": "12/15/2025 00:00:00",
                    "Headline": "Form 8937 - SATA",
                    "LinkToDetailPage": "/files/doc_downloads/2026/01/Form-8937-Strive-Inc-12-15-2025-SATA-Dividend.pdf",
                }
            ]
        }

    def fetcher(self, url: str, **_: object):
        if url == self.strategy["sec_submissions_url"]:
            return json.dumps(self.strategy_payload).encode(), "application/json", url
        if url == self.strive["sec_submissions_url"]:
            return json.dumps(self.strive_payload).encode(), "application/json", url
        if url == self.strategy["press_archive_url"]:
            return self.press_html, "text/html", url
        if url == self.strive["press_feed_url"]:
            return json.dumps(self.strive_press_payload).encode(), "application/json", url
        raise IssuerAnnouncementError("unexpected URL")

    def test_registry_binds_strategy_and_strive_official_identities(self):
        self.assertEqual(self.strategy["cik"], "0001050446")
        self.assertIn("STRC", self.strategy["symbols"])
        self.assertEqual(self.strive["cik"], "0001920406")
        self.assertIn("ASST", self.strive["symbols"])
        self.assertEqual(self.strive["press_mode"], "Q4_PUBLIC_JSON")
        self.assertEqual(self.registry["authority"]["external_action_authority"], "NONE")

    def test_sec_parser_classifies_capital_and_financial_events(self):
        strategy_events = parse_sec_submissions(
            self.strategy,
            sec_payload(
                self.strategy["cik"],
                "STRATEGY INC",
                [filing("0001193125-26-999999", "8-K", items="3.02,8.01")],
            ),
            material_forms=self.registry["material_forms"],
            material_keywords=self.registry["material_title_keywords"],
        )
        self.assertEqual(strategy_events[0]["classification"], "CAPITAL_RAISE_OR_DILUTION")
        strive_events = parse_sec_submissions(
            self.strive,
            self.strive_payload,
            material_forms=self.registry["material_forms"],
            material_keywords=self.registry["material_title_keywords"],
        )
        self.assertEqual(strive_events[0]["classification"], "FINANCIAL_RESULTS")

    def test_strategy_press_parser_extracts_official_release_without_score(self):
        events = parse_strategy_press_archive(
            self.strategy,
            self.press_html,
            source_url=self.strategy["press_archive_url"],
            material_keywords=self.registry["material_title_keywords"],
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["classification"], "CAPITAL_OR_TREASURY_POLICY")
        self.assertEqual(events[0]["source_type"], "OFFICIAL_PRESS_RELEASE")
        self.assertNotIn("score", events[0])

    def test_strive_q4_press_parser_extracts_official_release_without_score(self):
        events = parse_q4_press_feed(
            self.strive,
            json.dumps(self.strive_press_payload).encode(),
            source_url=self.strive["press_archive_url"],
            material_keywords=self.registry["material_title_keywords"],
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_id"], "STRIVE_INC:PRESS:1755")
        self.assertEqual(events[0]["filing_date"], "2026-08-10")
        self.assertEqual(events[0]["classification"], "FINANCIAL_RESULTS")
        self.assertTrue(events[0]["source_url"].startswith("https://investors.strive.com/"))
        self.assertNotIn("score", events[0])

    def test_first_poll_baselines_then_only_new_event_requests_reanalysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state.json"
            ledger = root / "events.jsonl"
            first = run_issuer_announcement_cycle(
                self.registry,
                state_path=state,
                ledger_path=ledger,
                now_ms=NOW_MS,
                fetcher=self.fetcher,
            )
            self.assertEqual(first["state"], "NO_WAKE")
            self.assertEqual(first["reason"], "BASELINE_ESTABLISHED")
            self.assertFalse(ledger.exists())

            new_row = filing("0001193125-26-100002", "8-K", items="2.03,8.01", document="mstr-new.htm")
            self.strategy_payload["filings"]["recent"] = sec_payload(
                self.strategy["cik"],
                "STRATEGY INC",
                [new_row, filing("0001193125-26-100001", "8-K", document="mstr.htm")],
            )["filings"]["recent"]
            second = run_issuer_announcement_cycle(
                self.registry,
                state_path=state,
                ledger_path=ledger,
                now_ms=NOW_MS + 3_600_000,
                fetcher=self.fetcher,
            )
            self.assertEqual(second["state"], "REANALYSIS_REQUESTED")
            self.assertEqual(second["new_event_count"], 1)
            self.assertEqual(second["new_events"][0]["classification"], "DEBT_OR_FINANCING")
            self.assertEqual(second["action_output"], "NONE")
            self.assertEqual(second["external_action_authority"], "NONE")
            self.assertFalse(second["external_action_performed"])
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

            third = run_issuer_announcement_cycle(
                self.registry,
                state_path=state,
                ledger_path=ledger,
                now_ms=NOW_MS + 7_200_000,
                fetcher=self.fetcher,
            )
            self.assertEqual(third["state"], "NO_WAKE")
            self.assertEqual(third["new_event_count"], 0)

    def test_failed_first_poll_does_not_turn_history_into_false_new_alert(self):
        def blocked_fetcher(url: str, **_: object):
            raise IssuerAnnouncementError(f"offline: {url}")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state.json"
            ledger = root / "events.jsonl"
            blocked = run_issuer_announcement_cycle(
                self.registry,
                state_path=state,
                ledger_path=ledger,
                now_ms=NOW_MS,
                fetcher=blocked_fetcher,
            )
            self.assertEqual(blocked["state"], "NO_WAKE")
            self.assertEqual(blocked["coverage_state"], "BLOCKED")
            self.assertEqual(blocked["reason"], "SOURCE_COVERAGE_BLOCKED")
            recovered = run_issuer_announcement_cycle(
                self.registry,
                state_path=state,
                ledger_path=ledger,
                now_ms=NOW_MS + 3_600_000,
                fetcher=self.fetcher,
            )
            self.assertEqual(recovered["state"], "NO_WAKE")
            self.assertEqual(recovered["reason"], "BASELINE_ESTABLISHED")
            self.assertEqual(recovered["new_event_count"], 0)

    def test_source_is_get_only_and_contains_no_execution_surface(self):
        source = (ROOT / "src" / "crt_radar" / "issuer_announcement_runner.py").read_text(encoding="utf-8")
        self.assertIn('method="GET"', source)
        for forbidden in ("place_order", "create_order", "cancel_order", "broker", "password", "api_key"):
            self.assertNotIn(forbidden, source.lower())
        windows_runner = (ROOT / "scripts" / "windows" / "run_observation_history_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("crt_radar.issuer_announcement_runner", windows_runner)
        self.assertIn("ISSUER_ANNOUNCEMENT_REGISTRY_V1.json", windows_runner)
        self.assertIn("issuer_announcements\\latest.json", windows_runner)


if __name__ == "__main__":
    unittest.main(verbosity=2)
