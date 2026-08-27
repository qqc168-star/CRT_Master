from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any


ADAPTER_SCHEMA_VERSION = "CRT_STRATEGY_CAPITAL_FACT_ADAPTER_V0.1"
SOURCE_ID = "STRATEGY_OFFICIAL_CAPITAL_DISCLOSURE"
ISSUER_ID = "CIK-0001050446"
MSTR_SECURITY_ID = "MSTR"
STRC_SECURITY_ID = "SEC-STRC-PERP"
EXTERNAL_ACTION_AUTHORITY = "NONE"
EMPTY_REASON = "VERIFIED_NO_MATCH"

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January", "February", "March", "April",
            "May", "June", "July", "August",
            "September", "October", "November", "December",
        ),
        start=1,
    )
}

_DATE_RE = (
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+"
    r"(\d{1,2}),\s+(20\d{2})"
)


class StrategyCapitalFactError(ValueError):
    pass


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def _plain(raw: str | bytes) -> tuple[str, bytes]:
    if isinstance(raw, bytes):
        raw_bytes = raw
        text = raw.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        text = raw
        raw_bytes = raw.encode("utf-8")
    else:
        raise StrategyCapitalFactError(
            "raw_document must be str or bytes"
        )

    parser = _TextParser()
    parser.feed(text)

    return (
        re.sub(r"\s+", " ", " ".join(parser.parts)).strip(),
        raw_bytes,
    )


def _validate_timestamp(value: int | None, name: str) -> None:
    if value is None:
        return
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise StrategyCapitalFactError(
            f"{name} must be a positive integer when supplied"
        )


def _source_ref(
    raw_bytes: bytes,
    *,
    document_id: str | None,
    accepted_at_ms: int | None,
    retrieved_at_ms: int | None,
) -> dict[str, Any]:
    digest = hashlib.sha256(raw_bytes).hexdigest()
    source_clock = accepted_at_ms or retrieved_at_ms or 1

    result: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "document_id": (
            document_id
            or f"DOC-STRATEGY-{digest[:20].upper()}"
        ),
        "source_as_of_ms": source_clock,
        "evidence_hash": digest,
    }

    if retrieved_at_ms is not None:
        result["retrieved_at_ms"] = retrieved_at_ms

    return result


def _scale_number(
    raw: str,
    scale: str | None = None,
) -> float:
    value = float(raw.replace(",", ""))

    if not scale:
        return value

    scale = scale.lower()

    if scale == "thousand":
        return value * 1_000.0
    if scale == "million":
        return value * 1_000_000.0
    if scale == "billion":
        return value * 1_000_000_000.0

    return value


def _scaled_match(
    patterns: tuple[str, ...],
    text: str,
) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if not match:
            continue

        return _scale_number(
            match.group("num"),
            match.groupdict().get("scale"),
        )

    return None


def _btc_holdings(text: str) -> float | None:
    return _scaled_match(
        (
            r"\b(?:holds|held)\s+(?:approximately\s+)?"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s*"
            r"bitcoins?\b",

            r"\bbitcoin holdings(?:\s+were|\s+was|\s+of|:)?\s*"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s*"
            r"bitcoins?\b",
        ),
        text,
    )


def _diluted_shares(text: str) -> float | None:
    return _scaled_match(
        (
            r"\b(?:fully\s+)?diluted shares(?: outstanding)?"
            r"(?:\s+were|\s+was|\s+of|:)?\s*"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",

            r"\bassumed diluted shares(?: outstanding)?"
            r"(?:\s+were|\s+was|\s+of|:)?\s*"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",
        ),
        text,
    )


def _atm_shares(text: str) -> float | None:
    return _scaled_match(
        (
            r"\b(?:at-the-market|ATM)\b.{0,220}?"
            r"\b(?:sold|issued)\s+"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s+shares\b",

            r"\b(?:sold|issued)\s+"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s+shares\b"
            r".{0,220}?\b(?:at-the-market|ATM)\b",
        ),
        text,
    )


def _strc_rate(text: str) -> float | None:
    patterns = (
        r"\bSTRC\b.{0,180}?"
        r"(?:annualized\s+)?(?:dividend|distribution)\s+rate"
        r"(?:\s+of|\s+is|:)?\s*"
        r"(?P<num>\d+(?:\.\d+)?)\s*%",

        r"(?:annualized\s+)?(?:dividend|distribution)\s+rate"
        r".{0,120}?\bSTRC\b.{0,80}?"
        r"(?P<num>\d+(?:\.\d+)?)\s*%",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group("num"))

    return None


