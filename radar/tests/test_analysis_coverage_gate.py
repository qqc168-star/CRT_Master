"""Q0 negative tests: slogans, omissions and forged pack bindings are not passes."""
import copy
import hashlib
import json
import unittest

from crt_radar.analysis_coverage_gate import ORGANS, REASONING_STEPS, audit_360_coverage


def fixture():
    pack = {
        "generated_at_ms": 1791960000000,
        "layers": {"L1": {"status": "VALID", "metrics": {"example": 1}}},
        "model_status": {"btc_season_router": {"state": "CANDIDATE_BLOCKED", "season": None}},
        "common_equity_health": {"assets": {"MSTR": {"health_direction": "STABLE"}}},
        "asset_strategy_delta": {"assets": {"STRC": {"strategy_delta": "INCOME_COVERAGE_REVIEW"}}},
        "portfolio_allocation_context": {"state": "BLOCKED"},
    }
    pack["evidence_pack_hash"] = hashlib.sha256(json.dumps(
        pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    base = {"state": "BLOCKED", "judgment": "這個項目的正式判讀尚未完成來源驗真",
            "contradictions": "與局部研究觀察仍存在待釐清的矛盾",
            "capital_effect": "不能據此增加持倉或宣稱取得交易資格",
            "invalidation": "若取得新的合格資料需要重新判斷",
            "next_trigger": "待當期來源及觀測時鐘符合正式要求",
            "evidence_paths": [], "blocked_reasons": ["正式來源與當期時間口徑未完成驗真"]}
    organs = {group: {key: copy.deepcopy(base) for key in keys}
              for group, keys in ORGANS.items()}
    # One independently usable piece of actual pack evidence; not a trade instruction.
    organs["BTC"]["L1"].update(state="SOURCE_BOUND", evidence_paths=["/layers/L1"], blocked_reasons=[])
    reasoning = {k: "已依現存來源做局部分析，其餘等待獨立來源驗證" for k in REASONING_STEPS}
    actions = {asset: {"action": "WAIT", "reason": "未具備足夠新增資本所需的完整證據",
                       "invalidation": "取得相反市場與發行人資訊時重估",
                       "next_trigger": "等候正式估值和券商已確認現金"}
               for asset in ("MSTR", "ASST", "STRC", "SATA")}
    return pack, {"analysis_as_of_ms": 1791960010000,
                  "evidence_pack_hash": pack["evidence_pack_hash"],
                  "organs": organs, "reasoning": reasoning, "actions": actions}


class Q0CoverageGateTests(unittest.TestCase):
    def test_accounted_for_but_blocked_is_not_falsely_certified(self):
        pack, report = fixture()
        result = audit_360_coverage(report, pack)
        self.assertEqual(result["coverage_state"], "REVIEWED_WITH_BLOCKERS")
        self.assertEqual(result["reasoning_state"], "NOT_YET_PROVEN")
        self.assertFalse(result["may_claim_crt_360_complete"])
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")

    def test_missing_company_health_fails_even_with_all_other_titles(self):
        pack, report = fixture()
        del report["organs"]["MSTR"]["company_health"]
        result = audit_360_coverage(report, pack)
        self.assertEqual(result["coverage_state"], "INCOMPLETE")
        self.assertIn("ORGAN_MISSING:MSTR.company_health", result["problems"])

    def test_missing_dual_hairpin_and_q1_fails(self):
        pack, report = fixture()
        del report["organs"]["PORTFOLIO"]["dual_hairpin_six_month_cash"]
        del report["organs"]["BTC"]["q1_control_transfer"]
        result = audit_360_coverage(report, pack)
        self.assertIn("ORGAN_MISSING:PORTFOLIO.dual_hairpin_six_month_cash", result["problems"])
        self.assertIn("ORGAN_MISSING:BTC.q1_control_transfer", result["problems"])

    def test_not_run_is_not_a_source_blocker(self):
        pack, report = fixture()
        report["organs"]["ASST"]["formal_mnav"]["state"] = "NOT_RUN"
        result = audit_360_coverage(report, pack)
        self.assertIn("ORGAN_NOT_RUN:ASST.formal_mnav", result["problems"])

    def test_labels_only_do_not_pass(self):
        pack, report = fixture()
        report["organs"]["MSTR"]["btc_per_diluted_share"] = {"state": "BLOCKED"}
        result = audit_360_coverage(report, pack)
        self.assertTrue(any(x.startswith("REVIEW_FIELD_MISSING:MSTR.btc_per_diluted_share")
                            for x in result["problems"]))

    def test_blocker_must_have_a_specific_reason(self):
        pack, report = fixture()
        report["organs"]["SATA"]["cash_income"]["blocked_reasons"] = []
        result = audit_360_coverage(report, pack)
        self.assertIn("BLOCKED_WITHOUT_SPECIFIC_REASON:SATA.cash_income", result["problems"])

    def test_source_reference_must_exist_and_match_organ_family(self):
        pack, report = fixture()
        report["organs"]["MSTR"]["formal_mnav"].update(
            state="SOURCE_BOUND", evidence_paths=["/layers/L1"], blocked_reasons=[])
        result = audit_360_coverage(report, pack)
        self.assertIn("EVIDENCE_ROOT_MISMATCH:MSTR.formal_mnav:/layers/L1", result["problems"])
        report["organs"]["MSTR"]["formal_mnav"]["evidence_paths"] = ["/asset_facts/no_such_fact"]
        result = audit_360_coverage(report, pack)
        self.assertTrue(any(x.startswith("PATH_NOT_IN_EVIDENCE_PACK:MSTR.formal_mnav")
                            for x in result["problems"]))

    def test_blocked_source_cannot_be_marked_source_bound(self):
        pack, report = fixture()
        report["organs"]["PORTFOLIO"]["allocation_translation"].update(
            state="SOURCE_BOUND", evidence_paths=["/portfolio_allocation_context"], blocked_reasons=[])
        result = audit_360_coverage(report, pack)
        self.assertTrue(any(x.startswith("BLOCKED_SOURCE_MARKED_BOUND:PORTFOLIO.allocation_translation")
                            for x in result["problems"]))

    def test_rehash_or_old_pack_is_rejected(self):
        pack, report = fixture()
        pack["layers"]["L1"]["metrics"]["example"] = 2
        result = audit_360_coverage(report, pack)
        self.assertIn("EVIDENCE_PACK_LINEAGE_INVALID", result["problems"])
        pack, report = fixture()
        report["analysis_as_of_ms"] = pack["generated_at_ms"] - 1
        result = audit_360_coverage(report, pack)
        self.assertIn("REPORT_CLOCK_BEFORE_EVIDENCE_OR_INVALID", result["problems"])

    def test_missing_reasoning_or_any_of_four_actions_fails(self):
        pack, report = fixture()
        del report["reasoning"]["evidence_independence"]
        del report["actions"]["SATA"]
        result = audit_360_coverage(report, pack)
        self.assertIn("REASONING_STEP_MISSING:evidence_independence", result["problems"])
        self.assertIn("ACTION_MISSING:SATA", result["problems"])

    def test_all_blocked_is_not_full_analysis(self):
        pack, report = fixture()
        report["organs"]["BTC"]["L1"].update(
            state="BLOCKED", evidence_paths=[], blocked_reasons=["L1正式輸入不可用"])
        result = audit_360_coverage(report, pack)
        self.assertEqual(result["coverage_state"], "INCOMPLETE")
        self.assertIn("NO_INDEPENDENT_SOURCE_BOUND_ANALYSIS", result["problems"])


if __name__ == "__main__":
    unittest.main()
