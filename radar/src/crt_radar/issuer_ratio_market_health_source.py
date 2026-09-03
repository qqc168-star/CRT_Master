from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .mstr_asst_market_health_runtime import seal_runtime_source


SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

ASSETS = {
    "MSTR": {
        "cik": "0001050446",
        "forms": {"FWP", "8-K", "8-K/A"},
    },
    "ASST": {
        "cik": "0001920406",
        "forms": {"8-K", "8-K/A"},
    },
}

NY = ZoneInfo("America/New_York")

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

DATE_RE = (
    r"(?P<month>"
    + "|".join(sorted(MONTHS, key=len, reverse=True))
    + r")\.?\s+"
    r"(?P<day>\d{1,2}),\s+"
    r"(?P<year>20\d{2})"
)

NUMBER = r"\d[\d,]*(?:\.\d+)?"
SCALE = r"(?:thousand|million|billion|[KMB])"


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def _plain(raw: bytes) -> str:
    parser = _HTMLText()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _scale(raw: str, scale: str | None = None) -> float:
    value = float(raw.replace(",", ""))

    if not scale:
        return value

    key = scale.lower()

    if key in {"thousand", "k"}:
        return value * 1_000.0

    if key in {"million", "m"}:
        return value * 1_000_000.0

    if key in {"billion", "b"}:
        return value * 1_000_000_000.0

    raise ValueError(f"unsupported numeric scale: {scale}")


def _date_ms(match: re.Match[str]) -> int:
    month = MONTHS[match.group("month").lower()]
    dt = datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        tzinfo=timezone.utc,
    )
    return int(dt.timestamp() * 1000)


def _accepted_ms(value: str) -> int:
    if not value:
        raise ValueError("SEC acceptance timestamp missing")

    text = value.strip()

    if text.endswith("Z"):
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(text)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=NY)

    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


_LAST_SEC_REQUEST_AT = 0.0
SEC_MIN_REQUEST_INTERVAL_SECONDS = 0.20


def _request(url: str, user_agent: str) -> bytes:
    global _LAST_SEC_REQUEST_AT

    if (
        not isinstance(user_agent, str)
        or "@" not in user_agent
        or len(user_agent.strip()) < 8
    ):
        raise ValueError(
            "SEC User-Agent must declare an application "
            "name and contact email"
        )

    now = time.monotonic()
    wait = (
        SEC_MIN_REQUEST_INTERVAL_SECONDS
        - (now - _LAST_SEC_REQUEST_AT)
    )

    if wait > 0:
        time.sleep(wait)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "identity",
            "Accept": "application/json,text/html,*/*",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            payload = response.read()
    finally:
        _LAST_SEC_REQUEST_AT = time.monotonic()

    return payload


def _json(url: str, user_agent: str) -> Any:
    return json.loads(_request(url, user_agent).decode("utf-8"))


def _recent_filings(
    cik: str,
    forms: set[str],
    user_agent: str,
    max_filings: int,
) -> list[dict[str, Any]]:
    payload = _json(
        f"{SEC_SUBMISSIONS}/CIK{cik}.json",
        user_agent,
    )

    recent = payload["filings"]["recent"]

    rows: list[dict[str, Any]] = []

    count = len(recent["accessionNumber"])

    for index in range(count):
        form = recent["form"][index]

        if form not in forms:
            continue

        primary = recent["primaryDocument"][index]

        if not primary:
            continue

        rows.append(
            {
                "accession": recent["accessionNumber"][index],
                "form": form,
                "primary": primary,
                "accepted":
                    recent.get("acceptanceDateTime", [""] * count)[index],
                "filing_date":
                    recent.get("filingDate", [""] * count)[index],
            }
        )

        if len(rows) >= max_filings:
            break

    return rows


def _document_url(cik: str, accession: str, primary: str) -> str:
    cik_numeric = str(int(cik))
    accession_compact = accession.replace("-", "")

    return (
        f"{SEC_ARCHIVES}/{cik_numeric}/"
        f"{accession_compact}/{primary}"
    )


