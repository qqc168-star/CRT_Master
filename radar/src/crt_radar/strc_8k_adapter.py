from __future__ import annotations

import hashlib
import html
import re
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from typing import Any


ADAPTER_SCHEMA_VERSION = "CRT_STRC_8K_ADAPTER_V0.1"
SOURCE_ID = "SEC-EDGAR-STRATEGY-8K"
ISSUER_ID = "CIK-0001050446"
SECURITY_ID = "SEC-STRC-PERP"
EXTERNAL_ACTION_AUTHORITY = "NONE"
EMPTY_REASON = "VERIFIED_NO_MATCH"

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ),
        start=1,
    )
}
_DATE_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})"


class Strc8KAdapterError(ValueError):
    """Raised when a Strategy 8-K cannot be normalized safely."""


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.text_parts: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.text_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(_normalize_space(" ".join(self._cell_parts)))
            self._cell_parts = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
            self._cell_parts = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None
            self._row = None
            self._cell_parts = None


def _parse_date(month: str, day: str, year: str) -> datetime:
    return datetime(int(year), _MONTHS[month], int(day), tzinfo=timezone.utc)


def _date_start_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _date_end_ms(value: datetime) -> int:
    return int((value + timedelta(days=1)).timestamp() * 1000) - 1


def _stable_suffix(start: datetime, end: datetime) -> str:
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


def _source_ref(
    raw_html: str | bytes,
    *,
    document_id: str | None,
    source_as_of_ms: int,
    retrieved_at_ms: int | None,
) -> dict[str, Any]:
    raw_bytes = raw_html if isinstance(raw_html, bytes) else raw_html.encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    result: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "document_id": document_id or f"DOC-SEC-{digest[:20]}",
        "source_as_of_ms": source_as_of_ms,
        "evidence_hash": digest,
    }
    if isinstance(retrieved_at_ms, int) and not isinstance(retrieved_at_ms, bool) and retrieved_at_ms > 0:
        result["retrieved_at_ms"] = retrieved_at_ms
    return result


def _parse_period(text: str) -> tuple[datetime, datetime] | None:
    match = re.search(rf"During Period\s+{_DATE_RE}\s+to\s+{_DATE_RE}", text, re.I)
    if not match:
        return None
    start = _parse_date(match.group(1).title(), match.group(2), match.group(3))
    end = _parse_date(match.group(4).title(), match.group(5), match.group(6))
    return (start, end) if end >= start else None


