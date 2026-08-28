from __future__ import annotations

import argparse
import importlib.util
import json
import math
import socket
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from .daily_evidence_runner import write_json_atomic
from .evidence_pack import attach_premarket_market_data
from .premarket_battle_map import build_premarket_battle_map
from .premarket_evidence_binding import build_premarket_evidence_binding
from .premarket_equity_live_snapshot import (
    ASSET_ORDER,
    SCHEMA_VERSION,
    build_equity_source_binding,
    seal_equity_live_snapshot,
    validate_equity_source_binding,
    validate_equity_live_snapshot,
)
from .premarket_live_market_handoff import (
    apply_live_market_handoff_to_asset_facts,
    build_premarket_live_market_handoff,
)
from .source_registry import SourceRegistry, canonical_json_bytes, sha256_hex


SOURCE_ID = "CRT-CONN-EQUITY-PREMARKET-IBKR-001"
PROVIDER_CONTRACT_ID = "IBKR-TWS-API-L1-RTBARS-5S-V1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7497
DEFAULT_CLIENT_ID = 168
DEFAULT_DURATION_SECONDS = 12.0

LIVE_MARKET_DATA_TYPE = 1
RT_VOLUME_TICK_TYPE = 48
INFORMATIONAL_ERROR_CODES = {
    2104,
    2106,
    2107,
    2108,
    2158,
}
ALLOWED_IBKR_REQUEST_METHODS = {
    "connect",
    "reqMarketDataType",
    "reqMktData",
    "reqRealTimeBars",
    "cancelMktData",
    "cancelRealTimeBars",
    "disconnect",
}


class IbkrIntakeError(RuntimeError):
    """The local IBKR market-data intake failed closed."""


@dataclass(frozen=True)
class IbkrIntakeConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    client_id: int = DEFAULT_CLIENT_ID
    duration_seconds: float = DEFAULT_DURATION_SECONDS
    connect_timeout_seconds: float = 8.0

    def validate(self) -> "IbkrIntakeConfig":
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("IBKR intake host must be local loopback")
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise ValueError("IBKR socket port must be an integer")
        if not 1 <= self.port <= 65535:
            raise ValueError("IBKR socket port is outside the valid range")
        if not isinstance(self.client_id, int) or isinstance(self.client_id, bool):
            raise ValueError("IBKR client id must be an integer")
        if self.client_id < 0:
            raise ValueError("IBKR client id must be nonnegative")
        if not math.isfinite(float(self.duration_seconds)):
            raise ValueError("IBKR capture duration must be finite")
        if float(self.duration_seconds) < 5.0:
            raise ValueError("IBKR capture duration must cover at least one 5-second bar")
        if not math.isfinite(float(self.connect_timeout_seconds)):
            raise ValueError("IBKR connect timeout must be finite")
        if float(self.connect_timeout_seconds) <= 0:
            raise ValueError("IBKR connect timeout must be positive")
        return self


class IbkrFeed(Protocol):
    def collect(self, config: IbkrIntakeConfig) -> dict[str, Any]: ...


