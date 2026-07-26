import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory


class InventoryTest(unittest.TestCase):
    def test_exact_final_inventory(self):
        cells = inventory.extract_inventory()
        self.assertEqual(sum(cells.values()), 167885)
        self.assertEqual(len(cells), 16)
        self.assertEqual(cells["$_MUX_"], 46717)
        self.assertEqual(cells["$_DFFE_PP_"], 8192)

    def test_provenance_is_pinned(self):
        data = inventory.manifest()
        self.assertEqual(data["base_commit"], inventory.BASE_COMMIT)
        self.assertEqual(len(data["source_sha256"]), 64)

    def test_generator_has_permanent_notice(self):
        text = (Path(__file__).parent / "generate.py").read_text()
        self.assertIn("CONCEPTUAL · SKY130-INFORMED · NOT GDS/P&R", text)


if __name__ == "__main__":
    unittest.main()
