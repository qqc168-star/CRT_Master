from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any


ADAPTER_SCHEMA_VERSION = "CRT_STRIVE_CAPITAL_FACT_ADAPTER_V0.1"
SOURCE_ID = "STRIVE_OFFICIAL_CAPITAL_DISCLOSURE"
ISSUER_ID = "CIK-0001920406"
ASST_SECURITY_ID = "ASST"
SATA_SECURITY_ID = "SATA"
EXTERNAL_ACTION_AUTHORITY = "NONE"
EMPTY_REASON = "VERIFIED_NO_MATCH"


class StriveCapitalFactError(ValueError):
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
        raise StriveCapitalFactError(
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
        raise StriveCapitalFactError(
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
    clock = accepted_at_ms or retrieved_at_ms or 1

    result: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "document_id": (
            document_id
            or f"DOC-STRIVE-{digest[:20].upper()}"
        ),
        "source_as_of_ms": clock,
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

        if match:
            return _scale_number(
                match.group("num"),
                match.groupdict().get("scale"),
            )

    return None


def _btc(text: str) -> float | None:
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
        ),
        text,
    )


def _warrants(text: str) -> float | None:
    return _scaled_match(
        (
            r"\bwarrants?\s+(?:outstanding\s+)?"
            r"(?:to purchase\s+)?"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s+shares\b",

            r"\bwarrants?\s+outstanding(?:\s+were|\s+was|:)?\s*"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",
        ),
        text,
    )


def _sata_liquidation_preference_aggregate(text: str) -> float | None:
    return _scaled_match(
        (
            r"\bSATA\b.{0,180}?"
            r"aggregate liquidation preference"
            r"(?:\s+of|\s+was|\s+is|:)?\s*\$"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",

            r"aggregate liquidation preference.{0,180}?"
            r"\bSATA\b.{0,80}?\$"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",
        ),
        text,
    )


def _strc_holdings(text: str) -> float | None:
    return _scaled_match(
        (
            r"\b(?:holds|held)\s+"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s+"
            r"shares?\s+of\s+STRC\b",

            r"\bSTRC holdings(?:\s+were|\s+was|\s+of|:)?\s*"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\s+shares?\b",
        ),
        text,
    )


def _strc_fair_value(text: str) -> float | None:
    return _scaled_match(
        (
            r"\bfair value\s+of(?:\s+our)?\s+STRC holdings"
            r"(?:\s+was|\s+is|\s+of|:)?\s*\$"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",

            r"\bSTRC holdings.{0,160}?\bfair value\b"
            r"(?:\s+was|\s+is|\s+of|:)?\s*\$"
            r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<scale>thousand|million|billion)?\b",
        ),
        text,
    )


def _rate(text: str) -> float | None:
    match = re.search(
        r"\bSATA\b.{0,180}?"
        r"(?:annualized\s+)?(?:dividend|distribution)\s+rate"
        r"(?:\s+of|\s+is|:)?\s*"
        r"(?P<num>\d+(?:\.\d+)?)\s*%",
        text,
        re.I,
    )
    return float(match.group("num")) if match else None


def _per_share_amount(
    text: str,
    label: str,
) -> float | None:
    match = re.search(
        rf"\bSATA\b.{{0,180}}?{label}"
        rf"(?:\s+of|\s+is|\s+was|:)?\s*\$"
        rf"(?P<num>\d[\d,]*(?:\.\d+)?)"
        rf"\s+(?:per\s+share|a\s+share)\b",
        text,
        re.I,
    )

    if not match:
        return None

    return float(match.group("num").replace(",", ""))


def _blocker(
    code: str,
    ids: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "scope": "FACT",
        "affected_ids": ids,
        "reason": reason,
        "required_to_clear": [
            "supply an official Strive disclosure "
            "that explicitly reports the missing fact"
        ],
    }


def _fact(
    *,
    fact_type: str,
    value: float,
    unit: str,
    security_id: str,
    accepted_at_ms: int,
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
        "effective_at_ms": accepted_at_ms,
        "origin": "REPORTED",
        "source_ref": dict(source_ref),
        "quality_state": "VALID_REPORTED",
    }