def build_ibkr_source_registry(
    base_registry: SourceRegistry,
    overlay: dict[str, Any],
) -> SourceRegistry:
    if not isinstance(base_registry, SourceRegistry):
        raise ValueError("base source registry required")
    if not isinstance(overlay, dict):
        raise ValueError("IBKR source overlay must be an object")
    if overlay.get("overlay_version") != "CRT_IBKR_EQUITY_SOURCE_OVERLAY_V0.1":
        raise ValueError("IBKR source overlay version mismatch")
    if overlay.get("base_registry_mutation") != "FORBIDDEN":
        raise ValueError("IBKR source overlay must forbid base registry mutation")
    if overlay.get("base_registry_id") != base_registry.payload.get("registry_id"):
        raise ValueError("IBKR source overlay base registry id mismatch")
    if overlay.get("external_action_authority") != "NONE":
        raise ValueError("IBKR source overlay external action authority must be NONE")
    if overlay.get("capital_decision_authority") != "USER_ONLY":
        raise ValueError("IBKR source overlay capital authority must be USER_ONLY")

    source = overlay.get("source")
    if not isinstance(source, dict):
        raise ValueError("IBKR source overlay source missing")
    if source.get("source_id") != SOURCE_ID:
        raise ValueError("IBKR source id mismatch")
    if source.get("provider_contract_id") != PROVIDER_CONTRACT_ID:
        raise ValueError("IBKR provider contract id mismatch")
    if source.get("order_api_surface") != "ABSENT":
        raise ValueError("IBKR order API surface must be absent")
    if source.get("api_request_surface") != [
        "reqMarketDataType",
        "reqMktData",
        "reqRealTimeBars",
        "cancelMktData",
        "cancelRealTimeBars",
    ]:
        raise ValueError("IBKR market-data request surface mismatch")
    if source.get("external_action_authority") != "NONE":
        raise ValueError("IBKR source external action authority must be NONE")
    if source.get("capital_decision_authority") != "USER_ONLY":
        raise ValueError("IBKR source capital authority must be USER_ONLY")
    if source.get("machine_may_execute_trade") is not False:
        raise ValueError("IBKR source cannot execute trades")
    market_contract = source.get("market_data_contract")
    if not isinstance(market_contract, dict):
        raise ValueError("IBKR market data contract missing")
    if market_contract.get("regulatory_snapshot") is not False:
        raise ValueError("IBKR regulatory snapshots must remain disabled")
    if market_contract.get("market_data_type") != "LIVE_ONLY":
        raise ValueError("IBKR source must remain live-data only")

    payload = deepcopy(base_registry.payload)
    payload["registry_id"] = f"{payload['registry_id']}+IBKR-EQUITY-V0.1"
    payload["version"] = f"{payload['version']}+ibkr-equity-v0.1"
    payload["status"] = "CANDIDATE_UNMERGED"
    payload["base_source_registry_hash"] = base_registry.hash
    payload["sources"].append(deepcopy(source))
    return SourceRegistry(payload)


def load_ibkr_source_registry(
    base_registry_path: str | Path,
    overlay_path: str | Path,
) -> SourceRegistry:
    base = SourceRegistry.load(base_registry_path)
    overlay = json.loads(Path(overlay_path).read_text(encoding="utf-8"))
    return build_ibkr_source_registry(base, overlay)


