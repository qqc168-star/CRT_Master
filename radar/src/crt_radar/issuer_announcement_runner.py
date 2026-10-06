from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse


REGISTRY_SCHEMA = "CRT_ISSUER_ANNOUNCEMENT_REGISTRY_V1"
STATE_SCHEMA = "CRT_ISSUER_ANNOUNCEMENT_STATE_V1"
OUTPUT_SCHEMA = "CRT_ISSUER_ANNOUNCEMENT_WAKE_V1"
LEDGER_SCHEMA = "CRT_ISSUER_ANNOUNCEMENT_EVENT_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/140.0 Safari/537.36 "
    "CRT-Radar/0.5"
)
ZERO_HASH = "0" * 64


class IssuerAnnouncementError(ValueError):
    pass


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        title = " ".join("".join(self._parts).split())
        self.anchors.append((self._href, title))
        self._href = None
        self._parts = []


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _validate_registry(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != REGISTRY_SCHEMA:
        raise IssuerAnnouncementError("issuer announcement registry schema invalid")
    authority = payload.get("authority")
    if not isinstance(authority, dict):
        raise IssuerAnnouncementError("issuer announcement authority missing")
    if authority.get("external_action_authority") != "NONE":
        raise IssuerAnnouncementError("external_action_authority must remain NONE")
    if authority.get("external_action_performed") is not False or authority.get("action_output") != "NONE":
        raise IssuerAnnouncementError("issuer announcement action boundary invalid")
    issuers = payload.get("issuers")
    if not isinstance(issuers, list) or not issuers:
        raise IssuerAnnouncementError("issuers must be a non-empty list")
    issuer_ids: set[str] = set()
    ciks: set[str] = set()
    for issuer in issuers:
        if not isinstance(issuer, dict):
            raise IssuerAnnouncementError("issuer entry invalid")
        issuer_id = issuer.get("issuer_id")
        cik = issuer.get("cik")
        if not isinstance(issuer_id, str) or not issuer_id or issuer_id in issuer_ids:
            raise IssuerAnnouncementError("issuer_id missing or duplicate")
        if not isinstance(cik, str) or not re.fullmatch(r"\d{10}", cik) or cik in ciks:
            raise IssuerAnnouncementError("issuer CIK missing, malformed, or duplicate")
        issuer_ids.add(issuer_id)
        ciks.add(cik)
        for url_field, hosts_field in (
            ("sec_submissions_url", "sec_allowed_hosts"),
            ("press_archive_url", "press_allowed_hosts"),
        ):
            url = issuer.get(url_field)
            hosts = issuer.get(hosts_field)
            if not isinstance(url, str) or urlparse(url).scheme != "https":
                raise IssuerAnnouncementError(f"{issuer_id} {url_field} must be HTTPS")
            if not isinstance(hosts, list) or urlparse(url).hostname not in hosts:
                raise IssuerAnnouncementError(f"{issuer_id} {hosts_field} does not bind source host")
        press_mode = issuer.get("press_mode")
        if press_mode not in {"DISCOVER_LINKS", "Q4_PUBLIC_JSON", "LOCATOR_ONLY_SEC_IS_PRIMARY"}:
            raise IssuerAnnouncementError(f"{issuer_id} press_mode invalid")
        if press_mode == "Q4_PUBLIC_JSON":
            feed_url = issuer.get("press_feed_url")
            allowed_hosts = issuer.get("press_allowed_hosts", [])
            if not isinstance(feed_url, str) or urlparse(feed_url).scheme != "https":
                raise IssuerAnnouncementError(f"{issuer_id} press_feed_url must be HTTPS")
            if urlparse(feed_url).hostname not in allowed_hosts:
                raise IssuerAnnouncementError(f"{issuer_id} press_feed_url host is not authority locked")
    return payload


def load_registry(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssuerAnnouncementError(f"issuer announcement registry unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise IssuerAnnouncementError("issuer announcement registry must be an object")
    return _validate_registry(payload)


def _fetch_bytes(
    url: str,
    *,
    allowed_hosts: list[str],
    timeout_seconds: int,
    maximum_response_bytes: int,
) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html;q=0.9,text/plain;q=0.8",
            "Accept-Encoding": "identity",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://{urlparse(url).hostname}/",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if urlparse(final_url).scheme != "https" or urlparse(final_url).hostname not in allowed_hosts:
                raise IssuerAnnouncementError("source redirected outside its authority-locked host")
            raw = response.read(maximum_response_bytes + 1)
            if len(raw) > maximum_response_bytes:
                raise IssuerAnnouncementError("source response exceeds maximum_response_bytes")
            content_type = response.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IssuerAnnouncementError(f"source fetch failed: {type(exc).__name__}: {exc}") from exc
    return raw, content_type, final_url


def _event_classification(form: str, items: str, title: str, material_keywords: list[str]) -> str:
    item_set = {part.strip() for part in items.split(",") if part.strip()}
    if form in {"424B2", "424B3", "424B5", "FWP", "S-1", "S-3", "EFFECT"} or "3.02" in item_set:
        return "CAPITAL_RAISE_OR_DILUTION"
    if "2.03" in item_set:
        return "DEBT_OR_FINANCING"
    if "2.02" in item_set or form in {"10-Q", "10-K"}:
        return "FINANCIAL_RESULTS"
    if "1.01" in item_set:
        return "MATERIAL_AGREEMENT"
    if "5.02" in item_set:
        return "GOVERNANCE_CHANGE"
    lowered = title.lower()
    if "financial results" in lowered or "earnings" in lowered:
        return "FINANCIAL_RESULTS"
    if any(keyword in lowered for keyword in ("offering", "at-the-market", "issuance")):
        return "CAPITAL_RAISE_OR_DILUTION"
    if any(keyword in lowered for keyword in ("debt", "senior notes", "convertible notes")):
        return "DEBT_OR_FINANCING"
    if any(keyword in lowered for keyword in ("acquisition", "merger")):
        return "MATERIAL_AGREEMENT"
    if any(keyword in lowered for keyword in material_keywords):
        return "CAPITAL_OR_TREASURY_POLICY"
    if form == "8-K":
        return "MATERIAL_CURRENT_REPORT"
    if form in {"DEF 14A", "PRE 14A"}:
        return "PROXY_OR_GOVERNANCE"
    return "OFFICIAL_ANNOUNCEMENT"


def parse_sec_submissions(
    issuer: dict[str, Any],
    payload: dict[str, Any],
    *,
    material_forms: list[str],
    material_keywords: list[str],
) -> list[dict[str, Any]]:
    cik = str(payload.get("cik", "")).zfill(10)
    if cik != issuer["cik"]:
        raise IssuerAnnouncementError(f"{issuer['issuer_id']} SEC CIK mismatch")
    name = str(payload.get("name", "")).strip().upper()
    aliases = {str(value).strip().upper() for value in issuer.get("name_aliases", [])}
    if name not in aliases:
        raise IssuerAnnouncementError(f"{issuer['issuer_id']} SEC issuer name mismatch")
    recent = payload.get("filings", {}).get("recent")
    if not isinstance(recent, dict):
        raise IssuerAnnouncementError(f"{issuer['issuer_id']} SEC recent filings missing")
    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        raise IssuerAnnouncementError(f"{issuer['issuer_id']} SEC accession list missing")
    events: list[dict[str, Any]] = []
    material_form_set = set(material_forms)
    cik_no_zero = str(int(issuer["cik"]))
    for index, accession in enumerate(accessions):
        try:
            form = str(recent.get("form", [])[index])
            filing_date = str(recent.get("filingDate", [])[index])
            primary_document = str(recent.get("primaryDocument", [])[index])
        except (IndexError, TypeError):
            raise IssuerAnnouncementError(f"{issuer['issuer_id']} SEC parallel arrays invalid") from None
        if form not in material_form_set:
            continue
        items_values = recent.get("items", [])
        descriptions = recent.get("primaryDocDescription", [])
        acceptance_values = recent.get("acceptanceDateTime", [])
        report_values = recent.get("reportDate", [])
        items = str(items_values[index]) if index < len(items_values) else ""
        description = str(descriptions[index]) if index < len(descriptions) else ""
        acceptance = str(acceptance_values[index]) if index < len(acceptance_values) else ""
        report_date = str(report_values[index]) if index < len(report_values) else ""
        accession_compact = str(accession).replace("-", "")
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zero}/{accession_compact}/{primary_document}"
        title = " ".join(part for part in (issuer["official_name"], form, items, description) if part).strip()
        event = {
            "event_id": f"{issuer['issuer_id']}:SEC:{accession}",
            "issuer_id": issuer["issuer_id"],
            "issuer_name": issuer["official_name"],
            "source_type": "SEC_FILING",
            "source_id": f"SEC_SUBMISSIONS_{issuer['cik']}",
            "source_url": filing_url,
            "accession_number": accession,
            "filing_date": filing_date,
            "report_date": report_date or None,
            "accepted_at": acceptance or None,
            "form": form,
            "items": items,
            "title": title,
            "classification": _event_classification(form, items, title, material_keywords),
            "symbols": list(issuer.get("symbols", [])),
            "position_relevance": list(issuer.get("position_relevance", [])),
        }
        event["event_hash"] = _canonical_hash(event)
        events.append(event)
    return events


def parse_strategy_press_archive(
    issuer: dict[str, Any],
    raw: bytes,
    *,
    source_url: str,
    material_keywords: list[str],
) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IssuerAnnouncementError("Strategy press archive is not UTF-8") from exc
    parser = _AnchorParser()
    parser.feed(text)
    events_by_url: dict[str, dict[str, Any]] = {}
    for href, title in parser.anchors:
        absolute = urljoin(source_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme != "https" or parsed.hostname not in issuer.get("press_allowed_hosts", []):
            continue
        if not parsed.path.startswith("/press/") or not title:
            continue
        date_match = re.search(r"_(\d{2})-(\d{2})-(\d{4})/?$", parsed.path)
        filing_date = None
        if date_match:
            filing_date = f"{date_match.group(3)}-{date_match.group(1)}-{date_match.group(2)}"
        event = {
            "event_id": f"{issuer['issuer_id']}:PRESS:{hashlib.sha256(absolute.encode('utf-8')).hexdigest()}",
            "issuer_id": issuer["issuer_id"],
            "issuer_name": issuer["official_name"],
            "source_type": "OFFICIAL_PRESS_RELEASE",
            "source_id": "STRATEGY_OFFICIAL_PRESS_ARCHIVE",
            "source_url": absolute,
            "accession_number": None,
            "filing_date": filing_date,
            "report_date": None,
            "accepted_at": None,
            "form": None,
            "items": "",
            "title": title,
            "classification": _event_classification("", "", title, material_keywords),
            "symbols": list(issuer.get("symbols", [])),
            "position_relevance": list(issuer.get("position_relevance", [])),
        }
        event["event_hash"] = _canonical_hash(event)
        events_by_url[absolute] = event
    if not events_by_url:
        raise IssuerAnnouncementError("Strategy press archive yielded no release links")
    return list(events_by_url.values())


def parse_q4_press_feed(
    issuer: dict[str, Any],
    raw: bytes,
    *,
    source_url: str,
    material_keywords: list[str],
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IssuerAnnouncementError("Q4 press feed is not valid UTF-8 JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("d"), str):
        try:
            payload = json.loads(payload["d"])
        except json.JSONDecodeError as exc:
            raise IssuerAnnouncementError("Q4 press feed wrapper is invalid") from exc
    if not isinstance(payload, dict):
        raise IssuerAnnouncementError("Q4 press feed root invalid")
    rows = payload.get("GetPressReleaseListResult")
    if not isinstance(rows, list):
        raise IssuerAnnouncementError("Q4 press release list missing")
    events_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise IssuerAnnouncementError("Q4 press release row invalid")
        press_release_id = str(row.get("PressReleaseId", "")).strip()
        title = " ".join(str(row.get("Headline", "")).split())
        link = str(row.get("LinkToDetailPage", "")).strip()
        date_text = str(row.get("PressReleaseDate", "")).strip()
        if not press_release_id or not title or not link or not date_text:
            raise IssuerAnnouncementError("Q4 press release identity fields missing")
        absolute = urljoin(source_url, link)
        parsed = urlparse(absolute)
        if parsed.scheme != "https" or parsed.hostname not in issuer.get("press_allowed_hosts", []):
            raise IssuerAnnouncementError("Q4 press release link escaped authority-locked host")
        if not (
            parsed.path.startswith("/news-events/news-releases/news-details/")
            or parsed.path.startswith("/files/doc_news/")
            or parsed.path.startswith("/files/doc_downloads/")
        ):
            raise IssuerAnnouncementError("Q4 press release link path is outside the official archive")
        date_match = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_text)
        if not date_match:
            raise IssuerAnnouncementError("Q4 press release date invalid")
        filing_date = f"{date_match.group(3)}-{date_match.group(1)}-{date_match.group(2)}"
        event = {
            "event_id": f"{issuer['issuer_id']}:PRESS:{press_release_id}",
            "issuer_id": issuer["issuer_id"],
            "issuer_name": issuer["official_name"],
            "source_type": "OFFICIAL_PRESS_RELEASE",
            "source_id": "STRIVE_Q4_OFFICIAL_PRESS_FEED",
            "source_url": absolute,
            "accession_number": None,
            "filing_date": filing_date,
            "report_date": None,
            "accepted_at": None,
            "form": None,
            "items": "",
            "title": title,
            "classification": _event_classification("", "", title, material_keywords),
            "symbols": list(issuer.get("symbols", [])),
            "position_relevance": list(issuer.get("position_relevance", [])),
        }
        event["event_hash"] = _canonical_hash(event)
        events_by_id[event["event_id"]] = event
    if not events_by_id:
        raise IssuerAnnouncementError("Q4 press feed yielded no releases")
    return list(events_by_id.values())



class _DocumentTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def _document_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    parser = _DocumentTextParser()
    parser.feed(text)
    return re.sub(
        r"\s+",
        " ",
        " ".join(parser.parts),
    ).strip()


def _event_accepted_at_ms(
    event: dict[str, Any],
) -> int | None:
    value = event.get("accepted_at")
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()

    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}\d{2}:\d{2}:\d{2}(?:\.\d+)?Z",
        text,
    ):
        text = text[:10] + "T" + text[10:]

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return int(parsed.timestamp() * 1000)


def _decision_relevant_event(
    event: dict[str, Any],
) -> bool:
    # SEC material filings are explicitly allowlisted by the registry.
    if event.get("source_type") == "SEC_FILING":
        return True

    # Ordinary corporate publicity is retained as observed, but it must
    # not wake GPT unless its title was classified into a CRT-relevant
    # capital / treasury / financial / governance event.
    return event.get("classification") != "OFFICIAL_ANNOUNCEMENT"


def _decision_excerpt(
    text: str,
    material_keywords: list[str],
) -> str:
    if not text:
        return ""

    lower = text.lower()
    needles = sorted(
        {
            *material_keywords,
            "daily dividend",
            "semi-monthly",
            "record date",
            "payment date",
            "shareholder approval",
            "stockholder approval",
            "subject to approval",
        },
        key=len,
        reverse=True,
    )

    snippets: list[str] = []

    for needle in needles:
        pos = lower.find(needle.lower())
        if pos < 0:
            continue

        start = max(0, pos - 220)
        end = min(len(text), pos + 650)
        snippet = text[start:end].strip()

        if snippet and snippet not in snippets:
            snippets.append(snippet)

        if sum(len(item) for item in snippets) >= 1600:
            break

    if not snippets:
        return text[:1200]

    return " ... ".join(snippets)[:1600]


def _policy_stage(
    title: str,
    text: str,
) -> str:
    probe = f"{title} {text}".lower()

    # Proposal language wins over hypothetical future-effective wording.
    if (
        re.search(r"\bpropos(?:e|es|ed|al)\b", probe)
        or "subject to shareholder approval" in probe
        or "subject to stockholder approval" in probe
        or "if approved" in probe
    ):
        return "PROPOSED"

    if (
        re.search(
            r"\b(?:shareholders?|stockholders?)\s+"
            r"(?:have\s+)?approved\b",
            probe,
        )
        or re.search(
            r"\bapproved by\s+"
            r"(?:shareholders?|stockholders?)\b",
            probe,
        )
    ):
        return "APPROVED"

    if re.search(
        r"\b(?:became effective|is effective|effective as of)\b",
        probe,
    ):
        return "EFFECTIVE"

    return "UNRESOLVED"


def _proposed_distribution_cadence(
    stage: str,
    title: str,
    text: str,
) -> str | None:
    if stage != "PROPOSED":
        return None

    probe = f"{title} {text}".lower()

    if re.search(
        r"\bpropos\w*.{0,160}\bdaily dividends?\b"
        r"|\bdaily dividends?\b.{0,160}\bpropos\w*",
        probe,
    ):
        return "DAILY"

    if re.search(
        r"\bpropos\w*.{0,160}\bsemi-monthly\b"
        r"|\bsemi-monthly\b.{0,160}\bpropos\w*",
        probe,
    ):
        return "SEMI_MONTHLY"

    if re.search(
        r"\bpropos\w*.{0,160}\bmonthly\b"
        r"|\bmonthly\b.{0,160}\bpropos\w*",
        probe,
    ):
        return "MONTHLY"

    return None


def _normalized_official_facts(
    event: dict[str, Any],
    raw: bytes,
    *,
    observed_at_ms: int,
) -> list[dict[str, Any]]:
    if event.get("source_type") != "SEC_FILING":
        return []

    accepted_at_ms = _event_accepted_at_ms(event)
    if accepted_at_ms is None:
        return []

    facts: list[dict[str, Any]] = []

    if event.get("issuer_id") == "STRATEGY_INC":
        from .strategy_capital_fact_adapter import (
            StrategyCapitalFactError,
            build_strategy_capital_reflexivity_input,
        )

        for mode in ("MSTR_CAPITAL", "STRC_DIVIDEND"):
            try:
                result = build_strategy_capital_reflexivity_input(
                    raw,
                    mode=mode,
                    document_id=str(event["event_id"]),
                    accepted_at_ms=accepted_at_ms,
                    retrieved_at_ms=observed_at_ms,
                )
            except StrategyCapitalFactError:
                continue

            section = result.get("issuer_facts", {})
            rows = section.get("items", [])
            if isinstance(rows, list):
                facts.extend(
                    deepcopy(row)
                    for row in rows
                    if isinstance(row, dict)
                )

    elif event.get("issuer_id") == "STRIVE_INC":
        from .strive_capital_fact_adapter import (
            StriveCapitalFactError,
            build_strive_capital_reflexivity_input,
        )

        for mode in ("ASST_CAPITAL", "SATA_TERMS"):
            try:
                result = build_strive_capital_reflexivity_input(
                    raw,
                    mode=mode,
                    document_id=str(event["event_id"]),
                    accepted_at_ms=accepted_at_ms,
                    retrieved_at_ms=observed_at_ms,
                )
            except StriveCapitalFactError:
                continue

            section = result.get("issuer_facts", {})
            rows = section.get("items", [])
            if isinstance(rows, list):
                facts.extend(
                    deepcopy(row)
                    for row in rows
                    if isinstance(row, dict)
                )

    deduped: dict[str, dict[str, Any]] = {}

    for fact in facts:
        fact_id = fact.get("fact_id")
        if isinstance(fact_id, str) and fact_id:
            deduped[fact_id] = fact

    return [
        deduped[key]
        for key in sorted(deduped)
    ]


def _enrich_new_event(
    event: dict[str, Any],
    issuer: dict[str, Any],
    *,
    fetcher: Callable[..., tuple[bytes, str, str]],
    observed_at_ms: int,
    timeout_seconds: int,
    maximum_response_bytes: int,
    material_keywords: list[str],
) -> dict[str, Any]:
    source_type = event.get("source_type")

    if source_type == "SEC_FILING":
        allowed_hosts = issuer["sec_allowed_hosts"]
    else:
        allowed_hosts = issuer["press_allowed_hosts"]

    raw, content_type, final_url = fetcher(
        event["source_url"],
        allowed_hosts=allowed_hosts,
        timeout_seconds=timeout_seconds,
        maximum_response_bytes=maximum_response_bytes,
    )

    if content_type not in {
        "text/html",
        "text/plain",
        "application/xhtml+xml",
    }:
        raise IssuerAnnouncementError(
            "issuer event document content type is not text"
        )

    text = _document_text(raw)

    if not text:
        raise IssuerAnnouncementError(
            "issuer event document yielded no text"
        )

    enriched = deepcopy(event)
    enriched.pop("event_hash", None)

    enriched["document_state"] = "VALID"
    enriched["document_url"] = final_url
    enriched["document_evidence_hash"] = hashlib.sha256(raw).hexdigest()
    enriched["decision_excerpt"] = _decision_excerpt(
        text,
        material_keywords,
    )

    stage = _policy_stage(
        str(enriched.get("title", "")),
        text,
    )
    enriched["policy_stage"] = stage

    cadence = _proposed_distribution_cadence(
        stage,
        str(enriched.get("title", "")),
        text,
    )
    if cadence is not None:
        enriched["proposed_distribution_cadence"] = cadence

    normalized_facts = _normalized_official_facts(
        enriched,
        raw,
        observed_at_ms=observed_at_ms,
    )
    enriched["normalized_fact_count"] = len(normalized_facts)
    enriched["normalized_facts"] = normalized_facts
    enriched["normalization_state"] = (
        "AVAILABLE"
        if normalized_facts
        else "NO_MATCH_OR_DISCLOSURE_CLOCK_UNRESOLVED"
    )

    enriched["event_hash"] = _canonical_hash(enriched)

    return enriched


def _load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssuerAnnouncementError(f"issuer announcement state invalid: {exc}") from exc
    if payload.get("schema_version") != STATE_SCHEMA:
        raise IssuerAnnouncementError("issuer announcement state schema invalid")
    seen = payload.get("seen_event_ids")
    if not isinstance(seen, list) or not all(isinstance(value, str) for value in seen):
        raise IssuerAnnouncementError("issuer announcement seen_event_ids invalid")
    baselined = payload.get("baselined_sources")
    if not isinstance(baselined, list) or not all(isinstance(value, str) for value in baselined):
        raise IssuerAnnouncementError("issuer announcement baselined_sources invalid")
    return payload


def _append_ledger(path: Path, events: list[dict[str, Any]], detected_at_ms: int) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = ZERO_HASH
    sequence = 0
    if path.exists():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            try:
                tail = json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                raise IssuerAnnouncementError("issuer event ledger tail invalid") from exc
            previous_hash = str(tail.get("record_hash"))
            sequence = int(tail.get("sequence", 0))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for event in sorted(events, key=lambda row: (str(row.get("filing_date")), row["event_id"])):
            sequence += 1
            record = {
                "schema_version": LEDGER_SCHEMA,
                "sequence": sequence,
                "detected_at_ms": detected_at_ms,
                "event": event,
                "previous_record_hash": previous_hash,
                "action_output": "NONE",
                "external_action_authority": "NONE",
                "external_action_performed": False,
            }
            record["record_hash"] = _canonical_hash(record)
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            previous_hash = record["record_hash"]
        handle.flush()
        os.fsync(handle.fileno())


def run_issuer_announcement_cycle(
    registry: dict[str, Any],
    *,
    state_path: str | Path,
    ledger_path: str | Path,
    now_ms: int | None = None,
    fetcher: Callable[..., tuple[bytes, str, str]] | None = None,
) -> dict[str, Any]:
    _validate_registry(registry)
    observed_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    policy = registry["poll_policy"]
    timeout_seconds = int(policy["timeout_seconds"])
    maximum_response_bytes = int(policy["maximum_response_bytes"])
    material_forms = [str(value) for value in registry["material_forms"]]
    material_keywords = [str(value).lower() for value in registry["material_title_keywords"]]
    active_fetcher = _fetch_bytes if fetcher is None else fetcher
    events_by_id: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []

    for issuer in registry["issuers"]:
        sec_url = issuer["sec_submissions_url"]
        try:
            raw, content_type, final_url = active_fetcher(
                sec_url,
                allowed_hosts=issuer["sec_allowed_hosts"],
                timeout_seconds=timeout_seconds,
                maximum_response_bytes=maximum_response_bytes,
            )
            if content_type not in {"application/json", "text/json", "text/plain"}:
                raise IssuerAnnouncementError("SEC submissions content type invalid")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise IssuerAnnouncementError("SEC submissions root invalid")
            events = parse_sec_submissions(
                issuer,
                payload,
                material_forms=material_forms,
                material_keywords=material_keywords,
            )
            events_by_id.update({event["event_id"]: event for event in events})
            coverage.append({
                "source_key": f"{issuer['issuer_id']}:SEC_FILING",
                "issuer_id": issuer["issuer_id"],
                "source_type": "SEC_FILING",
                "state": "VALID",
                "event_count": len(events),
                "source_url": final_url,
            })
        except (IssuerAnnouncementError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            coverage.append({
                "source_key": f"{issuer['issuer_id']}:SEC_FILING",
                "issuer_id": issuer["issuer_id"],
                "source_type": "SEC_FILING",
                "state": "BLOCKED",
                "reason": f"{type(exc).__name__}: {exc}",
                "source_url": sec_url,
            })

        press_mode = issuer.get("press_mode")
        if press_mode == "LOCATOR_ONLY_SEC_IS_PRIMARY":
            coverage.append({
                "source_key": f"{issuer['issuer_id']}:OFFICIAL_PRESS_RELEASE",
                "issuer_id": issuer["issuer_id"],
                "source_type": "OFFICIAL_PRESS_RELEASE",
                "state": "LOCATOR_ONLY",
                "reason": "SEC_IS_PRIMARY_UNTIL_STABLE_OFFICIAL_ARCHIVE_PARSER_EXISTS",
                "source_url": issuer["press_archive_url"],
            })
            continue
        press_url = issuer.get("press_feed_url", issuer["press_archive_url"])
        try:
            raw, content_type, final_url = active_fetcher(
                press_url,
                allowed_hosts=issuer["press_allowed_hosts"],
                timeout_seconds=timeout_seconds,
                maximum_response_bytes=maximum_response_bytes,
            )
            if press_mode == "DISCOVER_LINKS":
                if content_type not in {"text/html", "text/plain"}:
                    raise IssuerAnnouncementError("press archive content type invalid")
                events = parse_strategy_press_archive(
                    issuer,
                    raw,
                    source_url=final_url,
                    material_keywords=material_keywords,
                )
            elif press_mode == "Q4_PUBLIC_JSON":
                if content_type not in {"application/json", "text/json", "text/plain"}:
                    raise IssuerAnnouncementError("Q4 press feed content type invalid")
                events = parse_q4_press_feed(
                    issuer,
                    raw,
                    source_url=issuer["press_archive_url"],
                    material_keywords=material_keywords,
                )
            else:
                raise IssuerAnnouncementError("unsupported press_mode")
            events_by_id.update({event["event_id"]: event for event in events})
            coverage.append({
                "source_key": f"{issuer['issuer_id']}:OFFICIAL_PRESS_RELEASE",
                "issuer_id": issuer["issuer_id"],
                "source_type": "OFFICIAL_PRESS_RELEASE",
                "state": "VALID",
                "event_count": len(events),
                "source_url": final_url,
            })
        except IssuerAnnouncementError as exc:
            coverage.append({
                "source_key": f"{issuer['issuer_id']}:OFFICIAL_PRESS_RELEASE",
                "issuer_id": issuer["issuer_id"],
                "source_type": "OFFICIAL_PRESS_RELEASE",
                "state": "BLOCKED",
                "reason": f"{type(exc).__name__}: {exc}",
                "source_url": press_url,
            })

    state_target = Path(state_path)
    previous_state = _load_state(state_target)
    previously_seen = set(previous_state.get("seen_event_ids", [])) if previous_state else set()
    previously_baselined = set(previous_state.get("baselined_sources", [])) if previous_state else set()
    discovered_ids = set(events_by_id)
    valid_source_keys = {row["source_key"] for row in coverage if row["state"] == "VALID"}
    newly_baselined_sources = valid_source_keys - previously_baselined
    observed_new_events = []
    for event_id in sorted(discovered_ids - previously_seen):
        event = events_by_id[event_id]
        source_key = f"{event['issuer_id']}:{event['source_type']}"
        if source_key in previously_baselined:
            observed_new_events.append(event)

    suppressed_event_count = 0
    new_events = []

    for event in observed_new_events:
        if not _decision_relevant_event(event):
            suppressed_event_count += 1
            continue

        issuer = next(
            row
            for row in registry["issuers"]
            if row["issuer_id"] == event["issuer_id"]
        )

        try:
            enriched = _enrich_new_event(
                event,
                issuer,
                fetcher=active_fetcher,
                observed_at_ms=observed_at_ms,
                timeout_seconds=timeout_seconds,
                maximum_response_bytes=maximum_response_bytes,
                material_keywords=material_keywords,
            )
        except IssuerAnnouncementError as exc:
            enriched = deepcopy(event)
            enriched.pop("event_hash", None)
            enriched["document_state"] = "BLOCKED"
            enriched["document_reason"] = (
                f"{type(exc).__name__}: {exc}"
            )
            enriched["normalized_fact_count"] = 0
            enriched["normalized_facts"] = []
            enriched["normalization_state"] = "BLOCKED"
            enriched["policy_stage"] = "UNRESOLVED"
            enriched["event_hash"] = _canonical_hash(enriched)

        new_events.append(enriched)

    seen_event_ids = sorted(previously_seen | discovered_ids)
    baselined_sources = sorted(previously_baselined | valid_source_keys)
    blocked_count = sum(1 for row in coverage if row["state"] == "BLOCKED")
    valid_count = sum(1 for row in coverage if row["state"] == "VALID")
    if valid_count == 0:
        coverage_state = "BLOCKED"
    elif blocked_count:
        coverage_state = "PARTIAL"
    else:
        coverage_state = "VALID"
    if new_events:
        wake_state = "REANALYSIS_REQUESTED"
        reason = "NEW_OFFICIAL_ISSUER_ANNOUNCEMENT"
    elif observed_new_events:
        wake_state = "NO_WAKE"
        reason = "NEW_OFFICIAL_ANNOUNCEMENT_NOT_DECISION_RELEVANT"
    elif newly_baselined_sources:
        wake_state = "NO_WAKE"
        reason = "BASELINE_ESTABLISHED"
    elif coverage_state == "BLOCKED":
        wake_state = "NO_WAKE"
        reason = "SOURCE_COVERAGE_BLOCKED"
    elif coverage_state == "PARTIAL":
        wake_state = "NO_WAKE"
        reason = "SOURCE_COVERAGE_PARTIAL"
    else:
        wake_state = "NO_WAKE"
        reason = "NO_NEW_OFFICIAL_ISSUER_ANNOUNCEMENT"

    state_payload = {
        "schema_version": STATE_SCHEMA,
        "last_poll_at_ms": observed_at_ms,
        "seen_event_ids": seen_event_ids[-5000:],
        "baselined_sources": baselined_sources,
        "coverage": coverage,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    state_payload["state_hash"] = _canonical_hash(state_payload)
    _write_json_atomic(state_target, state_payload)
    _append_ledger(Path(ledger_path), new_events, observed_at_ms)

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": wake_state,
        "reason": reason,
        "observed_at_ms": observed_at_ms,
        "baseline_established_before_poll": bool(previously_baselined),
        "coverage_state": coverage_state,
        "coverage": coverage,
        "observed_new_event_count": len(observed_new_events),
        "suppressed_event_count": suppressed_event_count,
        "new_event_count": len(new_events),
        "new_events": new_events,
        "analyst_reanalysis_requested": wake_state == "REANALYSIS_REQUESTED",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    result["wake_hash"] = _canonical_hash(result)
    return result



def validate_issuer_announcement_wake(
    payload: dict[str, Any],
    *,
    generated_at_ms: int | None = None,
) -> dict[str, Any]:
    """Validate one issuer-announcement radar output without inventing meaning."""

    if not isinstance(payload, dict):
        raise IssuerAnnouncementError(
            "issuer announcement wake must be an object"
        )
    if payload.get("schema_version") != OUTPUT_SCHEMA:
        raise IssuerAnnouncementError(
            "issuer announcement wake schema invalid"
        )

    expected_authority = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    for key, value in expected_authority.items():
        if payload.get(key) != value:
            raise IssuerAnnouncementError(
                f"issuer announcement {key} must remain {value!r}"
            )

    supplied_hash = payload.get("wake_hash")
    if not isinstance(supplied_hash, str):
        raise IssuerAnnouncementError(
            "issuer announcement wake_hash missing"
        )
    material = deepcopy(payload)
    material.pop("wake_hash", None)
    if supplied_hash != _canonical_hash(material):
        raise IssuerAnnouncementError(
            "issuer announcement wake_hash mismatch"
        )

    observed_at_ms = payload.get("observed_at_ms")
    if (
        type(observed_at_ms) is not int
        or observed_at_ms <= 0
    ):
        raise IssuerAnnouncementError(
            "issuer announcement observed_at_ms invalid"
        )
    if (
        generated_at_ms is not None
        and observed_at_ms > generated_at_ms
    ):
        raise IssuerAnnouncementError(
            "issuer announcement clock is in the future"
        )

    state = payload.get("state")
    if state not in {"NO_WAKE", "REANALYSIS_REQUESTED"}:
        raise IssuerAnnouncementError(
            "issuer announcement wake state invalid"
        )

    events = payload.get("new_events")
    if not isinstance(events, list):
        raise IssuerAnnouncementError(
            "issuer announcement new_events must be a list"
        )
    if payload.get("new_event_count") != len(events):
        raise IssuerAnnouncementError(
            "issuer announcement event count mismatch"
        )

    for event in events:
        if not isinstance(event, dict):
            raise IssuerAnnouncementError(
                "issuer announcement event invalid"
            )

        for key in (
            "event_id",
            "issuer_id",
            "source_type",
            "source_id",
            "source_url",
            "classification",
            "event_hash",
        ):
            if not isinstance(event.get(key), str) or not event[key]:
                raise IssuerAnnouncementError(
                    f"issuer announcement event {key} invalid"
                )

        event_hash = event["event_hash"]
        event_material = deepcopy(event)
        event_material.pop("event_hash", None)
        if event_hash != _canonical_hash(event_material):
            raise IssuerAnnouncementError(
                "issuer announcement event_hash mismatch"
            )

    requested = state == "REANALYSIS_REQUESTED"
    if payload.get("analyst_reanalysis_requested") is not requested:
        raise IssuerAnnouncementError(
            "issuer announcement reanalysis flag mismatch"
        )

    if requested:
        if payload.get("reason") != "NEW_OFFICIAL_ISSUER_ANNOUNCEMENT":
            raise IssuerAnnouncementError(
                "issuer announcement wake reason invalid"
            )
        if not events:
            raise IssuerAnnouncementError(
                "issuer announcement wake has no triggering event"
            )

    return deepcopy(payload)


def compact_issuer_announcement_wake(
    payload: dict[str, Any],
    *,
    generated_at_ms: int | None = None,
) -> dict[str, Any]:
    """Keep decision-critical public issuer-event facts for GPT transport."""

    validated = validate_issuer_announcement_wake(
        payload,
        generated_at_ms=generated_at_ms,
    )
    compact_events: list[dict[str, Any]] = []

    for event in validated["new_events"]:
        row = {
            key: deepcopy(event.get(key))
            for key in (
                "event_id",
                "event_hash",
                "issuer_id",
                "source_type",
                "source_url",
                "accession_number",
                "filing_date",
                "accepted_at",
                "form",
                "items",
                "title",
                "classification",
                "symbols",
                "position_relevance",
                "document_state",
                "document_evidence_hash",
                "policy_stage",
                "proposed_distribution_cadence",
                "normalization_state",
            )
            if key in event
        }

        excerpt = event.get("decision_excerpt")
        if isinstance(excerpt, str) and excerpt:
            row["decision_excerpt"] = excerpt[:700]

        facts = event.get("normalized_facts")
        if isinstance(facts, list) and facts:
            row["normalized_facts"] = [
                {
                    key: deepcopy(fact.get(key))
                    for key in (
                        "issuer_id",
                        "security_id",
                        "fact_type",
                        "value",
                        "unit",
                        "effective_at_ms",
                        "quality_state",
                    )
                }
                for fact in facts
                if isinstance(fact, dict)
            ]

        compact_events.append(row)

    return {
        "schema_version": validated["schema_version"],
        "state": validated["state"],
        "reason": validated["reason"],
        "observed_at_ms": validated["observed_at_ms"],
        "coverage_state": validated["coverage_state"],
        "new_event_count": validated["new_event_count"],
        "new_events": compact_events,
        "analyst_reanalysis_requested": (
            validated["analyst_reanalysis_requested"]
        ),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "wake_hash": validated["wake_hash"],
    }


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "CONFIG" / "ISSUER_ANNOUNCEMENT_REGISTRY_V1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll official Strategy and Strive issuer announcements read-only.")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    registry = load_registry(args.registry)
    result = run_issuer_announcement_cycle(
        registry,
        state_path=args.state,
        ledger_path=args.ledger,
    )
    _write_json_atomic(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
