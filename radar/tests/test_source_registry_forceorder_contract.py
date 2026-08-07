import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "radar" / "src"

sys.path.insert(0, str(SRC))

from crt_radar.source_registry import RegistryError, SourceRegistry


class TestWaveBSourceRegistrySemanticContract(unittest.TestCase):

    def valid_market_item(self):
        return {
            "endpoint": (
                "wss://fstream.binance.com"
                "/market/ws/btcusdt@forceOrder"
            ),
            "endpoint_category": "MARKET",
            "metric_authority": "NONE",
        }

    def test_market_forceorder_route_is_accepted(self):
        item = self.valid_market_item()

        SourceRegistry._validate_liquidation_route(item)

    def test_public_forceorder_route_is_rejected(self):
        item = self.valid_market_item()
        item["endpoint"] = (
            "wss://fstream.binance.com"
            "/public/ws/btcusdt@forceOrder"
        )

        with self.assertRaisesRegex(
            RegistryError,
            r"/market route|/public route",
        ):
            SourceRegistry._validate_liquidation_route(item)

    def test_non_market_forceorder_route_is_rejected(self):
        item = self.valid_market_item()
        item["endpoint"] = (
            "wss://fstream.binance.com"
            "/ws/btcusdt@forceOrder"
        )

        with self.assertRaisesRegex(
            RegistryError,
            r"/market route",
        ):
            SourceRegistry._validate_liquidation_route(item)

    def test_public_endpoint_category_is_rejected(self):
        item = self.valid_market_item()
        item["endpoint_category"] = "PUBLIC"

        with self.assertRaisesRegex(
            RegistryError,
            r"endpoint_category must be MARKET",
        ):
            SourceRegistry._validate_liquidation_route(item)


if __name__ == "__main__":
    unittest.main(verbosity=2)