def _positive_number(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise IbkrIntakeError(f"{field} missing")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise IbkrIntakeError(f"{field} invalid") from exc
    if not math.isfinite(number) or number <= 0:
        raise IbkrIntakeError(f"{field} must be positive")
    return number


def _optional_positive(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _optional_nonnegative(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _port_open(host: str, port: int, timeout_seconds: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def inspect_ibkr_environment(
    *,
    host: str = DEFAULT_HOST,
    ports: tuple[int, ...] = (7497, 7496, 4002, 4001),
    module_available: Callable[[str], bool] | None = None,
    port_probe: Callable[[str, int], bool] | None = None,
) -> dict[str, Any]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("IBKR preflight only supports local loopback")

    if module_available is None:
        module_available = lambda name: importlib.util.find_spec(name) is not None
    if port_probe is None:
        port_probe = _port_open

    ibapi_available = bool(module_available("ibapi"))
    port_states = [
        {"port": int(port), "listening": bool(port_probe(host, int(port)))}
        for port in ports
    ]
    listening = [row["port"] for row in port_states if row["listening"]]

    blockers = []
    if not ibapi_available:
        blockers.append("IBAPI_PYTHON_PACKAGE_NOT_AVAILABLE")
    if not listening:
        blockers.append("TWS_OR_IB_GATEWAY_API_PORT_NOT_LISTENING")

    return {
        "schema_version": "CRT_IBKR_API_PREFLIGHT_V0.1",
        "state": "READY_FOR_OPERATOR_CONFIRMATION" if not blockers else "BLOCKED",
        "host": host,
        "ibapi_python_available": ibapi_available,
        "ports": port_states,
        "listening_ports": listening,
        "tws_read_only_api_setting": "USER_CONFIRMATION_REQUIRED",
        "required_tws_read_only_api_setting": True,
        "regulatory_snapshot_requests": False,
        "per_request_snapshot_fee_authority": "NONE",
        "allowed_api_request_methods": sorted(ALLOWED_IBKR_REQUEST_METHODS),
        "blockers": blockers,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
    }


def _parse_rt_volume(value: str) -> dict[str, Any] | None:
    parts = value.split(";")
    if len(parts) < 6:
        return None
    try:
        price = float(parts[0])
        size = float(parts[1])
        trade_at_ms = int(parts[2])
        total_volume = float(parts[3])
        vwap = float(parts[4])
        single_trade = parts[5].strip().lower() == "true"
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (price, size, total_volume, vwap)):
        return None
    if price <= 0 or size < 0 or trade_at_ms <= 0 or total_volume < 0:
        return None
    return {
        "price": price,
        "size": size,
        "trade_at_ms": trade_at_ms,
        "total_volume": total_volume,
        "vwap": vwap,
        "single_trade": single_trade,
    }


def _native_feed_app() -> tuple[type[Any], type[Any]]:
    try:
        from ibapi.client import EClient
        from ibapi.contract import Contract
        from ibapi.wrapper import EWrapper
    except ImportError as exc:
        raise IbkrIntakeError(
            "official IBKR TWS API Python package is not installed"
        ) from exc

    class MarketDataApp(EWrapper, EClient):
        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.lock = threading.Lock()
            self.request_map: dict[int, tuple[str, str]] = {}
            self.assets = {
                asset: {
                    "market_data_type": None,
                    "l1": {},
                    "rt_volume": None,
                    "bars_5s": [],
                    "last_received_at_ms": None,
                }
                for asset in ASSET_ORDER
            }
            self.failures: list[dict[str, Any]] = []

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            del orderId
            self.ready.set()

        def error(self, reqId: int, *args: Any) -> None:
            if len(args) >= 4:
                error_code = args[1]
                error_string = args[2]
            elif len(args) >= 2:
                error_code = args[0]
                error_string = args[1]
            else:
                error_code = -1
                error_string = "UNPARSEABLE_IBKR_ERROR"
            try:
                code = int(error_code)
            except (TypeError, ValueError):
                code = -1
            if code in INFORMATIONAL_ERROR_CODES:
                return
            with self.lock:
                self.failures.append(
                    {"req_id": reqId, "code": code, "message": str(error_string)}
                )

        def _asset(self, req_id: int, channel: str) -> str | None:
            bound = self.request_map.get(req_id)
            if bound is None or bound[1] != channel:
                return None
            return bound[0]

        def tickPrice(  # noqa: N802
            self,
            reqId: int,
            tickType: int,
            price: float,
            attrib: Any,
        ) -> None:
            del attrib
            asset = self._asset(reqId, "L1")
            if asset is None:
                return
            fields = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close"}
            field = fields.get(int(tickType))
            number = _optional_positive(price)
            if field is None or number is None:
                return
            received = int(time.time() * 1000)
            with self.lock:
                self.assets[asset]["l1"][field] = number
                self.assets[asset]["last_received_at_ms"] = received

        def tickSize(self, reqId: int, tickType: int, size: Any) -> None:  # noqa: N802
            asset = self._asset(reqId, "L1")
            if asset is None:
                return
            fields = {0: "bid_size", 3: "ask_size", 5: "last_size", 8: "volume"}
            field = fields.get(int(tickType))
            number = _optional_nonnegative(size)
            if field is None or number is None:
                return
            received = int(time.time() * 1000)
            with self.lock:
                self.assets[asset]["l1"][field] = number
                self.assets[asset]["last_received_at_ms"] = received

        def tickString(self, reqId: int, tickType: int, value: str) -> None:  # noqa: N802
            asset = self._asset(reqId, "L1")
            if asset is None or int(tickType) != RT_VOLUME_TICK_TYPE:
                return
            parsed = _parse_rt_volume(value)
            if parsed is None:
                return
            received = int(time.time() * 1000)
            parsed["received_at_ms"] = received
            with self.lock:
                self.assets[asset]["rt_volume"] = parsed
                self.assets[asset]["last_received_at_ms"] = received

        def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802
            asset = self._asset(reqId, "L1")
            if asset is None:
                return
            with self.lock:
                self.assets[asset]["market_data_type"] = int(marketDataType)

        def realtimeBar(  # noqa: N802
            self,
            reqId: int,
            date: int,
            open_: float,
            high: float,
            low: float,
            close: float,
            volume: Any,
            wap: Any,
            count: int,
        ) -> None:
            asset = self._asset(reqId, "BAR_5S")
            if asset is None:
                return
            bar = {
                "time_s": int(date),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "wap": float(wap),
                "count": int(count),
                "received_at_ms": int(time.time() * 1000),
            }
            with self.lock:
                self.assets[asset]["bars_5s"].append(bar)
                self.assets[asset]["last_received_at_ms"] = bar["received_at_ms"]

    return MarketDataApp, Contract


class NativeIbkrFeed:
    def collect(self, config: IbkrIntakeConfig) -> dict[str, Any]:
        locked = config.validate()
        MarketDataApp, Contract = _native_feed_app()
        app = MarketDataApp()
        thread: threading.Thread | None = None
        request_ids: list[tuple[int, int]] = []

        try:
            app.connect(locked.host, locked.port, locked.client_id)
            thread = threading.Thread(target=app.run, name="crt-ibkr-market-data", daemon=True)
            thread.start()
            if not app.ready.wait(locked.connect_timeout_seconds):
                raise IbkrIntakeError("IBKR API handshake timed out")

            app.reqMarketDataType(LIVE_MARKET_DATA_TYPE)
            for index, asset in enumerate(ASSET_ORDER):
                l1_id = 1000 + index
                bar_id = 2000 + index
                app.request_map[l1_id] = (asset, "L1")
                app.request_map[bar_id] = (asset, "BAR_5S")

                contract = Contract()
                contract.symbol = asset
                contract.secType = "STK"
                contract.exchange = "SMART"
                contract.currency = "USD"

                app.reqMktData(l1_id, contract, "233", False, False, [])
                app.reqRealTimeBars(bar_id, contract, 5, "TRADES", False, [])
                request_ids.append((l1_id, bar_id))

            threading.Event().wait(locked.duration_seconds)
        finally:
            for l1_id, bar_id in request_ids:
                try:
                    app.cancelMktData(l1_id)
                    app.cancelRealTimeBars(bar_id)
                except Exception:
                    pass
            try:
                app.disconnect()
            finally:
                if thread is not None:
                    thread.join(timeout=2.0)

        with app.lock:
            failures = deepcopy(app.failures)
            assets = deepcopy(app.assets)

        if failures:
            raise IbkrIntakeError(
                "IBKR market data request failed: "
                + json.dumps(failures, ensure_ascii=False, sort_keys=True)
            )

        return {
            "captured_at_ms": int(time.time() * 1000),
            "assets": assets,
        }


def _normalize_bar(asset: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise IbkrIntakeError(f"{asset} 5-second bar invalid")
    time_s = raw.get("time_s")
    if not isinstance(time_s, int) or isinstance(time_s, bool) or time_s <= 0:
        raise IbkrIntakeError(f"{asset} 5-second bar time invalid")
    open_ = _positive_number(raw.get("open"), f"{asset}.bar.open")
    high = _positive_number(raw.get("high"), f"{asset}.bar.high")
    low = _positive_number(raw.get("low"), f"{asset}.bar.low")
    close = _positive_number(raw.get("close"), f"{asset}.bar.close")
    if high < low or not low <= open_ <= high or not low <= close <= high:
        raise IbkrIntakeError(f"{asset} 5-second bar geometry invalid")
    volume = _optional_nonnegative(raw.get("volume"))
    wap = _optional_positive(raw.get("wap"))
    count = raw.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise IbkrIntakeError(f"{asset} 5-second bar count invalid")
    received_at_ms = raw.get("received_at_ms", time_s * 1000)
    if not isinstance(received_at_ms, int) or isinstance(received_at_ms, bool):
        raise IbkrIntakeError(f"{asset} 5-second bar reception time invalid")
    return {
        "time_s": time_s,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "wap": wap,
        "count": count,
        "received_at_ms": received_at_ms,
    }


def _is_premarket(timestamp_ms: int) -> bool:
    observed = datetime.fromtimestamp(timestamp_ms / 1000, tz=ZoneInfo("America/New_York"))
    local_time = observed.timetz().replace(tzinfo=None)
    return observed.weekday() < 5 and clock_time(4, 0) <= local_time < clock_time(9, 30)


def build_ibkr_equity_live_snapshot(
    capture: dict[str, Any],
    *,
    source_binding: dict[str, Any],
    config: IbkrIntakeConfig,
    retrieved_at_ms: int | None = None,
) -> dict[str, Any]:
    locked_config = config.validate()
    binding = validate_equity_source_binding(source_binding)

    if not isinstance(capture, dict) or not isinstance(capture.get("assets"), dict):
        raise IbkrIntakeError("IBKR capture assets missing")
    if list(capture["assets"]) != list(ASSET_ORDER):
        raise IbkrIntakeError("IBKR capture asset order mismatch")

    retrieved = int(time.time() * 1000) if retrieved_at_ms is None else int(retrieved_at_ms)
    normalized_assets: dict[str, dict[str, Any]] = {}
    observation_times: list[int] = []

    for asset in ASSET_ORDER:
        raw = capture["assets"].get(asset)
        if not isinstance(raw, dict):
            raise IbkrIntakeError(f"{asset} capture missing")
        if raw.get("market_data_type") != LIVE_MARKET_DATA_TYPE:
            raise IbkrIntakeError(f"{asset} did not confirm live market data type")

        l1 = raw.get("l1") if isinstance(raw.get("l1"), dict) else {}
        raw_bars = raw.get("bars_5s")
        if not isinstance(raw_bars, list):
            raise IbkrIntakeError(f"{asset} 5-second bar collection invalid")
        bars = [_normalize_bar(asset, row) for row in raw_bars]
        rt_volume = raw.get("rt_volume") if isinstance(raw.get("rt_volume"), dict) else None

        trade_price = None
        trade_at_ms = None
        if rt_volume is not None:
            trade_price = _optional_positive(rt_volume.get("price"))
            candidate_time = rt_volume.get("trade_at_ms")
            if isinstance(candidate_time, int) and not isinstance(candidate_time, bool):
                trade_at_ms = candidate_time

        if bars:
            latest_bar = max(bars, key=lambda row: row["time_s"])
            bar_time_ms = latest_bar["time_s"] * 1000
            if trade_at_ms is None or bar_time_ms >= trade_at_ms:
                trade_price = latest_bar["close"]
                trade_at_ms = bar_time_ms

        if trade_price is None or trade_at_ms is None:
            raise IbkrIntakeError(f"{asset} has no timestamped premarket trade")
        if trade_at_ms > retrieved:
            raise IbkrIntakeError(f"{asset} trade timestamp is in the future")
        if not _is_premarket(trade_at_ms):
            raise IbkrIntakeError(f"{asset} latest trade is outside US premarket")

        total_volume = None
        if rt_volume is not None:
            total_volume = _optional_nonnegative(rt_volume.get("total_volume"))

        normalized_assets[asset] = {
            "symbol": asset,
            "premarket_price": trade_price,
            "previous_close": _optional_positive(l1.get("close")),
            "premarket_high": None,
            "premarket_low": None,
            "premarket_volume": total_volume,
            "l1_streaming": {
                "state": "AVAILABLE",
                "market_data_type": LIVE_MARKET_DATA_TYPE,
                "bid": _optional_positive(l1.get("bid")),
                "ask": _optional_positive(l1.get("ask")),
                "last": _optional_positive(l1.get("last")),
                "bid_size": _optional_nonnegative(l1.get("bid_size")),
                "ask_size": _optional_nonnegative(l1.get("ask_size")),
                "last_size": _optional_nonnegative(l1.get("last_size")),
                "observed_trade_at_ms": trade_at_ms,
            },
            "real_time_bars_5s": {
                "state": "AVAILABLE" if bars else "BLOCKED",
                "reason": None if bars else "NO_5_SECOND_TRADE_BAR_DURING_CAPTURE",
                "bar_size_seconds": 5,
                "what_to_show": "TRADES",
                "use_rth": False,
                "items": bars,
            },
        }
        observation_times.append(trade_at_ms)

    request_identity = {
        "provider_contract_id": binding["provider_contract_id"],
        "host_scope": "LOCAL_LOOPBACK",
        "port": locked_config.port,
        "client_id": locked_config.client_id,
        "contracts": [
            {"symbol": asset, "security_type": "STK", "exchange": "SMART", "currency": "USD"}
            for asset in ASSET_ORDER
        ],
        "l1": {"streaming": True, "generic_ticks": [233], "snapshot": False, "regulatory_snapshot": False},
        "bars": {"bar_size_seconds": 5, "what_to_show": "TRADES", "use_rth": False},
        "api_request_methods": ["reqMarketDataType", "reqMktData", "reqRealTimeBars"],
    }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_id": binding["source_id"],
        "provider": binding["provider"],
        "provider_contract_id": binding["provider_contract_id"],
        "session": "PREMARKET",
        "observed_at_ms": min(observation_times),
        "retrieved_at_ms": retrieved,
        "first_seen_at_ms": retrieved,
        "request_identity_hash": sha256_hex(canonical_json_bytes(request_identity)),
        "raw_response_hash": sha256_hex(canonical_json_bytes(capture)),
        "request_contract": request_identity,
        "assets": normalized_assets,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
    }
    return seal_equity_live_snapshot(payload)


def collect_ibkr_live_snapshot(
    registry: SourceRegistry,
    *,
    config: IbkrIntakeConfig | None = None,
    feed: IbkrFeed | None = None,
    retrieved_at_ms: int | None = None,
) -> dict[str, Any]:
    locked_config = (config or IbkrIntakeConfig()).validate()
    binding = build_equity_source_binding(registry, source_id=SOURCE_ID)
    raw = (feed or NativeIbkrFeed()).collect(locked_config)
    snapshot = build_ibkr_equity_live_snapshot(
        raw,
        source_binding=binding,
        config=locked_config,
        retrieved_at_ms=retrieved_at_ms,
    )
    end_ms = snapshot["retrieved_at_ms"]
    start_ms = end_ms - binding["max_age_seconds"] * 1000
    return validate_equity_live_snapshot(
        snapshot,
        source_binding=binding,
        evaluation_window={"start_ms": start_ms, "end_ms": end_ms},
    )


def build_ibkr_crt_outputs(
    snapshot: dict[str, Any],
    *,
    registry: SourceRegistry,
    battle_map_contract: dict[str, Any],
    evidence_pack: dict[str, Any] | None = None,
    source_gate_result: dict[str, Any] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    binding = build_equity_source_binding(registry, source_id=SOURCE_ID)
    end_ms = int(snapshot["retrieved_at_ms"])
    window = {"start_ms": end_ms - binding["max_age_seconds"] * 1000, "end_ms": end_ms}
    locked_snapshot = validate_equity_live_snapshot(
        snapshot,
        source_binding=binding,
        evaluation_window=window,
    )
    evidence_binding = build_premarket_evidence_binding(
        reflexivity_overlay=evidence_pack,
        evaluation_window=window,
    )
    handoff = build_premarket_live_market_handoff(
        source_mode="MACHINE_VERIFIED_ONLY",
        evaluation_window=window,
        source_gate_result=source_gate_result,
        machine_equity_snapshot=locked_snapshot,
        machine_equity_source_registry=registry,
        machine_equity_source_id=SOURCE_ID,
    )
    asset_facts = apply_live_market_handoff_to_asset_facts(
        evidence_binding["asset_facts"],
        handoff,
    )
    battle_map = build_premarket_battle_map(
        contract=battle_map_contract,
        asset_facts=asset_facts,
        issuer_reflexivity=evidence_binding["issuer_reflexivity"],
        as_of=as_of,
        source_mode="MACHINE_VERIFIED_ONLY",
        live_market_handoff=handoff,
    )
    result = {
        "snapshot": locked_snapshot,
        "live_market_handoff": handoff,
        "battle_map": battle_map,
        "evidence_pack": None,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
    }
    if evidence_pack is not None:
        result["evidence_pack"] = attach_premarket_market_data(
            evidence_pack,
            live_market_handoff=handoff,
            battle_map=battle_map,
        )
    return result


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _default_radar_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only IBKR L1 plus 5-second real-time bar intake for CRT."
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--confirm-tws-read-only", action="store_true")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--registry", type=Path, default=_default_radar_path("CONFIG", "SOURCE_REGISTRY_V1.2.json"))
    parser.add_argument("--ibkr-source-overlay", type=Path, default=_default_radar_path("CONFIG", "IBKR_EQUITY_SOURCE_V0.1.json"))
    parser.add_argument("--battle-map-contract", type=Path, default=_default_radar_path("CONFIG", "PREMARKET_BATTLE_MAP_CONTRACT_V0.1.json"))
    parser.add_argument("--source-gate", type=Path, default=None)
    parser.add_argument("--evidence-pack-input", type=Path, default=None)
    parser.add_argument("--snapshot-output", type=Path, default=_default_radar_path("runtime", "equity", "premarket", "latest.json"))
    parser.add_argument("--handoff-output", type=Path, default=_default_radar_path("runtime", "equity", "premarket", "handoff.json"))
    parser.add_argument("--battle-map-output", type=Path, default=_default_radar_path("runtime", "equity", "premarket", "battle_map.json"))
    parser.add_argument("--evidence-pack-output", type=Path, default=None)
    args = parser.parse_args(argv)

    config = IbkrIntakeConfig(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        duration_seconds=args.duration_seconds,
    ).validate()
    preflight = inspect_ibkr_environment(host=config.host, ports=(config.port,))
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if preflight["state"] != "BLOCKED" else 2
    if preflight["state"] == "BLOCKED":
        raise IbkrIntakeError("IBKR preflight blocked: " + ",".join(preflight["blockers"]))
    if not args.confirm_tws_read_only:
        raise IbkrIntakeError("--confirm-tws-read-only is required before live intake")
    if args.evidence_pack_output is not None and args.evidence_pack_input is None:
        raise ValueError("--evidence-pack-output requires --evidence-pack-input")

    registry = load_ibkr_source_registry(args.registry, args.ibkr_source_overlay)
    snapshot = collect_ibkr_live_snapshot(registry, config=config)
    contract = _load_json(args.battle_map_contract)
    assert contract is not None
    outputs = build_ibkr_crt_outputs(
        snapshot,
        registry=registry,
        battle_map_contract=contract,
        evidence_pack=_load_json(args.evidence_pack_input),
        source_gate_result=_load_json(args.source_gate),
        as_of=datetime.now(tz=ZoneInfo("Asia/Taipei")).isoformat(),
    )
    write_json_atomic(args.snapshot_output, outputs["snapshot"])
    write_json_atomic(args.handoff_output, outputs["live_market_handoff"])
    write_json_atomic(args.battle_map_output, outputs["battle_map"])
    if args.evidence_pack_output is not None:
        assert outputs["evidence_pack"] is not None
        write_json_atomic(args.evidence_pack_output, outputs["evidence_pack"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
