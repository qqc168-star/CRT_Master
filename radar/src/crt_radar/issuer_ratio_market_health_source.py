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
from .mstr_asst_market_health import issuer_ratio_observation


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


class _LedgerTable(HTMLParser):
    """Keep cells within their own table/row; totals are not observations."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            if self.table is not None:
                raise ValueError("nested Ledger table is unsupported")
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def parse_strategy_ledger(raw: bytes, *, source_url: str,
                          retrieved_at_ms: int) -> list[dict[str, Any]]:
    parser = _LedgerTable()
    parser.feed(raw.decode("utf-8", errors="strict"))
    required = ("Count", "Reported", "BTC", "ADSO ('000)")
    matches = [(table, row) for table in parser.tables for row in table
               if all(row.count(name) == 1 for name in required)]
    if len(matches) != 1:
        raise ValueError("Ledger requires one unambiguous Reported/BTC/ADSO table")
    table, header = matches[0]
    indexes = [header.index(name) for name in required]
    digest = hashlib.sha256(raw).hexdigest()
    observations: dict[str, dict[str, Any]] = {}
    for row in table:
        if len(row) <= max(indexes):
            continue
        count, reported, btc_text, adso_text = [row[index] for index in indexes]
        if not count.isdecimal() or not reported:
            continue  # Headers and totals cannot supply a paired observation.
        reported_dt = datetime.strptime(reported, "%m/%d/%Y").replace(tzinfo=timezone.utc)
        reported_ms = int(reported_dt.timestamp() * 1000)
        if reported_ms > retrieved_at_ms:
            raise ValueError("Ledger reported date is in the future")
        if btc_text in {"", "-", "—"} or adso_text in {"", "-", "—"}:
            continue  # Earlier history may not publish ADSO.
        if not all(re.fullmatch(r"\d+(?:,\d{3})*(?:\.\d+)?", text)
                   for text in (btc_text, adso_text)):
            raise ValueError("Ledger paired BTC/ADSO numeric schema invalid")
        btc = float(btc_text.replace(",", ""))
        shares = float(adso_text.replace(",", "")) * 1000
        if btc <= 0 or shares <= 0:
            raise ValueError("Ledger paired BTC/ADSO must be positive")
        date_text = reported_dt.date().isoformat()
        observation = {
            "reported_date": date_text,
            "reported_at_ms": reported_ms,
            "btc_holdings": btc,
            "diluted_shares": shares,
            "btc_per_diluted_share": btc / shares,
            "retrieved_at_ms": retrieved_at_ms,
            "first_seen_at_ms": retrieved_at_ms,
            "source_url": source_url,
            "evidence_hash": digest,
        }
        if date_text in observations and observations[date_text] != observation:
            raise ValueError("Ledger conflicting observations for one reported date")
        observations[date_text] = observation
    return sorted(observations.values(), key=lambda row: row["reported_date"])


def build_ledger_ratio_data(history: list[dict[str, Any]]) -> dict[str, Any]:
    if len(history) < 2:
        raise ValueError("MSTR Ledger requires two valid reported observations")
    ordered = sorted(history, key=lambda row: row["reported_date"])
    if len({row["reported_date"] for row in ordered}) != len(ordered):
        raise ValueError("Ledger reported dates must be unique")
    previous, current = ordered[-2:]
    return {
        **{f"{prefix}_{key}": value for prefix, row in
           (("previous", previous), ("current", current)) for key, value in row.items()},
        "source_role": "PRIMARY_OFFICIAL_MSTR_BTC_ADSO_HISTORY",
        "time_semantic": "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME",
        "reported_at_rule": "REPORTED_DATE_UTC_MIDNIGHT_SORT_KEY_ONLY",
        "comparison_horizon": "ADJACENT_REPORTED_OBSERVATIONS",
        "ct_binding_state": "NOT_CT_BOUND",
        "ct_blocker": "ADSO_EFFECTIVE_TIME_UNRESOLVED",
        "wake_authority": "OBSERVATION_ONLY",
        "machine_execution": "FORBIDDEN",
        "semantic_source_url": "https://www.strategy.com/notes",
        "semantic_authority": "METRIC_SEMANTIC_AUTHORITY",
        "sec_authority": "DISCLOSURE_AND_CAPITAL_EVENT_AUTHORITY",
    }


def collect_ledger_states(*, raw_archive_dir: Path | None = None) -> list[dict[str, Any]]:
    contract_path = Path(__file__).resolve().parents[2] / "CONFIG" / "MSTR_ASST_MARKET_HEALTH_SOURCE_V0.1.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    url = contract["sources"]["issuer_btc_per_diluted_share"]["MSTR"]["ledger"]["source_url"]
    # The private SEC contact identity is never sent to an issuer or CDN.
    request = urllib.request.Request(url, headers={
        "User-Agent": "CRT-Radar/0.4-RC1 read-only source gate",
        "Accept": "text/html", "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("Ledger transport requires direct HTTP 200")
        content_type = response.headers.get("Content-Type", "")
        if not content_type.lower().startswith("text/html"):
            raise ValueError("Ledger transport requires HTML")
        raw = response.read()
    retrieved = int(time.time() * 1000)
    digest = hashlib.sha256(raw).hexdigest()
    if raw_archive_dir is not None:
        raw_archive_dir.mkdir(parents=True, exist_ok=True)
        (raw_archive_dir / f"ledger-{digest}.html").write_bytes(raw)
        (raw_archive_dir / f"retrieval-{retrieved}.json").write_text(json.dumps({
            "source_url": url, "http_status": 200, "content_type": content_type,
            "evidence_hash": digest, "retrieved_at_ms": retrieved,
            "first_seen_at_ms": retrieved,
        }, indent=2), encoding="utf-8")
    return parse_strategy_ledger(raw, source_url=url, retrieved_at_ms=retrieved)

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
    histories: dict[str, list[dict[str, Any]]],
    *, assets: tuple[str, ...] = ("MSTR", "ASST"),
) -> dict[str, Any]:
    data: dict[str, Any] = {}

    for asset in assets:
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
    raw_archive_dir: Path | None = None,
    mstr_source: str = "LEDGER",
) -> dict[str, Any]:
    if mstr_source not in {"LEDGER", "SEC"}:
        raise ValueError("MSTR source must be LEDGER or SEC")
    ledger_history = collect_ledger_states(raw_archive_dir=raw_archive_dir) if mstr_source == "LEDGER" else None
    sec_assets = ("MSTR", "ASST") if mstr_source == "SEC" else ("ASST",)
    histories = {
        asset: collect_states(
            asset,
            user_agent=user_agent,
            max_filings=max_filings,
        )
        for asset in sec_assets
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

    data = build_ratio_data(histories, assets=sec_assets)
    if mstr_source == "LEDGER":
        data["MSTR"] = build_ledger_ratio_data(ledger_history)
        issuer_ratio_observation("MSTR", data["MSTR"], generated_at_ms=int(time.time() * 1000))

    proof = seal_runtime_source(
        source_key="issuer_btc_per_diluted_share",
        data=data,
        observed_at_ms=int(time.time() * 1000),
    )

    proof["collection_contract"] = {
        "provider":
            "STRATEGY_LEDGER_AND_ASST_SEC" if mstr_source == "LEDGER"
            else "SEC_EDGAR_AND_ISSUER_OFFICIAL_DISCLOSURES",

        "transport":
            "HTTPS_READ_ONLY",

        "selection":
            "MSTR_ADJACENT_REPORTED_ASST_PAIRED_EFFECTIVE_STATES" if mstr_source == "LEDGER"
            else "LATEST_TWO_COMPLETE_PAIRED_OFFICIAL_STATES",

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
    parser.add_argument("--raw-archive-dir")
    parser.add_argument("--mstr-source", choices=("LEDGER", "SEC"), default="LEDGER")

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
        raw_archive_dir=Path(args.raw_archive_dir) if args.raw_archive_dir
        else Path(args.output).parent / "raw",
        mstr_source=args.mstr_source,
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
