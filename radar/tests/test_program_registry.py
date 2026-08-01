from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.validate_program_registry import REGISTRY, SCHEMA, validate


class ProgramRegistryTests(unittest.TestCase):
    def test_current_registry_passes(self):
        self.assertEqual(validate(), [])

    def test_duplicate_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "registry.csv"
            with REGISTRY.open(encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            rows[1]["id"] = rows[0]["id"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            self.assertIn("duplicate module ID", validate(path, SCHEMA))

    def test_external_authority_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "registry.csv"
            with REGISTRY.open(encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            rows[0]["external_action_authority"] = "ORDER"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            errors = validate(path, SCHEMA)
            self.assertTrue(any("external action authority" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
