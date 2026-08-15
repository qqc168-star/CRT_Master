#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DEFAULT_ADAPTER_CONTRACT = ROOT / "CRT_ETP_ISSUER_ADAPTER_CONTRACT_V0.1.json"
SOURCE_CONTRACT_ID = "US_SPOT_BTC_ETP_POINT_IN_TIME"
SNAPSHOT_SCHEMA_VERSION = "CRT_ETP_ISSUER_NORMALIZED_SNAPSHOT_V0.1"
CONTRACT_SCHEMA_VERSION = "CRT_ETP_ISSUER_ADAPTER_CONTRACT_V0.1"
CONTRACT_STATUS = "ADAPTER_PROFILES_IMPLEMENTED_CAPTURE_NOT_STARTED_SURFACES_PARTIAL"
EXPECTED_CONTRACT_SEMANTIC_SHA256 = (
    "89bb83ad892929db1c212fe278fe56abeb23d13e18c2ead138eed42592a771f1"
)
ALLOWED_CONTENT_TYPES = {"text/html", "text/plain"}
ALLOWED_EVIDENCE_CLASSES = {"CURRENT_FIRST_SEEN_CAPTURE", "SYNTHETIC_FIXTURE"}
PROVEN_TICKERS = {"IBIT", "BITB", "ARKB", "HODL", "GBTC", "BTC"}
REQUIRED_ALL_DATE_PATTERN_TICKERS = {"BITB", "ARKB"}
BLOCKED_SURFACE_STATES = {
    "FBTC": "CROSS_OFFICIAL_SURFACE_DAILY_ALIGNMENT_NOT_PROVEN",
    "BTCO": "REQUIRED_NAV_AND_SHARES_NOT_PROVEN_ON_STATIC_SURFACE",
    "EZBC": "NET_ASSETS_ONLY_ABBREVIATED_ON_VISIBLE_SURFACE",
    "BRRR": "SHARES_OUTSTANDING_NOT_PRESENT_ON_VISIBLE_SURFACE",
    "BTCW": "NET_ASSETS_SEMANTIC_EQUIVALENCE_NOT_PROVEN",
    "MSBT": "REQUIRED_VALUES_NOT_PROVEN_ON_STATIC_SURFACE",
}
EXPECTED_SEC_IDENTITIES = {
    "IBIT": (
        "0001980994",
        "000143774925006260",
        "10-K",
        "https://www.sec.gov/Archives/edgar/data/1980994/000143774925006260/bit20241231_10k.htm",
    ),
    "FBTC": (
        "0001852317",
        "000119312524006077",
        "424B3",
        "https://www.sec.gov/Archives/edgar/data/1852317/000119312524006077/d375081d424b3.htm",
    ),
    "BITB": (
        "0001763415",
        "000199937124000346",
        "424B3",
        "https://www.sec.gov/Archives/edgar/data/1763415/000199937124000346/bitcoin-424b3_011024.htm",
    ),
    "ARKB": (
        "0001869699",
        "000119312524003823",
        "S-1/A",
        "https://www.sec.gov/Archives/edgar/data/1869699/000119312524003823/d549524ds1a.htm",
    ),
    "BTCO": (
        "0001855781",
        "000119312524003812",
        "S-1/A",
        "https://www.sec.gov/Archives/edgar/data/1855781/000119312524003812/d507893ds1a.htm",
    ),
    "EZBC": (
        "0001992870",
        "000113743924000039",
        "S-1/A",
        "https://www.sec.gov/Archives/edgar/data/1992870/000113743924000039/ftdhts1a01082024.htm",
    ),
    "BRRR": (
        "0001841175",
        "000199937126005527",
        "10-K",
        "https://www.sec.gov/Archives/edgar/data/1841175/000199937126005527/brrr_10k-123125.htm",
    ),
    "HODL": (
        "0001838028",
        "000093041324000073",
        "424B3",
        "https://www.sec.gov/Archives/edgar/data/1838028/000093041324000073/c106800_424b3.htm",
    ),
    "BTCW": (
        "0001850391",
        "000121465924000453",
        "S-1/A",
        "https://www.sec.gov/Archives/edgar/data/1850391/000121465924000453/wtb17241s1a7.htm",
    ),
    "GBTC": (
        "0001588489",
        "000095017025029408",
        "10-K",
        "https://www.sec.gov/Archives/edgar/data/1588489/000095017025029408/gbtc-20241231.htm",
    ),
    "BTC": (
        "0002015034",
        "000095017025029405",
        "10-K",
        "https://www.sec.gov/Archives/edgar/data/2015034/000095017025029405/btc-20241231.htm",
    ),
    "MSBT": (
        "0002103612",
        "000110465926039992",
        "424B3",
        "https://www.sec.gov/Archives/edgar/data/2103612/000110465926039992/tm2534140-20_424b3.htm",
    ),
}
DATE_PATTERN = (
    r"(?:[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{4}-\d{2}-\d{2})"
)
NUMBER_SUFFIX_PATTERN = r"(?:THOUSAND|MILLION|BILLION|BN|MM|MN|K|M|B)"
NUMBER_PATTERN = (
    r"(?:USD\s*)?(?:\$\s*){0,2}\(?[-+]?[0-9][0-9,]*(?:\.[0-9]+)?\)?"
    rf"(?:\s*{NUMBER_SUFFIX_PATTERN}\b|(?!\s*{NUMBER_SUFFIX_PATTERN}\b)(?![\w.,]))"
)
FIELD_CODES = {
    "nav_per_share": "NAV_PER_SHARE",
    "net_assets": "NET_ASSETS",
    "raw_shares_outstanding": "RAW_SHARES_OUTSTANDING",
}


