"""Synthetic archive mechanics only; these fixtures confer no live readiness."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from crt_radar import l6_source_binding as l6
from crt_radar.evidence_pack import _group_layers
from crt_radar.observation_store import ObservationStore, extract_observations
from crt_radar.source_gate_runner import run_source_gate, default_registry_path, FetchResult
from crt_radar.source_registry import SourceRegistry, RegistryError
from crt_radar.v110_candidate import evaluate_v110_candidate

END = 1788134400000  # completed UTC day boundary
NOW = END + l6.DAY + 1000


def zipped(name, content):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, content)
    return output.getvalue()


class L6SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.authority = l6.lock()

    def artifact(self, raw, url, **extra):
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / "artifacts" / "sha256" / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return dict(sha256=digest, size_bytes=len(raw), request_identity="GET " + url,
                    first_seen_at_ms=NOW, retrieved_at_ms=NOW,
                    evidence_class="CURRENT_FIRST_SEEN_CAPTURE", license_classification="LOCAL_RESEARCH_ONLY",
                    source_authority_hash=l6.AUTHORITY_HASH, **extra)

    def manifest(self, family, artifacts):
        result = dict(schema_version="CRT_L6_SOURCE_ARCHIVES_V0.1", input_family=family,
                      source_id=l6.SOURCE_IDS[family], window_end_ms=END,
                      source_authority_hash=l6.AUTHORITY_HASH,
                      artifacts=artifacts)
        self.save(family, result)
        return result

    def save(self, family, manifest):
        (self.root / f"{family}.json").write_text(json.dumps(manifest), encoding="utf-8")

    def composite(self, *, missing_venue=False, missing_day=False, future=False):
        artifacts = []
        for index, venue in enumerate(self.authority["decisions"][l6.COMPOSITE]["venue_universe"]):
            if missing_venue and index == 2:
                continue
            rows = []
            for day in range(201):
                if missing_day and index == 1 and day == 200:
                    continue
                start = END - (201 - day) * l6.DAY
                if future and index == 1 and day == 200:
                    start = NOW // l6.DAY * l6.DAY
                base = 100 + day + index * 10
                rows.append((start // 1000, base, base + 8, base - 3, base + 2, 50))
            extra = dict(venue_id=venue["venue_id"], product=venue["product"], transport=venue["transport"])
            if index == 0:
                raw = json.dumps([[t, low, h, o, c, v] for t, o, h, low, c, v in rows]).encode()
                url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400"
            elif index == 1:
                raw = zipped("XBTUSD_1440.csv", "\n".join(",".join(map(str, row)) + ",5" for row in rows))
                url = "https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_2026Q2.zip"
                extra["archive_member"] = "XBTUSD_1440.csv"
                extra["official_link_artifact"] = self.artifact(
                    f'<a href="{url}">archive</a>'.encode(), venue["documentation"])
            else:
                raw = json.dumps({"data": {"pair": "BTC/USD", "ohlc": [dict(zip(
                    ("timestamp", "open", "high", "low", "close", "volume"), row)) for row in rows]}}).encode()
                url = "https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400"
            artifacts.append(self.artifact(raw, url, **extra))
        return self.manifest(l6.COMPOSITE, artifacts)

    def aggressor(self, *, unknown=False, gap=False, partial=False, boundary=False, old_units=False):
        artifacts = []
        for index in range(22):
            start = END - (21 - index) * l6.DAY
            from datetime import datetime, timezone
            date = datetime.fromtimestamp(start / 1000, timezone.utc).strftime("%Y-%m-%d")
            filename = f"BTCUSDT-aggTrades-{date}.zip"
            url = "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/" + filename
            identifier = index * 2
            if boundary and index == 10:
                identifier += 1
            timestamp = start if old_units else start * 1000
            if partial and index == 10:
                timestamp = (start + l6.DAY) * 1000
            side = "unknown" if unknown and index == 10 else "false"
            rows = [f"{identifier},10,3,{identifier},{identifier},{timestamp},{side},true",
                    f"{identifier+1},10,1,{identifier+1},{identifier+1},{timestamp+1000},true,true"]
            if gap and index == 10:
                rows.pop()
            raw = zipped(filename[:-4] + ".csv", "\n".join(rows))
            item = self.artifact(raw, url, symbol="BTCUSDT", day_start_ms=start)
            item["checksum_artifact"] = self.artifact(f'{item["sha256"]}  {filename}\n'.encode(), url + ".CHECKSUM")
            artifacts.append(item)
        return self.manifest(l6.AGGRESSOR, artifacts)

    def load(self, family):
        return l6.load_source(family, now_ms=NOW, root=self.root)

    def test_three_venues_ready_and_median_deterministic(self):
        self.composite()
        output = self.load(l6.COMPOSITE)
        self.assertEqual(output["state"], "READY")
        row = output["measurement_rows"][-1]
        self.assertEqual([row[x] for x in ("open", "high", "low", "close")], [310, 318, 307, 312])
        self.assertEqual(row["venue_count"], 3)
        self.assertEqual(row["volume"], 150)
        self.assertGreater(row["dispersion_bps"]["close"], 0)
        self.assertEqual(output["authority"]["formal_model"], "NOT_APPROVED")
        raw = {"schema_version": "CRT_CANDIDATE_RAW_INPUT_V0.2", "tables": {"OHLCV_DAILY": output["measurement_rows"]}}
        for metric, feature in l6.METRICS[l6.COMPOSITE].items():
            self.assertEqual(output[metric], round(l6.CALCULATORS[feature](raw, NOW), 10))

    def test_two_venues_blocked(self):
        self.composite(missing_venue=True)
        with self.assertRaisesRegex(l6.L6SourceError, "THREE_VENUE_DAY_MISSING"):
            self.load(l6.COMPOSITE)

    def test_incomplete_venue_blocks(self):
        self.composite(missing_day=True)
        with self.assertRaisesRegex(l6.L6SourceError, "THREE_VENUE_DAY_MISSING"):
            self.load(l6.COMPOSITE)

    def test_current_or_future_bar_cannot_replace_completed_day(self):
        self.composite(future=True)
        with self.assertRaisesRegex(l6.L6SourceError, "THREE_VENUE_DAY_MISSING"):
            self.load(l6.COMPOSITE)

    def test_future_retrieval_rejected(self):
        manifest = self.composite()
        manifest["artifacts"][0]["retrieved_at_ms"] = NOW + 1
        self.save(l6.COMPOSITE, manifest)
        with self.assertRaisesRegex(l6.L6SourceError, "AVAILABILITY"):
            self.load(l6.COMPOSITE)

    def test_bytes_tamper_and_synthetic_label_rejected(self):
        manifest = self.composite()
        item = manifest["artifacts"][0]
        item["evidence_class"] = "SYNTHETIC_FIXTURE"
        self.save(l6.COMPOSITE, manifest)
        with self.assertRaisesRegex(l6.L6SourceError, "NON_LIVE"):
            self.load(l6.COMPOSITE)
        item["evidence_class"] = "CURRENT_FIRST_SEEN_CAPTURE"
        self.save(l6.COMPOSITE, manifest)
        (self.root / "artifacts/sha256" / item["sha256"][:2] / item["sha256"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(l6.L6SourceError, "BYTES_MISMATCH"):
            self.load(l6.COMPOSITE)

    def test_proxy_identity_cannot_be_composite(self):
        manifest = self.composite()
        manifest["artifacts"][0]["venue_id"] = "BINANCE_BTCUSDT"
        self.save(l6.COMPOSITE, manifest)
        with self.assertRaisesRegex(l6.L6SourceError, "VENUE_NOT_LOCKED"):
            self.load(l6.COMPOSITE)

    def test_mapping_quote_volume_and_cvd(self):
        self.aggressor()
        output = self.load(l6.AGGRESSOR)
        self.assertEqual(output["cvd_20d_share"], 0.5)
        row = output["measurement_rows"][-1]
        self.assertEqual(row["buyer_initiated_quote_volume"], 30)
        self.assertEqual(row["seller_initiated_quote_volume"], 10)
        self.assertEqual(row["unknown_aggressor_quote_volume"], 0)

    def test_unknown_side_blocked(self):
        self.aggressor(unknown=True)
        with self.assertRaisesRegex(l6.L6SourceError, "UNKNOWN_AGGRESSOR"):
            self.load(l6.AGGRESSOR)

    def test_partial_daily_period_blocked(self):
        self.aggressor(partial=True)
        with self.assertRaisesRegex(l6.L6SourceError, "OUTSIDE_DAY"):
            self.load(l6.AGGRESSOR)

    def test_timestamp_units_enforced(self):
        self.aggressor(old_units=True)
        with self.assertRaisesRegex(l6.L6SourceError, "OUTSIDE_DAY"):
            self.load(l6.AGGRESSOR)

    def test_internal_and_adjacent_gaps_blocked(self):
        for option in ("gap", "boundary"):
            with self.subTest(option=option):
                self.aggressor(**{option: True})
                with self.assertRaisesRegex(l6.L6SourceError, "BOUNDARY_GAP"):
                    self.load(l6.AGGRESSOR)

    def test_missing_day_blocked(self):
        manifest = self.aggressor()
        manifest["artifacts"].pop(10)
        self.save(l6.AGGRESSOR, manifest)
        with self.assertRaisesRegex(l6.L6SourceError, "DAY_OR_BOUNDARY_MISSING"):
            self.load(l6.AGGRESSOR)

    def test_provider_checksum_required(self):
        manifest = self.aggressor()
        manifest["artifacts"][0]["checksum_artifact"]["request_identity"] += "wrong"
        self.save(l6.AGGRESSOR, manifest)
        with self.assertRaisesRegex(l6.L6SourceError, "CHECKSUM_IDENTITY"):
            self.load(l6.AGGRESSOR)

    def test_source_gate_to_candidate_qualifies_four_metrics(self):
        self.composite()
        self.aggressor()
        registry = SourceRegistry.load(default_registry_path())
        gate = run_source_gate(registry, fetch_overrides={}, now_ms=NOW, l6_source_root=self.root)
        observations = extract_observations(gate, recorded_at_ms=NOW)
        self.assertEqual(gate["l6_candidate_state"], "READY")
        self.assertEqual(gate["base_source_registry_hash"], registry.hash)
        layers = _group_layers(observations)
        proxies = [replace(x, input_family="PRICE_STRUCTURE_CONTEXT",
                           source_id="CRT-CONN-BTC-SPOT-PRICE-STRUCTURE-PROXY-001", value_num=-999)
                   for x in observations]
        self.assertEqual(_group_layers(observations + proxies), layers)
        self.assertEqual(_group_layers(proxies + observations), layers)
        store = ObservationStore(self.root / "observations.sqlite")
        self.addCleanup(store.close)
        store.record(observations)
        output = evaluate_v110_candidate(layers, store, evaluation_at_ms=NOW)
        self.assertFalse([x for x in output["input_blocked_reasons"] if x.startswith("L6_")])
        self.assertEqual(output["formal_model"], "NOT_APPROVED")
        self.assertEqual(output["production"], "NOT_APPROVED")
        self.assertEqual(output["action_output"], "NONE")
        self.assertEqual(output["authority"]["capital_decision_authority"], "USER_ONLY")
        for family, metrics in l6.METRICS.items():
            for metric in metrics:
                self.assertEqual(layers["L6"]["metrics"][metric]["source_id"], l6.SOURCE_IDS[family])
                self.assertEqual(layers["L6"]["metrics"][metric]["input_family"], family)

    def test_unavailable_sources_block_and_overrides_cannot_spoof(self):
        registry = SourceRegistry.load(default_registry_path())
        overrides = {source: FetchResult(source, "OK", payload={"cvd_20d_share": 0.5})
                     for source in l6.SOURCE_IDS.values()}
        gate = run_source_gate(registry, fetch_overrides=overrides, now_ms=NOW, l6_source_root=self.root)
        self.assertEqual(gate["formal_state"], "BLOCKED")
        self.assertEqual(gate["l6_candidate_state"], "BLOCKED")
        for family in l6.SOURCE_IDS:
            self.assertNotIn(family, gate["parsed"])
            self.assertIn(family + "_INVALID", gate["l6_candidate_blocked_reasons"])

    def test_registry_identity_and_authority_cannot_drift(self):
        payload = SourceRegistry.load(default_registry_path()).with_l6_candidate_sources().payload
        for field, value in (("source_id", "proxy"), ("formal_model", "APPROVED")):
            changed = deepcopy(payload)
            next(x for x in changed["sources"] if x["input_family"] == l6.COMPOSITE)[field] = value
            with self.assertRaises(RegistryError):
                SourceRegistry(changed)

    def test_base_registry_remains_sealed_and_overlay_idempotent(self):
        registry = SourceRegistry.load(default_registry_path())
        before = deepcopy(registry.payload)
        bound = registry.with_l6_candidate_sources()
        self.assertEqual(registry.payload, before)
        self.assertEqual(registry.hash, "30ee09f0c6403c9d782a49411c61c24b91d6522d8c4960c4dfd6ef572e7375bc")
        self.assertEqual(bound.with_l6_candidate_sources().hash, bound.hash)
        proxy = bound.by_input_family("PRICE_STRUCTURE_CONTEXT")
        self.assertEqual(proxy.raw["formal_composite_authority"], "NONE")

    def test_missing_l6_does_not_invalidate_independent_l4(self):
        from test_source_gate_migration import SourceGateMigrationTests, NOW_MS
        fixture = SourceGateMigrationTests()
        fixture.setUp()
        gate = run_source_gate(fixture.registry, fetch_overrides=fixture.overrides,
                               liquidation_aggregate_payload=fixture.aggregate(), now_ms=NOW_MS)
        self.assertEqual(gate["l6_candidate_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATES", gate["parsed"])
        self.assertEqual(gate["formal_state"], "OBSERVATION_ONLY")
        layers = _group_layers(extract_observations(gate, recorded_at_ms=NOW_MS))
        with ObservationStore(self.root / "missing.sqlite") as store:
            candidate = evaluate_v110_candidate(layers, store, evaluation_at_ms=NOW_MS)
        for suffix in ("SOURCE_NOT_APPROVED", "INPUT_FAMILY_NOT_APPROVED"):
            self.assertTrue(any(x.startswith("L6_") and x.endswith(suffix)
                                for x in candidate["input_blocked_reasons"]))

    def test_duplicate_venue_day_rejected(self):
        manifest = self.composite()
        manifest["artifacts"].append(deepcopy(manifest["artifacts"][0]))
        self.save(l6.COMPOSITE, manifest)
        with self.assertRaisesRegex(l6.L6SourceError, "DUPLICATE_VENUE_DAY"):
            self.load(l6.COMPOSITE)


if __name__ == "__main__":
    unittest.main()