def _parse_disclosure_date(text: str) -> datetime | None:
    patterns = (
        rf"On\s+{_DATE_RE},\s+Strategy(?:\s+Inc)?\b",
        rf"Date of Report\s*\(Date of earliest event reported\)\s*:\s*{_DATE_RE}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _parse_date(match.group(1).title(), match.group(2), match.group(3))
    return None


def _first_numeric(cell: str) -> float | None:
    match = re.search(r"(?<![A-Za-z])(\d[\d,]*(?:\.\d+)?)", cell)
    return float(match.group(1).replace(",", "")) if match else None


def _repurchase_table(
    tables: list[list[list[str]]],
) -> tuple[tuple[datetime, datetime] | None, tuple[float, float] | None]:
    for table in tables:
        table_text = _normalize_space(" ".join(cell for row in table for cell in row))
        if not re.search(r"\bShares Repurchased\b", table_text, re.I):
            continue
        if not re.search(r"\bAggregate Purchase Price\b", table_text, re.I):
            continue

        strc_row: list[str] | None = None
        label_index: int | None = None
        for row in table:
            for index, cell in enumerate(row):
                if re.search(r"\bSTRC\s+Stock(?:\s*\(\d+\))?\b", cell, re.I):
                    strc_row = row
                    label_index = index
                    break
            if strc_row is not None:
                break

        if strc_row is None or label_index is None:
            continue

        trailing = strc_row[label_index + 1 :]
        numbers = [value for cell in trailing if (value := _first_numeric(cell)) is not None]
        explicit_dash = any(cell.strip() in {"-", "—", "–"} for cell in trailing)

        if not numbers:
            values = (0.0, 0.0) if explicit_dash else None
        elif len(numbers) >= 2:
            values = (numbers[0], numbers[-1] * 1_000_000.0)
        else:
            values = None

        return _parse_period(table_text), values

    return None, None


def _remaining_authorization(text: str) -> float | None:
    match = re.search(
        r"\$(\d[\d,]*(?:\.\d+)?)\s*(million|billion)\s+aggregate purchase price "
        r"of Strategy(?:'s|’s)\s+preferred stock remains available under the "
        r"Digital Credit Securities Repurchase Program",
        text,
        re.I,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    multiplier = 1_000_000.0 if match.group(2).lower() == "million" else 1_000_000_000.0
    return value * multiplier


def _blocker(
    code: str,
    scope: str,
    affected_ids: list[str],
    reason: str,
    required_to_clear: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "scope": scope,
        "affected_ids": affected_ids,
        "reason": reason,
        "required_to_clear": required_to_clear,
    }


def build_strc_8k_reflexivity_input(
    raw_html: str | bytes,
    *,
    document_id: str | None = None,
    accepted_at_ms: int | None = None,
    retrieved_at_ms: int | None = None,
) -> dict[str, Any]:
    """Normalize one Strategy 8-K into fail-closed CRT-ISSUER-001 input.

    Only source-backed STRC weekly repurchase facts are extracted. Market
    reaction, causal interpretation and BUY/SELL output are intentionally out
    of scope.
    """
    if isinstance(raw_html, bytes):
        html_text = raw_html.decode("utf-8", errors="replace")
    elif isinstance(raw_html, str):
        html_text = raw_html
    else:
        raise Strc8KAdapterError("raw_html must be str or bytes")

    if accepted_at_ms is not None and (
        not isinstance(accepted_at_ms, int)
        or isinstance(accepted_at_ms, bool)
        or accepted_at_ms <= 0
    ):
        raise Strc8KAdapterError("accepted_at_ms must be a positive integer when supplied")

    parser = _TableParser()
    parser.feed(html_text)
    plain_text = _normalize_space(" ".join(parser.text_parts))

    period, repurchase = _repurchase_table(parser.tables)
    disclosure_date = _parse_disclosure_date(plain_text)
    remaining = _remaining_authorization(plain_text)

    blockers: list[dict[str, Any]] = []
    if period is None:
        blockers.append(
            _blocker(
                "EXECUTION_WINDOW_INCOMPLETE",
                "EVENT",
                ["STRC_REPURCHASE_PERIOD"],
                "The weekly STRC repurchase execution period could not be verified from the repurchase table.",
                ["verify the filing's During Period start and end dates"],
            )
        )
    if repurchase is None:
        blockers.append(
            _blocker(
                "STRC_REPURCHASE_ROW_NOT_FOUND",
                "FACT",
                ["STRC_REPURCHASE_ROW"],
                "The repurchase table did not yield a verifiable STRC Stock row.",
                ["verify STRC shares repurchased and aggregate purchase price"],
            )
        )
    if remaining is None:
        blockers.append(
            _blocker(
                "REMAINING_AUTHORIZATION_NOT_FOUND",
                "FACT",
                ["STRC_REMAINING_AUTHORIZATION"],
                "Remaining preferred-stock repurchase authorization was not verified.",
                ["verify the active Digital Credit Securities Repurchase Program footnote"],
            )
        )
    if accepted_at_ms is None:
        blockers.append(
            _blocker(
                "DISCLOSURE_TIMESTAMP_UNKNOWN",
                "EVENT",
                ["STRC_REPURCHASE_DISCLOSURE"],
                "SEC acceptance time was not supplied, so the disclosure window cannot be exact.",
                ["supply the SEC accepted timestamp from the filing index"],
            )
        )

    source_clock = accepted_at_ms
    if source_clock is None and disclosure_date is not None:
        source_clock = _date_start_ms(disclosure_date)
    if source_clock is None and period is not None:
        source_clock = _date_end_ms(period[1])
    if source_clock is None:
        source_clock = 1

    source_ref = _source_ref(
        raw_html,
        document_id=document_id,
        source_as_of_ms=source_clock,
        retrieved_at_ms=retrieved_at_ms,
    )

    if period is not None:
        suffix = _stable_suffix(*period)
        effective_at_ms = _date_end_ms(period[1])
    else:
        suffix = source_ref["evidence_hash"][:16].upper()
        effective_at_ms = source_clock

    facts: list[dict[str, Any]] = []
    if repurchase is not None:
        shares, spend_usd = repurchase
        shares_fact = {
            "fact_id": f"FACT-STRC-REPURCHASED-SHARES-{suffix}",
            "issuer_id": ISSUER_ID,
            "security_id": SECURITY_ID,
            "fact_type": "REPURCHASED_SHARES",
            "value": shares,
            "unit": "SHARES",
            "effective_at_ms": effective_at_ms,
            "origin": "REPORTED",
            "source_ref": deepcopy(source_ref),
            "quality_state": "VALID_REPORTED",
        }
        cash_fact = {
            "fact_id": f"FACT-STRC-REPURCHASE-CASH-{suffix}",
            "issuer_id": ISSUER_ID,
            "security_id": SECURITY_ID,
            "fact_type": "REPURCHASE_CASH_CONSIDERATION",
            "value": spend_usd,
            "unit": "USD",
            "effective_at_ms": effective_at_ms,
            "origin": "REPORTED",
            "source_ref": deepcopy(source_ref),
            "quality_state": "VALID_REPORTED",
        }
        if shares == 0:
            shares_fact["zero_state"] = "VERIFIED_REPORTED_ZERO"
        if spend_usd == 0:
            cash_fact["zero_state"] = "VERIFIED_REPORTED_ZERO"
        facts.extend([shares_fact, cash_fact])

    if remaining is not None:
        facts.append(
            {
                "fact_id": f"FACT-STRC-REMAINING-AUTH-{suffix}",
                "issuer_id": ISSUER_ID,
                "security_id": SECURITY_ID,
                "fact_type": "REMAINING_AUTHORIZATION",
                "value": remaining,
                "unit": "USD",
                "effective_at_ms": effective_at_ms,
                "origin": "REPORTED",
                "source_ref": deepcopy(source_ref),
                "quality_state": "VALID_REPORTED",
            }
        )

    events: list[dict[str, Any]] = []
    calculations: list[dict[str, Any]] = []
    event_id = f"EVENT-STRC-REPURCHASE-{suffix}"

    if period is not None and repurchase is not None and accepted_at_ms is not None:
        shares, spend_usd = repurchase
        reported_values = [
            {
                "fact_id": f"FACT-STRC-REPURCHASED-SHARES-{suffix}",
                "value": shares,
                "unit": "SHARES",
            },
            {
                "fact_id": f"FACT-STRC-REPURCHASE-CASH-{suffix}",
                "value": spend_usd,
                "unit": "USD",
            },
        ]
        if remaining is not None:
            reported_values.append(
                {
                    "fact_id": f"FACT-STRC-REMAINING-AUTH-{suffix}",
                    "value": remaining,
                    "unit": "USD",
                }
            )

        events.append(
            {
                "event_id": event_id,
                "issuer_id": ISSUER_ID,
                "security_id": SECURITY_ID,
                "event_type": "SECURITY_REPURCHASE",
                "execution_window": {
                    "kind": "EXECUTION",
                    "start_ms": _date_start_ms(period[0]),
                    "end_ms": _date_end_ms(period[1]),
                    "precision": "DATE_RANGE",
                },
                "disclosure_window": {
                    "kind": "DISCLOSURE",
                    "start_ms": accepted_at_ms,
                    "end_ms": accepted_at_ms,
                    "precision": "SECOND",
                },
                "reported_values": reported_values,
                "source_ref": deepcopy(source_ref),
                "supersession": {
                    "state": "ACTIVE",
                    "superseded_by_event_id": None,
                },
            }
        )

        if shares > 0:
            calculations.append(
                {
                    "calculation_id": f"CALC-STRC-REPURCHASE-AVG-PRICE-{suffix}",
                    "calculation_spec_id": "REPURCHASE_AVG_PRICE",
                    "issuer_id": ISSUER_ID,
                    "security_id": SECURITY_ID,
                    "inputs": {
                        "eligible_cash_consideration": spend_usd,
                        "repurchased_shares": shares,
                    },
                    "input_fact_ids": [
                        f"FACT-STRC-REPURCHASED-SHARES-{suffix}",
                        f"FACT-STRC-REPURCHASE-CASH-{suffix}",
                    ],
                    "input_event_ids": [event_id],
                    "output_unit": "USD_PER_SHARE",
                    "prerequisites": {
                        "same_event": True,
                        "same_currency": True,
                    },
                    "source_refs": [deepcopy(source_ref)],
                }
            )

    fact_coverage = (
        "COMPLETE"
        if period is not None and repurchase is not None and remaining is not None
        else "PARTIAL"
    )
    event_coverage = "COMPLETE" if events else "PARTIAL"

    return {
        "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "action_output": "NONE",
        "issuer_facts": {
            "coverage_state": fact_coverage,
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": [SECURITY_ID],
                "start_ms": _date_start_ms(period[0]) if period is not None else None,
                "end_ms": _date_end_ms(period[1]) if period is not None else None,
            },
            "items": facts,
        },
        "issuer_events": {
            "coverage_state": event_coverage,
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": [SECURITY_ID],
                "start_ms": _date_start_ms(period[0]) if period is not None else None,
                "end_ms": accepted_at_ms,
            },
            "items": events,
        },
        "market_reaction_facts": {
            "coverage_state": "NOT_EVALUATED",
            "scope": {"security_ids": [SECURITY_ID]},
            "items": [],
        },
        "reflexivity_blockers": {
            "coverage_state": "COMPLETE",
            "scope": {"overlay_id": "CRT-ISSUER-001"},
            "items": blockers,
            **({"empty_reason": EMPTY_REASON} if not blockers else {}),
        },
        "calculation_requests": calculations,
        "adapter_diagnostics": {
            "period_found": period is not None,
            "strc_repurchase_row_found": repurchase is not None,
            "remaining_authorization_found": remaining is not None,
            "accepted_timestamp_supplied": accepted_at_ms is not None,
            "market_reaction_intentionally_not_evaluated": True,
            "source_id": SOURCE_ID,
            "document_id": source_ref["document_id"],
            "evidence_hash": source_ref["evidence_hash"],
        },
    }
