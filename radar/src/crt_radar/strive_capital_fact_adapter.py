from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from .issuer_disclosure_tables import dated_table_facts, bind_table_context
from .strategy_capital_fact_adapter import distribution_terms


ADAPTER_SCHEMA_VERSION = "CRT_STRIVE_CAPITAL_FACT_ADAPTER_V0.1"
SOURCE_ID = "STRIVE_OFFICIAL_CAPITAL_DISCLOSURE"
ISSUER_ID = "CIK-0001920406"
ASST_SECURITY_ID = "ASST"
SATA_SECURITY_ID = "SATA"
EXTERNAL_ACTION_AUTHORITY = "NONE"
EMPTY_REASON = "VERIFIED_NO_MATCH"


def _sats_offering(text, source_ref, accepted, retrieved, issuer_id):
    """Read Strive's offering disclosure, never infer closing from a due date.

    Numeric terms describe the offer, not circulating shares or received cash.
    Identity is supplied by the existing CIK-verified issuer ingestion boundary.
    """
    blockers, facts = [], []
    def block(code):
        blockers.append(_blocker(code, ["SATS_OFFERING_TERMS"], code))
    if (issuer_id != ISSUER_ID or not re.search(r"Strive,?\s+Inc\.", text, re.I)
            or not re.search(r"Series A Perpetual SATS Preferred Stock", text, re.I)):
        block("SATS_STRIVE_SECURITY_IDENTITY_UNVERIFIED")
    if not accepted or not retrieved or retrieved < accepted:
        block("SATS_DISCLOSURE_VISIBILITY_UNVERIFIED")
    if blockers:
        return _result(facts=facts, blockers=blockers, security_id="SATS", source_ref=source_ref, mode="SATS_TERMS")

    def number(pattern):
        values = {float(v.replace(",", "")) for v in re.findall(pattern, text, re.I)}
        value = next(iter(values)) if len(values) == 1 else None
        return value if value is not None and math.isfinite(value) and value > 0 else None
    def date(pattern):
        values = set(re.findall(pattern, text, re.I))
        if len(values) != 1:
            return None
        try:
            return int(datetime.strptime(next(iter(values)), "%B %d, %Y").replace(tzinfo=timezone.utc).timestamp()*1000)
        except ValueError:
            return None

    shares = number(r"Amount Offered\s+([\d,]+) shares of SATS Stock")
    price = number(r"Public Offering Price\s+\$([\d,.]+) per share of SATS Stock")
    if shares is None and "Amount Offered" not in text:
        shares = number(r"(?:underwritten offering|initial public offering).{0,35}?of ([\d,]+) shares")
    if price is None and "Public Offering Price $" not in text:
        price = number(r"public offering price of \$([\d,.]+) per share")
    stated = number(r"Stated Amount\s+\$([\d,.]+) per share of SATS Stock")
    if stated is None:
        stated = number(r"stated amount of \$([\d,.]+) per share")
    rate = number(r"rate per annum equal to ([\d.]+)% on the Stated Amount")
    initial_claim = number(r"Liquidation Preference\s+Initially,\s*\$([\d,.]+) per share")
    if initial_claim is None:
        initial_claim = number(r"initially has a liquidation preference of \$([\d,.]+) per share")
    expected_close = date(r"Settlement Date\s+([A-Za-z]+ \d{1,2}, \d{4})")
    trade_date = date(r"Trade Date\s+([A-Za-z]+ \d{1,2}, \d{4})")
    closed = date(r"issuance and sale of the SATS Stock (?:was|were) completed on ([A-Za-z]+ \d{1,2}, \d{4})")
    if closed is None and re.search(r"announced today the closing of its upsized initial public offering", text, re.I):
        closed = date(r"DALLAS,? TX,? ([A-Za-z]+ \d{1,2}, \d{4})")
    stage = ("SETTLED" if closed and closed <= accepted else "PRICED" if price is not None and shares is not None
        else "ANNOUNCED" if re.search(r"SUBJECT TO COMPLETION|Proposed Initial Public Offering", text, re.I)
        else "UNRESOLVED")
    ranking = re.search(r"Ranking\s+(.*?)\s+Liquidation Preference", text, re.I)
    cusip = re.search(r"CUSIP / ISIN Numbers for SATS Stock\s+([\d ]{9,11})\s*/\s*(US\w+)", text)
    listing = date(r"SATS Stock (?:began|commenced) trading on Nasdaq on ([A-Za-z]+ \d{1,2}, \d{4})")
    terms = dict(issuer_id=ISSUER_ID, security_id="SATS", offering_stage=stage,
        stated_amount_usd=stated, initial_liquidation_preference_usd=initial_claim,
        offered_shares=shares, offering_price_usd=price, annual_dividend_rate_pct=rate,
        conditional_gross_proceeds_usd=shares*price if shares is not None and price is not None else None,
        conditional_initial_claims_usd=shares*initial_claim if shares is not None and initial_claim is not None else None,
        conditional_annual_dividends_usd=shares*stated*rate/100 if None not in (shares, stated, rate) else None,
        scheduled_settlement_date_ms=expected_close, reported_settlement_date_ms=closed,
        proposed_trade_date_ms=trade_date, listing_effective_date_ms=listing,
        reported_closed_shares=shares if stage == "SETTLED" else None,
        listing_qualification="REPORTED_LISTED" if listing and listing <= accepted else "NOT_PROVEN",
        cusip=cusip.group(1).replace(" ", "") if cusip else None,
        isin=cusip.group(2) if cusip else None,
        ranking_source_text=ranking.group(1) if ranking else None,
        # No regex or offer price can prove net cash, actual outstanding or deployment.
        settled_net_proceeds_usd=None, actual_outstanding_shares=None,
        actual_deployment_usd=None, evidence_authority="REPORTED_TERMS_ONLY",
        current_liquidation_claims_usd=None,
        liquidation_qualification="DYNAMIC_PREFERENCE_AND_ACCRUALS_NOT_VERIFIED",
        disclosure_time=accepted, first_seen_time=retrieved, retrieval_time=retrieved,
        source_ref=source_ref, date_precision="UTC_DATE_NOT_INTRADAY_EFFECTIVE_TIME")
    for field in ("offered_shares", "offering_price_usd", "stated_amount_usd", "annual_dividend_rate_pct",
                  "initial_liquidation_preference_usd", "ranking_source_text", "cusip"):
        if terms[field] is None:
            block("SATS_" + field.upper() + "_UNRESOLVED")
    block("SATS_SETTLED_ACCOUNTING_AND_DEPLOYMENT_NOT_BOUND")
    facts.append(_fact(fact_type="SATS_OFFERING_TERMS", value=terms, unit="STRUCTURED_REPORTED_TERMS",
        security_id="SATS", accepted_at_ms=accepted, source_ref=source_ref))
    return _result(facts=facts, blockers=blockers, security_id="SATS", source_ref=source_ref, mode="SATS_TERMS")


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
            # Adjacent numbers in flattened tables can be a footnote and a value.
            # Only dated cell extraction may resolve that ambiguity.
            if not match.groupdict().get("scale") and re.match(r"\s*\d", text[match.end():]):
                continue
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
    issuer_id: str | None = None,
) -> dict[str, Any]:
    _validate_timestamp(accepted_at_ms, "accepted_at_ms")
    _validate_timestamp(retrieved_at_ms, "retrieved_at_ms")

    if mode not in {"ASST_CAPITAL", "SATA_TERMS", "SATS_TERMS"}:
        raise StriveCapitalFactError(
            "mode must be ASST_CAPITAL, SATA_TERMS or SATS_TERMS"
        )

    text, raw_bytes = _plain(raw_document)
    table_facts = dated_table_facts(raw_bytes, "STRIVE", disclosed_at_ms=accepted_at_ms)

    def read_value(kind, fallback):
        return table_facts[kind]["value"] if kind in table_facts else fallback(text)

    source_ref = _source_ref(
        raw_bytes,
        document_id=document_id,
        accepted_at_ms=accepted_at_ms,
        retrieved_at_ms=retrieved_at_ms,
    )

    if mode == "SATS_TERMS":
        return _sats_offering(text, source_ref, accepted_at_ms, retrieved_at_ms, issuer_id)

    blockers: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for kind, item in table_facts.items():
        if item.get("reason"):
            blockers.append(_blocker(item["reason"], [kind], "Dated table claim is ambiguous; no narrative fallback is allowed."))

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
        btc = read_value("BTC_HOLDINGS", _btc)
        shares = read_value("DILUTED_SHARES", _diluted_shares)
        sata_liquidation_preference_aggregate = _sata_liquidation_preference_aggregate(text)
        warrants = read_value("WARRANTS_OUTSTANDING", _warrants)
        atm = read_value("ATM_SHARES_ISSUED", _atm_shares)

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

        bind_table_context(facts, table_facts)
        return _result(
            facts=facts,
            blockers=blockers,
            security_id=ASST_SECURITY_ID,
            source_ref=source_ref,
            mode=mode,
        )

    holdings = read_value("STRIVE_STRC_HOLDINGS", _strc_holdings)
    fair_value = read_value("STRIVE_STRC_FAIR_VALUE", _strc_fair_value)
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

    for fact in facts:
        if fact["fact_type"] == "DISTRIBUTION_RATE":
            fact["distribution_terms"] = distribution_terms(text, "SATA")
    bind_table_context(facts, table_facts)
    return _result(
        facts=facts,
        blockers=blockers,
        security_id=SATA_SECURITY_ID,
        source_ref=source_ref,
        mode=mode,
    )
