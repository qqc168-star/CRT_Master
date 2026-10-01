"""Offline fixtures only; never substitute them for live evidence."""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from crt_radar.daily_evidence_runner import main
from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate
from crt_radar.mstr_asst_market_health import build_issuer_ratio_observation, validate_issuer_ratio_observation, compact_issuer_ratio_observation
from crt_radar.mstr_asst_market_health_runtime import build_market_health_runtime_outputs, canonical_hash, seal_runtime_source
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.reanalysis_wake import fuse_reanalysis_wake
from tests.test_gpt_handoff import bridge_pack, pack as handoff_pack
from tests.test_strategy_ledger_runtime_binding import NOW, ledger_pair, ledger_runtime_bundle
from tests.test_wake_fusion import minimal_source_gate, no_wake, plan_drift


def proof(pair=None, observed=NOW):
    return seal_runtime_source(source_key="issuer_btc_per_diluted_share",data={"MSTR":pair or ledger_pair()},observed_at_ms=observed)


def observation(pair=None):
    return build_issuer_ratio_observation(proof(pair),generated_at_ms=NOW+1)


class IssuerObservationGptClosureTests(unittest.TestCase):
    def build_pack(self, td, section=None):
        capital=bridge_pack(handoff_pack(evidence_hash="a"*64,requested=False))["private_context"]
        return build_evidence_pack(minimal_source_gate(),observation_db=Path(td)/"obs.sqlite3",generated_at_ms=NOW+2,
            private_context=capital,reanalysis_wake=no_wake(),issuer_ratio_observation=section or observation())

    def test_commander_free_full_lane_preserves_locks_and_fact_surface(self):
        with tempfile.TemporaryDirectory() as td:
            result=self.build_pack(td)
            self.assertNotIn("mstr_asst_market_health",result)
            self.assertNotIn("issuer_facts",result)
            baseline=build_evidence_pack(minimal_source_gate(),observation_db=Path(td)/"base.sqlite3",generated_at_ms=NOW+2)
            self.assertEqual(result["asset_facts"],baseline["asset_facts"])
            self.assertEqual(result["formal_candidate"],baseline["formal_candidate"])
            self.assertEqual(result["pack_state"],"BLOCKED")
            wake=result["reanalysis_wake"]
            self.assertEqual(wake["state"],"REANALYSIS_REQUESTED")
            self.assertEqual(wake["wake_sources"],["MSTR_ISSUER_RATIO_OBSERVATION"])
            self.assertEqual(wake["wake_reasons"],["MSTR:BTC_PER_DILUTED_SHARE_DECREASED"])
            notice=build_plain_language_notice(result)
            self.assertIn("Observation only",notice["what_happened"])
            handoff=run_gpt_handoff_gate(result,notice,ledger_path=Path(td)/"handoff.jsonl")
            self.assertEqual(handoff["state"],"GPT_HANDOFF_READY")
            self.assertNotIn("LATEST_THREE_ARMY_COMMANDER_LINES",handoff["required_inputs"])
            self.assertIn("LATEST_ISSUER_RATIO_OBSERVATION",handoff["required_inputs"])
            bridge=build_minimized_bridge_payload(result,handoff)
            self.assertEqual(bridge["issuer_ratio_observation"]["observation_hash"],result["issuer_ratio_observation"]["observation_hash"])
            row=bridge["issuer_ratio_observation"]["observations"]["MSTR"]
            self.assertAlmostEqual(row["latest_to_previous_change_pct"],-0.12901833051349731)
            for key,value in {"time_semantic":"REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME","ct_binding_state":"NOT_CT_BOUND",
                "ct_blocker":"ADSO_EFFECTIVE_TIME_UNRESOLVED","wake_authority":"OBSERVATION_ONLY","machine_execution":"FORBIDDEN"}.items():
                self.assertEqual(row[key],value)
            self.assertFalse(any("effective_at" in k for k in row))
            self.assertEqual(bridge["authority"]["production"],"NOT_APPROVED")
            self.assertEqual(bridge["authority"]["trading_authority"],"NONE")
            self.assertLess(len(json.dumps(bridge,ensure_ascii=False,separators=(",",":")).encode()),16384)
            self.assertNotIn("never-export@example.com",json.dumps(bridge))

    def test_missing_commander_still_blocks_full_market_health(self):
        bundle=ledger_runtime_bundle(); del bundle["source_proofs"]["commander_lines"]
        with self.assertRaisesRegex(ValueError,"exactly the five"): build_market_health_runtime_outputs(bundle)
        self.assertEqual(observation()["state"],"VALID")

    def test_asst_sec_effective_clocks_preserved(self):
        sec={"previous_effective_at_ms":NOW-2000,"current_effective_at_ms":NOW-1000}
        for prefix,btc,shares in (("previous",26355,100144713),("current",27462,100776795)):
            sec.update({f"{prefix}_btc_holdings":btc,f"{prefix}_diluted_shares":shares,f"{prefix}_btc_per_diluted_share":btc/shares,
                f"{prefix}_source_url":"https://www.sec.gov/Archives/edgar/data/1920406/test.htm",f"{prefix}_evidence_hash":"c"*64})
        raw=seal_runtime_source(source_key="issuer_btc_per_diluted_share",data={"MSTR":ledger_pair(),"ASST":sec},observed_at_ms=NOW)
        row=build_issuer_ratio_observation(raw,generated_at_ms=NOW+1)["observations"]["ASST"]
        for key,value in sec.items(): self.assertEqual(row[key],value)
        self.assertNotIn("time_semantic",row)
        compact=compact_issuer_ratio_observation(build_issuer_ratio_observation(raw,generated_at_ms=NOW+1),generated_at_ms=NOW+2)["observations"]["ASST"]
        self.assertEqual(compact["previous_effective_at_ms"],sec["previous_effective_at_ms"])
        self.assertEqual(compact["current_effective_at_ms"],sec["current_effective_at_ms"])
        self.assertEqual(compact["evidence_hash"],sec["current_evidence_hash"])
        self.assertAlmostEqual(row["latest_to_previous_change_pct"],3.546786669848223)
        full=build_market_health_runtime_outputs(ledger_runtime_bundle())["market_health"]
        self.assertFalse(full["assets"]["ASST"]["reanalysis_required"])

    def test_flat_and_increasing_ratios_do_not_wake(self):
        for btc in (846000,850000):
            pair=ledger_pair(); pair["current_diluted_shares"]=pair["previous_diluted_shares"]
            pair["current_btc_holdings"]=btc; pair["current_btc_per_diluted_share"]=btc/pair["current_diluted_shares"]
            self.assertIsNone(fuse_reanalysis_wake(None,plan_drift=plan_drift(False),issuer_ratio_observation=observation(pair)))

    def test_tampered_source_proofs_fail_closed(self):
        for mutation in ({"data_hash":"0"*64},{"source_id":"UNVERIFIED"},{"validation_state":"BLOCKED"},
            {"observed_at_ms":NOW+10},{"external_action_authority":"TRADE"}):
            raw=proof(); raw.update(mutation)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): build_issuer_ratio_observation(raw,generated_at_ms=NOW+1)

    def test_resealed_clock_and_authority_fabrication_rejected(self):
        for mutation in ({"current_effective_at_ms":NOW},{"ct_binding_state":"CT_BOUND"},{"current_retrieved_at_ms":NOW+10},
            {"current_diluted_shares":1},{"machine_execution":"ALLOWED"},{"latest_to_previous_change_pct":0},{"email":"MUST_NOT_EXPORT"}):
            section=observation(); section["observations"]["MSTR"].update(mutation)
            section.pop("observation_hash"); section["observation_hash"]=canonical_hash(section)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): validate_issuer_ratio_observation(section)
        section=observation(); section["action_output"]="SELL"
        with self.assertRaises(ValueError): validate_issuer_ratio_observation(section)

    def test_future_section_rejected_at_pack_boundary(self):
        with tempfile.TemporaryDirectory() as td,self.assertRaises(ValueError):
            build_evidence_pack(minimal_source_gate(),observation_db=Path(td)/"obs.sqlite3",generated_at_ms=NOW,issuer_ratio_observation=observation())

    def test_fused_wakes_keep_btc_plan_and_issuer(self):
        base=no_wake(); base["state"]="REANALYSIS_REQUESTED"; base["reason"]="BTC_CHANGE"
        wake=fuse_reanalysis_wake(base,plan_drift=plan_drift(True),issuer_ratio_observation=observation())
        self.assertEqual(wake["reason"],"BTC_CHANGE")
        self.assertEqual(wake["wake_sources"],["BTC_INTRADAY","MSTR_ISSUER_RATIO_OBSERVATION","PLAN_DRIFT"])
        self.assertEqual(wake["action_output"],"NONE")

    def test_pair_identity_dedupes_refetch_but_not_changed_observation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger=Path(td)/"handoff.jsonl"; first=self.build_pack(td)
            a=run_gpt_handoff_gate(first,build_plain_language_notice(first),ledger_path=ledger)
            pair=ledger_pair(); pair["current_retrieved_at_ms"]=NOW+1
            section=build_issuer_ratio_observation(proof(pair,observed=NOW+1),generated_at_ms=NOW+2)
            second=self.build_pack(td,section)
            b=run_gpt_handoff_gate(second,build_plain_language_notice(second),ledger_path=ledger)
            self.assertEqual(b["state"],"DUPLICATE_SKIPPED"); self.assertEqual(a["event_id"],b["event_id"])
            pair=ledger_pair(); pair["current_btc_holdings"]-=10
            pair["current_btc_per_diluted_share"]=pair["current_btc_holdings"]/pair["current_diluted_shares"]
            third=self.build_pack(td,observation(pair))
            c=run_gpt_handoff_gate(third,build_plain_language_notice(third),ledger_path=ledger)
            self.assertEqual(c["state"],"GPT_HANDOFF_READY"); self.assertNotEqual(a["event_id"],c["event_id"])

    def test_daily_cli_consumes_existing_proof_without_commander(self):
        with tempfile.TemporaryDirectory() as td:
            raw=Path(td)/"proof.json"; raw.write_text(json.dumps(proof()))
            result=self.build_pack(td)
            with patch("crt_radar.daily_evidence_runner.run_daily_evidence",return_value=result) as runner,patch("builtins.print"):
                self.assertEqual(main(["--issuer-ratio-proof",str(raw),"--output",str(Path(td)/"pack.json")]),0)
            self.assertIsNone(runner.call_args.kwargs["mstr_asst_market_health"])
            self.assertEqual(runner.call_args.kwargs["issuer_ratio_observation"]["observations"]["MSTR"]["current_reported_date"],"2026-09-28")

    def test_invalid_section_rejected_by_bridge_after_pack_build(self):
        with tempfile.TemporaryDirectory() as td:
            result=self.build_pack(td)
            handoff=run_gpt_handoff_gate(result,build_plain_language_notice(result),ledger_path=Path(td)/"handoff.jsonl")
            result["issuer_ratio_observation"]["observations"]["MSTR"]["ct_binding_state"]="CT_BOUND"
            with self.assertRaises(ValueError): build_minimized_bridge_payload(result,handoff)

    def test_oversized_market_context_keeps_literal_issuer_contract(self):
        with tempfile.TemporaryDirectory() as td:
            result=self.build_pack(td)
            result["changes"]={str(i):"research-only detail"*100 for i in range(20)}
            handoff=run_gpt_handoff_gate(result,build_plain_language_notice(result),ledger_path=Path(td)/"handoff.jsonl")
            bridge=build_minimized_bridge_payload(result,handoff)
            row=bridge["issuer_ratio_observation"]["observations"]["MSTR"]
            self.assertEqual(row["time_semantic"],"REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME")
            self.assertEqual(row["current_reported_date"],"2026-09-28")
            self.assertLess(len(json.dumps(bridge,ensure_ascii=False,separators=(",",":")).encode()),16384)

    def test_a_new_adjacent_reported_pair_is_not_deduplicated(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            ledger=Path(td)/"handoff.jsonl"
            first=self.build_pack(td)
            a=run_gpt_handoff_gate(first,build_plain_language_notice(first),ledger_path=ledger)
            pair=ledger_pair()
            for prefix,date in (("previous","2026-09-14"),("current","2026-09-21")):
                pair[f"{prefix}_reported_date"]=date
                pair[f"{prefix}_reported_at_ms"]=int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()*1000)
            second=self.build_pack(td,observation(pair))
            b=run_gpt_handoff_gate(second,build_plain_language_notice(second),ledger_path=ledger)
            self.assertEqual(b["state"],"GPT_HANDOFF_READY")
            self.assertNotEqual(a["event_id"],b["event_id"])

if __name__ == "__main__": unittest.main()
