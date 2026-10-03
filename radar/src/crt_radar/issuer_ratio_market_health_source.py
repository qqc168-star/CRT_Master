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



def build_archived_issuer_ct_inputs(archive: str | Path, *, as_of_ms: int) -> dict:
    """Read retained official bytes only; normalize into the existing CT contract.

    No fetch, inferred effective clock, revision policy, or formal valuation.
    SEC date observations reuse _date_ms and retain DATE precision explicitly.
    Local visibility requires retrieval <= replay time (not just publication).
    """
    from .issuer_fact_history import select_fact_history
    from .treasury_company_ct import ISSUERS

    if type(as_of_ms) is not int or as_of_ms <= 0:
        raise ValueError("Positive replay time required")
    root = Path(archive)
    outputs = {asset: dict(issuer_id=issuer, as_of_ms=as_of_ms,
        asset_history=[], funding_instruments=[], capital_conversion_events=[],
        management_events=[], source_binding={"observations": [], "blockers": []})
        for asset, issuer in ISSUERS.items()}
    burdens = {asset: [] for asset in ISSUERS}
    def block(asset, claim, code):
        outputs[asset]["source_binding"]["blockers"].append(dict(claim=claim, code=code))
    manifest = json.loads((root / "sec-disclosures" / "manifest.json").read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, list):
        raise ValueError("SEC archive manifest must be a list")
    seen = set()
    for item in manifest:
        asset = item.get("asset")
        if asset not in ISSUERS:
            raise ValueError("Unknown archive issuer")
        accession = item.get("accession", "")
        claim = accession or "SEC_DOCUMENT"
        try:
            if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                raise ValueError("SEC_ACCESSION_INVALID")
            primary = item.get("primary", "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", primary):
                raise ValueError("SEC_DOCUMENT_IDENTITY_INVALID")
            expected = _document_url(ASSETS[asset]["cik"], accession, primary)
            if item.get("source_url") != expected:
                raise ValueError("SEC_ISSUER_SOURCE_MISMATCH")
            raw = (root / "sec-disclosures" / f"{asset}-{accession}.html").read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != item.get("raw_sha256"):
                raise ValueError("RAW_HASH_MISMATCH")
            disclosed = _accepted_ms(item.get("accepted", ""))
            retrieved = item.get("retrieved_at_ms")
            if type(retrieved) is not int or not 0 < disclosed <= retrieved:
                raise ValueError("SOURCE_CLOCK_INVALID")
            if retrieved > as_of_ms:
                raise ValueError("NOT_LOCALLY_VISIBLE_AT_REPLAY")
            identity = (asset, accession)
            if identity in seen:
                raise ValueError("DUPLICATE_ACCESSION_REQUIRES_REVIEW")
            seen.add(identity)
            text = _plain(raw)
            if ASSETS[asset]["cik"] not in raw.decode("utf-8"):
                raise ValueError("SEC_DOCUMENT_CIK_MISMATCH")
        except (ValueError, OSError, UnicodeError) as exc:
            block(asset, claim, "ARCHIVE_RAW_UNAVAILABLE" if isinstance(exc, OSError) else str(exc))
            continue
        out = outputs[asset]
        ref = expected + "#sha256=" + digest
        def meta(at, basis):
            return dict(issuer_id=ISSUERS[asset], source_ref=ref,
                verification_state="VALIDATED", effective_time=at,
                disclosure_time=disclosed, first_seen_time=retrieved,
                retrieval_time=retrieved, basis_ref=basis,
                source_semantic=dict(identity=basis, version="V1", effective_from=1, effective_to=None),
                source_evidence=dict(raw_sha256=digest, accession=accession,
                    effective_precision="DATE", effective_date=datetime.fromtimestamp(at / 1000, timezone.utc).date().isoformat(),
                    effective_time_rule="EXISTING_SEC_DATE_UTC_CONVERSION_NOT_INTRADAY_TIME",
                    first_seen_rule="FIRST_PROVEN_LOCAL_ARCHIVE_RETRIEVAL"))
        def event(at, key, source, destination, amount=None, **effects):
            row = dict(**meta(at, "SEC_DISCLOSED_CAPITAL_FLOW"), event_id=accession + ":" + key,
                source=source, destination=destination, amount_usd=amount,
                active_for_calculation=True, consequence_basis_ref=ref, **effects)
            out["capital_conversion_events"].append(row)
            out["management_events"].append(dict(**meta(at, "SEC_DISCLOSED_MANAGEMENT_ACTION"),
                event_id=row["event_id"], action_type=destination, action_ref=ref,
                active_for_calculation=True))
        if asset == "ASST":
            try:
                states = _strive_states(raw, accepted_at_ms=disclosed, source_url=expected)
                if any(r["btc_holdings"] <= 0 or r["diluted_shares"] <= 0 for r in states):
                    raise ValueError("Nonpositive issuer asset")
            except (ValueError, ZeroDivisionError, OverflowError):
                block(asset, "asset_history", "SEC_ASSET_SCHEMA_INVALID")
                states = []
            basis_text = re.search(r"Assumed Fully Diluted Shares Outstanding represents (.*?)\(5\)", text)
            if states and basis_text and "Traditional Warrants are excluded" in basis_text.group(1):
                # Comparison limited to the very same filing's restated pair;
                # no implicit cross-filing split or warrant-basis equivalence.
                basis = "ASST_AFDS_EXCLUDES_TRADITIONAL_WARRANTS:" + digest
                for state in states:
                    out["asset_history"].append(dict(**meta(state["effective_at_ms"], basis),
                        btc_holdings=state["btc_holdings"], diluted_shares=state["diluted_shares"]))
                cash = re.search(r"Cash and cash equivalents \(in thousands\) \$ ([\d,]+) \$ ([\d,]+)", text)
                if cash:
                    for state, value in zip(states, cash.groups()):
                        burdens[asset].append(dict(**meta(state["effective_at_ms"], basis),
                            usd_cash_usd=_scale(value) * 1000))
                preferred = re.search(r"SATA Stock ([\d,]+) ([\d,]+) ([\d,]+)", text)
                if preferred:
                    out["source_binding"]["observations"].append(dict(
                        source_ref=ref, claim="PREFERRED_SHARES_NOT_LIQUIDATION_VALUE",
                        previous_shares=_scale(preferred.group(1)), current_shares=_scale(preferred.group(2)),
                        previous_effective_date=states[0]["effective_at_ms"], current_effective_date=states[1]["effective_at_ms"],
                        disclosure_time=disclosed, retrieval_time=retrieved,
                        limitation="LIQUIDATION_TERMS_AND_ANNUAL_CARRY_COMPONENTS_NOT_BOUND"))
                purchase = re.search(r"Strive purchased ([\d,]+) bitcoin", text)
                if purchase and _scale(purchase.group(1)) == states[1]["btc_holdings"] - states[0]["btc_holdings"]:
                    event(states[1]["effective_at_ms"], "btc-purchase", "FUNDING_SOURCE_UNRESOLVED", "BTC_PURCHASE",
                        btc_change=_scale(purchase.group(1)))
            elif states:
                block(asset, "asset_history", "AFDS_BASIS_UNVERIFIED")
            rate = re.search(r"rate per annum on the Company[’']s SATA Stock at ([\d.]+)%, effective for periods commencing on or after (" + DATE_RE + r")", text, re.I)
            if rate:
                out["source_binding"]["observations"].append(dict(
                    source_ref=ref, claim="SATA_ANNUAL_RATE_TERMS", annual_rate_pct=float(rate.group(1)),
                    effective_date=rate.group(2), interpretation="FORWARD_SENSITIVITY_NOT_HISTORICAL_CARRY",
                    disclosure_time=disclosed, retrieval_time=retrieved))
        else:
            cash = re.search(r"As of " + DATE_RE + r", the balances of the USD Reserve and USD Cash were \$([\d.]+) billion and \$([\d.]+) billion, respectively", text, re.I)
            if cash:
                at = _date_ms(cash)
                burdens[asset].append(dict(**meta(at, "MSTR_SEPARATELY_DISCLOSED_USD_CASH_RESERVE"),
                    usd_reserve_usd=float(cash.group(4)) * 1e9, usd_cash_usd=float(cash.group(5)) * 1e9,
                    reserve_separate_from_cash=True,
                    reserve_usable_for_carry=(True if re.search(
                        r"USD Reserve.*?intended to support the payment of dividends.*?interest on its outstanding indebtedness", text) else None)))
                allocations = re.search(r"\$([\d.]+) million in net proceeds from MSTR Stock sales were used to fund bitcoin purchases and \$([\d.]+) million in net proceeds from MSTR Stock sales were used to fund repurchases of STRC Stock", text)
                if allocations:
                    for key, amount, dest in (("btc-purchase", allocations.group(1), "BTC_PURCHASE"),
                                              ("strc-repurchase-common-funded", allocations.group(2), "STRC_REPURCHASE")):
                        event(at, key, "MSTR_COMMON_ISSUANCE", dest, float(amount) * 1e6)
                    out["funding_instruments"].append(dict(**meta(at, "MSTR_REPORTED_COMMON_ISSUANCE_USE"),
                        instrument_id=accession + ":MSTR_COMMON", instrument_type="COMMON_ATM",
                        observed_funding_use_usd=sum(float(x) for x in allocations.groups()) * 1e6))
                nominal = re.search(r"MSTR Stock [\d,]+ \$ - \$ [\d.]+ (?:\(3\) )?\$ ([\d,.]+) Class A Common Stock Total", text)
                if nominal and allocations:
                    out["funding_instruments"][-1]["reported_remaining_nominal_capacity_usd"] = _scale(nominal.group(1)) * 1e6
                cash_use = re.search(r"used \$([\d.]+) million of USD Cash to fund repurchases of STRC Stock", text)
                if cash_use:
                    event(at, "strc-repurchase-cash-funded", "USD_CASH", "STRC_REPURCHASE",
                        float(cash_use.group(1)) * 1e6, liquidity_change_usd=-float(cash_use.group(1)) * 1e6)
        out["source_binding"]["observations"].append(dict(source_ref=ref,
            disclosure_time=disclosed, first_seen_time=retrieved, retrieval_time=retrieved,
            role="DISCLOSURE_AND_CAPITAL_EVENT_AUTHORITY"))
    for asset, out in outputs.items():
        # Whole pairs, not arbitrary latest rows: retain the latest locally
        # visible filing's explicit comparison while rejecting conflicting
        # values across all retained filings at the same effective date.
        rows = out["asset_history"]
        overlay = {"asset_facts": {"coverage_state": "PARTIAL", "items": [dict(
            asset_fact_id=str(i), fact_type="BTC_SHARE_PAIR", issuer_id=out["issuer_id"],
            quality_state="VALID_REPORTED", effective_at_ms=r["effective_time"],
            value=[r["btc_holdings"], r["diluted_shares"]], unit="BTC_AND_SHARES",
            source_refs=[{"evidence_hash": r["source_evidence"]["raw_sha256"]}]) for i, r in enumerate(rows)]}}
        history = select_fact_history(overlay, fact_type="BTC_SHARE_PAIR", issuer_id=out["issuer_id"])
        if history.get("reason") == "CONFLICTING_FACTS_AT_SAME_EFFECTIVE_TIME":
            out["asset_history"] = []
            block(asset, "asset_history", history["reason"])
        elif rows:
            latest = max(rows, key=lambda r: (r["effective_time"], r["disclosure_time"]))
            out["asset_history"] = sorted([r for r in rows if r["source_ref"] == latest["source_ref"]], key=lambda r: r["effective_time"])
        br = sorted(burdens[asset], key=lambda r: (r["effective_time"], r["disclosure_time"]))
        if br:
            latest = br[-1]
            pair = [r for r in br if r["basis_ref"] == latest["basis_ref"]]
            # MSTR same-date contradictory cash values are never latest-wins.
            if any(len({(r.get("usd_cash_usd"), r.get("usd_reserve_usd")) for r in pair if r["effective_time"] == t}) > 1 for t in {r["effective_time"] for r in pair}):
                block(asset, "burden", "CONFLICTING_BURDEN_AT_SAME_EFFECTIVE_TIME")
            else:
                out["burden_current"] = latest
                older = [r for r in pair if r["effective_time"] < latest["effective_time"]]
                if older:
                    out["burden_previous"] = older[-1]
    for receipt_path in sorted((root / "ledger-raw").glob("retrieval-*.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        try:
            digest = receipt.get("evidence_hash", "")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError("LEDGER_HASH_INVALID")
            retrieved = receipt.get("retrieved_at_ms")
            if (receipt.get("source_url") != "https://www.strategy.com/ledger"
                    or receipt.get("http_status") != 200
                    or type(retrieved) is not int or retrieved > as_of_ms):
                raise ValueError("LEDGER_SOURCE_OR_LOCAL_VISIBILITY_INVALID")
            raw = (root / "ledger-raw" / f"ledger-{digest}.html").read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("LEDGER_RAW_HASH_MISMATCH")
            rows = parse_strategy_ledger(raw, source_url=receipt["source_url"], retrieved_at_ms=retrieved)
            outputs["MSTR"]["source_binding"]["observations"].append({
                "claim": "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME",
                "ct_binding_state": "NOT_CT_BOUND", "reported_comparison": build_ledger_ratio_data(rows)})
        except (ValueError, OSError, UnicodeError) as exc:
            block("MSTR", "ledger", "ARCHIVE_RAW_UNAVAILABLE" if isinstance(exc, OSError) else str(exc))
    block("MSTR", "asset_history", "ADSO_EFFECTIVE_TIME_UNRESOLVED")
    return outputs


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
