from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "tools" / "verify_fabrication_bundle.py"
sys.path.insert(0, str(ROOT))

from tools.verify_fabrication_bundle import RECEIPT_TESTS, validate_receipt


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

    def test_candidate_identity_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value.update(candidate="totally-different-run")
        )
        self.assertNotEqual(result.returncode, 0)

    def test_manifest_hash_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(lambda value: value["payload"][0].update(sha256="0" * 64))
        self.assertNotEqual(result.returncode, 0)

    def test_payload_class_member_relabel_fails(self) -> None:
        def relabel(value) -> None:
            replacement = value["payload"][-1]
            value["payload"][0].update(
                member=replacement["member"],
                sha256=replacement["sha256"],
                min_bytes=0,
            )

        result = self.run_mutated_manifest(relabel)
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

    def test_source_receipt_hash_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["receipts"]["precheck"].update(source_payload_sha256="0" * 64)
        )
        self.assertNotEqual(result.returncode, 0)

    def test_projected_receipt_identity_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["receipts"]["precheck"].update(
                path="evidence/gatelevel-results.xml",
                sha256=value["receipts"]["gate_level"]["sha256"],
            )
        )
        self.assertNotEqual(result.returncode, 0)

    def test_skipped_required_receipt_fails(self) -> None:
        names = sorted(RECEIPT_TESTS["precheck"])
        spec = {"required_tests": names}
        cases = "".join(
            f'<testcase name="{name}">{"<skipped/>" if index == 0 else ""}</testcase>'
            for index, name in enumerate(names)
        )
        with self.assertRaises(SystemExit):
            validate_receipt(
                f"<testsuite>{cases}</testsuite>".encode(),
                spec,
                "precheck",
            )

    def test_empty_receipt_case_set_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["receipts"]["precheck"].update(required_tests=[])
        )
        self.assertNotEqual(result.returncode, 0)

    def test_empty_zero_metric_set_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["receipts"].update(metrics_zero_keys=[])
        )
        self.assertNotEqual(result.returncode, 0)

    def test_density_assertion_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["receipts"].update(
                density_key="magic__drc_error__count",
                density_expected=0,
            )
        )
        self.assertNotEqual(result.returncode, 0)

    def test_retained_archive_identity_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["retained_archive"].update(sha256="0" * 64)
        )
        self.assertNotEqual(result.returncode, 0)

    def test_external_payload_identity_mutation_fails(self) -> None:
        result = self.run_mutated_manifest(
            lambda value: value["external_exact_run_payload"].update(artifact_id=1)
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
