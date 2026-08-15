#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import candidate_acquisition
import issuer_adapters


ROOT = Path(__file__).resolve().parent
DEFAULT_CAPTURE_CONTRACT = ROOT / "CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1.json"
DEFAULT_ADAPTER_CONTRACT = ROOT / "CRT_ETP_ISSUER_ADAPTER_CONTRACT_V0.1.json"
DEFAULT_ACQUISITION_CONTRACT = ROOT / "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1.json"
DEFAULT_PUBLIC_SOURCE_AUTHORITY = ROOT / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
DEFAULT_SOURCE_CONTRACT = ROOT / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
DEFAULT_WALK_FORWARD_PROTOCOL = ROOT / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"

CONTRACT_SCHEMA_VERSION = "CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1"
CONTRACT_ID = "CRT-ETP-PROSPECTIVE-CAPTURE-CONTRACT-V0.1"
CONTRACT_STATUS = "RUNNER_IMPLEMENTED_LIVE_CAPTURE_NOT_STARTED"
EXPECTED_CONTRACT_SEMANTIC_SHA256 = (
    "408a7b201c9fb979a592125ffdf9753354df5a81a5152395cd3180d02b50fb29"
)
RECEIPT_SCHEMA_VERSION = "CRT_ETP_PROSPECTIVE_CAPTURE_RECEIPT_V0.1"
RUN_REPORT_SCHEMA_VERSION = "CRT_ETP_PROSPECTIVE_CAPTURE_RUN_V0.1"
READY_TICKERS = ("IBIT", "BITB", "ARKB", "HODL", "GBTC", "BTC")
BLOCKED_TICKERS = {"FBTC", "BTCO", "EZBC", "BRRR", "BTCW", "MSBT"}
SOURCE_CONTRACT_ID = "US_SPOT_BTC_ETP_POINT_IN_TIME"
REQUEST_USER_AGENT = "CRT-ETP-Prospective-Capture/0.1 local-research-read-only"
MAX_CLOCK_SKEW_MS = 300_000