def _result(
    *,
    facts: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    security_id: str,
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
                "security_ids": [security_id],
            },
            "items": facts,
        },
        "issuer_events": {
            "coverage_state": "PARTIAL",
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": [security_id],
            },
            "items": [],
        },
        "market_reaction_facts": {
            "coverage_state": "NOT_EVALUATED",
            "scope": {
                "security_ids": [security_id],
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


def build_strive_capital_reflexivity_input(
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

    if mode not in {"ASST_CAPITAL", "SATA_TERMS"}:
        raise StriveCapitalFactError(
            "mode must be ASST_CAPITAL or SATA_TERMS"
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

    if mode == "ASST_CAPITAL":
        btc = _btc(text)
        shares = _diluted_shares(text)
        sata_liquidation_preference_aggregate = _sata_liquidation_preference_aggregate(text)
        warrants = _warrants(text)
        atm = _atm_shares(text)

        required = {
            "ASST_BTC_HOLDINGS_NOT_FOUND": (
                btc,
                ["ASST_BTC_HOLDINGS"],
            ),
            "ASST_DILUTED_SHARES_NOT_FOUND": (
                shares,
                ["ASST_DILUTED_SHARES"],
            ),
            "ASST_SATA_LIQUIDATION_PREFERENCE_AGGREGATE_NOT_FOUND": (
                sata_liquidation_preference_aggregate,
                ["ASST_SATA_LIQUIDATION_PREFERENCE_AGGREGATE"],
            ),
            "ASST_WARRANTS_NOT_FOUND": (
                warrants,
                ["ASST_WARRANTS"],
            ),
        }

        for code, (value, ids) in required.items():
            if value is None:
                blockers.append(
                    _blocker(
                        code,
                        ids,
                        "Required ASST capital fact "
                        "was not explicitly verified.",
                    )
                )

        if require_atm and atm is None:
            blockers.append(
                _blocker(
                    "ASST_ATM_SHARES_NOT_FOUND",
                    ["ASST_ATM_SHARES"],
                    "Required ASST ATM issuance was not verified.",
                )
            )

        if accepted_at_ms is not None:
            rows = (
                ("BTC_HOLDINGS", btc, "BTC"),
                ("DILUTED_SHARES", shares, "SHARES"),
                ("SATA_LIQUIDATION_PREFERENCE_AGGREGATE", sata_liquidation_preference_aggregate, "USD"),
                ("WARRANTS_OUTSTANDING", warrants, "SHARES"),
                ("ATM_SHARES_ISSUED", atm, "SHARES"),
            )

            for fact_type, value, unit in rows:
                if value is not None:
                    facts.append(
                        _fact(
                            fact_type=fact_type,
                            value=value,
                            unit=unit,
                            security_id=ASST_SECURITY_ID,
                            accepted_at_ms=accepted_at_ms,
                            source_ref=source_ref,
                        )
                    )

        return _result(
            facts=facts,
            blockers=blockers,
            security_id=ASST_SECURITY_ID,
            source_ref=source_ref,
            mode=mode,
        )

    holdings = _strc_holdings(text)
    fair_value = _strc_fair_value(text)
    rate = _rate(text)
    stated = _per_share_amount(
        text,
        r"stated amount",
    )
    liquidation = _per_share_amount(
        text,
        r"liquidation preference",
    )

    required = {
        "STRIVE_STRC_HOLDINGS_NOT_FOUND": (
            holdings,
            ["STRIVE_STRC_HOLDINGS"],
        ),
        "STRIVE_STRC_FAIR_VALUE_NOT_FOUND": (
            fair_value,
            ["STRIVE_STRC_FAIR_VALUE"],
        ),
        "SATA_DISTRIBUTION_RATE_NOT_FOUND": (
            rate,
            ["SATA_DISTRIBUTION_RATE"],
        ),
        "SATA_STATED_AMOUNT_NOT_FOUND": (
            stated,
            ["SATA_STATED_AMOUNT"],
        ),
        "SATA_LIQUIDATION_PREFERENCE_NOT_FOUND": (
            liquidation,
            ["SATA_LIQUIDATION_PREFERENCE"],
        ),
    }

    for code, (value, ids) in required.items():
        if value is None:
            blockers.append(
                _blocker(
                    code,
                    ids,
                    "Required SATA term was not explicitly verified.",
                )
            )

    if accepted_at_ms is not None:
        rows = (
            ("STRIVE_STRC_HOLDINGS", holdings, "SHARES"),
            ("STRIVE_STRC_FAIR_VALUE", fair_value, "USD"),
            ("DISTRIBUTION_RATE", rate, "PERCENT_APR"),
            ("STATED_AMOUNT", stated, "USD_PER_SHARE"),
            (
                "LIQUIDATION_PREFERENCE",
                liquidation,
                "USD_PER_SHARE",
            ),
        )

        for fact_type, value, unit in rows:
            if value is not None:
                facts.append(
                    _fact(
                        fact_type=fact_type,
                        value=value,
                        unit=unit,
                        security_id=SATA_SECURITY_ID,
                        accepted_at_ms=accepted_at_ms,
                        source_ref=source_ref,
                    )
                )

    return _result(
        facts=facts,
        blockers=blockers,
        security_id=SATA_SECURITY_ID,
        source_ref=source_ref,
        mode=mode,
    )