class IssuerAdapterError(ValueError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self._suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"} and self._suppressed_depth:
            self._suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed_depth and data.strip():
            self.parts.append(data)


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


def _contract_semantic_hash(contract: dict[str, Any]) -> str:
    payload = dict(contract)
    payload.pop("implementation_sha256", None)
    return canonical_hash(payload)


def _require_embedded_contract(contract: dict[str, Any]) -> None:
    if (
        contract.get("schema_version") != CONTRACT_SCHEMA_VERSION
        or contract.get("contract_id")
        != "CRT-ETP-ISSUER-ADAPTER-CONTRACT-V0.1"
        or contract.get("status") != CONTRACT_STATUS
    ):
        raise IssuerAdapterError("ADAPTER_CONTRACT_IDENTITY_INVALID")
    if _contract_semantic_hash(contract) != EXPECTED_CONTRACT_SEMANTIC_SHA256:
        raise IssuerAdapterError("ADAPTER_CONTRACT_SEMANTIC_HASH_MISMATCH")
    if contract.get("implementation_sha256") != sha256_bytes(Path(__file__).read_bytes()):
        raise IssuerAdapterError("ADAPTER_IMPLEMENTATION_HASH_MISMATCH")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IssuerAdapterError("JSON_ROOT_NOT_OBJECT")
    return value


def _visible_text(raw_bytes: bytes, content_type: str) -> str:
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise IssuerAdapterError("RAW_BYTES_REQUIRED")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise IssuerAdapterError("CONTENT_TYPE_NOT_SUPPORTED")
    try:
        decoded = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IssuerAdapterError("RAW_BYTES_NOT_UTF8") from exc
    if content_type == "text/html":
        parser = _VisibleTextParser()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as exc:
            raise IssuerAdapterError("HTML_PARSE_FAILED") from exc
        decoded = "\n".join(parser.parts)
    decoded = html.unescape(decoded).replace("\u00a0", " ")
    decoded = re.sub(r"[ \t\f\v]+", " ", decoded)
    decoded = re.sub(r"\s*\n\s*", "\n", decoded)
    return decoded.strip()


def _compile_pattern(template: Any) -> re.Pattern[str]:
    if not isinstance(template, str) or not template:
        raise IssuerAdapterError("ADAPTER_PATTERN_INVALID")
    expanded = template.replace("{DATE}", f"(?P<date>{DATE_PATTERN})")
    expanded = expanded.replace("{NUMBER}", f"(?P<value>{NUMBER_PATTERN})")
    try:
        compiled = re.compile(expanded, flags=re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        raise IssuerAdapterError("ADAPTER_PATTERN_INVALID") from exc
    return compiled


def _parse_date(raw: str) -> date:
    value = re.sub(r"\s+", " ", raw.strip())
    formats = (
        "%b %d, %Y",
        "%B %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    )
    for format_string in formats:
        try:
            return datetime.strptime(value, format_string).date()
        except ValueError:
            continue
    raise IssuerAdapterError("SNAPSHOT_DATE_INVALID")


def _parse_decimal(raw: str, *, allow_abbreviated: bool, scale: Decimal, code: str) -> Decimal:
    value = raw.strip().upper().replace("USD", "").replace("$", "").replace(",", "")
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("() ")
    suffix_scale = Decimal(1)
    suffixes = {
        "THOUSAND": Decimal(1_000),
        "MILLION": Decimal(1_000_000),
        "BILLION": Decimal(1_000_000_000),
        "BN": Decimal(1_000_000_000),
        "MM": Decimal(1_000_000),
        "MN": Decimal(1_000_000),
        "K": Decimal(1_000),
        "M": Decimal(1_000_000),
        "B": Decimal(1_000_000_000),
    }
    suffix = next((item for item in suffixes if value.endswith(item)), None)
    if suffix is not None:
        if not allow_abbreviated:
            raise IssuerAdapterError(f"{code}_ABBREVIATED_FORBIDDEN")
        suffix_scale = suffixes[suffix]
        value = value[: -len(suffix)].strip()
    try:
        result = Decimal(value) * suffix_scale * scale
    except InvalidOperation as exc:
        raise IssuerAdapterError(f"{code}_VALUE_INVALID") from exc
    if negative:
        result = -result
    if not result.is_finite():
        raise IssuerAdapterError(f"{code}_VALUE_INVALID")
    return result


def _profile_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = contract.get("issuer_profiles")
    if not isinstance(profiles, list):
        raise IssuerAdapterError("ADAPTER_PROFILES_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for item in profiles:
        if not isinstance(item, dict) or not isinstance(item.get("ticker"), str):
            raise IssuerAdapterError("ADAPTER_PROFILE_INVALID")
        ticker = item["ticker"]
        if ticker in result:
            raise IssuerAdapterError("ADAPTER_PROFILE_DUPLICATE")
        result[ticker] = item
    return result


def _extract_snapshot_date(text: str, profile: dict[str, Any]) -> date:
    patterns = profile.get("snapshot_date_patterns")
    if not isinstance(patterns, list) or not patterns:
        raise IssuerAdapterError("SNAPSHOT_DATE_PATTERN_MISSING")
    require_all = profile.get("require_all_snapshot_date_patterns", False)
    if not isinstance(require_all, bool):
        raise IssuerAdapterError("SNAPSHOT_DATE_POLICY_INVALID")
    values: set[date] = set()
    for template in patterns:
        pattern_values: set[date] = set()
        for match in _compile_pattern(template).finditer(text):
            raw = match.groupdict().get("date")
            if raw:
                pattern_values.add(_parse_date(raw))
        if require_all and not pattern_values:
            raise IssuerAdapterError("SNAPSHOT_DATE_REQUIRED_PATTERN_MISSING")
        values.update(pattern_values)
    if not values:
        raise IssuerAdapterError("SNAPSHOT_DATE_MISSING")
    if len(values) != 1:
        raise IssuerAdapterError("SNAPSHOT_DATE_AMBIGUOUS")
    return next(iter(values))


def _extract_field(
    text: str,
    *,
    field_id: str,
    rule: dict[str, Any],
    snapshot_date: date,
) -> tuple[Decimal, dict[str, Any]]:
    code = FIELD_CODES[field_id]
    patterns = rule.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise IssuerAdapterError(f"{code}_PATTERN_MISSING")
    allow_abbreviated = rule.get("allow_abbreviated") is True
    try:
        scale = Decimal(str(rule.get("scale", "1")))
    except InvalidOperation as exc:
        raise IssuerAdapterError(f"{code}_SCALE_INVALID") from exc
    if not scale.is_finite() or scale <= 0:
        raise IssuerAdapterError(f"{code}_SCALE_INVALID")

    matches: list[tuple[Decimal, date | None, str, int]] = []
    for pattern_index, template in enumerate(patterns):
        for match in _compile_pattern(template).finditer(text):
            groups = match.groupdict()
            raw_value = groups.get("value")
            if not raw_value:
                continue
            value = _parse_decimal(
                raw_value,
                allow_abbreviated=allow_abbreviated,
                scale=scale,
                code=code,
            )
            matched_date = _parse_date(groups["date"]) if groups.get("date") else None
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            matches.append((value, matched_date, evidence[:300], pattern_index))
    if not matches:
        raise IssuerAdapterError(f"{code}_MISSING")

    unique = {(value, matched_date) for value, matched_date, _, _ in matches}
    if len(unique) != 1:
        raise IssuerAdapterError(f"{code}_AMBIGUOUS")
    value, matched_date = next(iter(unique))
    if matched_date is not None and matched_date != snapshot_date:
        raise IssuerAdapterError("FIELD_DATE_MISMATCH")
    if field_id in {"nav_per_share", "net_assets"} and value <= 0:
        raise IssuerAdapterError(f"{code}_NONPOSITIVE")
    if field_id == "raw_shares_outstanding":
        if value < 0:
            raise IssuerAdapterError("RAW_SHARES_OUTSTANDING_NEGATIVE")
        if value != value.to_integral_value():
            raise IssuerAdapterError("RAW_SHARES_OUTSTANDING_NOT_INTEGER")
    first = matches[0]
    return value, {
        "matched_text": first[2],
        "matched_date": snapshot_date.isoformat(),
        "pattern_index": first[3],
        "derived": False,
    }


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _observed_at_ms(observed_on: date) -> int:
    close = datetime.combine(observed_on, time(hour=16), tzinfo=ZoneInfo("America/New_York"))
    return int(close.astimezone(timezone.utc).timestamp() * 1_000)


def _split_adjustments(
    raw_shares: Decimal,
    raw_nav: Decimal,
    *,
    observed_on: date,
    profile: dict[str, Any],
) -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    adjusted_shares = raw_shares
    adjusted_nav = raw_nav
    applied: list[dict[str, Any]] = []
    events = profile.get("split_events", [])
    if not isinstance(events, list):
        raise IssuerAdapterError("SPLIT_LEDGER_INVALID")
    for item in sorted(events, key=lambda value: str(value.get("effective_on"))):
        if not isinstance(item, dict):
            raise IssuerAdapterError("SPLIT_LEDGER_INVALID")
        effective_on = _parse_date(str(item.get("effective_on")))
        numerator = item.get("numerator")
        denominator = item.get("denominator")
        if (
            isinstance(numerator, bool)
            or isinstance(denominator, bool)
            or not isinstance(numerator, int)
            or not isinstance(denominator, int)
            or numerator <= 0
            or denominator <= 0
        ):
            raise IssuerAdapterError("SPLIT_LEDGER_RATIO_INVALID")
        if effective_on > observed_on:
            adjusted_shares = (
                adjusted_shares * Decimal(numerator) / Decimal(denominator)
            )
            adjusted_nav = adjusted_nav * Decimal(denominator) / Decimal(numerator)
            applied.append(
                {
                    "effective_on": effective_on.isoformat(),
                    "numerator": numerator,
                    "denominator": denominator,
                    "event": item.get("event"),
                }
            )
    return adjusted_shares, adjusted_nav, applied


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = dict(snapshot)
    payload.pop("snapshot_sha256", None)
    return canonical_hash(payload)


def parse_issuer_snapshot(
    ticker: str,
    raw_bytes: bytes,
    *,
    source_url: str,
    content_type: str,
    first_seen_at_ms: int,
    evidence_class: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if contract is None:
        contract = load_json(DEFAULT_ADAPTER_CONTRACT)
    _require_embedded_contract(contract)
    profiles = _profile_map(contract)
    if ticker not in profiles:
        raise IssuerAdapterError("TICKER_NOT_LOCKED")
    profile = profiles[ticker]
    if source_url != profile.get("official_product_url"):
        raise IssuerAdapterError("SOURCE_URL_NOT_LOCKED")
    if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
        raise IssuerAdapterError("EVIDENCE_CLASS_NOT_SUPPORTED")
    if (
        evidence_class == "CURRENT_FIRST_SEEN_CAPTURE"
        and profile.get("surface_probe_state") != "CURRENT_REQUIRED_FIELDS_PROVEN"
    ):
        raise IssuerAdapterError("CURRENT_SURFACE_NOT_PROVEN")
    if isinstance(first_seen_at_ms, bool) or not isinstance(first_seen_at_ms, int):
        raise IssuerAdapterError("FIRST_SEEN_AT_INVALID")
    if first_seen_at_ms < 0:
        raise IssuerAdapterError("FIRST_SEEN_AT_INVALID")

    text = _visible_text(raw_bytes, content_type)
    markers = profile.get("identity_markers")
    if not isinstance(markers, list) or len(markers) < 2:
        raise IssuerAdapterError("IDENTITY_MARKERS_INVALID")
    folded = text.casefold()
    ticker_present = ticker.casefold() in folded
    named_marker_present = any(
        isinstance(marker, str) and marker.casefold() in folded
        for marker in markers
        if marker != ticker
    )
    if not ticker_present or not named_marker_present:
        raise IssuerAdapterError("ISSUER_IDENTITY_MISMATCH")

    observed_on = _extract_snapshot_date(text, profile)
    if observed_on.weekday() >= 5:
        raise IssuerAdapterError("OBSERVATION_DATE_NOT_WEEKDAY")
    try:
        membership_start = date.fromisoformat(str(profile.get("membership_effective_from")))
    except ValueError as exc:
        raise IssuerAdapterError("MEMBERSHIP_EFFECTIVE_DATE_INVALID") from exc
    if observed_on < membership_start:
        raise IssuerAdapterError("OBSERVATION_PRECEDES_MEMBERSHIP")
    observed_at_ms = _observed_at_ms(observed_on)
    if first_seen_at_ms < observed_at_ms:
        raise IssuerAdapterError("FIRST_SEEN_BEFORE_OBSERVATION")

    rules = profile.get("field_rules")
    if not isinstance(rules, dict) or set(rules) != set(FIELD_CODES):
        raise IssuerAdapterError("FIELD_RULES_INVALID")
    values: dict[str, Decimal] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for field_id in FIELD_CODES:
        value, field_evidence = _extract_field(
            text,
            field_id=field_id,
            rule=rules[field_id],
            snapshot_date=observed_on,
        )
        values[field_id] = value
        evidence[field_id] = field_evidence

    adjusted_shares, adjusted_nav, applied_splits = _split_adjustments(
        values["raw_shares_outstanding"],
        values["nav_per_share"],
        observed_on=observed_on,
        profile=profile,
    )
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source_contract_id": SOURCE_CONTRACT_ID,
        "adapter_contract_hash": canonical_hash(contract),
        "adapter_id": profile.get("adapter_id"),
        "fund_id": ticker,
        "issuer_label": profile.get("issuer_label"),
        "source_url": source_url,
        "content_type": content_type,
        "sec_identity": profile.get("sec_identity"),
        "observed_on": observed_on.isoformat(),
        "observed_at_ms": observed_at_ms,
        "published_at_ms": first_seen_at_ms,
        "available_at_ms": first_seen_at_ms,
        "first_seen_at_ms": first_seen_at_ms,
        "publication_time_semantics": "LOCAL_FIRST_SEEN_WHEN_ISSUER_TIMESTAMP_ABSENT",
        "availability_proof_type": "LOCAL_FIRST_SEEN_CAPTURE",
        "capture_scope": "PROSPECTIVE_ONLY_FROM_FIRST_SEEN",
        "historical_backfill_authority": "NONE",
        "evidence_class": evidence_class,
        "replay_eligible": evidence_class == "CURRENT_FIRST_SEEN_CAPTURE",
        "raw_snapshot_sha256": sha256_bytes(raw_bytes),
        "raw_nav_per_share": _json_number(values["nav_per_share"]),
        "nav_per_share": _json_number(adjusted_nav),
        "net_assets": _json_number(values["net_assets"]),
        "raw_shares_outstanding": _json_number(values["raw_shares_outstanding"]),
        "adjusted_shares_outstanding": _json_number(adjusted_shares),
        "split_adjustments_applied": applied_splits,
        "split_normalization_policy": "SHARES_AND_NAV_RECIPROCAL_CURRENT_SHARE_BASIS",
        "field_evidence": evidence,
        "field_derivation_policy": "NO_REQUIRED_SOURCE_FIELD_DERIVATION_SPLIT_NORMALIZATION_ONLY",
        "license_classification": contract.get("license_classification"),
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }
    snapshot["snapshot_sha256"] = snapshot_hash(snapshot)
    return snapshot


def build_acquisition_metadata(
    snapshot: dict[str, Any],
    *,
    public_source_authority_hash: str,
    content_type: str,
) -> dict[str, Any]:
    contract = load_json(DEFAULT_ADAPTER_CONTRACT)
    _require_embedded_contract(contract)
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise IssuerAdapterError("SNAPSHOT_SCHEMA_INVALID")
    if snapshot.get("snapshot_sha256") != snapshot_hash(snapshot):
        raise IssuerAdapterError("SNAPSHOT_HASH_INVALID")
    if snapshot.get("adapter_contract_hash") != canonical_hash(contract):
        raise IssuerAdapterError("SNAPSHOT_ADAPTER_CONTRACT_HASH_MISMATCH")
    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }
    if any(snapshot.get(key) != value for key, value in expected_authority.items()):
        raise IssuerAdapterError("SNAPSHOT_AUTHORITY_INVALID")
    if not _is_sha256(public_source_authority_hash):
        raise IssuerAdapterError("PUBLIC_SOURCE_AUTHORITY_HASH_INVALID")
    if content_type not in ALLOWED_CONTENT_TYPES or snapshot.get("content_type") != content_type:
        raise IssuerAdapterError("CONTENT_TYPE_MISMATCH")
    first_seen = snapshot.get("first_seen_at_ms")
    if isinstance(first_seen, bool) or not isinstance(first_seen, int) or first_seen < 0:
        raise IssuerAdapterError("FIRST_SEEN_AT_INVALID")
    evidence_class = snapshot.get("evidence_class")
    if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
        raise IssuerAdapterError("EVIDENCE_CLASS_NOT_SUPPORTED")
    replay_eligible = evidence_class == "CURRENT_FIRST_SEEN_CAPTURE"
    if evidence_class == "SYNTHETIC_FIXTURE":
        replay_eligible = False
    return {
        "source_contract_id": SOURCE_CONTRACT_ID,
        "request_identity": f'GET {snapshot.get("source_url")}',
        "retrieved_at_ms": first_seen,
        "first_seen_at_ms": first_seen,
        "available_at_coverage_start_ms": first_seen,
        "available_at_coverage_end_ms": first_seen,
        "integrity_proof_type": "LOCAL_FIRST_SEEN_SHA256",
        "provider_checksum": None,
        "license_classification": snapshot.get("license_classification"),
        "source_authority_hash": public_source_authority_hash,
        "evidence_class": evidence_class,
        "replay_eligible": replay_eligible,
        "content_type": content_type,
        "availability_proof_type": "LOCAL_FIRST_SEEN_CAPTURE",
        "revision_of_sha256": None,
    }


def validate_adapter_contract(
    contract: dict[str, Any],
    *,
    public_source_authority: dict[str, Any],
    etp_feasibility: dict[str, Any],
    acquisition_contract: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        errors.append("adapter contract schema_version mismatch")
    if contract.get("contract_id") != "CRT-ETP-ISSUER-ADAPTER-CONTRACT-V0.1":
        errors.append("adapter contract id mismatch")
    if contract.get("status") != CONTRACT_STATUS:
        errors.append("adapter contract status mismatch")
    if contract.get("public_source_authority_hash") != canonical_hash(
        public_source_authority
    ):
        errors.append("adapter contract public source authority hash mismatch")
    if contract.get("etp_replay_feasibility_hash") != canonical_hash(etp_feasibility):
        errors.append("adapter contract ETP feasibility hash mismatch")
    if contract.get("acquisition_contract_hash") != canonical_hash(acquisition_contract):
        errors.append("adapter contract acquisition hash mismatch")
    if contract.get("implementation_sha256") != sha256_bytes(Path(__file__).read_bytes()):
        errors.append("adapter contract implementation hash mismatch")
    if _contract_semantic_hash(contract) != EXPECTED_CONTRACT_SEMANTIC_SHA256:
        errors.append("adapter contract semantic hash mismatch")

    if contract.get("network_fetch_implemented") is not False:
        errors.append("adapter contract network fetch must remain false")
    if contract.get("raw_dataset_acquired") is not False:
        errors.append("adapter contract raw dataset must remain false")
    if contract.get("dataset_readiness_granted") is not False:
        errors.append("adapter contract dataset readiness must remain false")
    if contract.get("historical_backfill_state") != "BLOCKED_NOT_PROVEN":
        errors.append("adapter contract historical backfill must remain blocked")
    if contract.get("sec_identity_state") != "ALL_TWELVE_BOUND_TO_OFFICIAL_SEC_FILINGS":
        errors.append("adapter contract SEC identity state mismatch")
    if contract.get("adapter_profile_state") != "ALL_TWELVE_IMPLEMENTED_OFFLINE":
        errors.append("adapter contract profile state mismatch")

    authority = contract.get("authority")
    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }
    if not isinstance(authority, dict):
        errors.append("adapter contract authority invalid")
    else:
        for key, expected in expected_authority.items():
            if authority.get(key) != expected:
                errors.append(f"adapter contract authority.{key} drift")

    authority_members = public_source_authority.get("decisions", {}).get(
        "US_SPOT_BTC_ETP_POINT_IN_TIME", {}
    ).get("universe", {}).get("members", [])
    expected_members = {
        item.get("ticker"): item for item in authority_members if isinstance(item, dict)
    }
    try:
        profiles = _profile_map(contract)
    except IssuerAdapterError:
        profiles = {}
        errors.append("adapter contract profiles invalid")
    if set(profiles) != set(EXPECTED_SEC_IDENTITIES) or set(profiles) != set(expected_members):
        errors.append("adapter contract ticker registry mismatch")
    for ticker, expected_identity in EXPECTED_SEC_IDENTITIES.items():
        profile = profiles.get(ticker, {})
        member = expected_members.get(ticker, {})
        if (
            profile.get("issuer_label") != member.get("issuer_label")
            or profile.get("membership_effective_from")
            != member.get("membership_effective_from")
            or profile.get("official_product_url") != member.get("official_product_url")
        ):
            errors.append(f"adapter contract profile {ticker} authority registry drift")
        identity = profile.get("sec_identity")
        actual_identity = (
            identity.get("cik") if isinstance(identity, dict) else None,
            identity.get("accession") if isinstance(identity, dict) else None,
            identity.get("form") if isinstance(identity, dict) else None,
            identity.get("url") if isinstance(identity, dict) else None,
        )
        if actual_identity != expected_identity:
            errors.append(f"adapter contract profile {ticker} SEC identity drift")
        markers = profile.get("identity_markers")
        if not isinstance(markers, list) or ticker not in markers or len(markers) < 2:
            errors.append(f"adapter contract profile {ticker} identity markers invalid")
        rules = profile.get("field_rules")
        if not isinstance(rules, dict) or set(rules) != set(FIELD_CODES):
            errors.append(f"adapter contract profile {ticker} field rules invalid")
        else:
            for field_id, rule in rules.items():
                patterns = rule.get("patterns") if isinstance(rule, dict) else None
                if not isinstance(patterns, list) or not patterns:
                    errors.append(
                        f"adapter contract profile {ticker} {field_id} patterns invalid"
                    )
                    continue
                try:
                    for pattern in patterns:
                        _compile_pattern(pattern)
                except IssuerAdapterError:
                    errors.append(
                        f"adapter contract profile {ticker} {field_id} patterns invalid"
                    )
        date_patterns = profile.get("snapshot_date_patterns")
        if not isinstance(date_patterns, list) or not date_patterns:
            errors.append(f"adapter contract profile {ticker} date patterns invalid")
        else:
            try:
                for pattern in date_patterns:
                    _compile_pattern(pattern)
            except IssuerAdapterError:
                errors.append(f"adapter contract profile {ticker} date patterns invalid")
        require_all_dates = profile.get("require_all_snapshot_date_patterns", False)
        if (
            not isinstance(require_all_dates, bool)
            or require_all_dates != (ticker in REQUIRED_ALL_DATE_PATTERN_TICKERS)
        ):
            errors.append(f"adapter contract profile {ticker} date policy invalid")

    btc_splits = profiles.get("BTC", {}).get("split_events")
    expected_btc_splits = [
        {
            "effective_on": "2024-11-19",
            "numerator": 1,
            "denominator": 5,
            "event": "1_FOR_5_REVERSE_SPLIT",
            "evidence_url": EXPECTED_SEC_IDENTITIES["BTC"][3],
        }
    ]
    if btc_splits != expected_btc_splits:
        errors.append("adapter contract BTC split ledger drift")
    for ticker, profile in profiles.items():
        if ticker != "BTC" and profile.get("split_events") != []:
            errors.append(f"adapter contract profile {ticker} unexpected split event")

    surface = contract.get("surface_probe_result")
    if not isinstance(surface, dict):
        errors.append("adapter contract surface result invalid")
    else:
        proven = surface.get("proven_tickers")
        blocked = surface.get("blocked_tickers")
        if (
            not isinstance(proven, list)
            or set(proven) != PROVEN_TICKERS
            or not isinstance(blocked, dict)
            or blocked != BLOCKED_SURFACE_STATES
            or set(proven) & set(blocked)
            or set(proven) | set(blocked) != set(EXPECTED_SEC_IDENTITIES)
        ):
            errors.append("adapter contract surface partition invalid")
    return errors
