from __future__ import annotations

import argparse
import json
import math
import threading
import time
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .daily_evidence_runner import write_json_atomic
from .mstr_asst_market_health_runtime import AUTHORITY, canonical_hash, seal_runtime_source


ASSETS = ("MSTR", "ASST")
FOUR_ASSETS = ("MSTR", "ASST", "STRC", "SATA")
FOUR_DAILY_SCHEMA = "CRT_FOUR_ASSET_IBKR_DAILY_V0.1"
FOUR_DAILY_SOURCE_ID = "CRT-CONN-FOUR-ASSET-IBKR-EQUITY-DAILY-001"
PRICE_BASIS = "IBKR_TRADES_SPLIT_ADJUSTED_DIVIDEND_UNADJUSTED"
INFORMATIONAL_ERROR_CODES = {1102, 2104, 2106, 2107, 2108, 2158, 10167}


class IbkrMarketHealthSourceError(RuntimeError):
    pass


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IbkrMarketHealthSourceError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise IbkrMarketHealthSourceError(f"{label} must be positive")
    return number


def _nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IbkrMarketHealthSourceError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise IbkrMarketHealthSourceError(f"{label} must be nonnegative")
    return number


def _session_date(raw: Any) -> str:
    parts = str(raw).strip().split()
    text = parts[0] if parts else ""
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise IbkrMarketHealthSourceError(f"invalid IBKR daily bar date: {raw!r}")


def normalize_ibkr_daily_capture(
    capture: Any,
    *,
    assets: tuple[str, ...] = ASSETS,
    minimum_bars: int = 22,
) -> dict[str, list[dict[str, Any]]]:
    if not assets or len(set(assets)) != len(assets):
        raise IbkrMarketHealthSourceError("assets must be nonempty and unique")
    if type(minimum_bars) is not int or minimum_bars <= 0:
        raise IbkrMarketHealthSourceError("minimum_bars must be a positive integer")
    if not isinstance(capture, dict) or set(capture) != set(assets):
        scope = "MSTR and ASST" if assets == ASSETS else ", ".join(assets)
        raise IbkrMarketHealthSourceError(f"capture must contain exactly {scope}")
    result: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
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
        if len(normalized) < minimum_bars:
            raise IbkrMarketHealthSourceError(
                f"{asset} requires at least {minimum_bars} daily bars"
                + (" for RVOL20" if minimum_bars == 22 else "")
            )
        result[asset] = normalized
    return result


def _native_history_app(
    *, assets: tuple[str, ...] = ASSETS,
) -> tuple[type[Any], type[Any]]:
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
            self.done = {1000 + index: threading.Event() for index in range(len(assets))}
            self.request_asset = {
                1000 + index: asset for index, asset in enumerate(assets)
            }
            self.rows = {asset: [] for asset in assets}
            self.failures: list[dict[str, Any]] = []
            self.lock = threading.Lock()

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            del orderId
            self.ready.set()

        def error(self, reqId: int, *args: Any) -> None:
            error_time = None
            if (len(args) in {2, 3} and type(args[0]) is int
                    and all(type(value) is str for value in args[1:])):
                code, message = args[0], args[1]
            elif (len(args) in {3, 4} and type(args[0]) is int and type(args[1]) is int
                    and all(type(value) is str for value in args[2:])):
                error_time, code, message = args[:3]
            else:
                code, message = -1, "UNPARSEABLE_IBKR_ERROR"
            number = code
            if (type(reqId) is not int or not -(2 ** 31) <= reqId < 2 ** 31
                    or not 0 <= code < 2 ** 31
                    or (error_time is not None and not 0 <= error_time < 2 ** 63)):
                number, message = -1, "UNPARSEABLE_IBKR_ERROR"
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


