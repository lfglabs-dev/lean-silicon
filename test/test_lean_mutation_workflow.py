#!/usr/bin/env python3
"""Keep every checked-in Lean mutation guard on the actual CI path."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
MUTATION_GUARDS = (
    "check_full_profile_mutations.py",
    "check_accepted_deref_binding_mutations.py",
    "check_accepted_jump_binding_mutations.py",
    "check_accepted_scalar_binding_mutations.py",
    "check_accepted_sequence_mutations.py",
)


class LeanMutationWorkflowTest(unittest.TestCase):
    def lean_steps(self):
        workflow = WORKFLOW.read_text()
        lean_job = workflow.index("  lean:\n")
        next_job = workflow.index("\n  formal-toolchain:\n", lean_job)
        return workflow[lean_job:next_job]

    def test_lean_job_invokes_every_mutation_guard(self):
        lean_steps = self.lean_steps()

        for guard in MUTATION_GUARDS:
            with self.subTest(guard=guard):
                self.assertEqual(lean_steps.count(guard), 1)

    def test_lean_bootstrap_is_pinned_integrity_checked_and_retried(self):
        lean_steps = self.lean_steps()

        self.assertIn("releases/download/v4.2.3/", lean_steps)
        self.assertIn("ELAN_ARCHIVE_SHA256:", lean_steps)
        self.assertIn("sha256sum --check --status", lean_steps)
        self.assertIn("--connect-timeout 30", lean_steps)
        self.assertIn("--max-time 120", lean_steps)
        self.assertIn("--retry-all-errors", lean_steps)
        self.assertIn("--retry-max-time 600", lean_steps)
        self.assertIn("run: cd lean && lake build\n", lean_steps)

    def test_lean_job_executes_the_authored_rtl_contract(self):
        lean_steps = self.lean_steps()

        self.assertEqual(lean_steps.count("sudo apt-get install -y iverilog"), 1)
        self.assertEqual(lean_steps.count("make lsc1-authored-rtl-contract"), 1)


if __name__ == "__main__":
    unittest.main()
