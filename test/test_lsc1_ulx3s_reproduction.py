from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.verify_lsc1_ulx3s_reproduction import BASE, EVIDENCE, RECEIPT, verify


class ReproductionReceiptTest(unittest.TestCase):
    def receipt(self) -> dict:
        return json.loads(RECEIPT.read_text())

    def evidence_links(self, root: Path) -> None:
        for run_id in ("clean-build-1", "clean-build-2"):
            target = root / run_id
            target.mkdir()
            for source in (EVIDENCE / run_id).iterdir():
                (target / source.name).symlink_to(source)

    @staticmethod
    def replace(path: Path, payload: bytes) -> None:
        path.unlink()
        path.write_bytes(payload)

    def rejected(self, mutate_receipt=lambda _r: None, mutate_evidence=lambda _e, _r: None,
                 message: str = "") -> None:
        receipt = copy.deepcopy(self.receipt())
        mutate_receipt(receipt)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence = root / "evidence"
            evidence.mkdir()
            self.evidence_links(evidence)
            mutate_evidence(evidence, receipt)
            path = root / "receipt.json"
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, message):
                verify(path, evidence)

    def test_receipt_accepts(self):
        verify()

    def test_missing_second_run_receipt_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["runs"].pop(), message="exactly two runs")

    def test_missing_preserved_run_file_rejected(self):
        def remove(evidence: Path, _receipt: dict) -> None:
            (evidence / "clean-build-2" / "nextpnr.log").unlink()
        self.rejected(mutate_evidence=remove, message="complete run evidence clean-build-2")

    def test_substituted_run_file_rejected(self):
        def substitute(evidence: Path, _receipt: dict) -> None:
            payload = (EVIDENCE / "clean-build-1" / "nextpnr.log").read_bytes()
            self.replace(evidence / "clean-build-2" / "nextpnr.log", payload)
        self.rejected(mutate_evidence=substitute, message="preserved evidence hashes clean-build-2")

    def test_rehashed_inconsistent_timing_receipt_rejected(self):
        def inconsistent(evidence: Path, receipt: dict) -> None:
            path = evidence / "clean-build-1" / "timing.txt"
            payload = b"Info: Max frequency for clock 'core_clk': 99 MHz (PASS at 10.00 MHz)\n"
            self.replace(path, payload)
            receipt["runs"][0]["evidence_sha256"]["timing.txt"] = hashlib.sha256(payload).hexdigest()
        self.rejected(mutate_evidence=inconsistent, message="timing receipt consistency clean-build-1")

    def test_rehashed_self_authored_cad_log_rejected(self):
        def forged(evidence: Path, receipt: dict) -> None:
            path = evidence / "clean-build-1" / "nextpnr.log"
            payload = (b"Info: Derived frequency constraint of 10.0 MHz for net core_clk\n"
                       b"Info: Max frequency for clock '$glbnet$core_clk': 15.32 MHz (PASS at 10.00 MHz)\n")
            self.replace(path, payload)
            receipt["runs"][0]["evidence_sha256"]["nextpnr.log"] = hashlib.sha256(payload).hexdigest()
        self.rejected(mutate_evidence=forged, message="nextpnr completion clean-build-1")

    def test_rehashed_source_substitution_rejected(self):
        def substitute(evidence: Path, receipt: dict) -> None:
            path = evidence / "clean-build-1" / "SOURCE_MANIFEST.txt"
            payload = path.read_bytes().replace(b"revision: adc3e2c5", b"revision: fde1b885")
            self.replace(path, payload)
            receipt["runs"][0]["evidence_sha256"]["SOURCE_MANIFEST.txt"] = hashlib.sha256(payload).hexdigest()
        self.rejected(mutate_evidence=substitute, message="source manifest identity")

    def test_rehashed_source_input_name_substitution_rejected(self):
        def substitute(evidence: Path, receipt: dict) -> None:
            path = evidence / "clean-build-1" / "SOURCE_MANIFEST.txt"
            lines = path.read_text().splitlines()
            removed = next(i for i, line in enumerate(lines)
                           if line.endswith("  asic_core/rtl/gf128_mul_bitstream.sv"))
            del lines[removed]
            readme = subprocess.check_output(["git", "show", f"{BASE}:README.md"], cwd=RECEIPT.parents[2])
            lines.append(f"{hashlib.sha256(readme).hexdigest()}  README.md")
            payload = ("\n".join(lines) + "\n").encode()
            self.replace(path, payload)
            receipt["runs"][0]["evidence_sha256"]["SOURCE_MANIFEST.txt"] = hashlib.sha256(payload).hexdigest()
        self.rejected(mutate_evidence=substitute, message="complete source manifest")

    def test_nonzero_exit_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["runs"][1].update(exit_code=1), message="normal exit")

    def test_scope_expansion_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["scope"].update(physical_hardware=True),
                      message="scope boundary physical_hardware")

    def test_unpinned_option_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["nextpnr_options"].remove("--no-tmdriv"),
                      message="nextpnr options")

    def assert_post_squash_single_branch_checkout_accepts(self, source: Path) -> None:
        intermediate = "adc3e2c5b86fb08e1b0225573486ae08af4ac194"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging = root / "staging.git"
            checkout = root / "checkout"
            # upload-pack deliberately disables lazy fetching while serving a
            # partial clone.  Materialize its promised blobs in one fetch
            # before asking it to create an independent bare repository; do
            # not borrow the source's incomplete object store.
            promisor = subprocess.run(
                ["git", "-C", str(source), "config", "--get", "remote.origin.promisor"],
                text=True, stdout=subprocess.PIPE)
            if promisor.returncode == 0 and promisor.stdout.strip() == "true":
                subprocess.run(
                    ["git", "-C", str(source), "fetch", "--refetch", "--no-filter", "origin"],
                    check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "clone", "--bare", "--no-local", str(source), str(staging)],
                           check=True, stdout=subprocess.DEVNULL)
            tree = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"],
                                           text=True).strip()
            env = os.environ | {
                "GIT_AUTHOR_NAME": "post-squash regression",
                "GIT_AUTHOR_EMAIL": "regression@example.invalid",
                "GIT_COMMITTER_NAME": "post-squash regression",
                "GIT_COMMITTER_EMAIL": "regression@example.invalid",
            }
            squash = subprocess.check_output(
                ["git", f"--git-dir={staging}", "commit-tree", tree, "-p", BASE, "-m", "squash"],
                env=env, text=True).strip()
            refs = subprocess.check_output(
                ["git", f"--git-dir={staging}", "for-each-ref", "--format=%(refname)"],
                text=True).splitlines()
            for ref in refs:
                subprocess.run(["git", f"--git-dir={staging}", "update-ref", "-d", ref], check=True)
            subprocess.run(["git", f"--git-dir={staging}", "update-ref", "refs/heads/squash", squash],
                           check=True)
            subprocess.run(["git", "clone", "--no-local", "--single-branch", "--branch", "squash",
                            str(staging), str(checkout)], check=True, stdout=subprocess.DEVNULL)
            missing = subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", intermediate],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertNotEqual(missing.returncode, 0)
            subprocess.run([sys.executable, "tools/verify_lsc1_ulx3s_reproduction.py"],
                           cwd=checkout, check=True)
            subprocess.run([sys.executable, "test/test_lsc1_fpga_packet_evidence.py", "-v"],
                           cwd=checkout, env=os.environ | {"PYTHONPATH": "."}, check=True)

    def test_post_squash_single_branch_checkout_accepts(self):
        """P1 family: verification cannot depend on an intermediate PR commit."""
        self.assert_post_squash_single_branch_checkout_accepts(RECEIPT.parents[2])

    def test_post_squash_checkout_accepts_from_blob_filtered_source(self):
        """The squash fixture must copy/fetch objects from a partial checkout."""
        source = RECEIPT.parents[2]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            upstream = root / "upstream.git"
            partial = root / "partial"
            subprocess.run(["git", "clone", "--bare", "--no-local", str(source), str(upstream)],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", f"--git-dir={upstream}", "config", "uploadpack.allowFilter", "true"],
                           check=True)
            subprocess.run(["git", "clone", "--no-local", "--filter=blob:none", str(upstream),
                            str(partial)], check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(subprocess.check_output(
                ["git", "-C", str(partial), "config", "--bool", "remote.origin.promisor"],
                text=True).strip(), "true")
            missing = subprocess.check_output(
                ["git", "-C", str(partial), "rev-list", "--objects", "--missing=print",
                 BASE], text=True).splitlines()
            self.assertTrue(any(line.startswith("?") for line in missing))
            self.assert_post_squash_single_branch_checkout_accepts(partial)


if __name__ == "__main__":
    unittest.main()
