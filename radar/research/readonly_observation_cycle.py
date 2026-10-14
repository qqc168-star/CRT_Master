"""Bounded public/market-price collection; no account, provider, or notice path.

Reuses GO4 acquisition, the registered Source Gate, issuer/IBKR adapters and
the existing Evidence Pack. Each invocation performs one due cycle and exits.
The OS scheduler may invoke it again; the original daily duty task is untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlencode

RADAR = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(RADAR / "src"))

import candidate_acquisition as acquisition
from prospective_capture import fetch_official_bytes
from crt_radar import issuer_announcement_runner as announcements
from crt_radar import issuer_ratio_market_health_source as issuer_source
from crt_radar.daily_evidence_runner import run_daily_evidence, write_json_atomic
from crt_radar.gpt_handoff import _bridge_market_context, _bridge_capital_state
from crt_radar.mstr_asst_market_health import build_issuer_ratio_observation, compact_issuer_ratio_observation
from crt_radar.mstr_asst_market_health_runtime import seal_runtime_source
from crt_radar.ibkr_market_health_sources import (
    collect_ibkr_equity_daily_proof, validate_four_asset_daily_proof,
    latest_completed_equity_session, _four_asset_market_calendar,
)
from crt_radar.private_profile import load_private_profile
from crt_radar.liquidation_aggregator import verify_snapshot
from crt_radar.source_gate_runner import FetchResult, default_registry_path
from crt_radar.source_registry import SourceRegistry
from crt_radar.treasury_company_ct import build_retrospective_tracker_context

LOCKS = dict(production="NOT_APPROVED", external_action_authority="NONE",
             capital_decision_authority="USER_ONLY", machine_execution="FORBIDDEN")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def safe_root(config):
    root = Path(config["output_root"]).resolve()
    protected = [RADAR.parent.resolve(), *(Path(p).resolve() for p in config["protected_roots"])]
    protected += [Path(config[k]).resolve() for k in (
        "issuer_archive", "equity_proof", "tracker_archive", "private_profile",
        "fixed_income_inputs", "portfolio_allocation_inputs", "liquidation_snapshot") if config.get(k)]
    if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in protected):
        raise ValueError("OUTPUT_OVERLAPS_PROTECTED_OR_INPUT_PATH")
    if root == Path(root.anchor) or not config["protected_roots"]:
        raise ValueError("EXPLICIT_ISOLATION_BOUNDARY_REQUIRED")
    return root


class PublicArchive:
    """Acquisition wrapper, not a new parser or source authority."""
    def __init__(self, root, state, registry, *, fetcher=fetch_official_bytes, clock=None):
        self.root, self.state, self.registry = root, state, registry
        self.fetcher = fetcher
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.requests = []
        self.in_cycle = {}

    def allowed(self, url):
        permitted = {"https://www.strategy.com/ledger"}
        for row in self.registry.payload["sources"]:
            if row.get("transport", "").startswith(("HTTPS", "MULTI_HTTPS")):
                permitted.update((row.get("endpoints") or {"default": row.get("endpoint")}).values())
        issuer_registry = announcements.load_registry(announcements.default_registry_path())
        for issuer in issuer_registry["issuers"]:
            permitted.update(issuer.get(k) for k in ("sec_submissions_url", "press_archive_url", "press_feed_url"))
            press = issuer["press_archive_url"].rstrip("/") + "/"
            if url.startswith(press) and urlsplit(url).hostname in issuer["press_allowed_hosts"]:
                return True
        if url in permitted:
            return True
        if re.fullmatch(r"https://www\.sec\.gov/Archives/edgar/data/(?:1050446|1920406)/\d{18}/[A-Za-z0-9_.-]+", url):
            return True
        return bool(re.fullmatch(r"https://data-api\.binance\.vision/api/v3/klines\?symbol=BTCUSDT&interval=1m&startTime=\d+&endTime=\d+&limit=1", url))

    def get(self, url, source_id, authority_hash, *, refresh_ms, issuer=False):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or not self.allowed(url)):
            raise ValueError("PUBLIC_HTTPS_ONLY")
        if url in self.in_cycle:
            result = self.in_cycle[url]
            if isinstance(result, Exception):
                raise result
            return result
        now = self.clock()
        old = self.state.setdefault("requests", {}).get(url)
        if old and now < old["next_check_at_ms"]:
            if old.get("artifact"):
                artifact = old["artifact"]
                path = acquisition._safe_archive_path(self.root, artifact["archive_relpath"])
                if (path is None or artifact.get("request_identity") != "GET " + url
                        or artifact.get("source_contract_id") != source_id
                        or artifact.get("source_authority_hash") != authority_hash
                        or not 0 < artifact["first_seen_at_ms"] <= artifact["retrieved_at_ms"] <= now):
                    raise ValueError("CACHED_RAW_PATH_OR_IDENTITY_INVALID")
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
                    raise ValueError("CACHED_RAW_HASH_MISMATCH")
                result = raw, artifact, old["content_type"]
                self.in_cycle[url] = result
                return result
            raise ValueError("SOURCE_BACKOFF:" + old.get("reason", "BLOCKED"))
        request = dict(source_id=source_id, request_identity="GET " + url,
                       started_at_ms=now, attempts=1, state="BLOCKED")
        self.requests.append(request)
        try:
            if issuer:
                raw, content_type, final = announcements._fetch_bytes(
                    url, allowed_hosts=[parsed.hostname], timeout_seconds=20,
                    maximum_response_bytes=5_000_000)
                retrieved = self.clock()
            else:
                response = self.fetcher(ticker="BTC", url=url, timeout_s=20, max_bytes=5_000_000)
                if response["status_code"] != 200:
                    raise ValueError("SOURCE_HTTP_STATUS_INVALID")
                raw, content_type, final = response["body"], response["content_type"], response["final_url"]
                retrieved = response["retrieved_at_ms"]
            if final != url or not isinstance(raw, bytes) or not 0 < len(raw) <= 5_000_000:
                raise ValueError("SOURCE_REDIRECT_OR_BODY_INVALID")
            if not 0 < retrieved <= self.clock():
                raise ValueError("RETRIEVAL_CLOCK_INVALID")
            previous = (old or {}).get("artifact", {})
            same_bytes = previous.get("sha256") == hashlib.sha256(raw).hexdigest()
            first_seen = previous["first_seen_at_ms"] if same_bytes else retrieved
            artifact = acquisition.archive_artifact(self.root, raw,
                source_contract_id=source_id, request_identity="GET " + url,
                retrieved_at_ms=retrieved, first_seen_at_ms=first_seen,
                available_at_coverage_start_ms=first_seen, available_at_coverage_end_ms=first_seen,
                integrity_proof_type="LOCAL_SHA256", provider_checksum=None,
                license_classification="TERMS_REVIEW_REQUIRED_LOCAL_RESEARCH_ONLY",
                source_authority_hash=authority_hash, evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
                replay_eligible=False, content_type=content_type,
                availability_proof_type="ACTUAL_FIRST_SUCCESSFUL_RETRIEVAL", revision_of_sha256=None)
            self.state["requests"][url] = dict(artifact=artifact, content_type=content_type,
                next_check_at_ms=retrieved + refresh_ms)
            write_json_atomic(self.root / "collection-state.json", self.state)
            request.update(state="CAPTURED_NOT_YET_QUALIFIED", **artifact,
                           actual_retrieved_at_ms=retrieved)
            result = raw, artifact, content_type
            self.in_cycle[url] = result
            return result
        except Exception as exc:
            request["reason"] = type(exc).__name__ + ":" + str(exc)
            self.state["requests"][url] = {**(old or {}), "reason": request["reason"],
                                          "next_check_at_ms": now + refresh_ms}
            write_json_atomic(self.root / "collection-state.json", self.state)
            self.in_cycle[url] = exc
            raise
        finally:
            with (self.root / "public-requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n")

    def issuer_fetch(self, url, **kwargs):
        # The existing issuer parser supplies a locked host set.
        if urlsplit(url).hostname not in kwargs["allowed_hosts"]:
            raise announcements.IssuerAnnouncementError("ISSUER_SOURCE_HOST_MISMATCH")
        try:
            raw, _, content_type = self.get(url, "OFFICIAL_ISSUER_DISCLOSURE",
                announcements._canonical_hash(announcements.load_registry(announcements.default_registry_path())),
                refresh_ms=3_600_000, issuer=True)
            return raw, content_type, url
        except Exception as exc:
            raise announcements.IssuerAnnouncementError(str(exc)) from exc


def seed_archive(source, destination):
    """Copy original receipts byte-for-byte; copying is not a new retrieval."""
    if not source or destination.exists():
        return
    shutil.copytree(Path(source), destination)


def collect_issuers(capture, root):
    registry = announcements.load_registry(announcements.default_registry_path())
    result = announcements.run_issuer_announcement_cycle(registry,
        state_path=root / "issuer-state.json", ledger_path=root / "issuer-events.jsonl",
        fetcher=capture.issuer_fetch)
    archive = root / "issuer-archive"
    folder = archive / "sec-disclosures"
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else []
    known = {(item["asset"], item["accession"]): item for item in manifest}
    gaps = []
    for issuer in registry["issuers"]:
        asset = "MSTR" if issuer["cik"] == issuer_source.ASSETS["MSTR"]["cik"] else "ASST"
        try:
            raw, _, _ = capture.get(issuer["sec_submissions_url"], "SEC_SUBMISSIONS_" + issuer["cik"],
                announcements._canonical_hash(registry), refresh_ms=3_600_000, issuer=True)
            events = announcements.parse_sec_submissions(issuer, json.loads(raw),
                material_forms=registry["material_forms"], material_keywords=registry["material_title_keywords"])
            # Existing CT normalizer consumes 8-K/FWP facts, not every SEC form.
            candidates = [e for e in events if e["form"] in issuer_source.ASSETS[asset]["forms"]]
            for event in candidates[:2]:
                key = asset, event["accession_number"]
                if key in known:
                    continue
                url = event["source_url"]
                raw, artifact, _ = capture.get(url, "SEC_DOCUMENT_" + issuer["cik"],
                    announcements._canonical_hash(registry), refresh_ms=86_400_000, issuer=True)
                item = dict(asset=asset, accession=event["accession_number"],
                    primary=url.rsplit("/", 1)[-1], source_url=url,
                    accepted=event["accepted_at"], retrieved_at_ms=artifact["first_seen_at_ms"],
                    raw_sha256=artifact["sha256"])
                target = folder / (asset + "-" + item["accession"] + ".html")
                with target.open("xb") as stream:
                    stream.write(raw)
                manifest.append(item)
                known[key] = item
        except Exception as exc:
            gaps.append(dict(asset=asset, reason=type(exc).__name__ + ":" + str(exc)))
    write_json_atomic(manifest_path, manifest)
    # Reuse the existing official Ledger parser; never infer ADSO effective time.
    ledger_url = "https://www.strategy.com/ledger"
    try:
        raw, artifact, content_type = capture.get(ledger_url, "MSTR_OFFICIAL_LEDGER",
            announcements._canonical_hash(registry), refresh_ms=3_600_000)
        rows = issuer_source.parse_strategy_ledger(raw, source_url=ledger_url,
                                                  retrieved_at_ms=artifact["retrieved_at_ms"])
        ledger = archive / "ledger-raw"
        ledger.mkdir(exist_ok=True)
        target = ledger / ("ledger-" + artifact["sha256"] + ".html")
        if not target.exists():
            target.write_bytes(raw)
        receipt = ledger / ("retrieval-" + str(artifact["retrieved_at_ms"]) + ".json")
        if not receipt.exists():
            write_json_atomic(receipt, dict(source_url=ledger_url, http_status=200, content_type=content_type,
                evidence_hash=artifact["sha256"], retrieved_at_ms=artifact["retrieved_at_ms"],
                first_seen_at_ms=artifact["first_seen_at_ms"]))
        write_json_atomic(root / "reported-ledger-comparison.json", issuer_source.build_ledger_ratio_data(rows))
    except Exception as exc:
        gaps.append(dict(asset="MSTR", reason=type(exc).__name__ + ":" + str(exc)))
    return result, gaps


def collect_equities(config, root, state, now, *, collector=collect_ibkr_equity_daily_proof):
    path = root / "four-asset-daily-proof.json"
    if not path.exists() and config.get("equity_proof"):
        path.write_bytes(Path(config["equity_proof"]).read_bytes())
    proof = read_json(path) if path.exists() else None
    checked = validate_four_asset_daily_proof(proof, at_ms=now)
    if checked["state"] == "VALID":
        return proof, dict(state="REUSED_CURRENT_COMPLETED_SESSION", network_attempts=0)
    if config.get("allow_market_price_capture") is not True:
        return proof, dict(state="MARKET_PRICE_READ_NOT_ENABLED", network_attempts=0,
                           reason="EXPLICIT_MARKET_PRICE_ONLY_CAPTURE_REQUIRED")
    try:
        session = latest_completed_equity_session(now)
    except ValueError as exc:
        return proof, dict(state="MARKET_CALENDAR_BLOCKED", network_attempts=0, reason=str(exc))
    if session and state.get("equity_attempt_session") == session:
        return proof, dict(state=state.get("equity_state", "TWS_OFFLINE"), network_attempts=0,
            reason="ONE_ATTEMPT_PER_COMPLETED_SESSION; WAIT_FOR_NEXT_SESSION_OR_EXPLICIT_REARM")
    if now < state.get("next_equity_attempt_at_ms", 0):
        return proof, dict(state=state.get("equity_state", "TWS_OFFLINE"), network_attempts=0,
                           next_attempt_at_ms=state["next_equity_attempt_at_ms"])
    state["next_equity_attempt_at_ms"] = now + 3_600_000
    state["equity_attempt_session"] = session
    try:
        fresh = collector(host="127.0.0.1", port=7496, client_id=761,
                          timeout_seconds=15, four_asset_prices=True)
        write_json_atomic(root / ("equity-capture-" + fresh["proof_hash"] + ".json"), fresh)
        write_json_atomic(path, fresh)
        state["equity_state"] = validate_four_asset_daily_proof(fresh, at_ms=int(time.time()*1000))["state"]
        return fresh, dict(state=state["equity_state"], network_attempts=1)
    except Exception as exc:
        offline = any(word in str(exc).lower() for word in ("connect", "handshake", "socket"))
        state["equity_state"] = "TWS_OFFLINE" if offline else "EQUITY_CAPTURE_BLOCKED"
        return proof, dict(state=state["equity_state"], network_attempts=1,
                           reason=type(exc).__name__ + ":" + str(exc),
                           next_attempt_at_ms=state["next_equity_attempt_at_ms"])


def collect_close_mark(capture, equities, now):
    """Reuse the locked Binance market route; USDT is not certified USD.

    This bounded bar describes the minute ending at the equity session close.
    It is not an exact simultaneous executable trade or a formal USD input.
    """
    checked = validate_four_asset_daily_proof(equities, at_ms=now)
    rows = [r for r in checked["assets"].values() if r["state"] == "VALID"]
    closes = {r["as_of_ms"] for r in rows}
    if not closes:
        from crt_radar.mstr_asst_full_day_market_intake import _session_close_ms
        try:
            calendar = _four_asset_market_calendar()
            day = latest_completed_equity_session(now, calendar=calendar)
            closes = {_session_close_ms(day, early_close_dates=frozenset(calendar["early_close_dates"]))}
        except ValueError as exc:
            return dict(state="BLOCKED", reason=str(exc))
    if len(closes) != 1:
        return dict(state="BLOCKED", reason="EQUITY_CLOSE_TIMES_DISAGREE")
    close = closes.pop()
    url = "https://data-api.binance.vision/api/v3/klines?" + urlencode(dict(
        symbol="BTCUSDT", interval="1m", startTime=close-60_000, endTime=close-1, limit=1))
    try:
        contract = read_json(RADAR / "CONFIG/MSTR_ASST_MARKET_HEALTH_SOURCE_V0.1.json")
        raw, artifact, _ = capture.get(url, contract["sources"]["btc_exact_close"]["source_id"],
            announcements._canonical_hash(contract), refresh_ms=86_400_000)
        bars = json.loads(raw)
        if (len(bars) != 1 or len(bars[0]) < 7 or bars[0][0] != close-60_000
                or bars[0][6] != close-1 or not 0 < float(bars[0][4]) < float("inf")):
            raise ValueError("BTC_CLOSE_WINDOW_OR_PRICE_INVALID")
        return dict(state="RESEARCH_AVAILABLE", price=float(bars[0][4]), quote_currency="USDT",
            window_start_ms=close-60_000, window_end_ms=close,
            price_type="MINUTE_BAR_ENDING_AT_EQUITY_SCHEDULED_CLOSE_NOT_LIVE_BID_ASK",
            formal_usd_state="BLOCKED", reason="USDT_USD_CONVERSION_NOT_PROVEN",
            source_url=url, raw_sha256=artifact["sha256"],
            first_seen_time=artifact["first_seen_at_ms"], retrieval_time=artifact["retrieved_at_ms"])
    except Exception as exc:
        return dict(state="BLOCKED", reason=str(exc), source_url=url)


def retained_liquidations(config, root, registry, now):
    """Read an existing public collector output; do not start any collector."""
    if not config.get("liquidation_snapshot"):
        return None, None, None
    try:
        raw = Path(config["liquidation_snapshot"]).read_bytes()
        spec = registry.by_input_family("LIQUIDATION_AGGREGATES")
        digest = hashlib.sha256(raw).hexdigest()
        identity = "READ_LOCAL_PUBLIC_L4_SNAPSHOT:" + digest
        record_path = root / acquisition._identity_relpath(dict(
            source_contract_id=spec.source_id, request_identity=identity, sha256=digest))
        first_seen = now
        if record_path.exists():
            stored = read_json(record_path)
            if stored.get("record_sha256") != acquisition._record_hash(stored):
                raise ValueError("LOCAL_MARKET_IDENTITY_HASH_MISMATCH")
            first_seen = stored["artifact"]["first_seen_at_ms"]
        artifact = acquisition.archive_artifact(root, raw,
            source_contract_id=spec.source_id, request_identity=identity,
            retrieved_at_ms=now, first_seen_at_ms=first_seen,
            available_at_coverage_start_ms=first_seen, available_at_coverage_end_ms=first_seen,
            integrity_proof_type="LOCAL_SHA256", provider_checksum=None,
            license_classification="TERMS_REVIEW_REQUIRED_LOCAL_RESEARCH_ONLY",
            source_authority_hash=registry.hash, evidence_class="CURRENT_FIRST_SEEN_CAPTURE",
            replay_eligible=False, content_type="application/json",
            availability_proof_type="ACTUAL_FIRST_LOCAL_ARCHIVE_READ", revision_of_sha256=None)
        payload = json.loads(raw)
        verify_snapshot(payload)
        return payload, dict(source_url="LOCAL_EXISTING_PUBLIC_L4_SNAPSHOT", artifact=artifact,
                             actual_read_at_ms=now), None
    except (OSError, ValueError, KeyError) as exc:
        return None, None, dict(input="liquidation_snapshot", reason=str(exc))


def run_cycle(config, *, fetcher=fetch_official_bytes, equity_collector=collect_ibkr_equity_daily_proof):
    root = safe_root(config)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".cycle.lock"
    try:
        guard = lock.open("x")
    except FileExistsError:
        raise ValueError("CYCLE_ALREADY_RUNNING_OR_INTERRUPTED_REQUIRES_REVIEW") from None
    try:
        with guard:
            guard.write(str(time.time()))
        state_path = root / "collection-state.json"
        state = read_json(state_path) if state_path.exists() else {}
        registry = SourceRegistry.load(default_registry_path())
        capture = PublicArchive(root, state, registry, fetcher=fetcher)
        seed_archive(config.get("issuer_archive"), root / "issuer-archive")
        overrides = {}
        for item in registry.payload["sources"]:
            spec = registry.get(item["source_id"])
            if not spec.transport.startswith(("HTTPS", "MULTI_HTTPS")):
                overrides[spec.source_id] = FetchResult(spec.source_id, "MISSING", attempts=0,
                    error="NOT_PART_OF_PUBLIC_SNAPSHOT_COLLECTION")
                continue
            try:
                endpoints = spec.raw.get("endpoints") or {"default": spec.endpoint}
                values = {}
                for key, url in endpoints.items():
                    interval = ((int(time.time()*1000) // 86_400_000 + 1)*86_400_000 - int(time.time()*1000)
                                if spec.input_family == "PRICE_STRUCTURE_CONTEXT"
                                else min(spec.max_age_seconds * 1000, 3_600_000))
                    raw, _, _ = capture.get(url, spec.source_id, registry.hash, refresh_ms=interval)
                    transport = spec.raw.get("endpoint_transports", {}).get(key, spec.transport)
                    values[key] = raw.decode("utf-8-sig") if "CSV" in transport else json.loads(raw)
                payload = values if spec.raw.get("endpoints") else values["default"]
                overrides[spec.source_id] = FetchResult(spec.source_id, "OK", payload=payload)
            except Exception as exc:
                overrides[spec.source_id] = FetchResult(spec.source_id, "ERROR", error=str(exc))
        issuer_wake, issuer_gaps = collect_issuers(capture, root)
        now = int(time.time() * 1000)
        equities, equity_status = collect_equities(config, root, state, now, collector=equity_collector)
        now = int(time.time() * 1000)
        close_mark = collect_close_mark(capture, equities, now)
        now = int(time.time() * 1000)
        ct = issuer_source.build_archived_issuer_ct_inputs(root / "issuer-archive", as_of_ms=now)
        ratio_data = {}
        ledger_comparison = root / "reported-ledger-comparison.json"
        if ledger_comparison.exists():
            ratio_data["MSTR"] = read_json(ledger_comparison)
        asst_history = ct["ASST"].get("asset_history", [])
        if len(asst_history) >= 2:
            rows = [dict(btc_holdings=r["btc_holdings"], diluted_shares=r["diluted_shares"],
                btc_per_diluted_share=r["btc_holdings"]/r["diluted_shares"],
                effective_at_ms=r["effective_time"], source_url=r["source_ref"].split("#sha256=")[0],
                evidence_hash=r["source_evidence"]["raw_sha256"]) for r in asst_history]
            ratio_data.update(issuer_source.build_ratio_data({"ASST": rows}, assets=("ASST",)))
        ratio_observation = build_issuer_ratio_observation(seal_runtime_source(
            source_key="issuer_btc_per_diluted_share", data=ratio_data, observed_at_ms=now),
            generated_at_ms=now) if ratio_data else None
        research = {}
        if config.get("tracker_archive"):
            for asset in ("MSTR", "ASST"):
                research[asset] = build_retrospective_tracker_context(config["tracker_archive"], asset_id=asset, as_of_ms=now)
        source_archives = [dict(source_url=url, artifact=value[1]) for url, value in capture.in_cycle.items()
                           if not isinstance(value, Exception)]
        liquidation, local_market_artifact, local_market_gap = retained_liquidations(config, root, registry, now)
        if local_market_artifact is not None:
            source_archives.append(local_market_artifact)
        private = None
        private_gap = None
        if config.get("private_profile") and config.get("allow_retained_local_capital") is True:
            try:
                if not Path(config["private_profile"]).is_file():
                    raise ValueError("PRIVATE_PROFILE_MISSING")
                # This loader only reads retained local files and reconciles
                # their original clocks; it cannot connect to a broker.
                private = load_private_profile(config["private_profile"], include_capital_sidecars=True)
            except Exception as exc:
                private_gap = type(exc).__name__ + ":" + str(exc)
        else:
            private_gap = "LOCAL_PERSONAL_CAPITAL_NOT_READ"
        optional = {}
        input_gaps = [local_market_gap] if local_market_gap is not None else []
        for key in ("fixed_income_inputs", "portfolio_allocation_inputs"):
            if config.get(key):
                try:
                    optional[key] = read_json(config[key])
                except (OSError, ValueError) as exc:
                    input_gaps.append(dict(input=key, reason=str(exc)))
        pack = run_daily_evidence(registry, observation_db=root / "observations.sqlite3",
            fetch_overrides=overrides, probe_fetcher=lambda spec: overrides[spec.source_id],
            generated_at_ms=now, now_ms=now, treasury_company_ct_inputs=ct,
            treasury_valuation_inputs={a: {"retrospective_research": r} for a, r in research.items()},
            qualified_equity_daily_source=equities, private_context=private,
            liquidation_aggregate_payload=liquidation,
            issuer_ratio_observation=ratio_observation,
            issuer_announcement_wake=issuer_wake, **optional)
        folder = root / "cycles" / (str(now) + "-" + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        write_json_atomic(folder / "evidence-pack.json", pack)
        capital = None
        try:
            capital = _bridge_capital_state(pack.get("private_context"), generated_at_ms=now)
        except ValueError as exc:
            private_gap = str(exc)
        analysis = dict(storage="LOCAL_ONLY", state="ANALYST_REVIEW_INPUT_NOT_MODEL_RECEIPT",
            evidence_pack_hash=pack["evidence_pack_hash"], generated_at_ms=now,
            market_context=_bridge_market_context(pack),
            capital_state=capital,
            retrospective_research=research, capital_inputs_reason=private_gap,
            source_archives=source_archives,
            issuer_ratio_observation=(compact_issuer_ratio_observation(ratio_observation, generated_at_ms=now)
                                      if ratio_observation is not None else None),
            input_gaps=input_gaps,
            btc_equity_close_research=close_mark,
            model_request_performed=False, notification_performed=False, **LOCKS)
        write_json_atomic(folder / "capital-analysis-input.json", analysis)
        report = dict(state="READ_ONLY_OBSERVATION_CYCLE_COMPLETED", evaluated_at_ms=now,
            evidence_pack_hash=pack["evidence_pack_hash"], evidence_pack_state=pack["pack_state"],
            cycle_path=str(folder), requests=capture.requests, equity_status=equity_status,
            qualified_equity_prices=pack.get("qualified_equity_prices"), issuer_gaps=issuer_gaps,
            btc_equity_close_research=close_mark,
            retrospective_research=research, source_quality=pack["data_health"], source_archives=source_archives,
            paid_model_requests=0, account_refreshes=0, notifications=0, trades=0, **LOCKS)
        write_json_atomic(folder / "collection-receipt.json", report)
        write_json_atomic(state_path, state)
        write_json_atomic(root / "latest.json", report)
        return report
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_cycle(read_json(args.config))
    if sys.stdout is not None:
        print(json.dumps({k: result[k] for k in ("state", "evaluated_at_ms", "evidence_pack_state",
            "paid_model_requests", "account_refreshes", "notifications", "trades")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
