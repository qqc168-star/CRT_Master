"""Synthetic qualification tests; real public archives are replayed separately."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crt_radar.company_health_evidence_replay import build_health_receipt, run_archive_replay
from crt_radar.evidence_pack import build_evidence_pack, _sha256
from crt_radar.portfolio_allocation_context import build_common_equity_health
from test_company_health import scenario
from test_first_evidence_slice import gate, BASE_MS
import test_issuer_ratio_market_health_source as archive_fixtures
from test_strategy_ledger_runtime_binding import ledger_html, URL

MAIN="b"*40
ARCHIVE="c"*64


def seal(pack):
    pack.pop("evidence_pack_hash",None)
    pack["evidence_pack_hash"]=_sha256(pack)


class CompanyHealthEvidenceReplayTests(unittest.TestCase):
    def bundle(self, mutate=None):
        g=gate(0)
        data={"MSTR":scenario(),"ASST":scenario(True)}
        for row in data.values(): row["as_of_ms"]=BASE_MS
        if mutate: mutate(data)
        with tempfile.TemporaryDirectory() as d:
            p=build_evidence_pack(g,observation_db=Path(d)/"o.db",generated_at_ms=BASE_MS,
                treasury_company_ct_inputs=data)
        return p,g,data

    def receipt(self,p,g,**kw):
        return build_health_receipt(p,g,main_sha=MAIN,validated_at_ms=BASE_MS+1,archive_hash=ARCHIVE,**kw)

    def test_same_inputs_recompute_both_original_six_dimension_models_without_mutation(self):
        p,g,_=self.bundle();before=deepcopy(p)
        a=self.receipt(p,g);b=self.receipt(p,g)
        self.assertEqual(a,b)
        self.assertEqual(p,before)
        self.assertTrue(a["cached_health_matches"])
        expected=build_common_equity_health(p)
        for asset in ("MSTR","ASST"):
            row=a["calculation"]["companies"][asset]
            self.assertEqual(row["health"],expected["assets"][asset])
            self.assertEqual(len(row["health"]["company_health"]["dimensions"]),6)
        self.assertEqual(a["source_gate_run_id"],g["run_id"])
        self.assertEqual(a["evidence_pack_hash"],p["evidence_pack_hash"])
        self.assertEqual(a["action_output"],"NONE")
        self.assertEqual(a["production"],"NOT_APPROVED")
        self.assertEqual(a["formal_season"],None)

    def test_stale_expired_and_future_mstr_sources_block_affected_claim_not_asst(self):
        baseline,gate_data,_=self.bundle()
        other=self.receipt(baseline,gate_data)["calculation"]["companies"]["ASST"]
        for kind in ("STALE","EXPIRED","FUTURE"):
            def change(data):
                row=data["MSTR"]["asset_history"][-1]
                if kind=="STALE": row["quality_state"]="STALE"
                elif kind=="EXPIRED": row["valid_until_ms"]=BASE_MS-1
                else:
                    for k in ("disclosure_time","first_seen_time","retrieval_time"): row[k]=BASE_MS+1
            with self.subTest(kind=kind):
                p,g,data=self.bundle(change);r=self.receipt(p,g)["calculation"]["companies"]
                claim=r["MSTR"]["health"]["company_health"]["dimensions"]["per_share_asset_engine"]["claims"]["btc_per_diluted_share"]
                self.assertIsNone(claim["value"])
                self.assertEqual(claim["direction"],"BLOCKED")
                self.assertEqual(r["ASST"],other)
                self.assertEqual(data["MSTR"]["asset_history"][-1]["btc_holdings"],110)
                self.assertTrue(r["MSTR"]["health"]["company_health"]["dimensions"]["funding_market_acceptance"]["supporting_evidence"])

    def test_foreign_issuer_fact_is_excluded_not_reassigned_to_strategy(self):
        p,g,_=self.bundle();baseline=self.receipt(p,g)
        fact=next(f for f in p["asset_facts"]["items"] if f.get("issuer_id")=="CIK-0001920406"
            and f.get("ct_section")=="per_share_asset_engine")
        fact["asset_id"]="MSTR";seal(p)
        result=self.receipt(p,g)
        self.assertEqual(result["calculation"]["exclusions"][0]["reason"],"ASSET_ISSUER_BINDING_MISMATCH")
        self.assertEqual(result["calculation"]["companies"]["MSTR"],baseline["calculation"]["companies"]["MSTR"])
        self.assertIsNone(result["calculation"]["companies"]["ASST"]["health"]["btc_per_diluted_share"])

    def test_gate_pack_cutoff_hash_and_private_context_mismatches_refuse_receipt(self):
        p,g,_=self.bundle()
        for field,value in (("source_gate_run_id","foreign-run"),("source_gate_idempotency_key","0"*64),
                ("private_context",{"forbidden":"synthetic"})):
            x=deepcopy(p);x[field]=value;seal(x)
            with self.subTest(field=field),self.assertRaises(ValueError):self.receipt(x,g)
        bad=deepcopy(p);bad["evidence_pack_hash"]="0"*64
        with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"): self.receipt(bad,g)
        bad=deepcopy(g);bad["as_of_ms"]+=1
        with self.assertRaisesRegex(ValueError,"CLOCK_INVALID"):self.receipt(p,bad)

    def test_newer_scope_incomplete_snapshot_cannot_make_old_health_look_current(self):
        p,g,_=self.bundle();original=self.receipt(p,g)
        from test_treasury_company_ct import T2,evidence
        reported=evidence(T2+1,claim="REPORTED_CAPITAL_STRUCTURE_SNAPSHOT",reported_fields={"btc_holdings":999},share_basis="UNRESOLVED")
        reported["issuer_id"]="CIK-0001920406"
        p["asset_facts"]["items"].append(dict(issuer_id="CIK-0001920406",fact_type="ISSUER_CT_SOURCE_BINDING",
            evidence={"observations":[reported]}))
        seal(p);result=self.receipt(p,g)["calculation"]["companies"]
        self.assertEqual(result["ASST"]["current_health_qualification"],"BLOCKED")
        self.assertEqual(result["ASST"]["health"],original["calculation"]["companies"]["ASST"]["health"])
        self.assertEqual(result["MSTR"],original["calculation"]["companies"]["MSTR"])

    def test_offline_archive_replay_preserves_reported_adso_and_missing_initial_preference(self):
        fixture=archive_fixtures.ArchivedCapitalFactsTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.add("ASST",fixture.ASST)
        fixture.inputs()
        lane=fixture.root/"ledger-raw";lane.mkdir()
        raw=ledger_html();digest=hashlib.sha256(raw).hexdigest()
        (lane/f"ledger-{digest}.html").write_bytes(raw)
        (lane/"retrieval-test.json").write_text(json.dumps(dict(source_url=URL,http_status=200,
            evidence_hash=digest,retrieved_at_ms=fixture.NOW-1000)),encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);g=gate(0);g["as_of_ms"]=fixture.NOW
            gate_file=root/"gate.json";gate_file.write_text(json.dumps(g),encoding="utf-8")
            out=root/"research"
            with patch("urllib.request.urlopen",side_effect=AssertionError("NO_NETWORK")),\
                    patch("crt_radar.daily_evidence_runner.run_daily_evidence",side_effect=AssertionError("NO_NORMAL_RUNNER")):
                result=run_archive_replay(issuer_archive=fixture.root,source_gate_path=gate_file,
                    output_dir=out,main_sha=MAIN)
            self.assertEqual(result["state"],"PASS")
            self.assertEqual(result["health_calculation_hashes"][0],result["health_calculation_hashes"][1])
            p=json.loads((out/"replay-1/evidence-pack.json").read_text(encoding="utf-8"))
            receipt=json.loads((out/"replay-1/health-receipt.json").read_text(encoding="utf-8"))
            data=json.loads((out/"ct-inputs.json").read_text(encoding="utf-8"))
            self.assertEqual(data["MSTR"]["asset_history"],[])
            self.assertIn("ADSO_EFFECTIVE_TIME_UNRESOLVED",str(data["MSTR"]["source_binding"]["blockers"]))
            self.assertIsNone(receipt["calculation"]["companies"]["MSTR"]["health"]["btc_per_diluted_share"])
            coverage=receipt["calculation"]["companies"]["ASST"]["research_asset_coverage"]
            self.assertIsNone(coverage["value"])
            self.assertIn("initial_preferred_claims_usd",coverage["inputs"]["missing_components"])
            binding=next(f for f in p["asset_facts"]["items"] if f.get("fact_type")=="ISSUER_CT_SOURCE_BINDING"
                and f.get("issuer_id")=="CIK-0001920406")
            self.assertIn("284700000",str(binding["evidence"]))
            with self.assertRaisesRegex(ValueError,"OUTPUT_EXISTS"):
                run_archive_replay(issuer_archive=fixture.root,source_gate_path=gate_file,output_dir=out,main_sha=MAIN)

    def test_wrong_historical_raw_or_issuer_url_blocks_only_that_archived_company(self):
        from crt_radar.issuer_ratio_market_health_source import build_archived_issuer_ct_inputs
        for defect in ("HASH","ISSUER","FUTURE"):
            fixture=archive_fixtures.ArchivedCapitalFactsTests();fixture.setUp()
            try:
                row=fixture.add("ASST",fixture.ASST)
                fixture.add("MSTR","0001050446 As of October 4, 2026, the balances of the USD Reserve and USD Cash were $4.88 billion and $833.4 million, respectively.",2)
                if defect=="HASH":row["raw_sha256"]="0"*64
                elif defect=="ISSUER":row["source_url"]=row["source_url"].replace("1920406","1050446")
                else:row.update(accepted="2026-10-30T00:00:00Z",retrieved_at_ms=fixture.NOW+20*86400000)
                result=fixture.inputs()
                self.assertTrue(result["ASST"]["source_binding"]["blockers"])
                self.assertFalse(any(r.get("claim")=="REPORTED_CAPITAL_STRUCTURE_SNAPSHOT"
                    for r in result["ASST"]["source_binding"]["observations"]))
                self.assertEqual(result["MSTR"]["burden_current"]["usd_cash_usd"],833400000)
            finally: fixture.doCleanups()


if __name__=="__main__":unittest.main()
