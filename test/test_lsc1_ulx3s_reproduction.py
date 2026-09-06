from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.verify_lsc1_ulx3s_reproduction import RECEIPT, verify


class ReproductionReceiptTest(unittest.TestCase):
    def receipt(self) -> dict:
        return json.loads(RECEIPT.read_text())

    def rejected(self, mutate, message: str) -> None:
        receipt = copy.deepcopy(self.receipt())
        mutate(receipt)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "receipt.json"
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, message):
                verify(path)

    def test_receipt_accepts(self):
        verify()

    def test_missing_second_run_rejected(self):
        self.rejected(lambda r: r["runs"].pop(), "exactly two runs")

    def test_nonzero_exit_rejected(self):
        self.rejected(lambda r: r["runs"][1].update(exit_code=1), "normal exit")

    def test_timing_failure_rejected(self):
        self.rejected(lambda r: r["runs"][0].update(core_clock_pass=False), "10 MHz timing")

    def test_artifact_divergence_rejected(self):
        self.rejected(lambda r: r["runs"][1]["artifacts"].update(ulx3s_lsc1_packet={}), "run artifact hashes")

    def test_raw_log_digest_mutation_rejected(self):
        self.rejected(lambda r: r["runs"][0]["raw_receipt_sha256"].update({"nextpnr.log": "0" * 64}), "raw receipt hashes")

    def test_scope_expansion_rejected(self):
        self.rejected(lambda r: r["scope"].update(physical_hardware=True), "scope boundary physical_hardware")

    def test_unpinned_option_rejected(self):
        self.rejected(lambda r: r["nextpnr_options"].remove("--no-tmdriv"), "nextpnr options")


if __name__ == "__main__":
    unittest.main()