class ProspectiveCaptureError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveCaptureError("JSON_DOCUMENT_UNREADABLE") from exc
    if not isinstance(value, dict):
        raise ProspectiveCaptureError("JSON_ROOT_NOT_OBJECT")
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _timestamp_ms(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveCaptureError(code)
    return value


def _contract_semantic_hash(contract: dict[str, Any]) -> str:
    payload = dict(contract)
    payload.pop("implementation_sha256", None)
    return canonical_hash(payload)


def _profile_map(adapter_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = adapter_contract.get("issuer_profiles")
    if not isinstance(profiles, list):
        raise ProspectiveCaptureError("ADAPTER_PROFILES_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("ticker"), str):
            raise ProspectiveCaptureError("ADAPTER_PROFILE_INVALID")
        ticker = profile["ticker"]
        if ticker in result:
            raise ProspectiveCaptureError("ADAPTER_PROFILE_DUPLICATE")
        result[ticker] = profile
    return result


def _calendar_dates(calendar: dict[str, Any], field: str) -> list[date]:
    values = calendar.get(field)
    if not isinstance(values, list):
        raise ProspectiveCaptureError("MARKET_CALENDAR_DATES_INVALID")
    parsed: list[date] = []
    for value in values:
        if not isinstance(value, str):
            raise ProspectiveCaptureError("MARKET_CALENDAR_DATES_INVALID")
        try:
            parsed.append(date.fromisoformat(value))
        except ValueError as exc:
            raise ProspectiveCaptureError("MARKET_CALENDAR_DATES_INVALID") from exc
    if len(parsed) != len(set(parsed)):
        raise ProspectiveCaptureError("MARKET_CALENDAR_DATES_DUPLICATE")
    return parsed


def validate_capture_contract(
    contract: dict[str, Any],
    *,
    adapter_contract: dict[str, Any],
    acquisition_contract: dict[str, Any],
    public_source_authority: dict[str, Any],
    source_contract: dict[str, Any],
    walk_forward_protocol: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        errors.append("capture contract schema_version mismatch")
    if contract.get("contract_id") != CONTRACT_ID:
        errors.append("capture contract identity mismatch")
    if contract.get("status") != CONTRACT_STATUS:
        errors.append("capture contract status mismatch")
    if contract.get("mode") != "SHADOW_ONLY":
        errors.append("capture contract mode is not shadow only")
    if contract.get("base_sha") != "a267ea84e797d41a5e973523d7d013fdf00ba773":
        errors.append("capture contract base sha mismatch")
    if contract.get("implementation_sha256") != sha256_bytes(Path(__file__).read_bytes()):
        errors.append("capture contract implementation hash mismatch")
    if contract.get("acquisition_implementation_sha256") != sha256_bytes(
        Path(candidate_acquisition.__file__).read_bytes()
    ):
        errors.append("capture contract acquisition implementation hash mismatch")
    if adapter_contract.get("implementation_sha256") != sha256_bytes(
        Path(issuer_adapters.__file__).read_bytes()
    ):
        errors.append("capture contract adapter implementation hash mismatch")
    if _contract_semantic_hash(contract) != EXPECTED_CONTRACT_SEMANTIC_SHA256:
        errors.append("capture contract semantic hash mismatch")

    parent_hashes = {
        "public_source_authority_hash": canonical_hash(public_source_authority),
        "acquisition_contract_hash": canonical_hash(acquisition_contract),
        "source_contract_hash": canonical_hash(source_contract),
        "walk_forward_protocol_hash": canonical_hash(walk_forward_protocol),
        "adapter_contract_hash": canonical_hash(adapter_contract),
    }
    for field, expected in parent_hashes.items():
        if contract.get(field) != expected:
            errors.append(f"capture contract {field} mismatch")
    if contract.get("candidate_registry_hash") != source_contract.get(
        "candidate_registry_hash"
    ):
        errors.append("capture contract candidate registry hash mismatch")
    if contract.get("etp_replay_feasibility_hash") != adapter_contract.get(
        "etp_replay_feasibility_hash"
    ):
        errors.append("capture contract feasibility hash mismatch")

    universe = contract.get("capture_universe")
    if not isinstance(universe, dict):
        errors.append("capture contract universe invalid")
    else:
        if tuple(universe.get("ready_tickers", [])) != READY_TICKERS:
            errors.append("capture contract ready ticker drift")
        blocked = universe.get("blocked_tickers")
        if not isinstance(blocked, dict) or set(blocked) != BLOCKED_TICKERS:
            errors.append("capture contract blocked ticker drift")
        surface = adapter_contract.get("surface_probe_result", {})
        if universe.get("ready_tickers") != surface.get("proven_tickers"):
            errors.append("capture contract ready tickers do not match adapter proof")
        if blocked != surface.get("blocked_tickers"):
            errors.append("capture contract blockers do not match adapter proof")

    transport = contract.get("transport")
    if not isinstance(transport, dict):
        errors.append("capture contract transport invalid")
    else:
        expected_transport = {
            "method": "GET",
            "scheme": "HTTPS_ONLY",
            "url_policy": "EXACT_ADAPTER_LOCKED_URL_ONLY",
            "redirect_policy": "FORBIDDEN",
            "proxy_policy": "DISABLED_IGNORE_ENVIRONMENT",
            "credentials": "NONE",
            "cookies": "NONE",
            "request_body": "NONE",
            "content_encoding": "identity",
            "in_process_retry_count": 0,
        }
        if any(transport.get(key) != value for key, value in expected_transport.items()):
            errors.append("capture contract transport authority drift")
        if transport.get("allowed_content_types") != ["text/html", "text/plain"]:
            errors.append("capture contract content type drift")
        if transport.get("retrieval_clock_tolerance_ms") != MAX_CLOCK_SKEW_MS:
            errors.append("capture contract retrieval clock tolerance drift")
        timeout = transport.get("timeout_seconds")
        maximum = transport.get("max_response_bytes")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
            errors.append("capture contract timeout invalid")
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1_000 <= maximum <= 20_000_000
        ):
            errors.append("capture contract response limit invalid")

    policy = contract.get("capture_policy")
    if not isinstance(policy, dict):
        errors.append("capture contract policy invalid")
    else:
        if policy.get("capture_not_before_local_time") != "20:00:00":
            errors.append("capture contract local time drift")
        if policy.get("prior_value_carry_forward") != "FORBIDDEN":
            errors.append("capture contract carry-forward policy drift")
        if policy.get("scheduler") != "NONE_CALLER_OWNED":
            errors.append("capture contract scheduling authority drift")
        if policy.get("clock_source") != "SYSTEM_UTC_ONLY":
            errors.append("capture contract clock source drift")
        if (
            policy.get("programmatic_clock_or_fetcher_override")
            != "FORBIDDEN_ON_DEPLOYABLE_PATH"
        ):
            errors.append("capture contract injection boundary drift")

    calendar = contract.get("market_calendar")
    if not isinstance(calendar, dict):
        errors.append("capture contract market calendar invalid")
    else:
        try:
            valid_from = date.fromisoformat(str(calendar.get("valid_from")))
            valid_through = date.fromisoformat(str(calendar.get("valid_through")))
            full_closes = _calendar_dates(calendar, "full_close_dates")
            early_closes = _calendar_dates(calendar, "early_close_dates")
        except (ValueError, ProspectiveCaptureError):
            errors.append("capture contract market calendar dates invalid")
        else:
            if valid_from > valid_through:
                errors.append("capture contract market calendar range reversed")
            if any(not valid_from <= item <= valid_through for item in full_closes + early_closes):
                errors.append("capture contract market calendar date outside range")
            if any(item.weekday() >= 5 for item in full_closes + early_closes):
                errors.append("capture contract market calendar closure on weekend")
            if set(full_closes) & set(early_closes):
                errors.append("capture contract full and early closure overlap")
        if calendar.get("timezone") != "America/New_York":
            errors.append("capture contract market timezone mismatch")
        if calendar.get("weekday_sessions") != [0, 1, 2, 3, 4]:
            errors.append("capture contract weekday sessions drift")
        if calendar.get("valid_through") != "2028-12-31":
            errors.append("capture contract market calendar horizon drift")
        if calendar.get("official_source_url") != "https://www.nyse.com/trade/hours-calendars":
            errors.append("capture contract market calendar source drift")
        if calendar.get("out_of_range_policy") != "BLOCK_NO_FETCH":
            errors.append("capture contract market calendar boundary drift")

    authority = contract.get("authority")
    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }
    if not isinstance(authority, dict) or any(
        authority.get(key) != value for key, value in expected_authority.items()
    ):
        errors.append("capture contract authority invalid")
    promotion = contract.get("promotion")
    if (
        not isinstance(promotion, dict)
        or promotion.get("automatic_promotion") is not False
        or promotion.get("historical_backfill_state") != "BLOCKED_NOT_PROVEN"
        or promotion.get("external_action_authority") != "NONE"
    ):
        errors.append("capture contract promotion boundary invalid")
    if contract.get("historical_backfill_authority") is not False:
        errors.append("capture contract historical authority invalid")
    if contract.get("dataset_readiness_granted") is not False:
        errors.append("capture contract readiness authority invalid")
    return errors


def _load_contracts() -> tuple[dict[str, Any], ...]:
    return (
        load_json(DEFAULT_CAPTURE_CONTRACT),
        load_json(DEFAULT_ADAPTER_CONTRACT),
        load_json(DEFAULT_ACQUISITION_CONTRACT),
        load_json(DEFAULT_PUBLIC_SOURCE_AUTHORITY),
        load_json(DEFAULT_SOURCE_CONTRACT),
        load_json(DEFAULT_WALK_FORWARD_PROTOCOL),
    )


def _resolved_contracts(
    capture_contract: dict[str, Any] | None,
    adapter_contract: dict[str, Any] | None,
    acquisition_contract: dict[str, Any] | None,
    public_source_authority: dict[str, Any] | None,
    source_contract: dict[str, Any] | None,
    walk_forward_protocol: dict[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    defaults = _load_contracts()
    values = (
        capture_contract,
        adapter_contract,
        acquisition_contract,
        public_source_authority,
        source_contract,
        walk_forward_protocol,
    )
    resolved = tuple(default if value is None else value for value, default in zip(values, defaults))
    errors = validate_capture_contract(
        resolved[0],
        adapter_contract=resolved[1],
        acquisition_contract=resolved[2],
        public_source_authority=resolved[3],
        source_contract=resolved[4],
        walk_forward_protocol=resolved[5],
    )
    if errors:
        raise ProspectiveCaptureError("CAPTURE_CONTRACT_INVALID: " + "; ".join(errors))
    return resolved


def capture_decision(now_ms: int, contract: dict[str, Any]) -> dict[str, Any]:
    now = _timestamp_ms(now_ms, "NOW_MS_INVALID")
    calendar = contract.get("market_calendar")
    policy = contract.get("capture_policy")
    if not isinstance(calendar, dict) or not isinstance(policy, dict):
        raise ProspectiveCaptureError("CAPTURE_CALENDAR_CONTRACT_INVALID")
    if calendar.get("timezone") != "America/New_York":
        raise ProspectiveCaptureError("CAPTURE_TIMEZONE_INVALID")
    local = datetime.fromtimestamp(now / 1_000, tz=timezone.utc).astimezone(
        ZoneInfo("America/New_York")
    )
    local_date = local.date()
    try:
        valid_from = date.fromisoformat(str(calendar.get("valid_from")))
        valid_through = date.fromisoformat(str(calendar.get("valid_through")))
        not_before = datetime.strptime(
            str(policy.get("capture_not_before_local_time")), "%H:%M:%S"
        ).time()
    except ValueError as exc:
        raise ProspectiveCaptureError("CAPTURE_CALENDAR_CONTRACT_INVALID") from exc
    result = {
        "local_now": local.isoformat(),
        "expected_session_date": local_date.isoformat(),
        "calendar_id": calendar.get("calendar_id"),
    }
    if not valid_from <= local_date <= valid_through:
        return {**result, "state": "CALENDAR_OUT_OF_RANGE"}
    full_closes = set(_calendar_dates(calendar, "full_close_dates"))
    weekdays = calendar.get("weekday_sessions")
    if not isinstance(weekdays, list):
        raise ProspectiveCaptureError("CAPTURE_CALENDAR_CONTRACT_INVALID")
    if local_date.weekday() not in weekdays or local_date in full_closes:
        return {**result, "state": "MARKET_CLOSED"}
    if local.time().replace(tzinfo=None) < not_before:
        return {**result, "state": "NOT_DUE"}
    return {**result, "state": "CAPTURE_DUE"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_official_bytes(
    *,
    ticker: str,
    url: str,
    timeout_s: int,
    max_bytes: int,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or "@" in parsed.netloc:
        raise ProspectiveCaptureError("FETCH_URL_NOT_PUBLIC_HTTPS")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": REQUEST_USER_AGENT,
            "Accept": "text/html, text/plain;q=0.9",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
    )
    try:
        with opener.open(request, timeout=timeout_s) as response:
            status_code = int(response.status)
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            content_encoding = response.headers.get("Content-Encoding")
            if content_encoding not in (None, "", "identity"):
                raise ProspectiveCaptureError("FETCH_CONTENT_ENCODING_NOT_IDENTITY")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > max_bytes:
                        raise ProspectiveCaptureError("FETCH_BODY_TOO_LARGE")
                except ValueError as exc:
                    raise ProspectiveCaptureError("FETCH_CONTENT_LENGTH_INVALID") from exc
            body = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise ProspectiveCaptureError(f"FETCH_HTTP_STATUS_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ProspectiveCaptureError(
            f"FETCH_TRANSPORT_{type(exc.reason).__name__.upper()}"
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise ProspectiveCaptureError(f"FETCH_TRANSPORT_{type(exc).__name__.upper()}") from exc
    return {
        "status_code": status_code,
        "final_url": final_url,
        "content_type": content_type,
        "body": body,
        "retrieved_at_ms": int(time.time() * 1_000),
        "ticker": ticker,
    }


def _validated_response(
    response: Any,
    *,
    expected_url: str,
    run_at_ms: int,
    allowed_content_types: set[str],
    max_bytes: int,
) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ProspectiveCaptureError("FETCH_RESPONSE_NOT_OBJECT")
    if response.get("status_code") != 200:
        raise ProspectiveCaptureError("FETCH_STATUS_NOT_OK")
    if response.get("final_url") != expected_url:
        raise ProspectiveCaptureError("FETCH_FINAL_URL_NOT_LOCKED")
    content_type = response.get("content_type")
    if content_type not in allowed_content_types:
        raise ProspectiveCaptureError("FETCH_CONTENT_TYPE_NOT_ALLOWED")
    body = response.get("body")
    if not isinstance(body, bytes) or not body:
        raise ProspectiveCaptureError("FETCH_BODY_INVALID")
    if len(body) > max_bytes:
        raise ProspectiveCaptureError("FETCH_BODY_TOO_LARGE")
    retrieved = _timestamp_ms(response.get("retrieved_at_ms"), "FETCH_RETRIEVED_AT_INVALID")
    if abs(retrieved - run_at_ms) > MAX_CLOCK_SKEW_MS:
        raise ProspectiveCaptureError("FETCH_RETRIEVED_AT_CLOCK_SKEW")
    return {
        "status_code": 200,
        "final_url": expected_url,
        "content_type": content_type,
        "body": body,
        "retrieved_at_ms": retrieved,
    }


def _safe_path(root: Path, relpath: str, code: str) -> Path:
    if not isinstance(relpath, str) or not relpath or Path(relpath).is_absolute():
        raise ProspectiveCaptureError(code)
    resolved_root = root.resolve()
    candidate = (resolved_root / relpath).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ProspectiveCaptureError(code) from exc
    return candidate


def _raw_relpath(digest: str) -> str:
    return f"artifacts/sha256/{digest[:2]}/{digest}"


def _stage_raw(root: Path, body: bytes) -> dict[str, Any]:
    digest = sha256_bytes(body)
    relpath = _raw_relpath(digest)
    path = _safe_path(root, relpath, "RAW_ARCHIVE_PATH_INVALID")
    candidate_acquisition._write_content_addressed(path, body, digest)
    return {"sha256": digest, "size_bytes": len(body), "relpath": relpath}


def _request_identity(source_url: str) -> str:
    return f"GET {source_url}"


def _identity_relpath(source_url: str, digest: str) -> str:
    identity_hash = canonical_hash(
        {
            "source_contract_id": SOURCE_CONTRACT_ID,
            "request_identity": _request_identity(source_url),
            "sha256": digest,
        }
    )
    return f"metadata/identities/{identity_hash[:2]}/{identity_hash}.json"


def _load_existing_identity(
    root: Path,
    *,
    source_url: str,
    digest: str,
) -> dict[str, Any] | None:
    relpath = _identity_relpath(source_url, digest)
    path = _safe_path(root, relpath, "IDENTITY_METADATA_PATH_INVALID")
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveCaptureError("IDENTITY_METADATA_UNREADABLE") from exc
    if not isinstance(record, dict):
        raise ProspectiveCaptureError("IDENTITY_METADATA_INVALID")
    expected_record_hash = candidate_acquisition._record_hash(record)
    if record.get("record_sha256") != expected_record_hash:
        raise ProspectiveCaptureError("IDENTITY_METADATA_HASH_MISMATCH")
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise ProspectiveCaptureError("IDENTITY_METADATA_ARTIFACT_INVALID")
    expected = {
        "source_contract_id": SOURCE_CONTRACT_ID,
        "request_identity": _request_identity(source_url),
        "sha256": digest,
    }
    if any(artifact.get(field) != value for field, value in expected.items()):
        raise ProspectiveCaptureError("IDENTITY_METADATA_BINDING_MISMATCH")
    raw_path = _safe_path(root, str(artifact.get("archive_relpath")), "RAW_ARCHIVE_PATH_INVALID")
    if not raw_path.is_file() or sha256_bytes(raw_path.read_bytes()) != digest:
        raise ProspectiveCaptureError("RAW_ARCHIVE_SHA256_MISMATCH")
    return dict(artifact)


def _cas_json(root: Path, prefix: str, value: dict[str, Any]) -> dict[str, Any]:
    raw = canonical_bytes(value) + b"\n"
    digest = sha256_bytes(raw)
    relpath = f"{prefix}/sha256/{digest[:2]}/{digest}.json"
    path = _safe_path(root, relpath, "CAS_JSON_PATH_INVALID")
    candidate_acquisition._write_content_addressed(path, raw, digest)
    return {"sha256": digest, "relpath": relpath}


def _read_receipt(root: Path, relpath: str) -> dict[str, Any]:
    path = _safe_path(root, relpath, "RECEIPT_PATH_INVALID")
    if not path.is_file():
        raise ProspectiveCaptureError("RECEIPT_MISSING")
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if path.stem != digest:
        raise ProspectiveCaptureError("RECEIPT_FILE_SHA256_MISMATCH")
    expected_relpath = f"capture_receipts/sha256/{digest[:2]}/{digest}.json"
    if relpath != expected_relpath:
        raise ProspectiveCaptureError("RECEIPT_PATH_NOT_CONTENT_ADDRESSED")
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProspectiveCaptureError("RECEIPT_UNREADABLE") from exc
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ProspectiveCaptureError("RECEIPT_SCHEMA_INVALID")
    artifact = receipt.get("artifact")
    snapshot = receipt.get("snapshot")
    if not isinstance(artifact, dict) or not isinstance(snapshot, dict):
        raise ProspectiveCaptureError("RECEIPT_CONTENT_INVALID")
    digest = artifact.get("sha256")
    if not _is_sha256(digest):
        raise ProspectiveCaptureError("RECEIPT_RAW_SHA256_INVALID")
    raw_relpath = artifact.get("archive_relpath")
    if raw_relpath != _raw_relpath(digest):
        raise ProspectiveCaptureError("RAW_ARCHIVE_PATH_NOT_CONTENT_ADDRESSED")
    raw_path = _safe_path(root, str(raw_relpath), "RAW_ARCHIVE_PATH_INVALID")
    if not raw_path.is_file():
        raise ProspectiveCaptureError("RAW_ARCHIVE_MISSING")
    raw_body = raw_path.read_bytes()
    if sha256_bytes(raw_body) != artifact.get("sha256"):
        raise ProspectiveCaptureError("RAW_ARCHIVE_SHA256_MISMATCH")
    if len(raw_body) != artifact.get("size_bytes"):
        raise ProspectiveCaptureError("RAW_ARCHIVE_SIZE_MISMATCH")
    if snapshot.get("raw_snapshot_sha256") != artifact.get("sha256"):
        raise ProspectiveCaptureError("RECEIPT_RAW_SNAPSHOT_BINDING_MISMATCH")
    if snapshot.get("snapshot_sha256") != issuer_adapters.snapshot_hash(snapshot):
        raise ProspectiveCaptureError("RECEIPT_SNAPSHOT_HASH_MISMATCH")
    identity = _load_existing_identity(
        root,
        source_url=str(snapshot.get("source_url")),
        digest=str(artifact.get("sha256")),
    )
    if identity != artifact:
        raise ProspectiveCaptureError("RECEIPT_IDENTITY_METADATA_MISMATCH")
    return receipt


def _receipt_relpaths(root: Path) -> list[str]:
    receipt_root = root / "capture_receipts" / "sha256"
    if not receipt_root.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in receipt_root.glob("*/*.json")
        if path.is_file()
    )


def _find_prior_revision(
    root: Path,
    *,
    ticker: str,
    observed_on: str,
    current_raw_sha256: str,
    capture_contract_hash: str,
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for relpath in _receipt_relpaths(root):
        receipt = _read_receipt(root, relpath)
        artifact = receipt["artifact"]
        if receipt.get("capture_contract_hash") != capture_contract_hash:
            raise ProspectiveCaptureError("RECEIPT_CAPTURE_CONTRACT_HASH_MISMATCH")
        if (
            receipt.get("ticker") == ticker
            and receipt.get("observed_on") == observed_on
            and artifact.get("sha256") != current_raw_sha256
        ):
            first_seen = _timestamp_ms(
                artifact.get("first_seen_at_ms"),
                "RECEIPT_FIRST_SEEN_INVALID",
            )
            candidates.append((first_seen, str(artifact.get("sha256"))))
    if not candidates:
        return None
    return max(candidates)[1]


def _write_receipt(
    root: Path,
    *,
    ticker: str,
    artifact: dict[str, Any],
    snapshot: dict[str, Any],
    capture_contract: dict[str, Any],
    adapter_contract: dict[str, Any],
    acquisition_contract: dict[str, Any],
    source_contract: dict[str, Any],
    walk_forward_protocol: dict[str, Any],
) -> dict[str, Any]:
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "capture_contract_hash": canonical_hash(capture_contract),
        "adapter_contract_hash": canonical_hash(adapter_contract),
        "acquisition_contract_hash": canonical_hash(acquisition_contract),
        "source_contract_hash": canonical_hash(source_contract),
        "walk_forward_protocol_hash": canonical_hash(walk_forward_protocol),
        "ticker": ticker,
        "observed_on": snapshot["observed_on"],
        "source_url": snapshot["source_url"],
        "artifact": artifact,
        "snapshot": snapshot,
        "mode": "SHADOW_ONLY",
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
    }
    return _cas_json(root, "capture_receipts", receipt)


def replay_capture_receipt(
    archive_root: str | Path,
    receipt_relpath: str,
    *,
    capture_contract: dict[str, Any] | None = None,
    adapter_contract: dict[str, Any] | None = None,
    acquisition_contract: dict[str, Any] | None = None,
    public_source_authority: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
    walk_forward_protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contracts = _resolved_contracts(
        capture_contract,
        adapter_contract,
        acquisition_contract,
        public_source_authority,
        source_contract,
        walk_forward_protocol,
    )
    capture, adapters, acquisition, _, sources, protocol = contracts
    root = Path(archive_root)
    receipt = _read_receipt(root, receipt_relpath)
    expected_hashes = {
        "capture_contract_hash": canonical_hash(capture),
        "adapter_contract_hash": canonical_hash(adapters),
        "acquisition_contract_hash": canonical_hash(acquisition),
        "source_contract_hash": canonical_hash(sources),
        "walk_forward_protocol_hash": canonical_hash(protocol),
    }
    if any(receipt.get(field) != value for field, value in expected_hashes.items()):
        raise ProspectiveCaptureError("RECEIPT_PARENT_HASH_MISMATCH")
    artifact = receipt["artifact"]
    stored_snapshot = receipt["snapshot"]
    raw_path = _safe_path(
        root,
        str(artifact.get("archive_relpath")),
        "RAW_ARCHIVE_PATH_INVALID",
    )
    replayed = issuer_adapters.parse_issuer_snapshot(
        str(receipt.get("ticker")),
        raw_path.read_bytes(),
        source_url=str(stored_snapshot.get("source_url")),
        content_type=str(artifact.get("content_type")),
        first_seen_at_ms=_timestamp_ms(
            artifact.get("first_seen_at_ms"),
            "RECEIPT_FIRST_SEEN_INVALID",
        ),
        evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
        contract=adapters,
    )
    if replayed != stored_snapshot:
        raise ProspectiveCaptureError("OFFLINE_REPLAY_SNAPSHOT_MISMATCH")
    return replayed


def _run_report_base(
    *,
    now_ms: int,
    decision: dict[str, Any],
    capture_contract: dict[str, Any],
    adapter_contract: dict[str, Any],
    acquisition_contract: dict[str, Any],
    source_contract: dict[str, Any],
    walk_forward_protocol: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": RUN_REPORT_SCHEMA_VERSION,
        "run_at_ms": now_ms,
        "decision": decision,
        "capture_contract_hash": canonical_hash(capture_contract),
        "adapter_contract_hash": canonical_hash(adapter_contract),
        "acquisition_contract_hash": canonical_hash(acquisition_contract),
        "source_contract_hash": canonical_hash(source_contract),
        "walk_forward_protocol_hash": canonical_hash(walk_forward_protocol),
        "mode": "SHADOW_ONLY",
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "historical_backfill_authority": "NONE",
        "historical_dataset_ready": False,
        "prior_value_carry_forward": False,
    }


def _write_run_report(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    reference = _cas_json(root, "capture_runs", report)
    return {**report, "run_report": reference}


def run_capture_cycle(
    archive_root: str | Path,
    *,
    capture_contract: dict[str, Any] | None = None,
    adapter_contract: dict[str, Any] | None = None,
    acquisition_contract: dict[str, Any] | None = None,
    public_source_authority: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
    walk_forward_protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contracts = _resolved_contracts(
        capture_contract,
        adapter_contract,
        acquisition_contract,
        public_source_authority,
        source_contract,
        walk_forward_protocol,
    )
    capture, adapters, acquisition, authority, sources, protocol = contracts
    root = Path(archive_root)
    root.mkdir(parents=True, exist_ok=True)
    run_at = int(time.time() * 1_000)
    decision = capture_decision(run_at, capture)
    report = _run_report_base(
        now_ms=run_at,
        decision=decision,
        capture_contract=capture,
        adapter_contract=adapters,
        acquisition_contract=acquisition,
        source_contract=sources,
        walk_forward_protocol=protocol,
    )
    decision_states = {
        "MARKET_CLOSED": "MARKET_CLOSED_NO_CAPTURE",
        "NOT_DUE": "NOT_DUE_NO_CAPTURE",
        "CALENDAR_OUT_OF_RANGE": "BLOCKED_CALENDAR_OUT_OF_RANGE",
    }
    if decision["state"] != "CAPTURE_DUE":
        report.update(
            {
                "state": decision_states[decision["state"]],
                "ticker_results": {},
                "captured_count": 0,
                "retry_required_count": 0,
                "blocked_count": 0,
                "manifest": None,
            }
        )
        return _write_run_report(root, report)

    transport = capture["transport"]
    timeout_s = int(transport["timeout_seconds"])
    max_bytes = int(transport["max_response_bytes"])
    allowed_types = set(transport["allowed_content_types"])
    profiles = _profile_map(adapters)
    results: dict[str, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []

    for ticker in READY_TICKERS:
        profile = profiles[ticker]
        source_url = str(profile.get("official_product_url"))
        try:
            response = fetch_official_bytes(
                ticker=ticker,
                url=source_url,
                timeout_s=timeout_s,
                max_bytes=max_bytes,
            )
            validated = _validated_response(
                response,
                expected_url=source_url,
                run_at_ms=run_at,
                allowed_content_types=allowed_types,
                max_bytes=max_bytes,
            )
        except ProspectiveCaptureError as exc:
            results[ticker] = {
                "state": "FETCH_FAILED_RETRY_REQUIRED",
                "error": str(exc),
                "source_url": source_url,
            }
            continue
        except Exception as exc:
            results[ticker] = {
                "state": "FETCH_FAILED_RETRY_REQUIRED",
                "error": f"FETCHER_EXCEPTION_{type(exc).__name__.upper()}",
                "source_url": source_url,
            }
            continue

        staged = _stage_raw(root, validated["body"])
        try:
            existing = _load_existing_identity(
                root,
                source_url=source_url,
                digest=staged["sha256"],
            )
            first_seen = (
                int(existing["first_seen_at_ms"])
                if existing is not None
                else validated["retrieved_at_ms"]
            )
            snapshot = issuer_adapters.parse_issuer_snapshot(
                ticker,
                validated["body"],
                source_url=source_url,
                content_type=validated["content_type"],
                first_seen_at_ms=first_seen,
                evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
                contract=adapters,
            )
        except issuer_adapters.IssuerAdapterError as exc:
            state = (
                "FUTURE_SOURCE_DATE_BLOCKED"
                if str(exc) == "FIRST_SEEN_BEFORE_OBSERVATION"
                else "PARSE_FAILED_RETRY_REQUIRED"
            )
            results[ticker] = {
                "state": state,
                "error": str(exc),
                "source_url": source_url,
                "staged_raw": staged,
            }
            continue
        except ProspectiveCaptureError as exc:
            results[ticker] = {
                "state": "ARCHIVE_VALIDATION_BLOCKED",
                "error": str(exc),
                "source_url": source_url,
                "staged_raw": staged,
            }
            continue

        expected_date = decision["expected_session_date"]
        if snapshot["observed_on"] < expected_date:
            results[ticker] = {
                "state": "STALE_SOURCE_RETRY_REQUIRED",
                "error": "OBSERVED_SESSION_PRECEDES_EXPECTED_SESSION",
                "source_url": source_url,
                "observed_on": snapshot["observed_on"],
                "expected_session_date": expected_date,
                "staged_raw": staged,
            }
            continue
        if snapshot["observed_on"] > expected_date:
            results[ticker] = {
                "state": "FUTURE_SOURCE_DATE_BLOCKED",
                "error": "OBSERVED_SESSION_FOLLOWS_EXPECTED_SESSION",
                "source_url": source_url,
                "observed_on": snapshot["observed_on"],
                "expected_session_date": expected_date,
                "staged_raw": staged,
            }
            continue

        try:
            previous_revision = _find_prior_revision(
                root,
                ticker=ticker,
                observed_on=snapshot["observed_on"],
                current_raw_sha256=staged["sha256"],
                capture_contract_hash=canonical_hash(capture),
            )
            metadata = issuer_adapters.build_acquisition_metadata(
                snapshot,
                public_source_authority_hash=capture["public_source_authority_hash"],
                content_type=validated["content_type"],
            )
            metadata["retrieved_at_ms"] = validated["retrieved_at_ms"]
            metadata["revision_of_sha256"] = previous_revision
            artifact = candidate_acquisition.archive_artifact(
                root,
                validated["body"],
                **metadata,
            )
            if artifact["sha256"] != staged["sha256"]:
                raise ProspectiveCaptureError("STAGED_RAW_ARTIFACT_MISMATCH")
            receipt = _write_receipt(
                root,
                ticker=ticker,
                artifact=artifact,
                snapshot=snapshot,
                capture_contract=capture,
                adapter_contract=adapters,
                acquisition_contract=acquisition,
                source_contract=sources,
                walk_forward_protocol=protocol,
            )
        except (ProspectiveCaptureError, candidate_acquisition.AcquisitionError) as exc:
            results[ticker] = {
                "state": "ARCHIVE_VALIDATION_BLOCKED",
                "error": str(exc),
                "source_url": source_url,
                "staged_raw": staged,
            }
            continue

        artifacts.append(artifact)
        results[ticker] = {
            "state": "CAPTURED",
            "source_url": source_url,
            "staged_raw": staged,
            "artifact": artifact,
            "snapshot": snapshot,
            "receipt": receipt,
        }

    manifest_reference: dict[str, Any] | None = None
    if artifacts:
        manifest = candidate_acquisition.build_dataset_manifest(
            artifacts,
            candidate_registry_hash=capture["candidate_registry_hash"],
            public_source_authority_hash=canonical_hash(authority),
            acquisition_contract_hash=canonical_hash(acquisition),
            source_contract_hash=canonical_hash(sources),
            created_at_ms=run_at,
        )
        manifest_errors = candidate_acquisition.validate_dataset_manifest(
            manifest,
            archive_root=root,
            required_source_contract_ids={SOURCE_CONTRACT_ID},
        )
        if manifest_errors:
            raise ProspectiveCaptureError(
                "CAPTURE_MANIFEST_INVALID: " + "; ".join(manifest_errors)
            )
        manifest_path = candidate_acquisition.write_manifest_immutable(root, manifest)
        manifest_reference = {
            "sha256": manifest["manifest_sha256"],
            "relpath": manifest_path.relative_to(root).as_posix(),
        }

    captured_count = sum(item["state"] == "CAPTURED" for item in results.values())
    retry_states = {
        "FETCH_FAILED_RETRY_REQUIRED",
        "PARSE_FAILED_RETRY_REQUIRED",
        "STALE_SOURCE_RETRY_REQUIRED",
    }
    blocked_states = {
        "FUTURE_SOURCE_DATE_BLOCKED",
        "ARCHIVE_VALIDATION_BLOCKED",
    }
    retry_count = sum(item["state"] in retry_states for item in results.values())
    blocked_count = sum(item["state"] in blocked_states for item in results.values())
    if captured_count == len(READY_TICKERS):
        state = "COMPLETE_SHADOW_CAPTURE"
    elif blocked_count and captured_count:
        state = "PARTIAL_BLOCKED"
    elif blocked_count:
        state = "BLOCKED_NO_VALID_CAPTURE"
    elif captured_count:
        state = "PARTIAL_RETRY_REQUIRED"
    else:
        state = "RETRY_REQUIRED_NO_VALID_CAPTURE"
    report.update(
        {
            "state": state,
            "ticker_results": results,
            "captured_count": captured_count,
            "retry_required_count": retry_count,
            "blocked_count": blocked_count,
            "manifest": manifest_reference,
        }
    )
    return _write_run_report(root, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one read-only US spot Bitcoin ETP prospective shadow capture cycle."
    )
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_capture_cycle(args.archive_root)
    except ProspectiveCaptureError as exc:
        print(json.dumps({"state": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["state"] in {
        "COMPLETE_SHADOW_CAPTURE",
        "MARKET_CLOSED_NO_CAPTURE",
        "NOT_DUE_NO_CAPTURE",
    } else 2


if __name__ == "__main__":
    sys.exit(main())
