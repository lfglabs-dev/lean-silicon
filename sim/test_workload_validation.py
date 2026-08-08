"""Regression tests for fresh workload-comparison receipts."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import workload_validation


class WorkloadValidationReceiptTest(unittest.TestCase):
    def test_failed_run_cannot_reuse_stale_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "comparison.json"
            out.write_text(json.dumps({"stale": True}))
            failed = subprocess.CompletedProcess([], 1, stdout="current run failed\n")

            with mock.patch.object(workload_validation.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(SystemExit, "comparison produced no receipt"):
                    workload_validation.run_comparison(["comparison"], out, "case")

            self.assertFalse(out.exists())

    def test_nonzero_run_accepts_fresh_expected_mismatch_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "comparison.json"
            expected = {"comparison": {"result": "MISMATCH"}}

            def write_fresh_receipt(*_args, **_kwargs):
                out.write_text(json.dumps(expected))
                return subprocess.CompletedProcess([], 1, stdout="expected mismatch\n")

            with mock.patch.object(workload_validation.subprocess, "run", side_effect=write_fresh_receipt):
                run, receipt = workload_validation.run_comparison(
                    ["comparison"], out, "case"
                )

            self.assertEqual(run.returncode, 1)
            self.assertEqual(receipt, expected)


if __name__ == "__main__":
    unittest.main()
