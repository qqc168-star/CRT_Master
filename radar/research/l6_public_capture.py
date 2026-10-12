"""Operator-only acquisition for the existing locked L6 archive intake.

No scheduler, runtime mutation, alternative venue, or metric implementation.
Raw bytes and first-seen metadata use the existing acquisition store. Provider
failures are retained per source; a completed capture is not data qualification.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import zipfile
import io
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import candidate_acquisition as acquisition
from prospective_capture import fetch_official_bytes
from crt_radar import l6_source_binding as l6

PROXY = "PRICE_STRUCTURE_CONTEXT"


def proxy_source():
    from crt_radar.source_registry import SourceRegistry
    from crt_radar.source_gate_runner import default_registry_path
    registry = SourceRegistry.load(default_registry_path())
    registry.with_l6_candidate_sources()  # Verify the existing base registry seal.
    spec = registry.by_input_family(PROXY)
    l6.require(spec.parser_id == "BINANCE_PRICE_STRUCTURE_PROXY_V1"
               and spec.raw["formal_composite_authority"] == "NONE", "L6_PROXY_CONTRACT_CONFLICT")
    return registry, spec


def utc_date(at):
    return datetime.fromtimestamp(at / 1000, timezone.utc).strftime("%Y-%m-%d")


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


class ArchiveLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.extend(unescape(v) for k, v in attrs if k == "href" and v)


def quarterly_links(page):
    links = ArchiveLinks()
    links.feed(page.decode("utf-8"))
    # Only complete quarterly ZIPs explicitly linked by the locked documentation.
    # Multipart/full archives never masquerade as a complete quarterly ZIP.
    return sorted(set(u for u in links.urls if re.fullmatch(
        r"https://assets\.kraken\.com/marketing/institutions/Kraken_OHLCVT_20\d\dQ[1-4]\.zip", u)))


def quarterly_feasibility(urls, end):
    # A quarter name provides only an upper bound, never actual coverage or
    # publication proof. If even that bound is old, downloading cannot fix it.
    bounds = []
    for url in urls:
        match = re.search(r"_(20\d\d)Q([1-4])\.zip$", url)
        year, quarter = map(int, match.groups())
        year, month = (year+1, 1) if quarter == 4 else (year, quarter*3+1)
        bounds.append(int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp()*1000))
    latest = max(bounds) if bounds else None
    return {"state":"POTENTIALLY_COVERS_WINDOW_NOT_YET_VERIFIED" if latest and latest >= end else "BLOCKED",
            "latest_nominal_utc_day":utc_date(latest-l6.DAY) if latest else None,
            "archive_publication_time":"NOT_PROVEN", "reason":"L6_KRAKEN_QUARTERLY_PUBLICATION_LAG"
            if latest is None or latest < end else None}


def request_allowed(url, documentation, archives, proxy_url=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        return False
    if url == documentation or url in archives or url == proxy_url:
        return True
    if parsed.netloc == "api.exchange.coinbase.com" and parsed.path == "/products/BTC-USD/candles":
        from urllib.parse import parse_qs
        return parse_qs(parsed.query).get("granularity") == ["86400"]
    if parsed.netloc == "www.bitstamp.net" and parsed.path == "/api/v2/ohlc/btcusd/":
        from urllib.parse import parse_qs
        return parse_qs(parsed.query).get("step") == ["86400"]
    return bool(re.fullmatch(
        r"https://data\.binance\.vision/data/spot/daily/aggTrades/BTCUSDT/"
        r"BTCUSDT-aggTrades-\d{4}-\d{2}-\d{2}\.zip(?:\.CHECKSUM)?", url))


class Capture:
    def __init__(self, root, authority, *, fetcher, max_archive_bytes):
        self.root, self.authority = root, authority
        self.fetcher, self.max_archive_bytes = fetcher, max_archive_bytes
        self.attempts, self.cache = [], {}
        self.archives = set()
        self.proxy_registry, self.proxy_spec = proxy_source()
        self.documentation = next(v["documentation"] for v in
            authority["decisions"][l6.COMPOSITE]["venue_universe"] if v["venue_id"] == "KRAKEN_XBT_USD")

    def get(self, url, family, *, archive=False):
        if url in self.cache:
            cached = self.cache[url]
            if isinstance(cached, Exception):
                raise cached
            return cached
        l6.require(request_allowed(url, self.documentation, self.archives,
                                  self.proxy_spec.endpoint if family == PROXY else None),
                   "L6_CAPTURE_REQUEST_NOT_LOCKED")
        record = {"request_identity": "GET " + url, "attempts": 1,
                  "started_at_ms": int(time.time() * 1000), "state": "BLOCKED"}
        self.attempts.append(record)
        try:
            response = self.fetcher(ticker="BTC", url=url, timeout_s=60,
                max_bytes=self.max_archive_bytes if archive else 4 * 1024 * 1024)
            raw = response["body"]
            l6.require(response["status_code"] == 200 and response["final_url"] == url,
                       "L6_CAPTURE_STATUS_OR_REDIRECT_INVALID")
            l6.require(isinstance(raw, bytes) and 0 < len(raw) <=
                (self.max_archive_bytes if archive else 4 * 1024 * 1024), "L6_CAPTURE_BODY_INVALID")
            retrieved = response["retrieved_at_ms"]
            l6.require(type(retrieved) is int and 0 < retrieved <= int(time.time() * 1000),
                       "L6_CAPTURE_RETRIEVAL_INVALID")
            artifact = acquisition.archive_artifact(self.root, raw,
                source_contract_id=family, request_identity="GET " + url,
                retrieved_at_ms=retrieved, first_seen_at_ms=retrieved,
                available_at_coverage_start_ms=retrieved, available_at_coverage_end_ms=retrieved,
                integrity_proof_type="LOCAL_SHA256", provider_checksum=None,
                license_classification=("TERMS_REVIEW_REQUIRED_LOCAL_RESEARCH_ONLY" if family == PROXY
                    else self.authority["decisions"][family]["license_classification"]),
                source_authority_hash=self.proxy_registry.hash if family == PROXY else l6.AUTHORITY_HASH,
                evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
                replay_eligible=False, content_type=response["content_type"],
                availability_proof_type="ACTUAL_FIRST_SUCCESSFUL_RETRIEVAL", revision_of_sha256=None)
            record.update(state="CAPTURED_NOT_YET_QUALIFIED", sha256=artifact["sha256"],
                          size_bytes=len(raw), retrieved_at_ms=retrieved)
            self.cache[url] = raw, artifact
            return raw, artifact
        except Exception as exc:
            record["reason"] = f"{type(exc).__name__}:{exc}"
            # One request per identity, including failures; never loop until READY.
            self.cache[url] = exc
            raise


def verified_proxy_payload(root, artifact, now):
    """Verify original stored bytes; parsing remains exclusively in source_gate_runner."""
    from crt_radar.source_gate_runner import verified_price_structure_archive
    return verified_price_structure_archive(root, artifact, now)


def archive_structure_observation(root, artifact, store, *, recorded_at_ms,
                                  window_start_ms=None, window_end_ms=None):
    """Reuse GO4's sealed reader/parser; no fetch and no candidate classification.

    Historical market times remain separate from actual CRT first visibility.
    The existing observation database holds the immutable research observation.
    """
    from crt_radar.source_gate_runner import parse_price_structure
    from crt_radar.btc_control_transfer_validation import research_identity
    from crt_radar.btc_transition_replay_evidence import archived_structure_bars
    payload = verified_proxy_payload(Path(root), artifact, recorded_at_ms)
    parse_price_structure(payload, now_ms=artifact["retrieved_at_ms"])
    rows = [row for row in payload if row[6] < artifact["retrieved_at_ms"]]
    rows = rows[-201:]
    if window_start_ms is not None:
        rows = [row for row in rows if row[0] >= window_start_ms]
    if window_end_ms is not None:
        rows = [row for row in rows if row[6] <= window_end_ms]
    l6.require(bool(rows), "STRUCTURE_OBSERVATION_WINDOW_EMPTY")
    identity = {"source_id": artifact["source_id"], "product": "BTCUSDT",
                "window_start_ms": rows[0][0], "window_end_ms": rows[-1][6],
                "event_definition": "COMPLETED_DAILY_OHLC"}
    event_id = research_identity(identity)
    observation = {**identity, "observation_id": event_id,
        "raw_sha256": artifact["sha256"], "request_identity": artifact["request_identity"],
        "archive_root": str(Path(root).resolve()), "artifact": artifact,
        "source_authority_hash": artifact["source_authority_hash"],
        "source_available_at_ms": artifact["retrieved_at_ms"],
        "source_published_at_ms": None,
        "source_availability_proof_type": "ACTUAL_FIRST_SUCCESSFUL_RETRIEVAL_BOUND",
        "first_seen_at_ms": artifact["first_seen_at_ms"], "recorded_at_ms": recorded_at_ms,
        "quality_state": "RESEARCH_ARCHIVE_VERIFIED", "formal_composite_authority": "NONE",
        "availability_scope": "ACTUAL_FIRST_SEEN_NOT_HISTORICAL_FORECAST",
        "bars": archived_structure_bars(payload, available_at_ms=artifact["first_seen_at_ms"],
                    window_start_ms=identity["window_start_ms"], window_end_ms=identity["window_end_ms"])}
    prior = store.research_event(event_id, kind="structure_observation")
    if prior:
        # A new download hash/clock cannot manufacture another market event.
        l6.require(prior["bars"] == observation["bars"] or
                   [{k:v for k,v in b.items() if k != "available_at"} for b in prior["bars"]] ==
                   [{k:v for k,v in b.items() if k != "available_at"} for b in observation["bars"]],
                   "STRUCTURE_OBSERVATION_REVISION_CONFLICT")
        return prior
    store.record_research_event(event_id, "structure_observation", observation)
    return observation


def capture_directional_proxy(root, *, fetcher=fetch_official_bytes, l6_root=None):
    """One small registered research request; no quarterly/archive downloads."""
    authority = l6.lock()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    capture = Capture(root, authority, fetcher=fetcher, max_archive_bytes=4 * 1024 * 1024)
    result = {"scope": "BINANCE_BTCUSDT_DIRECTIONAL_PROXY_RESEARCH_ONLY",
              "formal_composite_authority": "NONE", "state": "BLOCKED"}
    try:
        raw, artifact = capture.get(capture.proxy_spec.endpoint, PROXY)
        artifact.update(source_id=capture.proxy_spec.source_id,
                        source_documentation=capture.proxy_spec.raw["documentation"],
                        formal_composite_authority="NONE")
        # Persist original acquisition even if parsing/freshness later fails.
        write_new(root/"directional_proxy_artifact.json", artifact)
        result["artifact"] = artifact
        now = int(time.time() * 1000)
        result["evidence_chain"] = verify_evidence_chain(root, now, proxy_artifact=artifact, l6_root=l6_root)
        quality = result["evidence_chain"]["directional_proxy_evidence"]["quality_state"]
        result["state"] = "PASS" if quality == "VALID_FRESH" else "STALE" if quality == "STALE" else "BLOCKED"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}:{exc}"
    result.update(requests=capture.attempts, request_count=len(capture.attempts),
                  evaluated_at_ms=int(time.time()*1000), authority=authority["authority"])
    write_new(root/"directional_proxy_capture.json", result)
    return result


def venue_coverage(raw, item, venue, end):
    """Validate each venue independently without promoting a partial composite."""
    bars = {}
    for t, o, h, low, close, volume in l6.ohlc_rows(raw, item, venue):
        start = l6.integer(t, "L6_BAR_TIME_INVALID") * 1000
        l6.require(start % l6.DAY == 0, "L6_BAR_NOT_UTC_DAILY")
        if start + l6.DAY > min(end, item["retrieved_at_ms"]):
            continue
        o, h, low, close = [l6.number(v, positive=True) for v in (o, h, low, close)]
        l6.number(volume)
        l6.require(low <= min(o, close) and h >= max(o, close), "L6_BAR_GEOMETRY_INVALID")
        l6.require(start not in bars, "L6_DUPLICATE_VENUE_DAY")
        bars[start] = close
    wanted = set(range(end - 201 * l6.DAY, end, l6.DAY))
    missing = sorted(wanted - bars.keys())
    return {"state": "PASS" if not missing else "BLOCKED", "required_days": 201,
            "complete_days_in_window": len(wanted & bars.keys()),
            "first_utc_day": utc_date(min(bars)) if bars else None,
            "last_utc_day": utc_date(max(bars)) if bars else None,
            "missing_utc_days": [utc_date(v) for v in missing], "artifact_sha256": item["sha256"]}


def capture_sources(root, *, fetcher=fetch_official_bytes, max_archive_bytes=512 * 1024 * 1024):
    authority = l6.lock()  # Verify existing source and metric locks before I/O.
    l6.require(type(max_archive_bytes) is int and max_archive_bytes > 0, "L6_CAPTURE_LIMIT_INVALID")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)  # No overwrite/rebinding of historical sources.
    capture = Capture(root, authority, fetcher=fetcher, max_archive_bytes=max_archive_bytes)
    started = int(time.time() * 1000)
    end = started // l6.DAY * l6.DAY
    manifests = {family: {"schema_version": "CRT_L6_SOURCE_ARCHIVES_V0.1",
        "input_family": family, "source_id": l6.SOURCE_IDS[family],
        "source_authority_hash": l6.AUTHORITY_HASH, "window_end_ms":
        end if family == l6.COMPOSITE else end - l6.DAY, "artifacts": []}
        for family in l6.SOURCE_IDS}
    results, errors = {}, {}
    for venue in authority["decisions"][l6.COMPOSITE]["venue_universe"]:
        vid = venue["venue_id"]
        try:
            if vid == "COINBASE_BTC_USD":
                query = urlencode({"granularity":86400,
                    "start":utc_date(end - 201*l6.DAY)+"T00:00:00Z", "end":utc_date(end)+"T00:00:00Z"})
                responses = [capture.get("https://api.exchange.coinbase.com/products/BTC-USD/candles?"+query,l6.COMPOSITE)]
            elif vid == "BITSTAMP_BTC_USD":
                query = urlencode({"step":86400,"limit":201,"end":end//1000-1,"exclude_current_candle":"true"})
                responses = [capture.get("https://www.bitstamp.net/api/v2/ohlc/btcusd/?"+query,l6.COMPOSITE)]
            else:
                page, link = capture.get(capture.documentation,l6.COMPOSITE)
                urls = quarterly_links(page)
                capture.archives.update(urls)
                l6.require(urls, "L6_KRAKEN_NO_OFFICIAL_QUARTERLY_LINKS")
                results[vid] = {"state":"BLOCKED", "official_quarterly_urls":urls,
                    "documentation_sha256":link["sha256"], "coverage":[]}
                feasibility = quarterly_feasibility(urls, end)
                results[vid]["feasibility"] = feasibility
                responses = []
                # Page-first feasibility: never download old giant archives
                # when they cannot possibly supply the requested latest window.
                for url in urls if feasibility["state"] != "BLOCKED" else []:
                    try:
                        raw, artifact = capture.get(url,l6.COMPOSITE,archive=True)
                        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                            members = [n for n in archive.namelist() if Path(n).name == "XBTUSD_1440.csv"]
                        l6.require(len(members)==1, "L6_KRAKEN_MEMBER_AMBIGUOUS")
                        artifact.update(archive_member=members[0], official_link_artifact=link,
                                        official_archive_link_verified=True)
                        responses.append((raw,artifact))
                    except Exception as exc:
                        errors[url] = f"{type(exc).__name__}:{exc}"
            coverages = []
            for raw, artifact in responses:
                artifact.update(venue_id=vid,product=venue["product"],transport=venue["transport"])
                manifests[l6.COMPOSITE]["artifacts"].append(artifact)
                coverages.append(venue_coverage(raw,artifact,venue,end))
            if vid == "KRAKEN_XBT_USD":
                results[vid]["coverage"] = coverages
                results[vid]["last_utc_day"] = max((v["last_utc_day"] for v in coverages if v["last_utc_day"]),default=None)
                missing = set.intersection(*(set(v["missing_utc_days"]) for v in coverages)) if coverages else set(
                    utc_date(d) for d in range(end-201*l6.DAY,end,l6.DAY))
                results[vid].update(state="PASS" if not missing else "BLOCKED",
                    complete_days_in_window=201-len(missing), missing_utc_days=sorted(missing))
            else:
                results[vid] = coverages[0]
        except Exception as exc:
            errors[vid] = f"{type(exc).__name__}:{exc}"
            results.setdefault(vid, {"state":"BLOCKED"})["reason"] = errors[vid]
    agg_end = manifests[l6.AGGRESSOR]["window_end_ms"]
    for start in range(agg_end-21*l6.DAY,agg_end+l6.DAY,l6.DAY):
        filename = f"BTCUSDT-aggTrades-{utc_date(start)}.zip"
        url = "https://data.binance.vision/" + authority["decisions"][l6.AGGRESSOR]["archive_pattern"].replace("YYYY-MM-DD",utc_date(start))
        try:
            checksum_raw, checksum = capture.get(url+".CHECKSUM",l6.AGGRESSOR)
            raw, artifact = capture.get(url,l6.AGGRESSOR,archive=True)
            l6.require(checksum_raw.decode().split()==[artifact["sha256"],filename],"L6_PROVIDER_CHECKSUM_MISMATCH")
            artifact.update(symbol="BTCUSDT",day_start_ms=start,checksum_artifact=checksum)
            manifests[l6.AGGRESSOR]["artifacts"].append(artifact)
        except Exception as exc:
            errors[utc_date(start)] = f"{type(exc).__name__}:{exc}"
    for family, manifest in manifests.items():
        write_new(root / f"{family}.json",manifest)
    now = int(time.time() * 1000)
    from crt_radar.source_gate_runner import _assert_fresh, StaleData
    qualified = {}
    for family in l6.SOURCE_IDS:
        try:
            value = l6.load_source(family,now_ms=now,root=root)
            _assert_fresh(value["as_of_ms"], now_ms=now, max_age_seconds=172800)
            qualified[family] = {"state":"PASS","as_of_ms":value["as_of_ms"],
                "metrics":{metric:value[metric] for metric in l6.METRICS[family]},
                "measurement_days":len(value["measurement_rows"])}
        except Exception as exc:
            qualified[family] = {"state":"STALE" if isinstance(exc, StaleData) else "BLOCKED",
                                 "reason":f"{type(exc).__name__}:{exc}"}
    result = {"schema_version":"CRT_L6_PUBLIC_CAPTURE_RESULT_V0.1", "started_at_ms":started,
        "evaluated_at_ms":now,"venues":results,"qualification":qualified,"errors":errors,
        "requests":capture.attempts,"request_count":len(capture.attempts),
        "retry_policy":"ONE_ATTEMPT_PER_EXACT_URL_NO_REDIRECT_OR_FALLBACK",
        "authority":authority["authority"]}
    result["evidence_chain"] = verify_evidence_chain(root, now)
    write_new(root/"capture_result.json",result)
    return result


def verify_evidence_chain(root, now, *, proxy_artifact=None, l6_root=None):
    """Existing gate and pack only; other uncaptured sources remain explicitly missing."""
    from crt_radar.source_registry import SourceRegistry
    from crt_radar.source_gate_runner import run_source_gate, default_registry_path, FetchResult
    from crt_radar.evidence_pack import build_evidence_pack
    registry = SourceRegistry.load(default_registry_path())
    overrides = {s["source_id"]:FetchResult(s["source_id"],"ERROR", attempts=0,
        error="SOURCE_NOT_COLLECTED_BY_THIS_L6_ONLY_CAPTURE") for s in registry.with_l6_candidate_sources().payload["sources"]}
    proxy_spec = registry.by_input_family(PROXY)
    if proxy_artifact is not None:
        overrides[proxy_spec.source_id] = FetchResult(proxy_spec.source_id, "OK", attempts=0,
            payload=verified_proxy_payload(root, proxy_artifact, now))
    gate = run_source_gate(registry, now_ms=now, l6_source_root=l6_root or root, fetch_overrides=overrides,
        probe_fetcher=lambda spec:overrides[spec.source_id])
    folder = root/"verification"
    folder.mkdir()
    pack = build_evidence_pack(gate, observation_db=folder/"observations.sqlite3",generated_at_ms=now)
    write_new(folder/"source_gate.json",gate)
    write_new(folder/"evidence_pack.json",pack)
    overlay = pack["season_transition_warning_overlay"]
    return {"l6_candidate_state":gate["l6_candidate_state"],
        "l6_blocked_reasons":gate["l6_candidate_blocked_reasons"],
        "evidence_pack_hash":pack["evidence_pack_hash"], "pack_state":pack["pack_state"],
        "l6_metrics":pack["layers"].get("L6", {}).get("metrics", {}),
        "directional_proxy_evidence":next(e for e in gate["evidence"] if e["input_family"] == PROXY),
        "scenario_id":overlay["scenario"]["id"], "formal_season":pack["formal_candidate"].get("formal_season"),
        "scope":"L6_AND_OPTIONAL_DIRECTIONAL_RESEARCH_OTHER_SOURCES_NOT_COLLECTED_NO_FORMAL_SEASON_RESTORATION_CLAIM"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root",type=Path,required=True,help="New isolated archive directory; existing roots are refused")
    parser.add_argument("--max-archive-bytes",type=int,default=512*1024*1024,help="Operator download resource bound, not a source qualification limit")
    parser.add_argument("--directional-proxy-only",action="store_true",help="Only the existing registered Binance daily research request; never a formal composite")
    parser.add_argument("--l6-source-root",type=Path,help="Read-only existing isolated archives for proxy-only evidence verification")
    args=parser.parse_args(argv)
    if args.l6_source_root and not args.directional_proxy_only:
        parser.error("--l6-source-root requires --directional-proxy-only")
    if args.directional_proxy_only:
        result=capture_directional_proxy(args.output_root,l6_root=args.l6_source_root)
        print(json.dumps({"state":result["state"],"request_count":result["request_count"]},ensure_ascii=False))
        return 0 if result["state"] == "PASS" else 2
    result=capture_sources(args.output_root,max_archive_bytes=args.max_archive_bytes)
    print(json.dumps({"qualification":result["qualification"],"request_count":result["request_count"]},ensure_ascii=False))
    return 0 if all(r["state"]=="PASS" for r in result["qualification"].values()) else 2


if __name__=="__main__":
    raise SystemExit(main())