def _date_to_ms(
    month: str,
    day: str,
    year: str,
) -> int:
    dt = datetime(
        int(year),
        _MONTHS[month.title()],
        int(day),
        tzinfo=timezone.utc,
    )
    return int(dt.timestamp() * 1000)


def _date_after(
    text: str,
    label_pattern: str,
) -> int | None:
    match = re.search(
        rf"{label_pattern}"
        rf"\s*(?:is|was|of|on|:|will be)?\s*"
        rf"{_DATE_RE}",
        text,
        re.I,
    )

    if not match:
        return None

    return _date_to_ms(
        match.group(1),
        match.group(2),
        match.group(3),
    )


def _as_of_ms(text: str) -> int | None:
    match = re.search(
        rf"\bas of\s+{_DATE_RE}",
        text,
        re.I,
    )

    if not match:
        return None

    return _date_to_ms(
        match.group(1),
        match.group(2),
        match.group(3),
    )


def _blocker(
    code: str,
    affected_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "scope": "FACT",
        "affected_ids": affected_ids,
        "reason": reason,
        "required_to_clear": [
            "supply an official Strategy disclosure "
            "that explicitly reports the missing fact"
        ],
    }


def _fact(
    *,
    fact_type: str,
    value: float | int,
    unit: str,
    security_id: str,
    effective_at_ms: int,
    source_ref: dict[str, Any],
) -> dict[str, Any]:
    suffix = source_ref["evidence_hash"][:16].upper()

    return {
        "fact_id": (
            f"FACT-{security_id}-{fact_type}-{suffix}"
        ),
        "issuer_id": ISSUER_ID,
        "security_id": security_id,
        "fact_type": fact_type,
        "value": value,
        "unit": unit,
        "effective_at_ms": effective_at_ms,
        "origin": "REPORTED",
        "source_ref": dict(source_ref),
        "quality_state": "VALID_REPORTED",
    }


def _result(
    *,
    facts: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    security_ids: list[str],
    source_ref: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    return {
        "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "action_output": "NONE",
        "issuer_facts": {
            "coverage_state": (
                "COMPLETE" if not blockers else "PARTIAL"
            ),
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": security_ids,
            },
            "items": facts,
        },
        "issuer_events": {
            "coverage_state": "PARTIAL",
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": security_ids,
            },
            "items": [],
        },
        "market_reaction_facts": {
            "coverage_state": "NOT_EVALUATED",
            "scope": {
                "security_ids": security_ids,
            },
            "items": [],
        },
        "reflexivity_blockers": {
            "coverage_state": "COMPLETE",
            "scope": {
                "overlay_id": "CRT-ISSUER-001",
            },
            "items": blockers,
            **(
                {"empty_reason": EMPTY_REASON}
                if not blockers
                else {}
            ),
        },
        "calculation_requests": [],
        "adapter_diagnostics": {
            "mode": mode,
            "source_id": SOURCE_ID,
            "document_id": source_ref["document_id"],
            "evidence_hash": source_ref["evidence_hash"],
            "issuer_event_routed_elsewhere": True,
            "market_reaction_intentionally_not_evaluated": True,
        },
    }


