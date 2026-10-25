from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from crt_radar.btc_tactical_forecast import (
    DAY_MS, PRE, POST, content_hash, freeze_pre, freeze_post, read_pre,
    revise_price_anchor, session_schedule,
)
from crt_radar.observation_store import ObservationRevisionConflict, ObservationStore


class TacticalForecastTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "observations.sqlite3"
        self.store = ObservationStore(self.path)
        self.schedule = session_schedule("2026-10-23")
        self.now = self.schedule["pre_due_ms"]
        self.source = {
            "source_id": "SYNTHETIC_TEST_ONLY", "source_ref": "fixture:btc",
            "evidence_hash": "a" * 64, "validation_ref": "fixture:source-gate",
            "quality_state": "RESEARCH_ONLY", "observed_at_ms": self.now - 1000,
            "available_at_ms": self.now - 900, "retrieved_at_ms": self.now - 800,
            "validated_at_ms": self.now - 700,
        }
        self.anchor = {"price": 80000.0, "currency": "USDT",
                       "price_basis": "SPOT_OBSERVATION", "source_ref": "fixture:btc",
                       "observed_at_ms": self.source["observed_at_ms"]}
        self.pre = {
            "id": "test:pre:2026-10-23", "session_date": "2026-10-23",
            "generated_at_ms": self.now, "market_cutoff_ms": self.now,
            "original_text": "合成案例，並非真實預測。\n上行待確認。",
            "main_scenario": "Conditional upward path, not a trade.",
            "invalidation_line": "A qualified close below the frozen anchor invalidates.",
            "strongest_counterevidence": "Weak spot participation.",
            "change_conditions": "A source-qualified failed retest changes the view.",
            "analyst_ref": "synthetic-test", "program_version": "test-version",
            "sources": [deepcopy(self.source)], "price_anchor": deepcopy(self.anchor),
            "claims": [{"claim_id": "direction", "statement": "Close above frozen anchor",
                        "verification_condition": "Compare same venue/currency completed close",
                        "target_at_ms": self.now + 7 * DAY_MS}],
        }

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def post(self, pre):
        now = self.schedule["post_due_ms"]
        source = dict(self.source, observed_at_ms=self.schedule["close_ms"],
                      available_at_ms=now - 3, retrieved_at_ms=now - 2,
                      validated_at_ms=now - 1, evidence_hash="b" * 64)
        return {
            "id": "test:post:2026-10-23", "pre_id": self.pre["id"],
            "pre_hash": pre["content_hash"], "session_date": "2026-10-23",
            "generated_at_ms": now, "market_cutoff_ms": now,
            "original_text": "First daily review; 1-week outcome is still pending.",
            "analyst_ref": "synthetic-reviewer", "program_version": "test-version",
            "sources": [source],
            "reviews": [{"claim_id": "direction", "result": "PENDING",
                         "source_refs": ["fixture:btc"], "reason": "Horizon incomplete"}],
        }

    def test_duplicate_identical_pre_is_idempotent_even_after_open(self):
        first = freeze_pre(self.store, self.pre, now_ms=self.now)
        second = freeze_pre(self.store, self.pre, now_ms=self.now + DAY_MS)
        self.assertEqual(first, second)
        count = self.store.conn.execute("SELECT count(*) FROM btc_research_events").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(first["content"]["timing_state"], "PRE_WINDOW")

    def test_same_pre_id_different_content_rejected(self):
        freeze_pre(self.store, self.pre, now_ms=self.now)
        self.pre["original_text"] += " changed target"
        with self.assertRaises(ObservationRevisionConflict):
            freeze_pre(self.store, self.pre, now_ms=self.now)

    def test_close_reopen_preserves_original_text_hash_and_generated_time(self):
        first = freeze_pre(self.store, self.pre, now_ms=self.now)
        self.store.close()
        self.store = ObservationStore(self.path)
        record = read_pre(self.store, self.pre["id"], first["content_hash"])
        self.assertEqual(record, first)
        self.assertEqual(record["content"]["original_text"], self.pre["original_text"])
        self.assertEqual(record["content_hash"], content_hash(record["content"]))
        self.assertEqual(record["content"]["generated_at_ms"], self.now)

    def test_post_missing_pre_and_wrong_hash_rejected(self):
        post = self.post({"content_hash": "b" * 64})
        with self.assertRaisesRegex(ValueError, "PRE_NOT_FOUND"):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])
        freeze_pre(self.store, self.pre, now_ms=self.now)
        with self.assertRaisesRegex(ValueError, "PRE_HASH_MISMATCH"):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_post_reviews_exact_original_claims_and_is_immutable(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        post = self.post(pre)
        result = freeze_post(self.store, post, now_ms=post["generated_at_ms"])
        self.assertEqual(result["content"]["linkage_state"], "PRE_LINK_VERIFIED")
        self.assertEqual(result["assessment_authority"], "RESEARCH_ONLY")
        self.assertEqual(freeze_post(self.store, post, now_ms=post["generated_at_ms"]), result)
        post["reviews"][0]["reason"] = "rewrite"
        with self.assertRaises(ObservationRevisionConflict):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_omitted_or_retargeted_claim_cannot_count_as_review(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        for reviews in ([], [{"claim_id": "new target"}]):
            post = self.post(pre)
            post["reviews"] = reviews
            with self.assertRaisesRegex(ValueError, "EACH_ORIGINAL_CLAIM"):
                freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_daily_review_cannot_claim_one_week_forecast_already_succeeded(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        post = self.post(pre)
        post["reviews"][0]["result"] = "SUPPORTED"
        with self.assertRaisesRegex(ValueError, "OUTCOME_OBSERVATION_MISSING|HORIZON_NOT_COMPLETE"):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_completed_horizon_can_store_supported_assessment_not_trade_authority(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        post = self.post(pre)
        post["session_date"] = "2026-10-30"
        post["generated_at_ms"] = post["market_cutoff_ms"] = session_schedule("2026-10-30")["post_due_ms"]
        post["sources"][0].update(
            observed_at_ms=session_schedule("2026-10-30")["close_ms"],
            available_at_ms=post["generated_at_ms"] - 3,
            retrieved_at_ms=post["generated_at_ms"] - 2,
            validated_at_ms=post["generated_at_ms"] - 1)
        post["reviews"][0]["result"] = "SUPPORTED"
        result = freeze_post(self.store, post, now_ms=post["generated_at_ms"])
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")

    def test_invalidated_before_horizon_can_be_recorded_with_evidence(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        post = self.post(pre)
        post["reviews"][0].update(result="REFUTED", reason="Frozen invalidation condition met")
        result = freeze_post(self.store, post, now_ms=post["generated_at_ms"])
        self.assertEqual(result["content"]["reviews"][0]["result"], "REFUTED")

    def test_post_before_close_plus_six_hours_is_rejected(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        post = self.post(pre)
        post["generated_at_ms"] -= 1
        post["market_cutoff_ms"] -= 1
        with self.assertRaisesRegex(ValueError, "POST_BEFORE_SESSION_REVIEW"):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_future_source_cannot_leak_into_pre_or_post(self):
        self.pre["sources"][0]["validated_at_ms"] = self.now + 1
        with self.assertRaisesRegex(ValueError, "SOURCE_NOT_VISIBLE"):
            freeze_pre(self.store, self.pre, now_ms=self.now)
        self.pre["sources"][0] = deepcopy(self.source)
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        post = self.post(pre)
        post["sources"][0]["retrieved_at_ms"] = post["market_cutoff_ms"] + 1
        with self.assertRaisesRegex(ValueError, "SOURCE_NOT_VISIBLE"):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_blocked_sources_preserved_but_cannot_prove_outcome(self):
        self.pre["sources"][0]["quality_state"] = "BLOCKED"
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        self.assertEqual(pre["content"]["sources"][0]["quality_state"], "BLOCKED")
        post = self.post(pre)
        post["sources"][0]["quality_state"] = "BLOCKED"
        post["reviews"][0]["result"] = "REFUTED"
        with self.assertRaisesRegex(ValueError, "REVIEW_EVIDENCE_BLOCKED"):
            freeze_post(self.store, post, now_ms=post["generated_at_ms"])
        post["reviews"][0]["result"] = "INCONCLUSIVE"
        freeze_post(self.store, post, now_ms=post["generated_at_ms"])

    def test_late_import_not_misrepresented_as_prospective_pre(self):
        result = freeze_pre(self.store, self.pre, now_ms=self.schedule["open_ms"] + 1)
        self.assertEqual(result["content"]["timing_state"], "OUTSIDE_PRE_WINDOW")

    def revision(self, pre):
        new = deepcopy(self.anchor)
        new["price"] += 100
        return {"id": "test:anchor:1", "pre_id": self.pre["id"],
                "pre_hash": pre["content_hash"], "previous_id": self.pre["id"],
                "old_anchor": deepcopy(self.anchor), "new_anchor": new,
                "changed_at_ms": self.now + 1000, "sources": [deepcopy(self.source)],
                "reason": "New observed anchor; original targets remain unchanged"}

    def test_anchor_changes_append_old_new_source_time_reason_without_rewriting_pre(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        revision = self.revision(pre)
        result = revise_price_anchor(self.store, revision, now_ms=self.now + 1000)
        self.assertEqual(result["content"], revision)
        self.assertEqual(revise_price_anchor(self.store, revision, now_ms=self.now + 2000), result)
        self.assertEqual(read_pre(self.store, self.pre["id"], pre["content_hash"]), pre)
        next_revision = deepcopy(revision)
        next_revision.update(id="test:anchor:2", previous_id=revision["id"],
                             old_anchor=revision["new_anchor"], changed_at_ms=self.now + 2000)
        next_revision["new_anchor"] = dict(revision["new_anchor"], price=80200)
        revise_price_anchor(self.store, next_revision, now_ms=self.now + 2000)
        stale = deepcopy(revision)
        stale["id"] = "test:anchor:fork"
        with self.assertRaisesRegex(ValueError, "ANCHOR_HISTORY_MISMATCH"):
            revise_price_anchor(self.store, stale, now_ms=self.now + 2000)

    def test_anchor_missing_reason_source_or_old_value_fails(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        for field, value in (("reason", ""), ("sources", []), ("old_anchor", {})):
            revision = self.revision(pre)
            revision[field] = value
            with self.assertRaises(ValueError):
                revise_price_anchor(self.store, revision, now_ms=self.now + 1000)

    def test_database_tamper_detected_by_existing_store(self):
        pre = freeze_pre(self.store, self.pre, now_ms=self.now)
        self.store.conn.execute("UPDATE btc_research_events SET payload_json='{}'")
        self.store.conn.commit()
        with self.assertRaises(ObservationRevisionConflict):
            read_pre(self.store, self.pre["id"], pre["content_hash"])

    def test_shared_calendar_dst_early_close_holiday_and_expiry(self):
        utc = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%H:%M")
        self.assertEqual(utc(self.schedule["pre_due_ms"]), "12:30")
        self.assertEqual(utc(self.schedule["post_due_ms"]), "02:00")
        winter = session_schedule("2026-11-02")
        self.assertEqual(utc(winter["pre_due_ms"]), "13:30")
        self.assertEqual(utc(winter["post_due_ms"]), "03:00")
        early = session_schedule("2026-11-27")
        self.assertEqual(utc(early["post_due_ms"]), "00:00")
        for day in ("2026-11-26", "2026-10-25", "2029-01-02"):
            with self.assertRaises(ValueError):
                session_schedule(day)

    def test_horizon_and_nonfinite_anchor_rejected(self):
        bad = deepcopy(self.pre)
        bad["claims"][0]["target_at_ms"] = self.now + DAY_MS
        with self.assertRaisesRegex(ValueError, "HORIZON_OUTSIDE"):
            freeze_pre(self.store, bad, now_ms=self.now)
        self.pre["price_anchor"]["price"] = float("nan")
        with self.assertRaisesRegex(ValueError, "PRICE_ANCHOR_INVALID"):
            freeze_pre(self.store, self.pre, now_ms=self.now)

    def test_only_existing_research_table_used(self):
        freeze_pre(self.store, self.pre, now_ms=self.now)
        tables = {row[0] for row in self.store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {"observations", "btc_research_events", "sqlite_sequence"})
        self.assertIsNotNone(self.store.research_event(self.pre["id"], kind=PRE))
        self.assertIsNone(self.store.research_event("none", kind=POST))

    def test_doctrine_preserves_scope_and_explains_cloud_boundary(self):
        doctrine = (Path(__file__).resolve().parents[2] / "CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md").read_text(encoding="utf-8")
        for text in ("BTC Daily Tactical PRE / POST", "PRE_LINK_VERIFIED", "OUTSIDE_PRE_WINDOW",
                     "跨環境", "BLOCKED", "$57K", "不得事後改靶", "1～3 週"):
            self.assertIn(text, doctrine)


if __name__ == "__main__":
    unittest.main()