def _strategy_state(
    raw: bytes,
    *,
    accepted_at_ms: int,
    source_url: str,
) -> dict[str, Any] | None:
    text = _plain(raw)

    btc_patterns = (
        rf"\b(?:aggregate\s+)?BTC holdings\b"
        rf"(?:\s+were|\s+was|\s+of|:)?\s*"
        rf"(?P<num>{NUMBER})\s*"
        rf"(?P<scale>{SCALE})?\s*"
        rf"(?:BTC|bitcoins?)\b",

        rf"\b(?:holds|held)\s+"
        rf"(?P<num>{NUMBER})\s*"
        rf"(?P<scale>{SCALE})?\s*"
        rf"bitcoins?\b",
    )

    btc_match = None

    for pattern in btc_patterns:
        btc_match = re.search(pattern, text, re.I)
        if btc_match:
            break

    share_patterns = (
        rf"~?\s*(?P<num>{NUMBER})\s*"
        rf"(?P<scale>{SCALE})?\s+"
        rf"(?:assumed\s+)?(?:fully\s+)?"
        rf"diluted shares(?: outstanding)?\b",

        rf"\b(?:assumed\s+)?(?:fully\s+)?"
        rf"diluted shares(?: outstanding)?"
        rf"(?:\s+were|\s+was|\s+of|:)?\s*"
        rf"(?P<num>{NUMBER})\s*"
        rf"(?P<scale>{SCALE})?\b",
    )

    share_match = None

    for pattern in share_patterns:
        share_match = re.search(pattern, text, re.I)
        if share_match:
            break

    if not btc_match or not share_match:
        return None

    btc = _scale(
        btc_match.group("num"),
        btc_match.groupdict().get("scale"),
    )

    shares = _scale(
        share_match.group("num"),
        share_match.groupdict().get("scale"),
    )

    if btc <= 0 or shares <= 0:
        return None

    effective = accepted_at_ms

    nearby = text[
        btc_match.end():
        min(len(text), btc_match.end() + 100)
    ]

    date_match = re.search(
        rf"\bas of\s+{DATE_RE}",
        nearby,
        re.I,
    )

    if date_match:
        effective = _date_ms(date_match)

    return {
        "effective_at_ms": effective,
        "btc_holdings": btc,
        "diluted_shares": shares,
        "btc_per_diluted_share": btc / shares,
        "source_url": source_url,
        "evidence_hash": hashlib.sha256(raw).hexdigest(),
    }


def _strive_states(
    raw: bytes,
    *,
    accepted_at_ms: int,
    source_url: str,
) -> list[dict[str, Any]]:
    text = _plain(raw)

    dates = [
        _date_ms(match)
        for match in re.finditer(
            rf"\bAs of\s+{DATE_RE}",
            text,
            re.I,
        )
    ]

    btc_match = re.search(
        rf"\bBitcoin held\b\s+"
        rf"(?P<previous>{NUMBER})\s+"
        rf"(?P<current>{NUMBER})\b",
        text,
        re.I,
    )

    shares_match = re.search(
        rf"\bAssumed Fully Diluted Shares"
        rf"(?:\s*\(\d+\))?\s+"
        rf"(?P<previous>{NUMBER})\s+"
        rf"(?P<current>{NUMBER})\b",
        text,
        re.I,
    )

    if (
        btc_match
        and shares_match
        and len(dates) >= 2
    ):
        previous_btc = _scale(btc_match.group("previous"))
        current_btc = _scale(btc_match.group("current"))

        previous_shares = _scale(
            shares_match.group("previous")
        )
        current_shares = _scale(
            shares_match.group("current")
        )

        digest = hashlib.sha256(raw).hexdigest()

        return [
            {
                "effective_at_ms": dates[0],
                "btc_holdings": previous_btc,
                "diluted_shares": previous_shares,
                "btc_per_diluted_share":
                    previous_btc / previous_shares,
                "source_url": source_url,
                "evidence_hash": digest,
            },
            {
                "effective_at_ms": dates[1],
                "btc_holdings": current_btc,
                "diluted_shares": current_shares,
                "btc_per_diluted_share":
                    current_btc / current_shares,
                "source_url": source_url,
                "evidence_hash": digest,
            },
        ]

    return []


def _dedupe(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}

    for state in states:
        key = (
            state["effective_at_ms"],
            state["btc_holdings"],
            state["diluted_shares"],
        )
        unique[key] = state

    return sorted(
        unique.values(),
        key=lambda row: row["effective_at_ms"],
    )


