#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_REGISTRY = ROOT / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"
DEFAULT_PUBLIC_SOURCE_AUTHORITY = ROOT / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
DEFAULT_ETP_REPLAY_FEASIBILITY = ROOT / "CRT_ETP_PUBLIC_REPLAY_FEASIBILITY_V0.1.json"
DEFAULT_ACQUISITION_CONTRACT = ROOT / "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1.json"
DEFAULT_SOURCE_CONTRACT = ROOT / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
DEFAULT_WALK_FORWARD_PROTOCOL = ROOT / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"
EXPECTED_MODEL_REGISTRY_HASH = "62497bab3e7d551f45e6b3bc23b367575927d5be6be9f25a0956566e1d64c2ee"
EXPECTED_PUBLIC_SOURCE_AUTHORITY_HASH = (
    "b090665891e84fc8ddbccd0e07d81e3b6abc9013e76bc43f4baab5c2406261fb"
)
EXPECTED_ETP_REPLAY_FEASIBILITY_HASH = (
    "380bd6713011510b1e15f292090c439f989294689ef3c4999c76419a165f3cfc"
)
EXPECTED_ACQUISITION_CONTRACT_HASH = (
    "2863f82ef52ba120e1f6c92018b13199a19df7e14897d0ad2e3f04cabdb18a05"
)
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
ALIGNMENT_TOLERANCE_MS = 300_000
EXPECTED_ETP_PRODUCT_REGISTRY = {
    "IBIT": (
        "iShares / BlackRock",
        "2024-01-11",
        "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf",
    ),
    "FBTC": (
        "Fidelity Investments",
        "2024-01-11",
        "https://digital.fidelity.com/prgw/digital/research/quote/dashboard/summary?symbol=FBTC",
    ),
    "BITB": (
        "Bitwise Asset Management",
        "2024-01-11",
        "https://bitbetf.com/",
    ),
    "ARKB": (
        "ARK / 21Shares",
        "2024-01-11",
        "https://www.21shares.com/en-us/products-us/arkb",
    ),
    "BTCO": (
        "Invesco / Galaxy",
        "2024-01-11",
        "https://www.invesco.com/us/en/financial-products/etfs/invesco-galaxy-bitcoin-etf.html",
    ),
    "EZBC": (
        "Franklin Templeton",
        "2024-01-11",
        "https://www.franklintempleton.com/investments/options/exchange-traded-funds/products/39639/SINGLCLASS/franklin-bitcoin-etf/EZBC",
    ),
    "BRRR": (
        "CoinShares",
        "2024-01-11",
        "https://coinshares.com/us/etf/brrr/",
    ),
    "HODL": (
        "VanEck",
        "2024-01-11",
        "https://www.vaneck.com/us/en/investments/bitcoin-etf-hodl/",
    ),
    "BTCW": (
        "WisdomTree",
        "2024-01-11",
        "https://www.wisdomtree.com/us/products/crypto/btcw",
    ),
    "GBTC": (
        "Grayscale",
        "2024-01-11",
        "https://etfs.grayscale.com/gbtc",
    ),
    "BTC": (
        "Grayscale",
        "2024-07-31",
        "https://etfs.grayscale.com/btc",
    ),
    "MSBT": (
        "Morgan Stanley Investment Management",
        "2026-04-08",
        "https://www.morganstanley.com/im/en-us/individual-investor/products/etfs/digital-assets/morgan-stanley-bitcoin-trust.html",
    ),
}
EXPECTED_ETP_REPLAY_CASES = {
    "NEW_LAUNCH": (
        "IBIT",
        "0001980994",
        "000143774925006260",
        "https://www.sec.gov/Archives/edgar/data/1980994/000143774925006260/bit20241231_10k.htm",
    ),
    "CONVERTED_TRUST": (
        "GBTC",
        "0001588489",
        "000095017025029408",
        "https://www.sec.gov/Archives/edgar/data/1588489/000095017025029408/gbtc-20241231.htm",
    ),
    "LATE_LAUNCH_DISTRIBUTION_AND_SPLIT": (
        "BTC",
        "0002015034",
        "000095017025029405",
        "https://www.sec.gov/Archives/edgar/data/2015034/000095017025029405/btc-20241231.htm",
    ),
}


