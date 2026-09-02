from __future__ import annotations

import argparse
import json
import threading
import time
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .daily_evidence_runner import write_json_atomic
from .mstr_asst_market_health_runtime import seal_runtime_source


ASSETS = ("MSTR", "ASST")
INFORMATIONAL_ERROR_CODES = {1102, 2104, 2106, 2107, 2108, 2158, 10167}


class IbkrMarketHealthSourceError(RuntimeError):
    pass


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IbkrMarketHealthSourceError(f"{label} must be numeric")
    number = float(value)
    if number <= 0:
        raise IbkrMarketHealthSourceError(f"{label} must be positive")
    return number


def _nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IbkrMarketHealthSourceError(f"{label} must be numeric")
    number = float(value)
    if number < 0:
        raise IbkrMarketHealthSourceError(f"{label} must be nonnegative")
    return number


def _session_date(raw: Any) -> str:
    text = str(raw).strip().split()[0]
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise IbkrMarketHealthSourceError(f"invalid IBKR daily bar date: {raw!r}")


def normalize_ibkr_daily_capture(capture: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(capture, dict) or set(capture) != set(ASSETS):
        raise IbkrMarketHealthSourceError("capture must contain exactly MSTR and ASST")
    result: dict[str, list[dict[str, Any]]] = {}
    for asset in ASSETS:
        rows = capture[asset]
        if not isinstance(rows, list) or not rows:
            raise IbkrMarketHealthSourceError(f"{asset} daily history is empty")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                raise IbkrMarketHealthSourceError(f"{asset} daily bar invalid")
            session_date = _session_date(raw.get("date"))
            if session_date in seen:
                raise IbkrMarketHealthSourceError(
                    f"{asset} duplicate daily bar {session_date}"
                )
            seen.add(session_date)
            open_ = _positive(raw.get("open"), f"{asset}.open")
            high = _positive(raw.get("high"), f"{asset}.high")
            low = _positive(raw.get("low"), f"{asset}.low")
            close = _positive(raw.get("close"), f"{asset}.close")
            if high < low or not low <= open_ <= high or not low <= close <= high:
                raise IbkrMarketHealthSourceError(f"{asset} daily bar geometry invalid")
            normalized.append(
                {
                    "session_date": session_date,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": _nonnegative(raw.get("volume"), f"{asset}.volume"),
                    "source_state": "IBKR_HISTORICAL_TRADES_RTH",
                }
            )
        normalized.sort(key=lambda row: row["session_date"])
        if len(normalized) < 22:
            raise IbkrMarketHealthSourceError(
                f"{asset} requires at least 22 daily bars for RVOL20"
            )
        result[asset] = normalized
    return result


def _native_history_app() -> tuple[type[Any], type[Any]]:
    try:
        from ibapi.client import EClient
        from ibapi.contract import Contract
        from ibapi.wrapper import EWrapper
    except ImportError as exc:
        raise IbkrMarketHealthSourceError(
            "official IBKR TWS API Python package is not installed"
        ) from exc

    class HistoryApp(EWrapper, EClient):
        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.done = {1000 + index: threading.Event() for index in range(len(ASSETS))}
            self.request_asset = {
                1000 + index: asset for index, asset in enumerate(ASSETS)
            }
            self.rows = {asset: [] for asset in ASSETS}
            self.failures: list[dict[str, Any]] = []
            self.lock = threading.Lock()

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            del orderId
            self.ready.set()

        def error(self, reqId: int, *args: Any) -> None:
            if len(args) >= 4:
                code, message = args[1], args[2]
            elif len(args) >= 2:
                code, message = args[0], args[1]
            else:
                code, message = -1, "UNPARSEABLE_IBKR_ERROR"
            try:
                number = int(code)
            except (TypeError, ValueError):
                number = -1
            if number in INFORMATIONAL_ERROR_CODES:
                return
            with self.lock:
                self.failures.append(
                    {"req_id": reqId, "code": number, "message": str(message)}
                )
            if reqId in self.done:
                self.done[reqId].set()

        def historicalData(self, reqId: int, bar: Any) -> None:  # noqa: N802
            asset = self.request_asset.get(reqId)
            if asset is None:
                return
            row = {
                "date": bar.date,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
            with self.lock:
                self.rows[asset].append(row)

        def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
            del start, end
            event = self.done.get(reqId)
            if event is not None:
                event.set()

    return HistoryApp, Contract


def collect_ibkr_equity_daily_proof(
    *,
    host: str = "127.0.0.1",
    port: int = 7496,
    client_id: int = 761,
    timeout_seconds: float = 30.0,
    observed_at_ms: int | None = None,
) -> dict[str, Any]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise IbkrMarketHealthSourceError("IBKR host must remain loopback")
    if port <= 0 or client_id < 0 or timeout_seconds <= 0:
        raise IbkrMarketHealthSourceError("IBKR connection parameters invalid")
    App, Contract = _native_history_app()
    app = App()
    thread: threading.Thread | None = None
    try:
        app.connect(host, port, client_id)
        thread = threading.Thread(
            target=app.run,
            name="crt-ibkr-market-health-history",
            daemon=True,
        )
        thread.start()
        if not app.ready.wait(timeout_seconds):
            raise IbkrMarketHealthSourceError("IBKR API handshake timed out")
        for index, asset in enumerate(ASSETS):
            request_id = 1000 + index
            contract = Contract()
            contract.symbol = asset
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            app.reqHistoricalData(
                request_id,
                contract,
                "",
                "2 M",
                "1 day",
                "TRADES",
                1,
                1,
                False,
                [],
            )
        deadline = time.monotonic() + timeout_seconds
        for request_id, event in app.done.items():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not event.wait(remaining):
                raise IbkrMarketHealthSourceError(
                    f"IBKR daily history request {request_id} timed out"
                )
    finally:
        try:
            app.disconnect()
        finally:
            if thread is not None:
                thread.join(timeout=2.0)

    with app.lock:
        failures = deepcopy(app.failures)
        capture = deepcopy(app.rows)
    if failures:
        raise IbkrMarketHealthSourceError(
            "IBKR daily history failed: "
            + json.dumps(failures, ensure_ascii=False, sort_keys=True)
        )
    data = normalize_ibkr_daily_capture(capture)
    observed = int(time.time() * 1000) if observed_at_ms is None else observed_at_ms
    proof = seal_runtime_source(
        source_key="equity_daily",
        data=data,
        observed_at_ms=observed,
    )
    proof["request_contract"] = {
        "host_scope": "LOCAL_LOOPBACK",
        "port": port,
        "client_id": client_id,
        "assets": list(ASSETS),
        "api_method": "reqHistoricalData",
        "duration": "2 M",
        "bar_size": "1 day",
        "what_to_show": "TRADES",
        "use_rth": True,
        "account_surface": "ABSENT",
        "order_surface": "ABSENT",
    }
    return proof


def _native_options_app() -> tuple[type[Any], type[Any]]:
    try:
        from ibapi.client import EClient
        from ibapi.contract import Contract
        from ibapi.wrapper import EWrapper
    except ImportError as exc:
        raise IbkrMarketHealthSourceError(
            "official IBKR TWS API Python package is not installed"
        ) from exc

    class OptionsApp(EWrapper, EClient):
        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.lock = threading.Lock()
            self.contract_details: dict[int, list[Any]] = {}
            self.contract_done: dict[int, threading.Event] = {}
            self.chains: dict[int, list[dict[str, Any]]] = {}
            self.chain_done: dict[int, threading.Event] = {}
            self.option_requests: dict[int, dict[str, Any]] = {}
            self.snapshot_done: dict[int, threading.Event] = {}
            self.failures: list[dict[str, Any]] = []

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            del orderId
            self.ready.set()

        def error(self, reqId: int, *args: Any) -> None:
            if len(args) >= 4:
                code, message = args[1], args[2]
            elif len(args) >= 2:
                code, message = args[0], args[1]
            else:
                code, message = -1, "UNPARSEABLE_IBKR_ERROR"
            try:
                number = int(code)
            except (TypeError, ValueError):
                number = -1
            if number in INFORMATIONAL_ERROR_CODES:
                return
            with self.lock:
                self.failures.append(
                    {"req_id": reqId, "code": number, "message": str(message)}
                )
            for mapping in (
                self.contract_done,
                self.chain_done,
                self.snapshot_done,
            ):
                event = mapping.get(reqId)
                if event is not None:
                    event.set()

        def contractDetails(self, reqId: int, details: Any) -> None:  # noqa: N802
            with self.lock:
                self.contract_details.setdefault(reqId, []).append(details)

        def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
            event = self.contract_done.get(reqId)
            if event is not None:
                event.set()

        def securityDefinitionOptionParameter(  # noqa: N802
            self,
            reqId: int,
            exchange: str,
            underlyingConId: int,
            tradingClass: str,
            multiplier: str,
            expirations: Any,
            strikes: Any,
        ) -> None:
            row = {
                "exchange": str(exchange),
                "underlying_con_id": int(underlyingConId),
                "trading_class": str(tradingClass),
                "multiplier": str(multiplier),
                "expirations": sorted(str(item) for item in expirations),
                "strikes": sorted(float(item) for item in strikes),
            }
            with self.lock:
                self.chains.setdefault(reqId, []).append(row)

        def securityDefinitionOptionParameterEnd(self, reqId: int) -> None:  # noqa: N802
            event = self.chain_done.get(reqId)
            if event is not None:
                event.set()

        def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802
            row = self.option_requests.get(reqId)
            if row is not None:
                row["market_data_type"] = int(marketDataType)
                self._maybe_option_done(reqId)

        def _maybe_option_done(self, reqId: int) -> None:
            row = self.option_requests.get(reqId)
            event = self.snapshot_done.get(reqId)
            if row is None or event is None:
                return
            if row.get("kind") == "UNDERLYING_AGGREGATE":
                complete = (
                    row.get("market_data_type") in {1, 2, 3, 4}
                    and row.get("call_volume") is not None
                    and row.get("put_volume") is not None
                )
            else:
                complete = (
                    row.get("market_data_type") in {3, 4}
                    and row.get("open_interest") is not None
                    and row.get("implied_volatility") is not None
                )
            if complete:
                event.set()

        def tickSize(self, reqId: int, tickType: int, size: Any) -> None:  # noqa: N802
            row = self.option_requests.get(reqId)
            if row is None:
                return
            try:
                number = float(size)
            except (TypeError, ValueError):
                return
            if row.get("kind") == "UNDERLYING_AGGREGATE":
                fields = {
                    27: "call_open_interest",
                    28: "put_open_interest",
                    29: "call_volume",
                    30: "put_volume",
                }
                field = fields.get(int(tickType))
                if field is not None:
                    row[field] = number
                self._maybe_option_done(reqId)
                return
            right = row["right"]
            if int(tickType) in ({27} if right == "CALL" else {28}):
                row["open_interest"] = number
            if int(tickType) == 8 or int(tickType) in (
                {29} if right == "CALL" else {30}
            ):
                row["volume"] = number
            self._maybe_option_done(reqId)

        def tickGeneric(self, reqId: int, tickType: int, value: float) -> None:  # noqa: N802
            row = self.option_requests.get(reqId)
            if row is None or int(tickType) != 24:
                return
            try:
                number = float(value)
            except (TypeError, ValueError):
                return
            if number > 0:
                row["implied_volatility"] = number
            self._maybe_option_done(reqId)

        def tickOptionComputation(  # noqa: N802
            self,
            reqId: int,
            tickType: int,
            tickAttrib: int,
            impliedVol: float,
            delta: float,
            optPrice: float,
            pvDividend: float,
            gamma: float,
            vega: float,
            theta: float,
            undPrice: float,
        ) -> None:
            del tickAttrib, delta, optPrice, pvDividend, gamma, vega, theta, undPrice
            row = self.option_requests.get(reqId)
            if row is None or int(tickType) not in {10, 11, 12, 13, 80, 81, 82, 83}:
                return
            try:
                value = float(impliedVol)
            except (TypeError, ValueError):
                return
            if value > 0:
                row["implied_volatility"] = value
            self._maybe_option_done(reqId)

        def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
            event = self.snapshot_done.get(reqId)
            if event is not None:
                event.set()

    return OptionsApp, Contract


def _nearest(values: list[float], target: float, count: int) -> list[float]:
    return sorted(sorted(values, key=lambda value: (abs(value - target), value))[:count])


def collect_ibkr_options_daily_proof(
    *,
    reference_prices: dict[str, float],
    session_date: str,
    host: str = "127.0.0.1",
    port: int = 7496,
    client_id: int = 762,
    timeout_seconds: float = 45.0,
    strike_count: int = 3,
    observed_at_ms: int | None = None,
) -> dict[str, Any]:
    if set(reference_prices) != set(ASSETS):
        raise IbkrMarketHealthSourceError(
            "reference_prices must contain exactly MSTR and ASST"
        )
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise IbkrMarketHealthSourceError("IBKR host must remain loopback")
    if strike_count <= 0 or strike_count > 10:
        raise IbkrMarketHealthSourceError("strike_count must be between 1 and 10")
    as_of = date.fromisoformat(session_date)
    App, Contract = _native_options_app()
    app = App()
    thread: threading.Thread | None = None
    option_req_ids: list[int] = []
    underlying_contracts: dict[str, Any] = {}
    try:
        app.connect(host, port, client_id)
        thread = threading.Thread(
            target=app.run,
            name="crt-ibkr-market-health-options",
            daemon=True,
        )
        thread.start()
        if not app.ready.wait(timeout_seconds):
            raise IbkrMarketHealthSourceError("IBKR API handshake timed out")
        app.reqMarketDataType(3)

        for index, asset in enumerate(ASSETS):
            req_id = 2000 + index
            app.contract_done[req_id] = threading.Event()
            contract = Contract()
            contract.symbol = asset
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            app.reqContractDetails(req_id, contract)
        for req_id, event in app.contract_done.items():
            if not event.wait(timeout_seconds):
                raise IbkrMarketHealthSourceError(
                    f"IBKR underlying contract request {req_id} timed out"
                )

        for index, asset in enumerate(ASSETS):
            details = app.contract_details.get(2000 + index, [])
            if not details:
                raise IbkrMarketHealthSourceError(
                    f"IBKR did not resolve {asset} underlying contract"
                )
            underlying = details[0].contract
            underlying_contracts[asset] = underlying
            req_id = 3000 + index
            app.chain_done[req_id] = threading.Event()
            app.reqSecDefOptParams(
                req_id,
                asset,
                "",
                "STK",
                int(underlying.conId),
            )
        for req_id, event in app.chain_done.items():
            if not event.wait(timeout_seconds):
                raise IbkrMarketHealthSourceError(
                    f"IBKR option chain request {req_id} timed out"
                )

        next_id = 4000
        for index, asset in enumerate(ASSETS):
            chains = app.chains.get(3000 + index, [])
            candidates = [
                row
                for row in chains
                if row["exchange"] in {"SMART", ""}
                and row["trading_class"] == asset
                and row["multiplier"] in {"100", "100.0"}
            ]
            if not candidates:
                candidates = [
                    row for row in chains if row["trading_class"] == asset
                ]
            if not candidates:
                raise IbkrMarketHealthSourceError(
                    f"IBKR returned no supported {asset} option chain"
                )
            chain = max(
                candidates,
                key=lambda row: (len(row["expirations"]), len(row["strikes"])),
            )
            expiries = [
                item
                for item in chain["expirations"]
                if datetime.strptime(item, "%Y%m%d").date() >= as_of
            ]
            if not expiries:
                raise IbkrMarketHealthSourceError(
                    f"IBKR returned no current {asset} option expiry"
                )
            expiry = min(expiries)
            strikes = _nearest(
                [value for value in chain["strikes"] if value > 0],
                _positive(reference_prices[asset], f"{asset}.reference_price"),
                strike_count,
            )
            for strike in strikes:
                for api_right, right in (("C", "CALL"), ("P", "PUT")):
                    contract = Contract()
                    contract.symbol = asset
                    contract.secType = "OPT"
                    contract.exchange = "SMART"
                    contract.currency = "USD"
                    contract.lastTradeDateOrContractMonth = expiry
                    contract.strike = strike
                    contract.right = api_right
                    contract.multiplier = chain["multiplier"] or "100"
                    contract.tradingClass = chain["trading_class"]
                    app.option_requests[next_id] = {
                        "kind": "OPTION_CONTRACT",
                        "asset": asset,
                        "expiry": expiry,
                        "strike": strike,
                        "right": right,
                        "volume": None,
                        "open_interest": None,
                        "implied_volatility": None,
                        "market_data_type": None,
                        "session_date": session_date,
                    }
                    app.snapshot_done[next_id] = threading.Event()
                    app.reqMktData(
                        next_id,
                        contract,
                        "100,101,106",
                        False,
                        False,
                        [],
                    )
                    option_req_ids.append(next_id)
                    next_id += 1

        for index, asset in enumerate(ASSETS):
            req_id = 5000 + index
            app.option_requests[req_id] = {
                "kind": "UNDERLYING_AGGREGATE",
                "asset": asset,
                "call_volume": None,
                "put_volume": None,
                "call_open_interest": None,
                "put_open_interest": None,
                "market_data_type": None,
            }
            app.snapshot_done[req_id] = threading.Event()
            app.reqMktData(
                req_id,
                underlying_contracts[asset],
                "100,101",
                False,
                False,
                [],
            )
            option_req_ids.append(req_id)

        deadline = time.monotonic() + timeout_seconds
        for req_id in option_req_ids:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                app.snapshot_done[req_id].wait(remaining)
    finally:
        for req_id in option_req_ids:
            try:
                app.cancelMktData(req_id)
            except Exception:
                pass
        try:
            app.disconnect()
        finally:
            if thread is not None:
                thread.join(timeout=2.0)

    with app.lock:
        failures = deepcopy(app.failures)
        rows = deepcopy(app.option_requests)
    if failures:
        raise IbkrMarketHealthSourceError(
            "IBKR options request failed: "
            + json.dumps(failures, ensure_ascii=False, sort_keys=True)
        )
    observed = int(time.time() * 1000) if observed_at_ms is None else observed_at_ms
    asset_inputs: dict[str, dict[str, Any]] = {}
    for asset in ASSETS:
        selected = [
            row
            for row in rows.values()
            if row["asset"] == asset and row["kind"] == "OPTION_CONTRACT"
        ]
        aggregate = next(
            (
                row
                for row in rows.values()
                if row["asset"] == asset
                and row["kind"] == "UNDERLYING_AGGREGATE"
            ),
            None,
        )
        incomplete = [
            row
            for row in selected
            if row["open_interest"] is None
            or row["market_data_type"] not in {3, 4}
        ]
        if incomplete:
            raise IbkrMarketHealthSourceError(
                f"{asset} option coverage incomplete or not delayed-available: "
                + json.dumps(incomplete, ensure_ascii=False, sort_keys=True)
            )
        if (
            aggregate is None
            or aggregate["call_volume"] is None
            or aggregate["put_volume"] is None
            or aggregate["market_data_type"] not in {1, 2, 3, 4}
        ):
            raise IbkrMarketHealthSourceError(
                f"{asset} underlying aggregate option volume unavailable: "
                + json.dumps(aggregate, ensure_ascii=False, sort_keys=True)
            )
        contracts = [
            {
                "expiry": row["expiry"],
                "strike": row["strike"],
                "right": row["right"],
                "volume": row["volume"],
                "open_interest": row["open_interest"],
                "implied_volatility": row["implied_volatility"],
                "volume_state": (
                    "IBKR_DELAYED_COVERED_CONTRACT"
                    if row["volume"] is not None
                    else "BLOCKED_NOT_AVAILABLE"
                ),
                "open_interest_state": "IBKR_DELAYED_COVERED_CONTRACT",
                "implied_volatility_state": (
                    "IBKR_DELAYED_COVERED_CONTRACT"
                    if row["implied_volatility"] is not None
                    else "BLOCKED_NOT_AVAILABLE"
                ),
                "observed_at_ms": observed,
                "oi_effective_at": session_date,
            }
            for row in selected
        ]
        calls = aggregate["call_volume"]
        puts = aggregate["put_volume"]
        strikes = sorted({row["strike"] for row in selected})
        asset_inputs[asset] = {
            "session_date": session_date,
            "aggregate_volume": {
                "call_volume": calls,
                "put_volume": puts,
                "source_state": (
                    "IBKR_LIVE_UNDERLYING_OPTION_VOLUME"
                    if aggregate["market_data_type"] == 1
                    else "IBKR_NONLIVE_UNDERLYING_OPTION_VOLUME"
                ),
                "observed_at_ms": observed,
            },
            "contracts": contracts,
            "coverage": {
                "state": "LIMITED",
                "claim_scope": "SELECTED_NEAREST_EXPIRY_AND_STRIKES_ONLY",
                "expiry_count": 1,
                "covered_contract_count": len(contracts),
                "strike_min": min(strikes),
                "strike_max": max(strikes),
                "selection_reference_price": reference_prices[asset],
            },
        }
    proof = seal_runtime_source(
        source_key="options_daily",
        data=asset_inputs,
        observed_at_ms=observed,
    )
    proof["request_contract"] = {
        "host_scope": "LOCAL_LOOPBACK",
        "port": port,
        "client_id": client_id,
        "assets": list(ASSETS),
        "api_methods": [
            "reqContractDetails",
            "reqSecDefOptParams",
            "reqMktData",
            "cancelMktData",
        ],
        "generic_ticks": [100, 101, 106],
        "snapshot": False,
        "collection_mode": "SHORT_STREAM_UNTIL_REQUIRED_FIELDS_THEN_CANCEL",
        "market_data_type": "DELAYED_REQUESTED_EXPLICITLY",
        "account_surface": "ABSENT",
        "order_surface": "ABSENT",
    }
    return proof


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect read-only IBKR daily bars for MSTR/ASST Market Health."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--client-id", type=int, default=761)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--equity-output")
    parser.add_argument("--options-output")
    parser.add_argument("--equity-proof-input")
    parser.add_argument("--strike-count", type=int, default=3)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.equity_output and not args.options_output:
        raise IbkrMarketHealthSourceError(
            "at least one of --equity-output or --options-output is required"
        )
    if args.equity_output:
        proof = collect_ibkr_equity_daily_proof(
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            timeout_seconds=args.timeout_seconds,
        )
        write_json_atomic(Path(args.equity_output), proof)
    if args.options_output:
        if not args.equity_proof_input:
            raise IbkrMarketHealthSourceError(
                "--equity-proof-input is required with --options-output"
            )
        equity_proof = json.loads(
            Path(args.equity_proof_input).read_text(encoding="utf-8")
        )
        equity_data = equity_proof.get("data")
        if not isinstance(equity_data, dict):
            raise IbkrMarketHealthSourceError("equity proof data missing")
        latest_dates = {
            asset: equity_data[asset][-1]["session_date"] for asset in ASSETS
        }
        if len(set(latest_dates.values())) != 1:
            raise IbkrMarketHealthSourceError(
                "MSTR and ASST latest equity sessions do not align"
            )
        reference_prices = {
            asset: equity_data[asset][-1]["close"] for asset in ASSETS
        }
        proof = collect_ibkr_options_daily_proof(
            reference_prices=reference_prices,
            session_date=latest_dates[ASSETS[0]],
            host=args.host,
            port=args.port,
            client_id=args.client_id + 1,
            timeout_seconds=args.timeout_seconds,
            strike_count=args.strike_count,
        )
        write_json_atomic(Path(args.options_output), proof)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