def _four_asset_market_calendar() -> dict[str, Any]:
    path = (Path(__file__).resolve().parents[2] / "research"
            / "CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1.json")
    calendar = json.loads(path.read_text(encoding="utf-8")).get("market_calendar")
    if not isinstance(calendar, dict) or not calendar.get("calendar_id"):
        raise IbkrMarketHealthSourceError("tracked US market calendar missing")
    return calendar


def build_four_asset_daily_proof(
    capture: Any,
    *,
    observed_at_ms: int,
    request_started_at_ms: int,
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind captured vendor bars and request semantics without qualifying closes."""
    if not isinstance(capture, dict) or set(capture) - set(FOUR_ASSETS):
        raise IbkrMarketHealthSourceError("four-asset capture scope invalid")
    if (type(request_started_at_ms) is not int
            or type(observed_at_ms) is not int
            or not 0 < request_started_at_ms <= observed_at_ms):
        raise IbkrMarketHealthSourceError("daily proof capture clocks invalid")
    failures = [] if failures is None else failures
    request_ids = {1000 + index for index in range(len(FOUR_ASSETS))}
    if (not isinstance(failures, list)
            or any(not isinstance(row, dict) or row.get("req_id") not in request_ids
                   or type(row.get("code")) is not int for row in failures)):
        raise IbkrMarketHealthSourceError("daily proof failure scope invalid")
    assets: dict[str, Any] = {}
    for index, asset in enumerate(FOUR_ASSETS):
        bars = capture.get(asset, [])
        if not isinstance(bars, list):
            raise IbkrMarketHealthSourceError(f"{asset} raw daily bars must be a list")
        assets[asset] = {
            "symbol": asset,
            "currency": "USD",
            "bars": deepcopy(bars),
            "failure_codes": [row["code"] for row in failures
                              if row["req_id"] == 1000 + index],
            "raw_data_hash": canonical_hash(bars),
        }
    calendar = _four_asset_market_calendar()
    proof = {
        "schema_version": FOUR_DAILY_SCHEMA,
        "source_id": FOUR_DAILY_SOURCE_ID,
        "request_started_at_ms": request_started_at_ms,
        "observed_at_ms": observed_at_ms,
        "timezone": "America/New_York",
        "calendar_id": calendar["calendar_id"],
        "calendar_hash": canonical_hash(calendar),
        "request_contract": {
            "assets": list(FOUR_ASSETS),
            "api_method": "reqHistoricalData",
            "duration": "2 M",
            "bar_size": "1 day",
            "what_to_show": "TRADES",
            "use_rth": True,
            "keep_up_to_date": False,
            "price_adjustment_basis": PRICE_BASIS,
            "account_surface": "ABSENT",
            "order_surface": "ABSENT",
        },
        "assets": assets,
        **AUTHORITY,
    }
    proof["proof_hash"] = canonical_hash(proof)
    return proof


def collect_ibkr_equity_daily_proof(
    *,
    host: str = "127.0.0.1",
    port: int = 7496,
    client_id: int = 761,
    timeout_seconds: float = 30.0,
    observed_at_ms: int | None = None,
    four_asset_prices: bool = False,
) -> dict[str, Any]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise IbkrMarketHealthSourceError("IBKR host must remain loopback")
    if port <= 0 or client_id < 0 or timeout_seconds <= 0:
        raise IbkrMarketHealthSourceError("IBKR connection parameters invalid")
    assets = FOUR_ASSETS if four_asset_prices else ASSETS
    App, Contract = (_native_history_app(assets=assets)
                     if four_asset_prices else _native_history_app())
    app = App()
    thread: threading.Thread | None = None
    request_started_at_ms: int | None = None
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
        request_started_at_ms = int(time.time() * 1000)
        for index, asset in enumerate(assets):
            request_id = 1000 + index
            contract = Contract()
            contract.symbol = asset
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            try:
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
            except Exception as exc:
                if not four_asset_prices:
                    raise
                with app.lock:
                    app.failures.append({"req_id": request_id, "code": -1,
                                         "message": str(exc)})
                app.done[request_id].set()
        deadline = time.monotonic() + timeout_seconds
        for request_id, event in app.done.items():
            if four_asset_prices and event.is_set():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not event.wait(remaining):
                message = f"IBKR daily history request {request_id} timed out"
                if not four_asset_prices:
                    raise IbkrMarketHealthSourceError(message)
                with app.lock:
                    app.failures.append({"req_id": request_id, "code": -1,
                                         "message": message})
    finally:
        try:
            app.disconnect()
        finally:
            if thread is not None:
                thread.join(timeout=2.0)

    with app.lock:
        failures = deepcopy(app.failures)
        capture = deepcopy(app.rows)
    if failures and (not four_asset_prices
                     or any(row.get("req_id") not in app.done for row in failures)):
        raise IbkrMarketHealthSourceError(
            "IBKR daily history failed: "
            + json.dumps([{"code": row["code"]} for row in failures]
                         if four_asset_prices else failures,
                         ensure_ascii=False, sort_keys=True)
        )
    observed = (int(time.time() * 1000)
                if four_asset_prices or observed_at_ms is None else observed_at_ms)
    if four_asset_prices:
        return build_four_asset_daily_proof(
            capture,
            observed_at_ms=observed,
            request_started_at_ms=request_started_at_ms,
            failures=failures,
        )
    data = normalize_ibkr_daily_capture(capture)
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


def validate_four_asset_daily_proof(raw: Any, *, at_ms: int) -> dict[str, Any]:
    """Qualify each retained close without completing bars on a replay clock.

    Hashes prove local content integrity, not an external attestation of IBKR.
    The bounded, already retained US calendar determines which close is due.
    """
    from datetime import timedelta
    from .mstr_asst_full_day_market_intake import NEW_YORK, _session_close_ms

    result: dict[str, Any] = {
        "state": "BLOCKED", "scope": "LAST_COMPLETED_RTH_CLOSE_NOT_LIVE_QUOTE",
        "source_id": FOUR_DAILY_SOURCE_ID, "source_hash": None,
        "source_trust": "LOCAL_CAPTURE_CONTRACT_NOT_EXTERNAL_ATTESTATION",
        "raw_hash_basis": "CANONICAL_CAPTURED_VENDOR_BARS_NOT_WIRE_BYTES",
        "currency": "USD", "timezone": "America/New_York",
        "price_adjustment_basis": PRICE_BASIS,
        "assets": {}, **AUTHORITY,
    }

    def blocked(asset: str, reason: str, state: str = "BLOCKED") -> dict[str, Any]:
        return {"asset": asset, "currency": "USD", "state": state,
                "price_usd": None, "reason": reason}

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError(reason)

    try:
        require(isinstance(raw, dict), "DAILY_SOURCE_MISSING")
        require(raw.get("schema_version") == FOUR_DAILY_SCHEMA
                and raw.get("source_id") == FOUR_DAILY_SOURCE_ID, "DAILY_SOURCE_ID_MISMATCH")
        require(all(raw.get(k) == v for k, v in AUTHORITY.items()), "DAILY_SOURCE_AUTHORITY_INVALID")
        require(raw.get("proof_hash") == canonical_hash({
            k: v for k, v in raw.items() if k != "proof_hash"}), "DAILY_PROOF_HASH_MISMATCH")
        observed, cutoff = raw.get("observed_at_ms"), raw.get("request_started_at_ms")
        require(type(at_ms) is int and type(observed) is int and type(cutoff) is int
                and 0 < cutoff <= observed <= at_ms, "DAILY_CAPTURE_CLOCK_INVALID")
        contract = raw.get("request_contract")
        require(isinstance(contract, dict), "DAILY_REQUEST_CONTRACT_MISSING")
        require(contract.get("price_adjustment_basis") == PRICE_BASIS, "PRICE_ADJUSTMENT_BASIS_UNQUALIFIED")
        expected = {"assets": list(FOUR_ASSETS), "api_method": "reqHistoricalData",
                    "duration": "2 M", "bar_size": "1 day", "what_to_show": "TRADES",
                    "use_rth": True, "keep_up_to_date": False,
                    "account_surface": "ABSENT", "order_surface": "ABSENT"}
        require(all(type(contract.get(k)) is type(v) and contract[k] == v
                    for k, v in expected.items()), "DAILY_REQUEST_CONTRACT_MISMATCH")
        calendar = _four_asset_market_calendar()
        require(raw.get("calendar_id") == calendar["calendar_id"]
                and raw.get("calendar_hash") == canonical_hash(calendar)
                and raw.get("timezone") == calendar["timezone"] == "America/New_York",
                "DAILY_CALENDAR_BINDING_MISMATCH")
        start, end = date.fromisoformat(calendar["valid_from"]), date.fromisoformat(calendar["valid_through"])
        closed, early = set(calendar["full_close_dates"]), frozenset(calendar["early_close_dates"])
        weekdays = set(calendar["weekday_sessions"])

        def local_day(clock: int) -> date:
            return datetime.fromtimestamp(clock / 1000, NEW_YORK).date()

        def is_session(day: date) -> bool:
            return day.weekday() in weekdays and day.isoformat() not in closed

        def latest_completed(clock: int) -> str:
            day = local_day(clock)
            require(start <= day <= end, "MARKET_CALENDAR_OUT_OF_RANGE")
            while day >= start:
                text = day.isoformat()
                if is_session(day) and _session_close_ms(text, early_close_dates=early) <= clock:
                    return text
                day -= timedelta(days=1)
            raise ValueError("NO_COMPLETED_SESSION_IN_CALENDAR")

        required_day = latest_completed(at_ms)
        captured_day = latest_completed(cutoff)
        rows = raw.get("assets")
        require(isinstance(rows, dict) and not set(rows) - set(FOUR_ASSETS), "DAILY_ASSET_SCOPE_INVALID")
        result.update(source_hash=raw["proof_hash"], observed_at_ms=observed,
                      request_started_at_ms=cutoff, retrieved_at_ms=observed,
                      retrieval_timezone="UTC", evaluated_at_ms=at_ms,
                      required_session_date=required_day,
                      calendar_id=calendar["calendar_id"], calendar_hash=raw["calendar_hash"])
    except (ValueError, IbkrMarketHealthSourceError, KeyError, TypeError, OSError, OverflowError) as exc:
        # Do not expose arbitrary provider messages or private input strings.
        known = str(exc) if isinstance(exc, ValueError) else "DAILY_SOURCE_INVALID"
        allowed = {"DAILY_SOURCE_MISSING", "DAILY_SOURCE_ID_MISMATCH", "DAILY_SOURCE_AUTHORITY_INVALID",
                   "DAILY_PROOF_HASH_MISMATCH", "DAILY_CAPTURE_CLOCK_INVALID", "DAILY_REQUEST_CONTRACT_MISSING",
                   "PRICE_ADJUSTMENT_BASIS_UNQUALIFIED", "DAILY_REQUEST_CONTRACT_MISMATCH",
                   "DAILY_CALENDAR_BINDING_MISMATCH", "MARKET_CALENDAR_OUT_OF_RANGE",
                   "NO_COMPLETED_SESSION_IN_CALENDAR", "DAILY_ASSET_SCOPE_INVALID"}
        reason = known if known in allowed else "DAILY_SOURCE_INVALID"
        result["assets"] = {a: blocked(a, reason) for a in FOUR_ASSETS}
        return result

    for asset in FOUR_ASSETS:
        try:
            row = rows.get(asset)
            require(isinstance(row, dict), "ASSET_DAILY_SOURCE_MISSING")
            require(row.get("symbol") == asset and row.get("currency") == "USD", "ASSET_SOURCE_BINDING_MISMATCH")
            bars = row.get("bars")
            require(isinstance(bars, list) and bool(bars), "ASSET_DAILY_BARS_MISSING")
            require(row.get("raw_data_hash") == canonical_hash(bars), "ASSET_RAW_HASH_MISMATCH")
            require(row.get("failure_codes") == [], "ASSET_HISTORY_REQUEST_FAILED")
            # Dates must be daily labels, never intraday/premarket timestamps.
            require(all(isinstance(b, dict) and isinstance(b.get("date"), str)
                        and b["date"] in {_session_date(b["date"]), _session_date(b["date"]).replace("-", "")}
                        for b in bars), "ASSET_DAILY_DATE_INVALID")
            normalized = normalize_ibkr_daily_capture({asset: bars}, assets=(asset,), minimum_bars=1)[asset]
            complete = []
            for bar in normalized:
                day = date.fromisoformat(bar["session_date"])
                require(day <= local_day(cutoff), "ASSET_FUTURE_BAR")
                if day < start:
                    continue  # Older 2 M history is outside this close-only claim.
                require(day <= end and is_session(day), "ASSET_NONTRADING_SESSION")
                close_ms = _session_close_ms(bar["session_date"], early_close_dates=early)
                if close_ms <= cutoff:
                    complete.append((bar, close_ms))
            require(bool(complete), "NO_COMPLETE_EQUITY_SESSION")
            bar, close_ms = complete[-1]
            if bar["session_date"] != captured_day or captured_day != required_day:
                result["assets"][asset] = blocked(asset, "LATEST_COMPLETED_SESSION_MISSING", "STALE")
                continue
            result["assets"][asset] = {
                "asset": asset, "currency": "USD", "state": "VALID", "reason": "LATEST_COMPLETED_SESSION_VERIFIED",
                "price_usd": bar["close"], "price_type": "RTH_SESSION_CLOSE",
                "as_of_ms": close_ms, "session_date": bar["session_date"], "session_state": "COMPLETE",
                "session_clock": "SCHEDULED_RTH_END_NOT_TRADE_TIMESTAMP",
                "source_state": bar["source_state"], "source_id": FOUR_DAILY_SOURCE_ID,
                "raw_data_hash": row["raw_data_hash"], "price_adjustment_basis": PRICE_BASIS,
                "observed_at_ms": observed, "request_started_at_ms": cutoff,
                "calendar_id": calendar["calendar_id"],
                "source_ref": {"source_id": FOUR_DAILY_SOURCE_ID, "evidence_hash": raw["proof_hash"],
                               "source_as_of_ms": close_ms},
            }
        except (ValueError, IbkrMarketHealthSourceError, KeyError, TypeError, OverflowError) as exc:
            reason = str(exc)
            allowed = {"ASSET_DAILY_SOURCE_MISSING", "ASSET_SOURCE_BINDING_MISMATCH", "ASSET_DAILY_BARS_MISSING",
                       "ASSET_RAW_HASH_MISMATCH", "ASSET_HISTORY_REQUEST_FAILED", "ASSET_DAILY_DATE_INVALID",
                       "ASSET_FUTURE_BAR", "ASSET_NONTRADING_SESSION", "NO_COMPLETE_EQUITY_SESSION"}
            result["assets"][asset] = blocked(asset, reason if reason in allowed else "ASSET_DAILY_BAR_INVALID")
    count = sum(row["state"] == "VALID" for row in result["assets"].values())
    result["state"] = "VALID" if count == len(FOUR_ASSETS) else "PARTIAL" if count else "BLOCKED"
    return result


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
    parser.add_argument("--four-asset-prices", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.four_asset_prices and (not args.equity_output or args.options_output):
        raise IbkrMarketHealthSourceError(
            "--four-asset-prices requires --equity-output and cannot use --options-output"
        )
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
            four_asset_prices=args.four_asset_prices,
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
