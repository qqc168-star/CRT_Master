"""Read-only, byte-verified intake for the two locked L6 candidate sources.

This consumes archived provider responses, never precomputed metric assertions.
Missing archives fail closed; acquiring archives is a separate operator task.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import statistics
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from . import l6_calculations as calculations

DAY = 86_400_000
ROOT = Path(__file__).resolve().parents[2]
COMPOSITE = "BTC_SPOT_COMPOSITE_OHLCV"
AGGRESSOR = "BTC_SPOT_AGGRESSOR_DAILY"
SOURCE_IDS = {
    COMPOSITE: "CRT-CONN-BTC-SPOT-THREE-VENUE-COMPOSITE-001",
    AGGRESSOR: "CRT-CONN-BTC-SPOT-AGGRESSOR-BINANCE-001",
}
AUTHORITY_HASH = "b090665891e84fc8ddbccd0e07d81e3b6abc9013e76bc43f4baab5c2406261fb"
CALCULATORS = {
    "L6_CLOSE_MINUS_SMA200_OVER_ATR20": calculations._close_minus_sma200,
    "L6_SMA50_MINUS_SMA200_OVER_ATR20": calculations._sma50_minus_sma200,
    "L6_RETURN_20D_OVER_ATR_VOL": calculations._return_20d_over_atr,
    "L6_CVD_20D_SHARE": calculations._cvd,
}
METRICS = {
    COMPOSITE: {
        "close_minus_sma200_over_atr20": "L6_CLOSE_MINUS_SMA200_OVER_ATR20",
        "sma50_minus_sma200_over_atr20": "L6_SMA50_MINUS_SMA200_OVER_ATR20",
        "return_20d_over_atr_vol": "L6_RETURN_20D_OVER_ATR_VOL",
    },
    AGGRESSOR: {"cvd_20d_share": "L6_CVD_20D_SHARE"},
}


class L6SourceError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise L6SourceError(reason)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def lock() -> dict[str, Any]:
    authority = json.loads((ROOT / "research/CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json").read_text(encoding="utf-8"))
    require(canonical_hash(authority) == AUTHORITY_HASH, "L6_RESEARCH_LOCK_INVALID")
    contract = json.loads((ROOT / "CONFIG/V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json").read_text())
    for family, metrics in METRICS.items():
        for metric, feature in metrics.items():
            binding = next(x for x in contract["feature_bindings"] if x["feature_id"] == feature)
            require(binding["input_family"] == family and binding["metric"] == metric
                    and binding["allowed_source_ids"] == [SOURCE_IDS[family]], "L6_BINDING_CONFLICT")
    return authority


def integer(value: Any, code: str) -> int:
    require(not isinstance(value, bool), code)
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise L6SourceError(code) from exc
    require(str(result) == str(value) and result >= 0, code)
    return result


def number(value: Any, *, positive: bool = False) -> float:
    require(not isinstance(value, bool), "L6_NUMBER_INVALID")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise L6SourceError("L6_NUMBER_INVALID") from exc
    require(math.isfinite(result) and (result > 0 if positive else result >= 0), "L6_NUMBER_INVALID")
    return result


def read_artifact(root: Path, item: dict, now: int) -> bytes:
    digest = item.get("sha256")
    require(isinstance(digest, str) and len(digest) == 64
            and all(c in "0123456789abcdef" for c in digest), "L6_HASH_INVALID")
    require(item.get("evidence_class") in {"CURRENT_FIRST_SEEN_CAPTURE", "IMMUTABLE_PROVIDER_ARCHIVE"},
            "L6_NON_LIVE_ARTIFACT")
    first = integer(item.get("first_seen_at_ms"), "L6_FIRST_SEEN_INVALID")
    retrieved = integer(item.get("retrieved_at_ms"), "L6_RETRIEVAL_INVALID")
    require(0 < first <= retrieved <= now, "L6_AVAILABILITY_INVALID")
    require(bool(item.get("license_classification")), "L6_LICENSE_MISSING")
    require(item.get("source_authority_hash") == AUTHORITY_HASH,
            "L6_AUTHORITY_HASH_MISMATCH")
    path = (root / "artifacts" / "sha256" / digest[:2] / digest).resolve()
    require(path.is_relative_to(root.resolve()), "L6_ARTIFACT_PATH_ESCAPE")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == digest and len(raw) == item.get("size_bytes"),
            "L6_ARTIFACT_BYTES_MISMATCH")
    return raw


def request_url(item: dict):
    request = item.get("request_identity", "")
    require(request.startswith("GET https://"), "L6_REQUEST_IDENTITY_INVALID")
    url = urlparse(request[4:])
    require(not url.username and not url.password and not url.fragment, "L6_REQUEST_IDENTITY_INVALID")
    return url


def ohlc_rows(raw: bytes, item: dict, venue: dict) -> list[tuple]:
    url = request_url(item)
    query = parse_qs(url.query)
    venue_id = venue["venue_id"]
    require(item.get("product") == venue["product"] and item.get("transport") == venue["transport"],
            "L6_VENUE_IDENTITY_INVALID")
    if venue_id == "COINBASE_BTC_USD":
        require(url.netloc == "api.exchange.coinbase.com" and url.path == "/products/BTC-USD/candles"
                and query.get("granularity") == ["86400"], "L6_COINBASE_REQUEST_INVALID")
        rows = json.loads(raw)
        require(isinstance(rows, list), "L6_COINBASE_PAYLOAD_INVALID")
        require(all(isinstance(x, list) and len(x) == 6 for x in rows), "L6_COINBASE_ROW_INVALID")
        return [(x[0], x[3], x[2], x[1], x[4], x[5]) for x in rows]
    if venue_id == "BITSTAMP_BTC_USD":
        require(url.netloc == "www.bitstamp.net" and url.path == "/api/v2/ohlc/btcusd/"
                and query.get("step") == ["86400"], "L6_BITSTAMP_REQUEST_INVALID")
        data = json.loads(raw)["data"]
        require(data.get("pair") == "BTC/USD", "L6_BITSTAMP_PAIR_INVALID")
        return [(x["timestamp"], x["open"], x["high"], x["low"], x["close"], x["volume"])
                for x in data["ohlc"]]
    require(venue_id == "KRAKEN_XBT_USD", "L6_VENUE_NOT_LOCKED")
    # Official archive download links are published on Kraken's locked documentation page.
    # Require a byte-verified capture of that page linking the exact archive URL.
    require(item.get("official_archive_link_verified") is True, "L6_KRAKEN_OFFICIAL_LINK_MISSING")
    member = item.get("archive_member")
    require(isinstance(member, str) and Path(member).name == "XBTUSD_1440.csv", "L6_KRAKEN_MEMBER_INVALID")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(archive.namelist().count(member) == 1, "L6_KRAKEN_MEMBER_AMBIGUOUS")
        with archive.open(member) as stream:
            rows = list(csv.reader(io.TextIOWrapper(stream, encoding="utf-8-sig")))
    require(all(len(x) == 7 for x in rows), "L6_KRAKEN_ROW_INVALID")
    return [tuple(x[:6]) for x in rows]


def composite(root: Path, manifest: dict, now: int, authority: dict) -> tuple[list, list]:
    doctrine = authority["decisions"][COMPOSITE]
    venues = {v["venue_id"]: v for v in doctrine["venue_universe"]}
    by_venue: dict[str, dict] = {v: {} for v in venues}
    provenance = []
    for original in manifest["artifacts"]:
        item = dict(original)
        venue_id = item.get("venue_id")
        require(venue_id in venues, "L6_VENUE_NOT_LOCKED")
        raw = read_artifact(root, item, now)
        if venue_id == "KRAKEN_XBT_USD":
            link = item.get("official_link_artifact", {})
            page = read_artifact(root, link, now).decode("utf-8")
            require(link.get("request_identity") == "GET " + venues[venue_id]["documentation"],
                    "L6_KRAKEN_DOCUMENTATION_INVALID")
            from html import unescape
            from html.parser import HTMLParser

            class Links(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.urls = []

                def handle_starttag(self, tag, attrs):
                    if tag == "a":
                        self.urls.extend(value for key, value in attrs if key == "href")

            links = Links()
            links.feed(page)
            require(item.get("request_identity", "")[4:] in [unescape(x) for x in links.urls],
                    "L6_KRAKEN_ARCHIVE_NOT_OFFICIAL")
            item["official_archive_link_verified"] = True
        for t, o, h, low, c, volume in ohlc_rows(raw, item, venues[venue_id]):
            start = integer(t, "L6_BAR_TIME_INVALID") * 1000
            end = start + DAY
            require(start % DAY == 0, "L6_BAR_NOT_UTC_DAILY")
            # Ignore incomplete API extras, never count them toward the required window.
            if end > min(now, item["retrieved_at_ms"]):
                continue
            values = [number(x, positive=True) for x in (o, h, low, c)]
            o, h, low, c = values
            require(low <= min(o, c) and h >= max(o, c) and low <= h, "L6_BAR_GEOMETRY_INVALID")
            bar = dict(zip(("open", "high", "low", "close"), values))
            bar.update(volume=number(volume), available_at_ms=item["retrieved_at_ms"])
            require(end not in by_venue[venue_id], "L6_DUPLICATE_VENUE_DAY")
            by_venue[venue_id][end] = bar
        provenance.append(original)
    # Use the requested completed window, not the latest intersection (which hides missing days).
    end = integer(manifest.get("window_end_ms"), "L6_WINDOW_INVALID")
    require(end % DAY == 0 and end <= now, "L6_WINDOW_INCOMPLETE")
    rows = []
    for at in range(end - 200 * DAY, end + 1, DAY):
        require(all(at in values for values in by_venue.values()), "L6_THREE_VENUE_DAY_MISSING")
        bars = [values[at] for values in by_venue.values()]
        require(len(bars) >= doctrine["minimum_venue_count"], "L6_VENUE_COUNT_INSUFFICIENT")
        row = {field: statistics.median(b[field] for b in bars) for field in ("open", "high", "low", "close")}
        row.update(observed_at_ms=at, available_at_ms=max(b["available_at_ms"] for b in bars),
                   complete=True, volume=sum(b["volume"] for b in bars), venue_count=len(bars),
                   dispersion_bps={f: max(abs(b[f] - row[f]) / row[f] * 10000 for b in bars)
                                   for f in ("open", "high", "low", "close")})
        rows.append(row)
    return rows, provenance


def aggressor(root: Path, manifest: dict, now: int, authority: dict) -> tuple[list, list]:
    doctrine = authority["decisions"][AGGRESSOR]
    days = {}
    provenance = []
    for item in manifest["artifacts"]:
        raw = read_artifact(root, item, now)
        start = integer(item.get("day_start_ms"), "L6_DAY_INVALID")
        require(start % DAY == 0 and start + DAY <= item["retrieved_at_ms"], "L6_AGGRESSOR_PARTIAL_DAY")
        require(start not in days, "L6_DUPLICATE_AGGRESSOR_DAY")
        date = datetime.fromtimestamp(start / 1000, timezone.utc).strftime("%Y-%m-%d")
        filename = f"BTCUSDT-aggTrades-{date}.zip"
        url = "https://data.binance.vision/" + doctrine["archive_pattern"].replace("YYYY-MM-DD", date)
        require(item.get("request_identity") == "GET " + url and item.get("symbol") == doctrine["symbol"],
                "L6_AGGRESSOR_IDENTITY_INVALID")
        checksum = item.get("checksum_artifact", {})
        require(checksum.get("request_identity") == "GET " + url + ".CHECKSUM", "L6_CHECKSUM_IDENTITY_INVALID")
        checksum_bytes = read_artifact(root, checksum, now)
        require(checksum_bytes.decode().split() == [item["sha256"], filename], "L6_PROVIDER_CHECKSUM_MISMATCH")
        buy = sell = 0.0
        first_id = last_id = first_trade = last_trade = previous_time = None
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            member = filename[:-4] + ".csv"
            require(archive.namelist() == [member], "L6_AGGRESSOR_ARCHIVE_MEMBER_INVALID")
            with archive.open(member) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding="utf-8-sig"))
                for index, row in enumerate(reader):
                    if index == 0 and row == doctrine["required_columns"]:
                        continue
                    require(len(row) == 8, "L6_AGGRESSOR_ROW_INVALID")
                    agg_id, first, last = (integer(row[i], "L6_TRADE_ID_INVALID") for i in (0, 3, 4))
                    timestamp = integer(row[5], "L6_TRADE_TIME_INVALID")
                    timestamp = timestamp // 1000 if start >= 1735689600000 else timestamp
                    require(start <= timestamp < start + DAY, "L6_TRADE_OUTSIDE_DAY")
                    require(previous_time is None or timestamp >= previous_time, "L6_TRADE_TIME_UNORDERED")
                    require(last_id is None or agg_id == last_id + 1, "L6_AGGREGATE_ID_GAP_OR_DUPLICATE")
                    require(first <= last and (last_trade is None or first == last_trade + 1), "L6_TRADE_ID_GAP")
                    require(row[6].lower() in {"true", "false"}, "L6_UNKNOWN_AGGRESSOR_VOLUME")
                    require(row[7].lower() in {"true", "false"}, "L6_AGGRESSOR_ROW_INVALID")
                    quote = number(row[1], positive=True) * number(row[2], positive=True)
                    if (row[6].lower() == "true") == doctrine["buyer_initiated_when_is_buyer_maker"]:
                        buy += quote
                    else:
                        sell += quote
                    if first_id is None:
                        first_id, first_trade = agg_id, first
                    last_id, last_trade, previous_time = agg_id, last, timestamp
        # Empty files remain explicit artifacts; neighboring non-empty IDs still need to join.
        days[start] = dict(observed_at_ms=start + DAY, complete=True,
                           available_at_ms=max(item["retrieved_at_ms"], checksum["retrieved_at_ms"]),
                           buyer_initiated_quote_volume=buy, seller_initiated_quote_volume=sell,
                           unknown_aggressor_quote_volume=0, total_quote_volume=buy + sell,
                           first_id=first_id, last_id=last_id, first_trade=first_trade, last_trade=last_trade)
        provenance.append(item)
    end = integer(manifest.get("window_end_ms"), "L6_WINDOW_INVALID")
    require(end % DAY == 0 and end + DAY <= now, "L6_ADJACENT_COMPLETE_DAY_REQUIRED")
    starts = list(range(end - 21 * DAY, end + DAY, DAY))
    require(set(days) == set(starts), "L6_AGGRESSOR_DAY_OR_BOUNDARY_MISSING")
    populated = [days[t] for t in starts if days[t]["first_id"] is not None]
    for previous, current in zip(populated, populated[1:]):
        require(current["first_id"] == previous["last_id"] + 1
                and current["first_trade"] == previous["last_trade"] + 1,
                "L6_AGGRESSOR_ADJACENT_BOUNDARY_GAP")
    return [days[t] for t in starts[1:-1]], provenance


def load_source(family: str, *, now_ms: int, root: Path | None = None) -> dict:
    authority = lock()
    root = root or Path(os.environ.get("CRT_L6_SOURCE_ROOT", ROOT / "runtime" / "l6_sources"))
    manifest_path = root / f"{family}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema_version") == "CRT_L6_SOURCE_ARCHIVES_V0.1"
            and manifest.get("input_family") == family and manifest.get("source_id") == SOURCE_IDS[family],
            "L6_MANIFEST_IDENTITY_INVALID")
    require(manifest.get("source_authority_hash") == canonical_hash(authority), "L6_AUTHORITY_HASH_MISMATCH")
    rows, provenance = (composite if family == COMPOSITE else aggressor)(root, manifest, now_ms, authority)
    table = "OHLCV_DAILY" if family == COMPOSITE else "AGGRESSOR_DAILY"
    raw = {"schema_version": "CRT_CANDIDATE_RAW_INPUT_V0.2", "tables": {table: rows}}
    values = {metric: round(CALCULATORS[feature](raw, now_ms), 10)
              for metric, feature in METRICS[family].items()}
    return {**values, "as_of_ms": rows[-1]["observed_at_ms"], "input_family": family,
            "source_id": SOURCE_IDS[family], "state": "READY", "source_provenance": provenance,
            "source_authority_hash": canonical_hash(authority),
            "available_at_ms": max(row["available_at_ms"] for row in rows),
            "venue_coverage": [v["venue_id"] for v in authority["decisions"][COMPOSITE]["venue_universe"]]
            if family == COMPOSITE else [],
            "measurement_rows": rows, "authority": authority["authority"]}