def collect_states(
    asset: str,
    *,
    user_agent: str,
    max_filings: int,
) -> list[dict[str, Any]]:
    spec = ASSETS[asset]

    filings = _recent_filings(
        spec["cik"],
        spec["forms"],
        user_agent,
        max_filings,
    )

    states: list[dict[str, Any]] = []

    for filing in filings:
        accepted = filing["accepted"]

        if not accepted:
            continue

        accepted_ms = _accepted_ms(accepted)

        url = _document_url(
            spec["cik"],
            filing["accession"],
            filing["primary"],
        )

        try:
            raw = _request(url, user_agent)
        except Exception as exc:
            print(
                f"{asset} SKIP_FETCH {url} "
                f"{type(exc).__name__}"
            )
            continue

        if asset == "MSTR":
            state = _strategy_state(
                raw,
                accepted_at_ms=accepted_ms,
                source_url=url,
            )

            if state:
                states.append(state)

        else:
            states.extend(
                _strive_states(
                    raw,
                    accepted_at_ms=accepted_ms,
                    source_url=url,
                )
            )

        states = _dedupe(states)

        if len(states) >= 2:
            break

        time.sleep(0.12)

    return _dedupe(states)


def build_ratio_data(
    histories: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    data: dict[str, Any] = {}

    for asset in ("MSTR", "ASST"):
        history = histories[asset]

        if len(history) < 2:
            raise ValueError(
                f"{asset} requires at least two "
                f"official paired states; found {len(history)}"
            )

        previous, current = history[-2:]

        if (
            current["effective_at_ms"]
            <= previous["effective_at_ms"]
        ):
            raise ValueError(
                f"{asset} state time ordering invalid"
            )

        data[asset] = {
            "previous_btc_per_diluted_share":
                previous["btc_per_diluted_share"],

            "current_btc_per_diluted_share":
                current["btc_per_diluted_share"],

            "previous_effective_at_ms":
                previous["effective_at_ms"],

            "current_effective_at_ms":
                current["effective_at_ms"],

            "previous_btc_holdings":
                previous["btc_holdings"],

            "current_btc_holdings":
                current["btc_holdings"],

            "previous_diluted_shares":
                previous["diluted_shares"],

            "current_diluted_shares":
                current["diluted_shares"],

            "previous_source_url":
                previous["source_url"],

            "current_source_url":
                current["source_url"],

            "previous_evidence_hash":
                previous["evidence_hash"],

            "current_evidence_hash":
                current["evidence_hash"],
        }

    return data


def build_live_issuer_ratio_proof(
    *,
    user_agent: str,
    max_filings: int = 30,
) -> dict[str, Any]:
    histories = {
        asset: collect_states(
            asset,
            user_agent=user_agent,
            max_filings=max_filings,
        )
        for asset in ("MSTR", "ASST")
    }

    for asset, history in histories.items():
        print(f"{asset}_PAIRED_STATES={len(history)}")

        for row in history[-3:]:
            print(
                asset,
                row["effective_at_ms"],
                "BTC=",
                row["btc_holdings"],
                "SHARES=",
                row["diluted_shares"],
                "BTC_PER_SHARE=",
                row["btc_per_diluted_share"],
            )
            print(" SOURCE=", row["source_url"])

    data = build_ratio_data(histories)

    proof = seal_runtime_source(
        source_key="issuer_btc_per_diluted_share",
        data=data,
        observed_at_ms=int(time.time() * 1000),
    )

    proof["collection_contract"] = {
        "provider":
            "SEC_EDGAR_AND_ISSUER_OFFICIAL_DISCLOSURES",

        "transport":
            "HTTPS_READ_ONLY",

        "selection":
            "LATEST_TWO_COMPLETE_PAIRED_OFFICIAL_STATES",

        "machine_invented_fact":
            False,

        "account_surface":
            "ABSENT",

        "order_surface":
            "ABSENT",
    }

    return proof


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument("--output", required=True)

    parser.add_argument(
        "--user-agent",
        required=True,
        help=(
            "SEC declared User-Agent containing "
            "application identity and contact email"
        ),
    )

    parser.add_argument(
        "--max-filings",
        type=int,
        default=30,
    )

    return parser


def main() -> int:
    args = _parser().parse_args()

    proof = build_live_issuer_ratio_proof(
        user_agent=args.user_agent,
        max_filings=args.max_filings,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    temp = output.with_suffix(
        output.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            proof,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    temp.replace(output)

    print("ISSUER_RATIO_LIVE_CANDIDATE_WRITTEN")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())