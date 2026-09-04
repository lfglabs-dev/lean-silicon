#!/usr/bin/env python3
"""Keep the bounded scalar STATUS differential fail-closed and on CI."""

from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class ScalarStatusWorkflowTest(unittest.TestCase):
    def test_lean_job_runs_the_differential_and_mutation_family(self):
        workflow = WORKFLOW.read_text()
        start = workflow.index("  lean:\n")
        end = workflow.index("\n  formal-toolchain:\n", start)
        lean_job = workflow[start:end]
        for target in (
            "make lsc1-scalar-status-host-boundary",
            "make lsc1-scalar-status-host-boundary-mutation",
        ):
            with self.subTest(target=target):
                self.assertEqual(lean_job.count(f"run: {target}\n"), 1)

    def test_mutation_target_fails_closed_when_python_cannot_run(self):
        completed = subprocess.run(
            ["make", "PYTHON=false", "lsc1-scalar-status-host-boundary-mutation"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("LSC1_SCALAR_STATUS_MUTATION_PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
