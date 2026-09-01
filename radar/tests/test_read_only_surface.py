from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "assert_read_only_surface.py"
spec = importlib.util.spec_from_file_location("assert_read_only_surface", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class ReadOnlySurfaceTests(unittest.TestCase):
    def test_current_source_and_config_pass(self):
        errors = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            errors.extend(module.scan_python(path))
        for path in sorted((ROOT / "CONFIG").rglob("*.json")):
            errors.extend(module.scan_json(path))
        self.assertEqual(errors, [])

    def test_forbidden_call_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.py"
            path.write_text("def x():\n    place_order()\n", encoding="utf-8")
            errors = module.scan_python(path)
            self.assertTrue(any("place_order" in item for item in errors))

    def test_ibkr_order_call_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_ibkr.py"
            path.write_text(
                "def x(client):\n    client.placeOrder(1, None, None)\n",
                encoding="utf-8",
            )
            errors = module.scan_python(path)
            self.assertTrue(any("placeOrder" in item for item in errors))

    def test_non_none_authority_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"external_action_authority": "TRADE"}), encoding="utf-8")
            errors = module.scan_json(path)
            self.assertTrue(any("authority must be NONE" in item for item in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
