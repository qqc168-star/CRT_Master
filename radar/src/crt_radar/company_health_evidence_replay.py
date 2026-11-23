"""Offline receipt for the existing two-issuer CT -> Evidence Pack -> health path.

No collector, private profile, provider, notification, scheduler or trade path.
Hashes bind retained inputs; they do not establish external economic truth.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time

from .evidence_pack import build_evidence_pack, _sha256, _data_health, _assert_authority
from .issuer_ratio_market_health_source import build_archived_issuer_ct_inputs
from .portfolio_allocation_context import build_common_equity_health
from .treasury_company_ct import ISSUERS, validate_pit_replay
from .daily_quantitative_report import build_report

SCHEMA = "CRT_COMPANY_HEALTH_EVIDENCE_REPLAY_V0.1"
LOCKS = dict(production="NOT_APPROVED", external_action_authority="NONE",
    capital_decision_authority="USER_ONLY", machine_execution="FORBIDDEN", action_output="NONE")


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def archive_inventory(archive):
    """Fingerprint existing public archive lanes without changing receipts."""
    root=Path(archive).resolve()
    inventory=[]
    for lane in ("sec-disclosures", "shares-raw", "ledger-raw"):
        for path in sorted((root/lane).rglob("*")):
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError("ARCHIVE_PATH_ESCAPE")
            raw=path.read_bytes()
            inventory.append(dict(path=path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw)))
    if not any(r["path"]=="sec-disclosures/manifest.json" for r in inventory):
        raise ValueError("SEC_MANIFEST_REQUIRED")
    return inventory


def build_health_receipt(pack, source_gate, *, main_sha, validated_at_ms, archive_hash):
    """Recompute the original health model; keep calculation and audit clocks separate."""
    if not isinstance(main_sha,str) or not re.fullmatch(r"[0-9a-f]{40}",main_sha):
        raise ValueError("ENGINEERING_MAIN_SHA_REQUIRED")
    if not isinstance(archive_hash,str) or not re.fullmatch(r"[0-9a-f]{64}",archive_hash):
        raise ValueError("ARCHIVE_INVENTORY_HASH_REQUIRED")
    material=deepcopy(pack)
    pack_hash=material.pop("evidence_pack_hash",None)
    if pack_hash!=_sha256(material):
        raise ValueError("EVIDENCE_PACK_HASH_MISMATCH")
    _assert_authority(source_gate)
    cutoff=pack.get("generated_at_ms")
    if (type(cutoff) is not int or type(validated_at_ms) is not int
            or not 0<cutoff<=validated_at_ms or source_gate.get("as_of_ms")!=cutoff):
        raise ValueError("REPLAY_CUTOFF_OR_VALIDATION_CLOCK_INVALID")
    if (not source_gate.get("run_id") or pack.get("source_gate_run_id")!=source_gate["run_id"]
            or pack.get("source_gate_idempotency_key")!=source_gate.get("idempotency_key")
            or pack.get("data_health")!=_data_health(source_gate)):
        raise ValueError("SOURCE_GATE_PACK_LINEAGE_MISMATCH")
    if pack.get("private_context") is not None or pack.get("capital_state") is not None:
        raise ValueError("PUBLIC_REPLAY_ONLY_NO_PERSONAL_CAPITAL")
    for key,value in (("production","NOT_APPROVED"),("external_action_authority","NONE"),
            ("capital_decision_authority","USER_ONLY")):
        if pack.get("authority",{}).get(key)!=value:
            raise ValueError("PACK_AUTHORITY_MISMATCH")
    # Never relabel a foreign issuer as this company, even in a caller-built
    # sealed pack. Preserve the original pack and log the excluded fact identity.
    view=deepcopy(pack)
    accepted=[];exclusions=[]
    for fact in view.get("asset_facts",{}).get("items",[]):
        if fact.get("fact_type") in {"TREASURY_COMPANY_CT","TREASURY_VALUATION_CONTEXT","ISSUER_CT_SOURCE_BINDING"}:
            asset=fact.get("asset_id")
            issuer=fact.get("issuer_id")
            if (asset is not None and (asset not in ISSUERS or issuer!=ISSUERS[asset])) or issuer not in ISSUERS.values():
                exclusions.append(dict(asset_fact_id=fact.get("asset_fact_id"),asset_id=asset,
                    issuer_id=issuer,reason="ASSET_ISSUER_BINDING_MISMATCH"))
                continue
        accepted.append(fact)
    view["asset_facts"]["items"]=accepted
    health=build_common_equity_health(view)
    # Reuse the approved Strive report qualification, never derive initial
    # preference from dynamic claims or make it a seventh health dimension.
    asst_coverage=next(row for row in build_report(pack,generated_at_ms=validated_at_ms)["rows"]
        if row["metric"]=="research asset coverage / initial preferred claims")
    companies={}
    for asset,issuer in ISSUERS.items():
        facts=[deepcopy(f) for f in accepted if f.get("issuer_id")==issuer and
            f.get("fact_type") in {"TREASURY_COMPANY_CT","TREASURY_VALUATION_CONTEXT","ISSUER_CT_SOURCE_BINDING"}]
        engine=next((f["evidence"] for f in facts if f.get("ct_section")=="per_share_asset_engine"),{})
        latest=engine.get("current") or {}; previous=engine.get("previous") or {}
        reported_times=[r["effective_time"] for f in facts if f["fact_type"]=="ISSUER_CT_SOURCE_BINDING"
            for r in f["evidence"].get("observations",[]) if r.get("claim")=="REPORTED_CAPITAL_STRUCTURE_SNAPSHOT"
            and validate_pit_replay(r,issuer_id=issuer,replay_at=cutoff,mode="AUDIT_REPLAY")["state"]=="AVAILABLE"]
        latest_reported=max(reported_times,default=None)
        current_blocked=(not latest or (latest_reported is not None and latest_reported>latest["effective_time"]))
        companies[asset]=dict(issuer_id=issuer,health=health["assets"][asset],source_facts=facts,
            source_fact_count=len(facts),
            health_comparison_window_ms=[previous.get("effective_time"),latest.get("effective_time")],
            latest_reported_snapshot_ms=latest_reported,
            current_health_qualification="BLOCKED" if current_blocked else "RESEARCH_ONLY",
            current_health_reason="LATEST_REPORTED_SCOPE_OR_EFFECTIVE_DILUTION_UNQUALIFIED" if current_blocked
                else "SOURCE_DATED_COMPARISON_NOT_CURRENT_CASH_OR_TRADING_CLEARANCE",
            current_formal_valuation="NOT_GRANTED_BY_THIS_RECEIPT")
        if asset=="ASST":
            companies[asset]["research_asset_coverage"]=asst_coverage
    calculation=dict(companies=companies,health_state=health["state"],
        quantitative_inspection=health["quantitative_inspection"],exclusions=exclusions)
    program_hashes={name:hashlib.sha256(Path(__file__).with_name(name+".py").read_bytes()).hexdigest()
        for name in ("company_health_evidence_replay","company_health","portfolio_allocation_context",
            "treasury_company_ct","diluted_equity_mnav","issuer_ratio_market_health_source",
            "daily_quantitative_report","evidence_pack")}
    receipt=dict(schema_version=SCHEMA,main_sha=main_sha,program_hashes=program_hashes,
        source_gate_run_id=source_gate["run_id"],source_gate_hash=_sha256(source_gate),
        source_gate_idempotency_key=source_gate.get("idempotency_key"),
        source_registry_hash=source_gate.get("source_registry_hash"),
        market_source_qualification=deepcopy(pack["data_health"]),
        source_gate_evidence=deepcopy(source_gate.get("evidence",[])),
        evidence_pack_hash=pack_hash,archive_inventory_hash=archive_hash,
        data_cutoff_ms=cutoff,validated_at_ms=validated_at_ms,
        calculation=calculation,health_calculation_hash=_sha256(calculation),
        cached_health_matches=pack.get("common_equity_health")==health,
        evidence_use="ARCHIVED_PUBLIC_SOURCE_AUDIT_REPLAY_NOT_NEW_CURRENT_OBSERVATION",
        reasoning_state="NOT_YET_PROVEN",formal_season=None,**LOCKS)
    receipt["receipt_hash"]=_sha256(receipt)
    return receipt


def run_archive_replay(*, issuer_archive, source_gate_path, output_dir, main_sha):
    """Two fresh isolated stores; no normal daily runner or input overwrite."""
    archive=Path(issuer_archive).resolve(); gate_path=Path(source_gate_path).resolve()
    output=Path(output_dir).resolve(); repo=Path(__file__).resolve().parents[3]
    for protected in (archive,gate_path,repo):
        if output==protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("OUTPUT_OVERLAPS_INPUT_OR_REPOSITORY")
    if output.exists():
        raise ValueError("REPLAY_OUTPUT_EXISTS_NO_OVERWRITE")
    source_gate=_load(gate_path)
    _assert_authority(source_gate)
    cutoff=source_gate.get("as_of_ms")
    if type(cutoff) is not int or cutoff<=0:
        raise ValueError("SOURCE_GATE_CUTOFF_REQUIRED")
    inventory=archive_inventory(archive);gate_hash=_sha256(source_gate)
    inputs=build_archived_issuer_ct_inputs(archive,as_of_ms=cutoff)
    output.mkdir(parents=True)
    def write(path,value):
        with path.open("x",encoding="utf-8") as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
    write(output/"archive-inventory.json",inventory)
    write(output/"ct-inputs.json",inputs)
    write(output/"source-gate.json",source_gate)
    receipts=[];pack_hashes=[]
    for index in (1,2):
        lane=output/f"replay-{index}";lane.mkdir()
        pack=build_evidence_pack(source_gate,observation_db=lane/"observations.sqlite3",
            generated_at_ms=cutoff,treasury_company_ct_inputs=deepcopy(inputs))
        receipt=build_health_receipt(pack,source_gate,main_sha=main_sha,
            archive_hash=_sha256(inventory),validated_at_ms=int(time.time()*1000))
        write(lane/"evidence-pack.json",pack);write(lane/"health-receipt.json",receipt)
        receipts.append(receipt);pack_hashes.append(pack["evidence_pack_hash"])
    identical=(receipts[0]["health_calculation_hash"]==receipts[1]["health_calculation_hash"]
        and pack_hashes[0]==pack_hashes[1])
    unchanged=inventory==archive_inventory(archive) and gate_hash==_sha256(_load(gate_path))
    comparison=dict(state="PASS" if identical and unchanged else "BLOCKED",
        health_calculation_hashes=[r["health_calculation_hash"] for r in receipts],
        evidence_pack_hashes=pack_hashes,source_inputs_unchanged=unchanged,
        actual_validation_times_ms=[r["validated_at_ms"] for r in receipts],
        future_sources_or_current_data_not_created=True,**LOCKS)
    write(output/"replay-comparison.json",comparison)
    if comparison["state"]!="PASS":
        raise ValueError("REPLAY_COMPARISON_FAILED")
    return comparison


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer-archive",required=True,type=Path)
    parser.add_argument("--source-gate",required=True,type=Path)
    parser.add_argument("--output-dir",required=True,type=Path)
    parser.add_argument("--main-sha",required=True)
    args=parser.parse_args()
    print(json.dumps(run_archive_replay(issuer_archive=args.issuer_archive,
        source_gate_path=args.source_gate,output_dir=args.output_dir,main_sha=args.main_sha),sort_keys=True))


if __name__=="__main__":
    main()