class CandidateDataError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _manifest_hash(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    return canonical_hash(payload)


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateDataError("JSON_ROOT_NOT_OBJECT")
    return value


def _model_feature_ids(model_registry: dict[str, Any]) -> set[str]:
    return {
        feature["feature_id"]
        for layer in model_registry.get("layers", [])
        if isinstance(layer, dict)
        for feature in layer.get("features", [])
        if isinstance(feature, dict) and isinstance(feature.get("feature_id"), str)
    }


def validate_public_source_authority(
    public_source_authority: dict[str, Any],
    model_registry: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if public_source_authority.get("schema_version") != (
        "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1"
    ):
        errors.append("public source authority schema_version mismatch")
    if public_source_authority.get("status") != (
        "PUBLIC_RESEARCH_ROUTE_LOCKED_DATA_NOT_READY"
    ):
        errors.append("public source authority status mismatch")

    model_hash = canonical_hash(model_registry)
    if model_hash != EXPECTED_MODEL_REGISTRY_HASH:
        errors.append("candidate model registry hash drift")
    if public_source_authority.get("candidate_registry_hash") != model_hash:
        errors.append("public source authority candidate_registry_hash mismatch")
    if canonical_hash(public_source_authority) != EXPECTED_PUBLIC_SOURCE_AUTHORITY_HASH:
        errors.append("public source authority canonical hash drift")

    authorization = public_source_authority.get("authorization")
    if not isinstance(authorization, dict):
        errors.append("public source authority authorization must be an object")
    else:
        expected_authorization = {
            "user_route_selection": "PUBLIC_ROUTE_CONTINUE",
            "scope": "RESEARCH_SOURCE_SELECTION_ONLY",
            "commercial_provider_route": "NOT_SELECTED",
            "formal_model_approval": "NOT_GRANTED",
            "production_approval": "NOT_GRANTED",
            "external_action_authority": "NONE",
        }
        for key, expected in expected_authorization.items():
            if authorization.get(key) != expected:
                errors.append(f"public source authority authorization.{key} drift")

    authority = public_source_authority.get("authority")
    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }
    if not isinstance(authority, dict):
        errors.append("public source authority authority must be an object")
    else:
        for key, expected in expected_authority.items():
            if authority.get(key) != expected:
                errors.append(f"public source authority authority.{key} must be {expected}")

    decisions = public_source_authority.get("decisions")
    expected_decision_ids = {
        "STABLECOIN_POINT_IN_TIME_UNIVERSE",
        "US_SPOT_BTC_ETP_POINT_IN_TIME",
        "BINANCE_BTCUSDT_CONTRACT_MULTIPLIER",
        "BTC_SPOT_COMPOSITE_OHLCV",
        "BTC_SPOT_AGGRESSOR_DAILY",
    }
    if not isinstance(decisions, dict) or set(decisions) != expected_decision_ids:
        errors.append("public source authority decisions mismatch")
        decisions = {}

    stablecoin = decisions.get("STABLECOIN_POINT_IN_TIME_UNIVERSE", {})
    if stablecoin.get("decision_state") != "LOCKED_RESEARCH_SOURCE":
        errors.append("public source authority stablecoin decision state drift")
    if stablecoin.get("selected_route") != "DEFILLAMA_FIXED_CORE_FIAT_PANEL":
        errors.append("public source authority stablecoin route drift")
    if stablecoin.get("universe", {}).get("members") != [
        {"provider_id": "1", "symbol": "USDT"},
        {"provider_id": "2", "symbol": "USDC"},
    ]:
        errors.append("public source authority stablecoin universe drift")
    if stablecoin.get("fallback_policy") != "NONE_BLOCK_ON_SOURCE_OR_COVERAGE_FAILURE":
        errors.append("public source authority stablecoin fallback drift")

    etp = decisions.get("US_SPOT_BTC_ETP_POINT_IN_TIME", {})
    if etp.get("decision_state") != "LOCKED_RESEARCH_SOURCE":
        errors.append("public source authority ETP decision state drift")
    if etp.get("calculation_authority") != "OFFICIAL_ISSUER_DAILY_SNAPSHOT":
        errors.append("public source authority ETP calculation authority drift")
    if etp.get("farside_role") != "CROSS_CHECK_ONLY_NOT_CALCULATION_AUTHORITY":
        errors.append("public source authority ETP Farside role drift")
    expected_etp_members = [
        {
            "ticker": ticker,
            "issuer_label": issuer_label,
            "membership_effective_from": effective_from,
            "official_product_url": product_url,
        }
        for ticker, (issuer_label, effective_from, product_url) in (
            EXPECTED_ETP_PRODUCT_REGISTRY.items()
        )
    ]
    if etp.get("universe", {}).get("members") != expected_etp_members:
        errors.append("public source authority ETP product registry drift")
    expected_registry_binding = {
        "official_product_url_state": "LOCKED_FOR_ALL_MEMBERS",
        "sec_identity_state": "CIK_AND_ACCESSION_BINDING_REQUIRED_BEFORE_ACQUISITION",
        "daily_snapshot_adapter_state": "NOT_IMPLEMENTED_BLOCKED",
        "historical_replay_state": "NOT_PROVEN_BLOCKED",
    }
    registry_binding = etp.get("registry_binding")
    if not isinstance(registry_binding, dict):
        errors.append("public source authority ETP registry binding missing")
    else:
        for key, expected in expected_registry_binding.items():
            if registry_binding.get(key) != expected:
                errors.append(f"public source authority ETP registry binding {key} drift")

    multiplier = decisions.get("BINANCE_BTCUSDT_CONTRACT_MULTIPLIER", {})
    if multiplier.get("decision_state") != "ELIMINATED_BY_OFFICIAL_NOTIONAL_FIELD":
        errors.append("public source authority multiplier decision state drift")
    if multiplier.get("replacement_field") != "sumOpenInterestValue":
        errors.append("public source authority multiplier replacement field drift")
    if set(multiplier.get("forbidden_inputs", [])) != {
        "contract_multiplier_btc",
        "OPEN_INTEREST_TIMES_MARK_PRICE",
    }:
        errors.append("public source authority multiplier forbidden inputs drift")

    composite = decisions.get("BTC_SPOT_COMPOSITE_OHLCV", {})
    if composite.get("decision_state") != "LOCKED_RESEARCH_SOURCE":
        errors.append("public source authority composite decision state drift")
    venue_ids = [
        item.get("venue_id")
        for item in composite.get("venue_universe", [])
        if isinstance(item, dict)
    ]
    if venue_ids != ["COINBASE_BTC_USD", "KRAKEN_XBT_USD", "BITSTAMP_BTC_USD"]:
        errors.append("public source authority composite venue universe drift")
    if composite.get("minimum_venue_count") != 3:
        errors.append("public source authority composite minimum_venue_count drift")
    if composite.get("aggregation") != "COORDINATE_WISE_MEDIAN_OHLC":
        errors.append("public source authority composite aggregation drift")
    if composite.get("fallback_policy") != (
        "NONE_BLOCK_IF_ANY_VENUE_DAY_IS_MISSING_OR_INVALID"
    ):
        errors.append("public source authority composite fallback drift")

    aggressor = decisions.get("BTC_SPOT_AGGRESSOR_DAILY", {})
    if aggressor.get("decision_state") != "LOCKED_RESEARCH_SOURCE":
        errors.append("public source authority aggressor decision state drift")
    if aggressor.get("symbol") != "BTCUSDT":
        errors.append("public source authority aggressor symbol drift")
    if aggressor.get("buyer_initiated_when_is_buyer_maker") is not False:
        errors.append("public source authority aggressor buyer mapping drift")
    if aggressor.get("seller_initiated_when_is_buyer_maker") is not True:
        errors.append("public source authority aggressor seller mapping drift")
    if aggressor.get("quote_volume_formula") != "price*quantity":
        errors.append("public source authority aggressor quote volume formula drift")

    promotion = public_source_authority.get("promotion")
    if not isinstance(promotion, dict):
        errors.append("public source authority promotion must be an object")
    else:
        if promotion.get("automatic_source_promotion") is not False:
            errors.append("public source authority automatic promotion forbidden")
        if promotion.get("source_lock_is_dataset_readiness") is not False:
            errors.append("public source authority cannot imply dataset readiness")
        if promotion.get("source_lock_is_model_approval") is not False:
            errors.append("public source authority cannot imply model approval")
        if promotion.get("merge_is_approval") is not False:
            errors.append("public source authority merge cannot be approval")
        if promotion.get("external_action_authority") != "NONE":
            errors.append("public source authority external action must remain NONE")
    return errors


def validate_etp_replay_feasibility(
    feasibility: dict[str, Any],
    public_source_authority: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if feasibility.get("schema_version") != "CRT_ETP_PUBLIC_REPLAY_FEASIBILITY_V0.1":
        errors.append("ETP replay feasibility schema_version mismatch")
    if feasibility.get("status") != (
        "REPRESENTATIVE_PROBE_COMPLETE_HISTORICAL_BACKFILL_NOT_PROVEN"
    ):
        errors.append("ETP replay feasibility status mismatch")
    if feasibility.get("public_source_authority_id") != (
        "CRT-PUBLIC-SOURCE-AUTHORITY-LOCK-V0.1"
    ):
        errors.append("ETP replay feasibility authority id mismatch")
    authority_hash = canonical_hash(public_source_authority)
    if feasibility.get("public_source_authority_hash") != authority_hash:
        errors.append("ETP replay feasibility authority hash mismatch")
    if canonical_hash(feasibility) != EXPECTED_ETP_REPLAY_FEASIBILITY_HASH:
        errors.append("ETP replay feasibility canonical hash drift")

    cases = feasibility.get("representative_cases")
    if not isinstance(cases, list):
        errors.append("ETP replay representative cases invalid")
        cases = []
    by_type = {
        item.get("case_type"): item
        for item in cases
        if isinstance(item, dict) and isinstance(item.get("case_type"), str)
    }
    if len(cases) != len(by_type) or set(by_type) != set(EXPECTED_ETP_REPLAY_CASES):
        errors.append("ETP replay representative case registry mismatch")
    for case_type, expected in EXPECTED_ETP_REPLAY_CASES.items():
        item = by_type.get(case_type, {})
        actual = (
            item.get("ticker"),
            item.get("sec_cik"),
            item.get("sec_identity_accession"),
            item.get("sec_identity_url"),
        )
        if actual != expected:
            errors.append(f"ETP replay {case_type} identity drift")
        if item.get("daily_historical_replay_state") != "NOT_PROVEN_BLOCKED":
            errors.append(f"ETP replay {case_type} must remain blocked")
        if item.get("date_addressable_daily_snapshot_state") != "NOT_PROVEN":
            errors.append(f"ETP replay {case_type} date-addressable state drift")
        if item.get("immutable_daily_archive_state") != "NOT_PROVEN":
            errors.append(f"ETP replay {case_type} immutable archive state drift")

    result = feasibility.get("result")
    expected_result = {
        "representative_sec_identity_state": "PROVEN_FOR_THREE_CASES",
        "all_twelve_sec_identity_state": "NOT_PROVEN_BLOCKED",
        "historical_backfill_state": "BLOCKED_NOT_PROVEN",
        "prospective_capture_state": "CONTRACT_READY_ADAPTERS_NOT_IMPLEMENTED",
        "dataset_readiness": "NOT_GRANTED",
        "walk_forward_start": "BLOCKED",
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }
    if not isinstance(result, dict):
        errors.append("ETP replay result invalid")
    else:
        for key, expected in expected_result.items():
            if result.get(key) != expected:
                errors.append(f"ETP replay result.{key} drift")
    return errors


def validate_acquisition_contract(
    acquisition_contract: dict[str, Any],
    model_registry: dict[str, Any],
    public_source_authority: dict[str, Any],
    etp_feasibility: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if validate_etp_replay_feasibility(etp_feasibility, public_source_authority):
        errors.append("ETP replay feasibility invalid")
    if acquisition_contract.get("schema_version") != (
        "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1"
    ):
        errors.append("acquisition contract schema_version mismatch")
    if acquisition_contract.get("contract_id") != (
        "CRT-CANDIDATE-ACQUISITION-CONTRACT-V0.1"
    ):
        errors.append("acquisition contract id mismatch")
    if acquisition_contract.get("status") != (
        "PROOF_SLICE_IMPLEMENTED_DATA_NOT_ACQUIRED"
    ):
        errors.append("acquisition contract status mismatch")
    if acquisition_contract.get("candidate_registry_hash") != canonical_hash(model_registry):
        errors.append("acquisition contract candidate registry hash mismatch")
    if acquisition_contract.get("public_source_authority_hash") != canonical_hash(
        public_source_authority
    ):
        errors.append("acquisition contract public source authority hash mismatch")
    if acquisition_contract.get("etp_replay_feasibility_id") != (
        "CRT-ETP-PUBLIC-REPLAY-FEASIBILITY-V0.1"
    ):
        errors.append("acquisition contract ETP feasibility id mismatch")
    if acquisition_contract.get("etp_replay_feasibility_hash") != canonical_hash(
        etp_feasibility
    ):
        errors.append("acquisition contract ETP feasibility hash mismatch")
    if canonical_hash(acquisition_contract) != EXPECTED_ACQUISITION_CONTRACT_HASH:
        errors.append("acquisition contract canonical hash drift")

    for field in (
        "network_fetch_implemented",
        "issuer_adapters_implemented",
        "raw_dataset_acquired",
        "dataset_readiness_granted",
    ):
        if acquisition_contract.get(field) is not False:
            errors.append(f"acquisition contract {field} must remain false")

    authority = acquisition_contract.get("authority")
    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }
    if not isinstance(authority, dict):
        errors.append("acquisition contract authority invalid")
    else:
        for key, expected in expected_authority.items():
            if authority.get(key) != expected:
                errors.append(f"acquisition contract authority.{key} drift")

    archive = acquisition_contract.get("archive_contract")
    if not isinstance(archive, dict):
        errors.append("acquisition archive contract invalid")
    else:
        if archive.get("layout") != "artifacts/sha256/{sha256_prefix_2}/{sha256}":
            errors.append("acquisition archive layout drift")
        if archive.get("identity_layout") != (
            "metadata/identities/{identity_hash_prefix_2}/{identity_hash}.json"
        ):
            errors.append("acquisition archive identity layout drift")
        if archive.get("identity_write_policy") != (
            "ATOMIC_CREATE_ON_FIRST_CAPTURE_NEVER_REWRITE_FIRST_SEEN_METADATA"
        ):
            errors.append("acquisition archive identity write policy drift")
        if archive.get("write_policy") != "ATOMIC_CREATE_IF_ABSENT_NEVER_OVERWRITE":
            errors.append("acquisition archive write policy drift")

    manifest = acquisition_contract.get("manifest_contract")
    required_root_fields = {
        "schema_version",
        "candidate_registry_hash",
        "public_source_authority_hash",
        "acquisition_contract_hash",
        "source_contract_hash",
        "created_at_ms",
        "artifacts",
        "manifest_sha256",
    }
    required_artifact_fields = {
        "source_contract_id",
        "request_identity",
        "retrieved_at_ms",
        "first_seen_at_ms",
        "available_at_coverage_start_ms",
        "available_at_coverage_end_ms",
        "sha256",
        "size_bytes",
        "archive_relpath",
        "content_type",
        "integrity_proof_type",
        "provider_checksum",
        "license_classification",
        "source_authority_hash",
        "evidence_class",
        "availability_proof_type",
        "replay_eligible",
        "revision_of_sha256",
    }
    if not isinstance(manifest, dict):
        errors.append("acquisition manifest contract invalid")
    else:
        if manifest.get("schema_version") != (
            "CRT_CANDIDATE_POINT_IN_TIME_DATASET_MANIFEST_V0.3"
        ):
            errors.append("acquisition manifest schema drift")
        if set(manifest.get("required_root_fields", [])) != required_root_fields:
            errors.append("acquisition manifest root fields drift")
        if set(manifest.get("required_artifact_fields", [])) != required_artifact_fields:
            errors.append("acquisition manifest artifact fields drift")

    evidence_classes = acquisition_contract.get("evidence_classes")
    if not isinstance(evidence_classes, dict) or set(evidence_classes) != {
        "CURRENT_FIRST_SEEN_CAPTURE",
        "IMMUTABLE_PROVIDER_ARCHIVE",
        "OFFICIAL_FILING",
        "SYNTHETIC_FIXTURE",
    }:
        errors.append("acquisition evidence classes mismatch")
    elif evidence_classes["SYNTHETIC_FIXTURE"].get("replay_eligible") is not False:
        errors.append("acquisition synthetic fixture must remain ineligible")

    etp = acquisition_contract.get("etp_proof_slice")
    if not isinstance(etp, dict):
        errors.append("acquisition ETP proof slice invalid")
    else:
        if etp.get("representative_tickers") != ["IBIT", "GBTC", "BTC"]:
            errors.append("acquisition ETP representative tickers drift")
        if etp.get("historical_backfill_state") != "BLOCKED_NOT_PROVEN":
            errors.append("acquisition ETP historical backfill must remain blocked")

    promotion = acquisition_contract.get("promotion")
    if not isinstance(promotion, dict):
        errors.append("acquisition promotion invalid")
    else:
        for field in (
            "archive_write_is_dataset_readiness",
            "manifest_creation_is_history_completion",
            "feasibility_probe_is_source_promotion",
            "merge_is_approval",
            "automatic_promotion",
        ):
            if promotion.get(field) is not False:
                errors.append(f"acquisition promotion.{field} must remain false")
        if promotion.get("external_action_authority") != "NONE":
            errors.append("acquisition promotion external action authority must remain NONE")
    return errors


def validate_source_contract(
    source_contract: dict[str, Any],
    model_registry: dict[str, Any],
    public_source_authority: dict[str, Any] | None = None,
    acquisition_contract: dict[str, Any] | None = None,
    etp_feasibility: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if public_source_authority is None:
        try:
            public_source_authority = load_json(DEFAULT_PUBLIC_SOURCE_AUTHORITY)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            public_source_authority = {}
            errors.append("public source authority unreadable")
    if validate_public_source_authority(public_source_authority, model_registry):
        errors.append("public source authority invalid")
    if etp_feasibility is None:
        try:
            etp_feasibility = load_json(DEFAULT_ETP_REPLAY_FEASIBILITY)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            etp_feasibility = {}
            errors.append("ETP replay feasibility unreadable")
    if acquisition_contract is None:
        try:
            acquisition_contract = load_json(DEFAULT_ACQUISITION_CONTRACT)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            acquisition_contract = {}
            errors.append("acquisition contract unreadable")
    if validate_acquisition_contract(
        acquisition_contract,
        model_registry,
        public_source_authority,
        etp_feasibility,
    ):
        errors.append("acquisition contract invalid")

    if source_contract.get("schema_version") != "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2":
        errors.append("source contract schema_version mismatch")
    if source_contract.get("status") != "RESEARCH_ONLY_NOT_APPROVED":
        errors.append("source contract must remain research-only and not approved")

    model_hash = canonical_hash(model_registry)
    if model_hash != EXPECTED_MODEL_REGISTRY_HASH:
        errors.append("candidate model registry hash drift")
    if source_contract.get("candidate_registry_hash") != model_hash:
        errors.append("source contract candidate_registry_hash mismatch")
    if source_contract.get("public_source_authority_id") != (
        "CRT-PUBLIC-SOURCE-AUTHORITY-LOCK-V0.1"
    ):
        errors.append("source contract public_source_authority_id mismatch")
    if source_contract.get("public_source_authority_hash") != canonical_hash(
        public_source_authority
    ):
        errors.append("source contract public_source_authority_hash mismatch")
    if source_contract.get("acquisition_contract_id") != (
        "CRT-CANDIDATE-ACQUISITION-CONTRACT-V0.1"
    ):
        errors.append("source contract acquisition_contract_id mismatch")
    if source_contract.get("acquisition_contract_hash") != canonical_hash(
        acquisition_contract
    ):
        errors.append("source contract acquisition_contract_hash mismatch")

    authority = source_contract.get("authority")
    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }
    if not isinstance(authority, dict):
        errors.append("source contract authority must be an object")
    else:
        for key, expected in expected_authority.items():
            if authority.get(key) != expected:
                errors.append(f"source contract authority.{key} must be {expected}")

    point_in_time = source_contract.get("point_in_time_observation_contract")
    if not isinstance(point_in_time, dict):
        errors.append("point_in_time_observation_contract must be an object")
    elif point_in_time.get("schema_version") != "CRT_CANDIDATE_RAW_INPUT_V0.2":
        errors.append("raw input schema mismatch")

    locks = source_contract.get("calculation_locks")
    expected_locks = {
        "cross_source_alignment_tolerance_ms": ALIGNMENT_TOLERANCE_MS,
        "funding_interval_ms": 8 * HOUR_MS,
        "funding_observation_count": 9,
        "crypto_daily_bar_ms": DAY_MS,
        "open_interest_notional_policy": "DIRECT_PROVIDER_NOTIONAL_ONLY",
        "liquidation_zero_policy": "ZERO_ONLY_WHEN_VERIFIED_COMPLETE_COVERAGE",
        "parameter_policy": "NO_UNAPPROVED_SCALAR_PARAMETERS",
    }
    if not isinstance(locks, dict):
        errors.append("calculation_locks must be an object")
    else:
        for key, expected in expected_locks.items():
            if locks.get(key) != expected:
                errors.append(f"calculation lock {key} drift")

    source_contracts = source_contract.get("source_contracts")
    if not isinstance(source_contracts, dict) or not source_contracts:
        errors.append("source_contracts must be a non-empty object")
        source_contracts = {}
    else:
        allowed_history = {"NOT_PRESENT", "INSUFFICIENT", "NOT_APPLICABLE"}
        for source_id, item in source_contracts.items():
            if not isinstance(item, dict):
                errors.append(f"source contract {source_id} must be an object")
                continue
            if item.get("approval_state") != "LOCKED_RESEARCH_INPUT":
                errors.append(f"source contract {source_id} must be locked research input")
            if item.get("history_data_state") not in allowed_history:
                errors.append(f"source contract {source_id} has invalid history_data_state")
            if item.get("history_data_state") in {"NOT_PRESENT", "INSUFFICIENT"} and not item.get(
                "history_blocker"
            ):
                errors.append(f"source contract {source_id} lacks history_blocker")
        expected_source_ids = {
            "FRED_MACRO_VINTAGE",
            "FRED_MARKET_DAILY",
            "STABLECOIN_POINT_IN_TIME_UNIVERSE",
            "US_SPOT_BTC_ETP_POINT_IN_TIME",
            "BINANCE_USDM_MARKET_HISTORY",
            "CRT_LIQUIDATION_AGGREGATE_HISTORY",
            "COINMETRICS_BTC_CAPS",
            "BTC_SPOT_COMPOSITE_OHLCV",
            "BTC_SPOT_AGGRESSOR_DAILY",
        }
        if set(source_contracts) != expected_source_ids:
            errors.append("source contracts must match the locked public route")
        binance = source_contracts.get("BINANCE_USDM_MARKET_HISTORY", {})
        if binance.get("series") != ["OPEN_INTEREST_NOTIONAL_USD", "FUNDING_RATE"]:
            errors.append("Binance market history series must use direct OI notional")

    feature_sources = source_contract.get("feature_sources")
    model_features = _model_feature_ids(model_registry)
    if not isinstance(feature_sources, dict):
        errors.append("feature_sources must be an object")
        feature_sources = {}
    if set(feature_sources) != model_features:
        errors.append("feature_sources must cover exactly the candidate model features")
    for feature_id, item in feature_sources.items():
        if not isinstance(item, dict):
            errors.append(f"feature source {feature_id} must be an object")
            continue
        if not isinstance(item.get("calculator_id"), str) or not item["calculator_id"]:
            errors.append(f"feature source {feature_id} lacks calculator_id")
        source_ids = item.get("source_contract_ids")
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"feature source {feature_id} lacks source_contract_ids")
            continue
        unknown = sorted(set(source_ids) - set(source_contracts))
        if unknown:
            errors.append(f"feature source {feature_id} has unknown source contracts: {unknown}")

    manifest = source_contract.get("dataset_manifest_contract")
    if not isinstance(manifest, dict):
        errors.append("dataset_manifest_contract must be an object")
    elif manifest.get("schema_version") != "CRT_CANDIDATE_POINT_IN_TIME_DATASET_MANIFEST_V0.3":
        errors.append("dataset manifest schema mismatch")
    elif "public_source_authority_hash" not in manifest.get("required_root_fields", []):
        errors.append("dataset manifest must require public_source_authority_hash")
    elif "acquisition_contract_hash" not in manifest.get("required_root_fields", []):
        errors.append("dataset manifest must require acquisition_contract_hash")
    elif "manifest_sha256" not in manifest.get("required_root_fields", []):
        errors.append("dataset manifest must require manifest_sha256")
    return errors


def validate_walk_forward_protocol(
    protocol: dict[str, Any],
    source_contract: dict[str, Any],
    model_registry: dict[str, Any],
    public_source_authority: dict[str, Any] | None = None,
    acquisition_contract: dict[str, Any] | None = None,
    etp_feasibility: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if public_source_authority is None:
        try:
            public_source_authority = load_json(DEFAULT_PUBLIC_SOURCE_AUTHORITY)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            public_source_authority = {}
            errors.append("public source authority unreadable")
    if validate_public_source_authority(public_source_authority, model_registry):
        errors.append("public source authority invalid")
    if etp_feasibility is None:
        try:
            etp_feasibility = load_json(DEFAULT_ETP_REPLAY_FEASIBILITY)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            etp_feasibility = {}
            errors.append("ETP replay feasibility unreadable")
    if acquisition_contract is None:
        try:
            acquisition_contract = load_json(DEFAULT_ACQUISITION_CONTRACT)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            acquisition_contract = {}
            errors.append("acquisition contract unreadable")
    if validate_acquisition_contract(
        acquisition_contract,
        model_registry,
        public_source_authority,
        etp_feasibility,
    ):
        errors.append("acquisition contract invalid")

    if protocol.get("schema_version") != "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2":
        errors.append("walk-forward protocol schema_version mismatch")
    if protocol.get("status") != "PREREGISTERED_RESEARCH_ONLY_NOT_STARTED":
        errors.append("walk-forward protocol status must remain not started")
    if protocol.get("retrospective_role") != "EXPLORATORY_FALSIFICATION_ONLY":
        errors.append("retrospective evidence cannot be labeled confirmatory")

    model_hash = canonical_hash(model_registry)
    source_hash = canonical_hash(source_contract)
    if protocol.get("candidate_registry_hash") != model_hash:
        errors.append("walk-forward candidate_registry_hash mismatch")
    if protocol.get("public_source_authority_hash") != canonical_hash(
        public_source_authority
    ):
        errors.append("walk-forward public_source_authority_hash mismatch")
    if protocol.get("acquisition_contract_hash") != canonical_hash(acquisition_contract):
        errors.append("walk-forward acquisition_contract_hash mismatch")
    if protocol.get("source_contract_hash") != source_hash:
        errors.append("walk-forward source_contract_hash mismatch")

    authority = protocol.get("authority")
    if not isinstance(authority, dict):
        errors.append("walk-forward authority must be an object")
    else:
        if authority.get("formal_model") != "NOT_APPROVED":
            errors.append("walk-forward formal_model must be NOT_APPROVED")
        if authority.get("production") != "NOT_APPROVED":
            errors.append("walk-forward production must be NOT_APPROVED")
        if authority.get("external_action_authority") != "NONE":
            errors.append("walk-forward external_action_authority must be NONE")
        if authority.get("external_action_performed") is not False:
            errors.append("walk-forward external_action_performed must be false")
        if authority.get("action_output") != "NONE":
            errors.append("walk-forward action_output must be NONE")

    target = protocol.get("target")
    sources = source_contract.get("source_contracts", {})
    if not isinstance(target, dict) or target.get("source_contract_id") not in sources:
        errors.append("walk-forward target source contract is unknown")
    elif target.get("horizons_calendar_days") != [7, 30, 90]:
        errors.append("walk-forward horizons must remain 7/30/90 days")

    dataset_gate = protocol.get("dataset_gate")
    if not isinstance(dataset_gate, dict):
        errors.append("walk-forward dataset_gate must be an object")
    else:
        required = dataset_gate.get("required_source_contract_ids")
        if not isinstance(required, list) or set(required) != set(sources):
            errors.append("walk-forward dataset gate must require every source contract")
        if dataset_gate.get("required_manifest_schema") != (
            "CRT_CANDIDATE_POINT_IN_TIME_DATASET_MANIFEST_V0.3"
        ):
            errors.append("walk-forward dataset manifest schema mismatch")
        if dataset_gate.get("start_policy") != (
            "BLOCK_UNTIL_ALL_REQUIRED_CONTRACTS_LOCKED_AND_ALL_BYTE_VERIFIED_REPLAY_ELIGIBLE_ARTIFACTS_PRESENT"
        ):
            errors.append("walk-forward start policy must fail closed")
        if dataset_gate.get("archive_root_required") is not True:
            errors.append("walk-forward archive root must be required")
        if dataset_gate.get("synthetic_artifact_policy") != (
            "NEVER_SATISFIES_SOURCE_PRESENCE_OR_HISTORY"
        ):
            errors.append("walk-forward synthetic artifact policy drift")

    promotion = protocol.get("promotion")
    if not isinstance(promotion, dict):
        errors.append("walk-forward promotion must be an object")
    else:
        if promotion.get("automatic_promotion") is not False:
            errors.append("automatic promotion is forbidden")
        if promotion.get("merge_is_approval") is not False:
            errors.append("merge cannot constitute model approval")
        if promotion.get("backtest_is_sufficient") is not False:
            errors.append("backtest cannot be sufficient for approval")
        if promotion.get("capital_decision_authority") != "USER_ONLY":
            errors.append("capital decision authority must remain USER_ONLY")
        if promotion.get("external_action_authority") != "NONE":
            errors.append("promotion external action authority must remain NONE")
    return errors


def assess_walk_forward_readiness(
    source_contract: dict[str, Any],
    protocol: dict[str, Any],
    *,
    dataset_manifest: dict[str, Any] | None,
    dataset_root: str | Path | None = None,
    public_source_authority: dict[str, Any] | None = None,
    acquisition_contract: dict[str, Any] | None = None,
    etp_feasibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: set[str] = set()
    try:
        model_registry = load_json(DEFAULT_MODEL_REGISTRY)
    except (OSError, json.JSONDecodeError, CandidateDataError):
        model_registry = {}
        blockers.add("CANDIDATE_MODEL_REGISTRY_UNREADABLE")
    if public_source_authority is None:
        try:
            public_source_authority = load_json(DEFAULT_PUBLIC_SOURCE_AUTHORITY)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            public_source_authority = {}
            blockers.add("PUBLIC_SOURCE_AUTHORITY_UNREADABLE")
    if etp_feasibility is None:
        try:
            etp_feasibility = load_json(DEFAULT_ETP_REPLAY_FEASIBILITY)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            etp_feasibility = {}
            blockers.add("ETP_REPLAY_FEASIBILITY_UNREADABLE")
    if acquisition_contract is None:
        try:
            acquisition_contract = load_json(DEFAULT_ACQUISITION_CONTRACT)
        except (OSError, json.JSONDecodeError, CandidateDataError):
            acquisition_contract = {}
            blockers.add("ACQUISITION_CONTRACT_UNREADABLE")
    if validate_public_source_authority(public_source_authority, model_registry):
        blockers.add("PUBLIC_SOURCE_AUTHORITY_INVALID")
    if validate_etp_replay_feasibility(etp_feasibility, public_source_authority):
        blockers.add("ETP_REPLAY_FEASIBILITY_INVALID")
    if validate_acquisition_contract(
        acquisition_contract,
        model_registry,
        public_source_authority,
        etp_feasibility,
    ):
        blockers.add("ACQUISITION_CONTRACT_INVALID")
    if validate_source_contract(
        source_contract,
        model_registry,
        public_source_authority,
        acquisition_contract,
        etp_feasibility,
    ):
        blockers.add("SOURCE_CONTRACT_INVALID")
    if validate_walk_forward_protocol(
        protocol,
        source_contract,
        model_registry,
        public_source_authority,
        acquisition_contract,
        etp_feasibility,
    ):
        blockers.add("WALK_FORWARD_PROTOCOL_INVALID")
    for source_id, item in source_contract.get("source_contracts", {}).items():
        if item.get("approval_state") != "LOCKED_RESEARCH_INPUT":
            blockers.add(str(item.get("approval_blocker") or f"{source_id}_APPROVAL_REQUIRED"))
        if item.get("history_data_state") in {"NOT_PRESENT", "INSUFFICIENT"}:
            blockers.add(str(item.get("history_blocker") or f"{source_id}_HISTORY_MISSING"))

    if dataset_manifest is None:
        blockers.add("POINT_IN_TIME_DATASET_MISSING")
    else:
        expected_schema = source_contract.get("dataset_manifest_contract", {}).get(
            "schema_version"
        )
        if dataset_manifest.get("schema_version") != expected_schema:
            blockers.add("POINT_IN_TIME_DATASET_SCHEMA_INVALID")
        if dataset_manifest.get("candidate_registry_hash") != protocol.get(
            "candidate_registry_hash"
        ):
            blockers.add("POINT_IN_TIME_DATASET_MODEL_HASH_MISMATCH")
        if dataset_manifest.get("public_source_authority_hash") != canonical_hash(
            public_source_authority
        ):
            blockers.add("POINT_IN_TIME_DATASET_PUBLIC_SOURCE_HASH_MISMATCH")
        if dataset_manifest.get("acquisition_contract_hash") != canonical_hash(
            acquisition_contract
        ):
            blockers.add("POINT_IN_TIME_DATASET_ACQUISITION_HASH_MISMATCH")
        if dataset_manifest.get("source_contract_hash") != canonical_hash(source_contract):
            blockers.add("POINT_IN_TIME_DATASET_SOURCE_HASH_MISMATCH")
        if dataset_manifest.get("manifest_sha256") != _manifest_hash(dataset_manifest):
            blockers.add("POINT_IN_TIME_DATASET_MANIFEST_HASH_MISMATCH")
        required_root_fields = set(
            source_contract.get("dataset_manifest_contract", {}).get(
                "required_root_fields", []
            )
        )
        if not required_root_fields.issubset(dataset_manifest):
            blockers.add("POINT_IN_TIME_DATASET_ROOT_FIELDS_INVALID")
        archive_root: Path | None = None
        if dataset_root is None:
            blockers.add("POINT_IN_TIME_DATASET_ARCHIVE_ROOT_MISSING")
        else:
            archive_root = Path(dataset_root).resolve()
        artifacts = dataset_manifest.get("artifacts")
        if not isinstance(artifacts, list):
            blockers.add("POINT_IN_TIME_DATASET_ARTIFACTS_INVALID")
        else:
            required_fields = set(
                source_contract.get("dataset_manifest_contract", {}).get(
                    "required_artifact_fields", []
                )
            )
            present: set[str] = set()
            for index, artifact in enumerate(artifacts):
                artifact_valid = True
                if not isinstance(artifact, dict) or not required_fields.issubset(artifact):
                    blockers.add(f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_INVALID")
                    continue
                digest = artifact.get("sha256")
                if not _is_sha256(digest):
                    blockers.add(f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_HASH_INVALID")
                    artifact_valid = False
                if artifact.get("source_authority_hash") != canonical_hash(
                    public_source_authority
                ):
                    blockers.add(
                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_SOURCE_AUTHORITY_HASH_MISMATCH"
                    )
                    artifact_valid = False
                evidence_class = artifact.get("evidence_class")
                replay_eligible = artifact.get("replay_eligible")
                if replay_eligible is not True or evidence_class == "SYNTHETIC_FIXTURE":
                    blockers.add(
                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_NOT_REPLAY_ELIGIBLE"
                    )
                    artifact_valid = False
                timestamp_fields = (
                    "retrieved_at_ms",
                    "first_seen_at_ms",
                    "available_at_coverage_start_ms",
                    "available_at_coverage_end_ms",
                )
                timestamps = [artifact.get(field) for field in timestamp_fields]
                if any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in timestamps
                ):
                    blockers.add(
                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_TIMESTAMP_INVALID"
                    )
                    artifact_valid = False
                else:
                    retrieved, first_seen, coverage_start, coverage_end = timestamps
                    if first_seen > retrieved:
                        blockers.add(
                            f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_FIRST_SEEN_AFTER_RETRIEVAL"
                        )
                        artifact_valid = False
                    if coverage_start > coverage_end or coverage_end > retrieved:
                        blockers.add(
                            f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_AVAILABILITY_COVERAGE_INVALID"
                        )
                        artifact_valid = False
                if evidence_class == "CURRENT_FIRST_SEEN_CAPTURE" and (
                    artifact.get("available_at_coverage_start_ms")
                    != artifact.get("first_seen_at_ms")
                    or artifact.get("available_at_coverage_end_ms")
                    != artifact.get("first_seen_at_ms")
                ):
                    blockers.add(
                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_CURRENT_CAPTURE_BACKDATED"
                    )
                    artifact_valid = False
                if evidence_class == "IMMUTABLE_PROVIDER_ARCHIVE" and not artifact.get(
                    "provider_checksum"
                ):
                    blockers.add(
                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_PROVIDER_CHECKSUM_MISSING"
                    )
                    artifact_valid = False

                if archive_root is None:
                    artifact_valid = False
                elif _is_sha256(digest):
                    expected_relpath = f"artifacts/sha256/{digest[:2]}/{digest}"
                    relpath = artifact.get("archive_relpath")
                    if relpath != expected_relpath:
                        blockers.add(
                            f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_PATH_INVALID"
                        )
                        artifact_valid = False
                    else:
                        path = (archive_root / relpath).resolve()
                        try:
                            path.relative_to(archive_root)
                        except ValueError:
                            blockers.add(
                                f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_PATH_ESCAPE"
                            )
                            artifact_valid = False
                        else:
                            if not path.is_file():
                                blockers.add(
                                    f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_BYTES_MISSING"
                                )
                                artifact_valid = False
                            else:
                                raw_bytes = path.read_bytes()
                                if hashlib.sha256(raw_bytes).hexdigest() != digest:
                                    blockers.add(
                                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_BYTES_HASH_MISMATCH"
                                    )
                                    artifact_valid = False
                                if artifact.get("size_bytes") != len(raw_bytes):
                                    blockers.add(
                                        f"POINT_IN_TIME_DATASET_ARTIFACT_{index}_BYTES_SIZE_MISMATCH"
                                    )
                                    artifact_valid = False

                source_id = artifact.get("source_contract_id")
                if artifact_valid and isinstance(source_id, str) and source_id:
                    present.add(source_id)
            required = set(
                protocol.get("dataset_gate", {}).get("required_source_contract_ids", [])
            )
            for source_id in sorted(required - present):
                blockers.add(f"{source_id}_ARTIFACT_MISSING")

    state = "BLOCKED" if blockers else "READY_FOR_EXPLORATORY_WALK_FORWARD"
    return {
        "schema_version": "CRT_CANDIDATE_WALK_FORWARD_READINESS_V0.1",
        "state": state,
        "blocked_reasons": sorted(blockers),
        "candidate_registry_hash": protocol.get("candidate_registry_hash"),
        "public_source_authority_hash": canonical_hash(public_source_authority),
        "etp_replay_feasibility_hash": canonical_hash(etp_feasibility),
        "acquisition_contract_hash": canonical_hash(acquisition_contract),
        "source_contract_hash": canonical_hash(source_contract),
        "walk_forward_result": None,
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "capital_decision": None,
    }


def _finite(value: Any, code: str) -> float:
    if isinstance(value, bool):
        raise CandidateDataError(code)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateDataError(code) from exc
    if not math.isfinite(result):
        raise CandidateDataError(code)
    return result


def _positive(value: Any, code: str) -> float:
    result = _finite(value, code)
    if result <= 0:
        raise CandidateDataError(code)
    return result


def _nonnegative(value: Any, code: str) -> float:
    result = _finite(value, code)
    if result < 0:
        raise CandidateDataError(code)
    return result


def _integer_ms(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandidateDataError(code)
    return value


def _select_latest_revisions(
    rows: Any,
    *,
    as_of_ms: int,
    identity: Callable[[dict[str, Any]], Any],
    code_prefix: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise CandidateDataError(f"{code_prefix}_MISSING")
    selected: dict[Any, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise CandidateDataError(f"{code_prefix}_ROW_INVALID")
        observed_at_ms = _integer_ms(
            raw.get("observed_at_ms"), f"{code_prefix}_OBSERVED_AT_INVALID"
        )
        available_at_ms = _integer_ms(
            raw.get("available_at_ms"), f"{code_prefix}_AVAILABLE_AT_INVALID"
        )
        if observed_at_ms > available_at_ms:
            raise CandidateDataError(f"{code_prefix}_AVAILABLE_BEFORE_OBSERVATION")
        if available_at_ms > as_of_ms:
            continue
        key = identity(raw)
        if key is None:
            raise CandidateDataError(f"{code_prefix}_IDENTITY_INVALID")
        previous = selected.get(key)
        if previous is None or available_at_ms > previous["available_at_ms"]:
            selected[key] = raw
        elif available_at_ms == previous["available_at_ms"] and raw != previous:
            raise CandidateDataError(f"{code_prefix}_AMBIGUOUS_REVISION")
    if not selected:
        raise CandidateDataError(f"{code_prefix}_NO_POINT_IN_TIME_OBSERVATION")
    return sorted(selected.values(), key=lambda row: (row["observed_at_ms"], str(identity(row))))


def _series(raw_inputs: dict[str, Any], name: str, as_of_ms: int) -> list[dict[str, Any]]:
    series = raw_inputs.get("series")
    if not isinstance(series, dict):
        raise CandidateDataError("RAW_SERIES_NOT_OBJECT")
    rows = _select_latest_revisions(
        series.get(name),
        as_of_ms=as_of_ms,
        identity=lambda row: row.get("period", row.get("observed_at_ms")),
        code_prefix=name,
    )
    result = []
    for row in rows:
        item = dict(row)
        item["value"] = _finite(row.get("value"), f"{name}_VALUE_INVALID")
        result.append(item)
    return result


def _table(
    raw_inputs: dict[str, Any],
    name: str,
    as_of_ms: int,
    *,
    identity_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    tables = raw_inputs.get("tables")
    if not isinstance(tables, dict):
        raise CandidateDataError("RAW_TABLES_NOT_OBJECT")

    def identity(row: dict[str, Any]) -> tuple[Any, ...] | None:
        values = tuple(row.get(field) for field in identity_fields)
        return None if any(value is None for value in values) else values

    return _select_latest_revisions(
        tables.get(name),
        as_of_ms=as_of_ms,
        identity=identity,
        code_prefix=name,
    )


def _last(rows: list[dict[str, Any]], count: int, code: str) -> list[dict[str, Any]]:
    if len(rows) < count:
        raise CandidateDataError(f"{code}_HISTORY_INSUFFICIENT")
    return rows[-count:]


def _month_number(period: Any, code: str) -> int:
    if not isinstance(period, str) or len(period) != 7 or period[4] != "-":
        raise CandidateDataError(f"{code}_MONTHLY_PERIOD_INVALID")
    try:
        year = int(period[:4])
        month = int(period[5:])
    except ValueError as exc:
        raise CandidateDataError(f"{code}_MONTHLY_PERIOD_INVALID") from exc
    if year < 1900 or not 1 <= month <= 12:
        raise CandidateDataError(f"{code}_MONTHLY_PERIOD_INVALID")
    return year * 12 + month - 1


def _monthly_rows(
    raw_inputs: dict[str, Any],
    name: str,
    as_of_ms: int,
    count: int,
) -> list[dict[str, Any]]:
    rows = _last(_series(raw_inputs, name, as_of_ms), count, name)
    months = [_month_number(row.get("period"), name) for row in rows]
    if any(right - left != 1 for left, right in zip(months, months[1:])):
        raise CandidateDataError(f"{name}_MONTHLY_PERIOD_GAP")
    return rows


def _calendar_lag_pair(
    rows: list[dict[str, Any]],
    *,
    lag_ms: int,
    code: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = rows[-1]
    target = current["observed_at_ms"] - lag_ms
    prior = next((row for row in rows if row["observed_at_ms"] == target), None)
    if prior is None:
        raise CandidateDataError(f"{code}_EXACT_CALENDAR_LAG_MISSING")
    return prior, current


def _require_parameters(raw_inputs: dict[str, Any]) -> dict[str, Any]:
    parameters = raw_inputs.get("parameters")
    if not isinstance(parameters, dict):
        raise CandidateDataError("RAW_PARAMETERS_NOT_OBJECT")
    return parameters


def _core_inflation(raw: dict[str, Any], as_of_ms: int) -> float:
    values = [row["value"] for row in _monthly_rows(raw, "CPILFESL", as_of_ms, 13)]
    current = _positive(values[-1], "CPILFESL_VALUE_NONPOSITIVE")
    lag_3 = _positive(values[-4], "CPILFESL_VALUE_NONPOSITIVE")
    lag_12 = _positive(values[-13], "CPILFESL_VALUE_NONPOSITIVE")
    return 100 * ((current / lag_3) ** 4 - 1) - 100 * (current / lag_12 - 1)


def _unemployment_deterioration(raw: dict[str, Any], as_of_ms: int) -> float:
    values = [row["value"] for row in _monthly_rows(raw, "UNRATE", as_of_ms, 15)]
    current_mean = statistics.fmean(values[-3:])
    prior_means = [
        statistics.fmean(values[end_index - 2 : end_index + 1])
        for end_index in range(len(values) - 2, 1, -1)
    ]
    if len(prior_means) != 12:
        raise CandidateDataError("UNRATE_PRIOR_WINDOW_COUNT_INVALID")
    return current_mean - min(prior_means)


def _real_policy_rate(raw: dict[str, Any], as_of_ms: int) -> float:
    effr = _series(raw, "EFFR", as_of_ms)[-1]["value"]
    pce = [row["value"] for row in _monthly_rows(raw, "PCEPILFE", as_of_ms, 13)]
    current = _positive(pce[-1], "PCEPILFE_VALUE_NONPOSITIVE")
    lag_12 = _positive(pce[-13], "PCEPILFE_VALUE_NONPOSITIVE")
    return effr - 100 * (current / lag_12 - 1)


def _trading_20d_log_change(raw: dict[str, Any], as_of_ms: int, name: str) -> float:
    rows = _last(_series(raw, name, as_of_ms), 21, name)
    prior = _positive(rows[0]["value"], f"{name}_VALUE_NONPOSITIVE")
    current = _positive(rows[-1]["value"], f"{name}_VALUE_NONPOSITIVE")
    return 100 * math.log(current / prior)


def _trading_20d_change_bp(raw: dict[str, Any], as_of_ms: int, name: str) -> float:
    rows = _last(_series(raw, name, as_of_ms), 21, name)
    return 100 * (rows[-1]["value"] - rows[0]["value"])


def _stablecoin_supply_change(raw: dict[str, Any], as_of_ms: int) -> float:
    parameters = _require_parameters(raw)
    universe = parameters.get("approved_stablecoin_ids")
    version = parameters.get("stablecoin_universe_version")
    if not isinstance(universe, list) or not universe or len(set(universe)) != len(universe):
        raise CandidateDataError("STABLECOIN_UNIVERSE_INVALID")
    if not isinstance(version, str) or not version:
        raise CandidateDataError("STABLECOIN_UNIVERSE_VERSION_MISSING")
    rows = _table(
        raw,
        "STABLECOIN_CAP",
        as_of_ms,
        identity_fields=("asset_id", "observed_at_ms"),
    )
    relevant = [row for row in rows if row.get("asset_id") in universe]
    current_time = max(row["observed_at_ms"] for row in relevant)
    prior_time = current_time - 30 * DAY_MS

    def aggregate(observed_at_ms: int) -> float:
        by_asset = {
            row["asset_id"]: _nonnegative(row.get("value"), "STABLECOIN_CAP_VALUE_INVALID")
            for row in relevant
            if row["observed_at_ms"] == observed_at_ms
        }
        if set(by_asset) != set(universe):
            raise CandidateDataError("STABLECOIN_UNIVERSE_COVERAGE_INCOMPLETE")
        return _positive(sum(by_asset.values()), "STABLECOIN_AGGREGATE_NONPOSITIVE")

    return 100 * math.log(aggregate(current_time) / aggregate(prior_time))


def _etp_flow(raw: dict[str, Any], as_of_ms: int) -> float:
    parameters = _require_parameters(raw)
    universe = parameters.get("approved_etp_ids")
    version = parameters.get("etp_universe_version")
    if not isinstance(universe, list) or not universe or len(set(universe)) != len(universe):
        raise CandidateDataError("ETP_UNIVERSE_INVALID")
    if not isinstance(version, str) or not version:
        raise CandidateDataError("ETP_UNIVERSE_VERSION_MISSING")
    rows = _table(
        raw,
        "SPOT_BTC_ETP",
        as_of_ms,
        identity_fields=("fund_id", "observed_at_ms"),
    )
    relevant = [row for row in rows if row.get("fund_id") in universe]
    times = sorted({row["observed_at_ms"] for row in relevant})
    if len(times) < 21:
        raise CandidateDataError("ETP_20D_HISTORY_INSUFFICIENT")
    times = times[-21:]
    by_key = {(row["fund_id"], row["observed_at_ms"]): row for row in relevant}
    starting_aum = 0.0
    total_flow = 0.0
    for fund_id in universe:
        for timestamp in times:
            if (fund_id, timestamp) not in by_key:
                raise CandidateDataError("ETP_UNIVERSE_COVERAGE_INCOMPLETE")
        starting_aum += _positive(
            by_key[(fund_id, times[0])].get("net_assets"),
            "ETP_STARTING_NET_ASSETS_INVALID",
        )
        for previous_time, current_time in zip(times, times[1:]):
            previous = by_key[(fund_id, previous_time)]
            current = by_key[(fund_id, current_time)]
            previous_shares = _nonnegative(
                previous.get("adjusted_shares_outstanding"),
                "ETP_ADJUSTED_SHARES_INVALID",
            )
            current_shares = _nonnegative(
                current.get("adjusted_shares_outstanding"),
                "ETP_ADJUSTED_SHARES_INVALID",
            )
            nav = _positive(current.get("nav_per_share"), "ETP_NAV_INVALID")
            total_flow += (current_shares - previous_shares) * nav
    return 100 * total_flow / _positive(starting_aum, "ETP_STARTING_AUM_NONPOSITIVE")


def _latest_aligned(
    raw: dict[str, Any],
    as_of_ms: int,
    names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    parameters = _require_parameters(raw)
    tolerance = _integer_ms(
        parameters.get("cross_source_alignment_tolerance_ms"),
        "CROSS_SOURCE_ALIGNMENT_TOLERANCE_INVALID",
    )
    if tolerance != ALIGNMENT_TOLERANCE_MS:
        raise CandidateDataError("CROSS_SOURCE_ALIGNMENT_TOLERANCE_NOT_LOCKED")
    selected = {name: _series(raw, name, as_of_ms)[-1] for name in names}
    timestamps = [item["observed_at_ms"] for item in selected.values()]
    if max(timestamps) - min(timestamps) > tolerance:
        raise CandidateDataError("CROSS_SOURCE_ALIGNMENT_EXCEEDED")
    return selected


def _oi_notional(raw: dict[str, Any], as_of_ms: int) -> float:
    return _nonnegative(
        _series(raw, "OPEN_INTEREST_NOTIONAL_USD", as_of_ms)[-1]["value"],
        "OPEN_INTEREST_NOTIONAL_VALUE_INVALID",
    )


def _oi_to_market_cap(raw: dict[str, Any], as_of_ms: int) -> float:
    aligned = _latest_aligned(
        raw,
        as_of_ms,
        ("OPEN_INTEREST_NOTIONAL_USD", "MARKET_CAP_USD"),
    )
    notional = _nonnegative(
        aligned["OPEN_INTEREST_NOTIONAL_USD"]["value"],
        "OPEN_INTEREST_NOTIONAL_VALUE_INVALID",
    )
    market_cap = _positive(aligned["MARKET_CAP_USD"]["value"], "MARKET_CAP_VALUE_INVALID")
    return 100 * notional / market_cap


def _abs_funding(raw: dict[str, Any], as_of_ms: int) -> float:
    rows = _last(_series(raw, "FUNDING_RATE", as_of_ms), 9, "FUNDING_RATE")
    timestamps = [row["observed_at_ms"] for row in rows]
    if any(right - left != 8 * HOUR_MS for left, right in zip(timestamps, timestamps[1:])):
        raise CandidateDataError("FUNDING_RATE_INTERVAL_NOT_8H")
    return 10_000 * abs(statistics.fmean(row["value"] for row in rows))


def _liquidation(raw: dict[str, Any], as_of_ms: int) -> dict[str, float | int | str]:
    item = raw.get("liquidation_24h")
    if not isinstance(item, dict):
        raise CandidateDataError("LIQUIDATION_24H_MISSING")
    window_end_ms = _integer_ms(item.get("window_end_ms"), "LIQUIDATION_WINDOW_END_INVALID")
    available_at_ms = _integer_ms(
        item.get("available_at_ms"), "LIQUIDATION_AVAILABLE_AT_INVALID"
    )
    if window_end_ms > available_at_ms or available_at_ms > as_of_ms:
        raise CandidateDataError("LIQUIDATION_POINT_IN_TIME_INVALID")
    coverage = item.get("coverage_state")
    if coverage != "VERIFIED_COMPLETE":
        if _finite(item.get("total_liquidation_usd"), "LIQUIDATION_TOTAL_INVALID") == 0:
            raise CandidateDataError("LIQUIDATION_ZERO_REQUIRES_VERIFIED_COMPLETE_COVERAGE")
        raise CandidateDataError("LIQUIDATION_COVERAGE_NOT_VERIFIED_COMPLETE")
    long_value = _nonnegative(item.get("long_liquidation_usd"), "LIQUIDATION_LONG_INVALID")
    short_value = _nonnegative(item.get("short_liquidation_usd"), "LIQUIDATION_SHORT_INVALID")
    total = _nonnegative(item.get("total_liquidation_usd"), "LIQUIDATION_TOTAL_INVALID")
    if not math.isclose(total, long_value + short_value, rel_tol=1e-12, abs_tol=1e-9):
        raise CandidateDataError("LIQUIDATION_COMPONENT_SUM_MISMATCH")
    return {
        "window_end_ms": window_end_ms,
        "coverage_state": coverage,
        "long": long_value,
        "short": short_value,
        "total": total,
    }


def _liquidation_intensity(raw: dict[str, Any], as_of_ms: int) -> float:
    item = _liquidation(raw, as_of_ms)
    latest = _latest_aligned(raw, as_of_ms, ("OPEN_INTEREST_NOTIONAL_USD",))
    parameters = _require_parameters(raw)
    tolerance = _integer_ms(
        parameters.get("cross_source_alignment_tolerance_ms"),
        "CROSS_SOURCE_ALIGNMENT_TOLERANCE_INVALID",
    )
    if tolerance != ALIGNMENT_TOLERANCE_MS:
        raise CandidateDataError("CROSS_SOURCE_ALIGNMENT_TOLERANCE_NOT_LOCKED")
    timestamps = [item["window_end_ms"]] + [row["observed_at_ms"] for row in latest.values()]
    if max(timestamps) - min(timestamps) > tolerance:
        raise CandidateDataError("LIQUIDATION_OI_ALIGNMENT_EXCEEDED")
    return 100 * float(item["total"]) / _positive(
        _oi_notional(raw, as_of_ms), "OPEN_INTEREST_NOTIONAL_NONPOSITIVE"
    )


def _liquidation_direction(raw: dict[str, Any], as_of_ms: int) -> float:
    item = _liquidation(raw, as_of_ms)
    total = float(item["total"])
    if total == 0:
        return 0.0
    return (float(item["short"]) - float(item["long"])) / total


def _mvrv(raw: dict[str, Any], as_of_ms: int) -> float:
    aligned = _latest_aligned(raw, as_of_ms, ("CAP_MARKET_USD", "CAP_REALIZED_USD"))
    market_cap = _positive(aligned["CAP_MARKET_USD"]["value"], "CAP_MARKET_VALUE_INVALID")
    realized_cap = _positive(
        aligned["CAP_REALIZED_USD"]["value"], "CAP_REALIZED_VALUE_INVALID"
    )
    return market_cap / realized_cap


def _realized_cap_change(raw: dict[str, Any], as_of_ms: int) -> float:
    rows = _series(raw, "CAP_REALIZED_USD", as_of_ms)
    prior, current = _calendar_lag_pair(
        rows,
        lag_ms=30 * DAY_MS,
        code="CAP_REALIZED_USD",
    )
    return 100 * math.log(
        _positive(current["value"], "CAP_REALIZED_VALUE_INVALID")
        / _positive(prior["value"], "CAP_REALIZED_VALUE_INVALID")
    )


def _ohlcv(raw: dict[str, Any], as_of_ms: int) -> tuple[list[dict[str, float]], float]:
    rows = _table(
        raw,
        "OHLCV_DAILY",
        as_of_ms,
        identity_fields=("observed_at_ms",),
    )
    rows = _last(rows, 201, "OHLCV_DAILY")
    timestamps = [row["observed_at_ms"] for row in rows]
    if any(right - left != DAY_MS for left, right in zip(timestamps, timestamps[1:])):
        raise CandidateDataError("OHLCV_DAILY_PERIOD_GAP")
    parsed: list[dict[str, float]] = []
    for row in rows:
        if row.get("complete") is not True:
            raise CandidateDataError("OHLCV_DAILY_PARTIAL_BAR")
        open_value = _positive(row.get("open"), "OHLCV_OPEN_INVALID")
        high = _positive(row.get("high"), "OHLCV_HIGH_INVALID")
        low = _positive(row.get("low"), "OHLCV_LOW_INVALID")
        close = _positive(row.get("close"), "OHLCV_CLOSE_INVALID")
        if high < max(open_value, close, low) or low > min(open_value, close, high):
            raise CandidateDataError("OHLCV_BAR_GEOMETRY_INVALID")
        parsed.append({"open": open_value, "high": high, "low": low, "close": close})
    true_ranges = []
    for index in range(len(parsed) - 20, len(parsed)):
        current = parsed[index]
        previous_close = parsed[index - 1]["close"]
        true_ranges.append(
            max(
                current["high"] - current["low"],
                abs(current["high"] - previous_close),
                abs(current["low"] - previous_close),
            )
        )
    atr20 = _positive(statistics.fmean(true_ranges), "ATR20_NONPOSITIVE")
    return parsed, atr20


def _close_minus_sma200(raw: dict[str, Any], as_of_ms: int) -> float:
    bars, atr20 = _ohlcv(raw, as_of_ms)
    closes = [bar["close"] for bar in bars]
    return (closes[-1] - statistics.fmean(closes[-200:])) / atr20


def _sma50_minus_sma200(raw: dict[str, Any], as_of_ms: int) -> float:
    bars, atr20 = _ohlcv(raw, as_of_ms)
    closes = [bar["close"] for bar in bars]
    return (statistics.fmean(closes[-50:]) - statistics.fmean(closes[-200:])) / atr20


def _return_20d_over_atr(raw: dict[str, Any], as_of_ms: int) -> float:
    bars, atr20 = _ohlcv(raw, as_of_ms)
    current = bars[-1]["close"]
    lag_20 = bars[-21]["close"]
    return math.log(current / lag_20) / ((atr20 / current) * math.sqrt(20))


def _cvd(raw: dict[str, Any], as_of_ms: int) -> float:
    rows = _table(
        raw,
        "AGGRESSOR_DAILY",
        as_of_ms,
        identity_fields=("observed_at_ms",),
    )
    rows = _last(rows, 20, "AGGRESSOR_DAILY")
    timestamps = [row["observed_at_ms"] for row in rows]
    if any(right - left != DAY_MS for left, right in zip(timestamps, timestamps[1:])):
        raise CandidateDataError("AGGRESSOR_DAILY_PERIOD_GAP")
    signed = 0.0
    total_sum = 0.0
    for row in rows:
        if row.get("complete") is not True:
            raise CandidateDataError("AGGRESSOR_DAILY_PARTIAL_BAR")
        buyer = _nonnegative(
            row.get("buyer_initiated_quote_volume"), "CVD_BUYER_VOLUME_INVALID"
        )
        seller = _nonnegative(
            row.get("seller_initiated_quote_volume"), "CVD_SELLER_VOLUME_INVALID"
        )
        unknown = _nonnegative(
            row.get("unknown_aggressor_quote_volume"), "CVD_UNKNOWN_VOLUME_INVALID"
        )
        total = _nonnegative(row.get("total_quote_volume"), "CVD_TOTAL_VOLUME_INVALID")
        if unknown != 0:
            raise CandidateDataError("CVD_UNKNOWN_AGGRESSOR_VOLUME")
        if not math.isclose(total, buyer + seller + unknown, rel_tol=1e-12, abs_tol=1e-9):
            raise CandidateDataError("CVD_VOLUME_SUM_MISMATCH")
        signed += buyer - seller
        total_sum += total
    return signed / _positive(total_sum, "CVD_TOTAL_VOLUME_NONPOSITIVE")


CALCULATORS: dict[str, Callable[[dict[str, Any], int], float]] = {
    "L1_CORE_INFLATION_ACCELERATION": _core_inflation,
    "L1_UNEMPLOYMENT_DETERIORATION": _unemployment_deterioration,
    "L1_REAL_POLICY_RATE": _real_policy_rate,
    "L2_BROAD_USD_20D_LOG_CHANGE": lambda raw, as_of: _trading_20d_log_change(
        raw, as_of, "DTWEXBGS"
    ),
    "L2_REAL_10Y_YIELD_20D_CHANGE_BP": lambda raw, as_of: _trading_20d_change_bp(
        raw, as_of, "DFII10"
    ),
    "L2_NOMINAL_2Y_YIELD_20D_CHANGE_BP": lambda raw, as_of: _trading_20d_change_bp(
        raw, as_of, "DGS2"
    ),
    "L3_STABLECOIN_SUPPLY_30D_LOG_CHANGE": _stablecoin_supply_change,
    "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM": _etp_flow,
    "L3_HIGH_YIELD_OAS_20D_CHANGE_BP": lambda raw, as_of: _trading_20d_change_bp(
        raw, as_of, "BAMLH0A0HYM2"
    ),
    "L4_OI_TO_MARKET_CAP": _oi_to_market_cap,
    "L4_ABS_FUNDING_3D_MEAN_BP": _abs_funding,
    "L4_LIQUIDATION_INTENSITY_24H": _liquidation_intensity,
    "L4_SHORT_MINUS_LONG_LIQUIDATION_SHARE_24H": _liquidation_direction,
    "L5_MVRV_LEVEL": _mvrv,
    "L5_REALIZED_CAP_30D_LOG_CHANGE": _realized_cap_change,
    "L6_CLOSE_MINUS_SMA200_OVER_ATR20": _close_minus_sma200,
    "L6_SMA50_MINUS_SMA200_OVER_ATR20": _sma50_minus_sma200,
    "L6_RETURN_20D_OVER_ATR_VOL": _return_20d_over_atr,
    "L6_CVD_20D_SHARE": _cvd,
}


def _rounded(value: float) -> float:
    result = round(float(value), 10)
    return 0.0 if result == 0 else result


def calculate_feature(
    feature_id: str,
    raw_inputs: dict[str, Any],
    *,
    as_of_ms: int,
    source_contract: dict[str, Any] | None = None,
    model_registry: dict[str, Any] | None = None,
    public_source_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if public_source_authority is None:
        public_source_authority = load_json(DEFAULT_PUBLIC_SOURCE_AUTHORITY)
    if source_contract is None:
        source_contract = load_json(DEFAULT_SOURCE_CONTRACT)
    if model_registry is None:
        model_registry = load_json(DEFAULT_MODEL_REGISTRY)
    errors = validate_source_contract(
        source_contract,
        model_registry,
        public_source_authority,
    )
    if errors:
        raise CandidateDataError("SOURCE_CONTRACT_INVALID:" + "|".join(errors))
    if feature_id not in CALCULATORS:
        raise CandidateDataError("FEATURE_CALCULATOR_UNKNOWN")
    if feature_id not in source_contract["feature_sources"]:
        raise CandidateDataError("FEATURE_SOURCE_CONTRACT_MISSING")
    if not isinstance(raw_inputs, dict) or raw_inputs.get("schema_version") != (
        "CRT_CANDIDATE_RAW_INPUT_V0.2"
    ):
        raise CandidateDataError("RAW_INPUT_SCHEMA_INVALID")
    as_of = _integer_ms(as_of_ms, "AS_OF_INVALID")
    value = _finite(CALCULATORS[feature_id](raw_inputs, as_of), "FEATURE_RESULT_INVALID")
    output: dict[str, Any] = {
        "schema_version": "CRT_CANDIDATE_RAW_FEATURE_OBSERVATION_V0.2",
        "state": "MECHANICALLY_CALCULATED_RESEARCH_ONLY",
        "feature_id": feature_id,
        "calculator_id": source_contract["feature_sources"][feature_id]["calculator_id"],
        "as_of_ms": as_of,
        "value": _rounded(value),
        "candidate_registry_hash": canonical_hash(model_registry),
        "public_source_authority_hash": canonical_hash(public_source_authority),
        "source_contract_hash": canonical_hash(source_contract),
        "raw_input_hash": canonical_hash(
            {
                "feature_id": feature_id,
                "as_of_ms": as_of,
                "raw_inputs": raw_inputs,
            }
        ),
        "authority": {
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
            "capital_decision_authority": "USER_ONLY",
        },
        "capital_decision": None,
    }
    output["observation_hash"] = canonical_hash(output)
    return output
