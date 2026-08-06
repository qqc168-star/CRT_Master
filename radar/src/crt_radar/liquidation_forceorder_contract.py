"""Fail-closed contract for the Binance forceOrder stream.

This module validates a data-source route only.
It never authorizes trading or any external action.
"""

from typing import Dict, Optional


MARKET_FORCEORDER_STREAM_URL = (
    "wss://fstream.binance.com/market/ws/btcusdt@forceOrder"
)


def evaluate_forceorder_route(url: Optional[str]) -> Dict[str, str]:
    """Return a data-only result and block every unapproved route."""

    if url != MARKET_FORCEORDER_STREAM_URL:
        return {
            "decision_status": "BLOCKED",
            "quality_state": "INVALID_FORCEORDER_ROUTE",
            "action_output": "NONE",
        }

    return {
        "decision_status": "DATA_ONLY",
        "quality_state": "VALID_FORCEORDER_ROUTE",
        "action_output": "NONE",
    }
