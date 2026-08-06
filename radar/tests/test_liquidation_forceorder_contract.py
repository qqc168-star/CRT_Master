from pathlib import Path
import sys
import unittest


def find_repo_root() -> Path:
    current = Path(__file__).resolve()

    for parent in current.parents:
        if (parent / ".git").exists():
            return parent

    raise RuntimeError("Repository root not found")


REPO_ROOT = find_repo_root()
SRC_ROOT = REPO_ROOT / "radar" / "src"

sys.path.insert(0, str(SRC_ROOT))

from crt_radar.liquidation_forceorder_contract import (
    MARKET_FORCEORDER_STREAM_URL,
    evaluate_forceorder_route,
)


class TestForceOrderContract(unittest.TestCase):

    def test_market_route_constant_is_exact(self):
        self.assertEqual(
            MARKET_FORCEORDER_STREAM_URL,
            "wss://fstream.binance.com/market/ws/btcusdt@forceOrder",
        )

    def test_valid_market_route_is_data_only(self):
        result = evaluate_forceorder_route(
            MARKET_FORCEORDER_STREAM_URL
        )

        self.assertEqual(result["decision_status"], "DATA_ONLY")
        self.assertEqual(
            result["quality_state"],
            "VALID_FORCEORDER_ROUTE",
        )
        self.assertEqual(result["action_output"], "NONE")

    def test_legacy_public_route_fails_closed(self):
        result = evaluate_forceorder_route(
            "wss://fstream.binance.com/public/ws/btcusdt@forceOrder"
        )

        self.assertEqual(result["decision_status"], "BLOCKED")
        self.assertEqual(
            result["quality_state"],
            "INVALID_FORCEORDER_ROUTE",
        )
        self.assertEqual(result["action_output"], "NONE")

    def test_missing_route_fails_closed(self):
        result = evaluate_forceorder_route(None)

        self.assertEqual(result["decision_status"], "BLOCKED")
        self.assertEqual(result["action_output"], "NONE")

    def test_arbitrary_route_fails_closed(self):
        result = evaluate_forceorder_route(
            "wss://example.invalid/ws/btcusdt@forceOrder"
        )

        self.assertEqual(result["decision_status"], "BLOCKED")
        self.assertEqual(result["action_output"], "NONE")

    def test_runtime_contract_contains_no_public_endpoint(self):
        module_path = (
            SRC_ROOT
            / "crt_radar"
            / "liquidation_forceorder_contract.py"
        )

        text = module_path.read_text(
            encoding="utf-8",
            errors="strict",
        )

        self.assertIn("/market/ws/", text)
        self.assertNotIn("/public/ws/", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
