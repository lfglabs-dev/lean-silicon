from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "tools" / "verify_fabrication_bundle.py"


class FabricationBundleTest(unittest.TestCase):
    def run_mutated_manifest(self, mutate) -> subprocess.CompletedProcess:
        original = ROOT / "release" / "v0.1.1" / "FABRICATION_MANIFEST.json"
        value = json.loads(original.read_text())
        mutate(value)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "FABRICATION_MANIFEST.json"
            target.write_text(json.dumps(value))
            return subprocess.run([sys.executable, str(VERIFY), str(target)], cwd=ROOT)

    def test_fabrication_bundle_passes(self) -> None:
        subprocess.run([sys.executable, str(VERIFY)], cwd=ROOT, check=True)

    def test_manifest_hash_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(lambda value: value["payload"][0].update(sha256="0" * 64))
        self.assertNotEqual(result.returncode, 0)

    def test_source_commit_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["source"].update(
                commit="86a9d7ea06beab9bef266d9dca0da0e7810b614f",
                tree="773efe52ff9cb88a9fdd947e9864085df5a4e42a",
            )
        )
        self.assertNotEqual(result.returncode, 0)

    def test_toolchain_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(lambda value: value["toolchain"].update(physical_flow="LibreLane 0.0.0"))
        self.assertNotEqual(result.returncode, 0)

    def test_required_receipt_name_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(lambda value: value["receipts"]["precheck"]["required_tests"].__setitem__(0, "Not a real check"))
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
