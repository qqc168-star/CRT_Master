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


def request_allowed(url, documentation, archives):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        return False
    if url == documentation or url in archives:
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
        self.documentation = next(v["documentation"] for v in
            authority["decisions"][l6.COMPOSITE]["venue_universe"] if v["venue_id"] == "KRAKEN_XBT_USD")

    def get(self, url, family, *, archive=False):
        if url in self.cache:
            cached = self.cache[url]
            if isinstance(cached, Exception):
                raise cached
            return cached
        l6.require(request_allowed(url, self.documentation, self.archives), "L6_CAPTURE_REQUEST_NOT_LOCKED")
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
                license_classification=self.authority["decisions"][family]["license_classification"],
                source_authority_hash=l6.AUTHORITY_HASH, evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
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
                responses = []
                for url in urls:
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
    qualified = {}
    for family in l6.SOURCE_IDS:
        try:
            value = l6.load_source(family,now_ms=now,root=root)
            l6.require(now-value["as_of_ms"] <= 172800000, "L6_CAPTURE_WINDOW_STALE")
            qualified[family] = {"state":"PASS","as_of_ms":value["as_of_ms"],
                "metrics":{metric:value[metric] for metric in l6.METRICS[family]},
                "measurement_days":len(value["measurement_rows"])}
        except Exception as exc:
            qualified[family] = {"state":"BLOCKED","reason":f"{type(exc).__name__}:{exc}"}
    result = {"schema_version":"CRT_L6_PUBLIC_CAPTURE_RESULT_V0.1", "started_at_ms":started,
        "evaluated_at_ms":now,"venues":results,"qualification":qualified,"errors":errors,
        "requests":capture.attempts,"request_count":len(capture.attempts),
        "retry_policy":"ONE_ATTEMPT_PER_EXACT_URL_NO_REDIRECT_OR_FALLBACK",
        "authority":authority["authority"]}
    result["evidence_chain"] = verify_evidence_chain(root, now)
    write_new(root/"capture_result.json",result)
    return result


def verify_evidence_chain(root, now):
    """Existing gate and pack only; other uncaptured sources remain explicitly missing."""
    from crt_radar.source_registry import SourceRegistry
    from crt_radar.source_gate_runner import run_source_gate, default_registry_path, FetchResult
    from crt_radar.evidence_pack import build_evidence_pack
    registry = SourceRegistry.load(default_registry_path())
    overrides = {s["source_id"]:FetchResult(s["source_id"],"ERROR", attempts=0,
        error="SOURCE_NOT_COLLECTED_BY_THIS_L6_ONLY_CAPTURE") for s in registry.with_l6_candidate_sources().payload["sources"]}
    gate = run_source_gate(registry, now_ms=now, l6_source_root=root, fetch_overrides=overrides,
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
        "scenario_id":overlay["scenario"]["id"], "formal_season":pack["formal_candidate"].get("formal_season"),
        "scope":"L6_ONLY_OTHER_SOURCES_NOT_COLLECTED_NO_FORMAL_SEASON_RESTORATION_CLAIM"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root",type=Path,required=True,help="New isolated archive directory; existing roots are refused")
    parser.add_argument("--max-archive-bytes",type=int,default=512*1024*1024,help="Operator download resource bound, not a source qualification limit")
    args=parser.parse_args(argv)
    result=capture_sources(args.output_root,max_archive_bytes=args.max_archive_bytes)
    print(json.dumps({"qualification":result["qualification"],"request_count":result["request_count"]},ensure_ascii=False))
    return 0 if all(r["state"]=="PASS" for r in result["qualification"].values()) else 2


if __name__=="__main__":
    raise SystemExit(main())
