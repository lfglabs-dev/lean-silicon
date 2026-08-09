from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "tools" / "verify_fabrication_bundle.py"


class FabricationBundleTest(unittest.TestCase):
    def test_fabrication_bundle_passes(self) -> None:
        subprocess.run([sys.executable, str(VERIFY)], cwd=ROOT, check=True)

    def test_manifest_hash_mutation_fails(self) -> None:
        original = ROOT / "release" / "v0.1.1" / "FABRICATION_MANIFEST.json"
        mutated = original.read_text().replace(
            "52a10ef119b3cf435ad13041203f9b6200902df10f82b1e00890193abb2cc307",
            "0" * 64,
        )
        self.assertNotEqual(mutated, original.read_text())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FABRICATION_MANIFEST.json"
            target.write_text(mutated)
            result = subprocess.run([sys.executable, str(VERIFY), str(target)], cwd=ROOT)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
