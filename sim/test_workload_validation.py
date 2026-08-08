"""Regression tests for fresh workload-comparison receipts."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import workload_validation


class WorkloadValidationReceiptTest(unittest.TestCase):
    def test_new_invocation_invalidates_stale_aggregate_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            stale = cache / "receipt.json"
            stale.write_text(json.dumps({"status": "pass"}))

            receipt_path = workload_validation.prepare_receipt_path(cache)

            self.assertEqual(receipt_path, stale)
            self.assertFalse(stale.exists())

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

    def test_changed_checkout_cannot_publish_aggregate_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt_path = Path(temp) / "receipt.json"
            with mock.patch.object(
                workload_validation, "clean_head", return_value=("new-head", "new-tree")
            ):
                with self.assertRaisesRegex(SystemExit, "checkout changed"):
                    workload_validation.publish_receipt(
                        receipt_path, {"status": "pass"}, ("old-head", "old-tree")
                    )

            self.assertFalse(receipt_path.exists())


if __name__ == "__main__":
    unittest.main()
