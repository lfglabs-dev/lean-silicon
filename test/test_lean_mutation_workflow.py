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
)


class LeanMutationWorkflowTest(unittest.TestCase):
    def test_lean_job_invokes_every_mutation_guard(self):
        workflow = WORKFLOW.read_text()
        lean_job = workflow.index("  lean:\n")
        next_job = workflow.index("\n  formal-and-lint:\n", lean_job)
        lean_steps = workflow[lean_job:next_job]

        for guard in MUTATION_GUARDS:
            with self.subTest(guard=guard):
                self.assertEqual(lean_steps.count(guard), 1)


if __name__ == "__main__":
    unittest.main()
