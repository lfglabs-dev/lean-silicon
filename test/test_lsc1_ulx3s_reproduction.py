from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.verify_lsc1_ulx3s_reproduction import EVIDENCE, RECEIPT, verify


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

    def test_nonzero_exit_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["runs"][1].update(exit_code=1), message="normal exit")

    def test_scope_expansion_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["scope"].update(physical_hardware=True),
                      message="scope boundary physical_hardware")

    def test_unpinned_option_rejected(self):
        self.rejected(mutate_receipt=lambda r: r["nextpnr_options"].remove("--no-tmdriv"),
                      message="nextpnr options")


if __name__ == "__main__":
    unittest.main()
