"""Regression tests for fresh workload-comparison receipts."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import workload_validation


class WorkloadValidationReceiptTest(unittest.TestCase):
    def test_duplicate_workload_ids_are_rejected_before_comparison(self):
        plan = {"workloads": [{"id": "same"}, {"id": "same"}]}
        with self.assertRaisesRegex(SystemExit, "ids must be unique"):
            workload_validation.validate_unique_workload_ids(plan)

    def test_workload_ids_must_be_single_safe_filename_components(self):
        plan = {"workloads": [{"id": "suite/case"}]}
        with self.assertRaisesRegex(SystemExit, "safe filename components"):
            workload_validation.validate_unique_workload_ids(plan)

    def test_upstream_repository_attribution_is_pinned(self):
        upstream = {
            "repository": workload_validation.SUPPORTED_UPSTREAM_REPOSITORY
        }
        workload_validation.validate_upstream_repository(upstream)

        upstream["repository"] = "https://example.invalid/not-the-oracle.git"
        with self.assertRaisesRegex(SystemExit, "repository is unsupported"):
            workload_validation.validate_upstream_repository(upstream)

    def test_hidden_tracked_change_is_not_accepted_as_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            tracked = repo / "tracked.txt"
            tracked.write_text("committed\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            subprocess.run(
                ["git", "update-index", "--assume-unchanged", "tracked.txt"],
                cwd=repo,
                check=True,
            )
            tracked.write_text("hidden change\n")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=repo, text=True
                ),
                "",
            )

            with self.assertRaisesRegex(SystemExit, "must match HEAD"):
                workload_validation.require_clean_tracked_worktree(repo)

    def test_selected_count_is_derived_from_validated_plan(self):
        plan = {"workloads": [{"id": "one"}, {"id": "two"}]}
        self.assertEqual(workload_validation.selected_workload_count(plan), 2)

    def test_plan_runtime_must_match_fixed_comparator_runtime(self):
        changed = dict(workload_validation.SUPPORTED_RUNTIME)
        changed["public_input"] = ["0x2", "0x0"]

        with self.assertRaisesRegex(SystemExit, "plan runtime differs"):
            workload_validation.validate_runtime(changed)

    def test_expected_outcome_includes_precise_model_boundary(self):
        comparison = {
            "comparison": {
                "result": "MISMATCH",
                "mismatches": [{"field": "terminal", "host": "fault"}],
            },
            "upstream": {"cycles": 58},
            "lean_silicon": {
                "terminal": "fault",
                "reason": "pc 1 raised bad_pointer preparing the transaction",
                "steps": [{"pc": 0}],
            },
        }

        outcome = workload_validation.comparison_outcome(comparison)

        self.assertEqual(outcome["model_steps"], 1)
        self.assertEqual(
            outcome["reason"], "pc 1 raised bad_pointer preparing the transaction"
        )
        self.assertEqual(
            outcome["mismatches"], [{"field": "terminal", "host": "fault"}]
        )

    def test_comparison_profile_must_match_planned_runtime(self):
        comparison = {"lean_silicon": {"profile": "INTERPRETER_COMPAT"}}
        runtime = dict(workload_validation.SUPPORTED_RUNTIME)
        workload_validation.validate_comparison_runtime(comparison, runtime)

        comparison["lean_silicon"]["profile"] = "FORWARD_ONLY"
        with self.assertRaisesRegex(SystemExit, "comparison profile differs"):
            workload_validation.validate_comparison_runtime(comparison, runtime)

    def test_artifact_embedded_source_must_match_checked_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "case.zkdsl"
            source.write_text("def main():\n    return\n")
            artifact = {
                "source": {
                    "path": "workloads/case.zkdsl",
                    "sha256": workload_validation.sha(source),
                    "text": source.read_text(),
                }
            }
            workload_validation.validate_source_binding(
                source, artifact, "workloads/case.zkdsl"
            )

            artifact["source"]["text"] = "def main():\n    assert 1 == 0\n"
            with self.assertRaisesRegex(SystemExit, "source binding mismatch"):
                workload_validation.validate_source_binding(
                    source, artifact, "workloads/case.zkdsl"
                )

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