def build_strategy_capital_reflexivity_input(
    raw_document: str | bytes,
    *,
    mode: str,
    document_id: str | None = None,
    accepted_at_ms: int | None = None,
    retrieved_at_ms: int | None = None,
    require_atm: bool = False,
) -> dict[str, Any]:
    _validate_timestamp(accepted_at_ms, "accepted_at_ms")
    _validate_timestamp(retrieved_at_ms, "retrieved_at_ms")

    if mode not in {"MSTR_CAPITAL", "STRC_DIVIDEND"}:
        raise StrategyCapitalFactError(
            "mode must be MSTR_CAPITAL or STRC_DIVIDEND"
        )

    text, raw_bytes = _plain(raw_document)

    source_ref = _source_ref(
        raw_bytes,
        document_id=document_id,
        accepted_at_ms=accepted_at_ms,
        retrieved_at_ms=retrieved_at_ms,
    )

    blockers: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []

    if accepted_at_ms is None:
        blockers.append(
            _blocker(
                "DISCLOSURE_TIMESTAMP_UNKNOWN",
                ["DISCLOSURE_TIMESTAMP"],
                "Official disclosure timestamp is required "
                "to prevent look-ahead in historical replay.",
            )
        )

    if mode == "MSTR_CAPITAL":
        btc = _btc_holdings(text)
        shares = _diluted_shares(text)
        atm = _atm_shares(text)

        if btc is None:
            blockers.append(
                _blocker(
                    "MSTR_BTC_HOLDINGS_NOT_FOUND",
                    ["MSTR_BTC_HOLDINGS"],
                    "MSTR BTC holdings were not explicitly verified.",
                )
            )

        if shares is None:
            blockers.append(
                _blocker(
                    "MSTR_DILUTED_SHARES_NOT_FOUND",
                    ["MSTR_DILUTED_SHARES"],
                    "MSTR diluted shares were not explicitly verified.",
                )
            )

        if require_atm and atm is None:
            blockers.append(
                _blocker(
                    "MSTR_ATM_SHARES_NOT_FOUND",
                    ["MSTR_ATM_SHARES"],
                    "Required MSTR ATM share issuance was not verified.",
                )
            )

        if accepted_at_ms is not None:
            effective = _as_of_ms(text) or accepted_at_ms

            if btc is not None:
                facts.append(
                    _fact(
                        fact_type="BTC_HOLDINGS",
                        value=btc,
                        unit="BTC",
                        security_id=MSTR_SECURITY_ID,
                        effective_at_ms=effective,
                        source_ref=source_ref,
                    )
                )

            if shares is not None:
                facts.append(
                    _fact(
                        fact_type="DILUTED_SHARES",
                        value=shares,
                        unit="SHARES",
                        security_id=MSTR_SECURITY_ID,
                        effective_at_ms=effective,
                        source_ref=source_ref,
                    )
                )

            if atm is not None:
                facts.append(
                    _fact(
                        fact_type="ATM_SHARES_ISSUED",
                        value=atm,
                        unit="SHARES",
                        security_id=MSTR_SECURITY_ID,
                        effective_at_ms=effective,
                        source_ref=source_ref,
                    )
                )

        return _result(
            facts=facts,
            blockers=blockers,
            security_ids=[MSTR_SECURITY_ID],
            source_ref=source_ref,
            mode=mode,
        )

    rate = _strc_rate(text)
    ex_date = _date_after(
        text,
        r"\bex[- ]dividend date\b",
    )
    record_date = _date_after(
        text,
        r"\brecord date\b",
    )
    payment_date = _date_after(
        text,
        r"\bpayment date\b",
    )

    required = {
        "STRC_DISTRIBUTION_RATE_NOT_FOUND": (
            rate,
            ["STRC_DISTRIBUTION_RATE"],
        ),
        "STRC_EX_DIVIDEND_DATE_NOT_FOUND": (
            ex_date,
            ["STRC_EX_DIVIDEND_DATE"],
        ),
        "STRC_RECORD_DATE_NOT_FOUND": (
            record_date,
            ["STRC_RECORD_DATE"],
        ),
        "STRC_PAYMENT_DATE_NOT_FOUND": (
            payment_date,
            ["STRC_PAYMENT_DATE"],
        ),
    }

    for code, (value, ids) in required.items():
        if value is None:
            blockers.append(
                _blocker(
                    code,
                    ids,
                    "Required STRC dividend term was not "
                    "explicitly reported; no inference is allowed.",
                )
            )

    if accepted_at_ms is not None:
        if rate is not None:
            facts.append(
                _fact(
                    fact_type="DISTRIBUTION_RATE",
                    value=rate,
                    unit="PERCENT_APR",
                    security_id=STRC_SECURITY_ID,
                    effective_at_ms=accepted_at_ms,
                    source_ref=source_ref,
                )
            )

        for fact_type, value in (
            ("EX_DIVIDEND_DATE", ex_date),
            ("RECORD_DATE", record_date),
            ("PAYMENT_DATE", payment_date),
        ):
            if value is not None:
                facts.append(
                    _fact(
                        fact_type=fact_type,
                        value=value,
                        unit="DATE_MS",
                        security_id=STRC_SECURITY_ID,
                        effective_at_ms=accepted_at_ms,
                        source_ref=source_ref,
                    )
                )

    return _result(
        facts=facts,
        blockers=blockers,
        security_ids=[STRC_SECURITY_ID],
        source_ref=source_ref,
        mode=mode,
    )
