#!/usr/bin/env python3
"""Focused regressions for lifecycle task selection and fail-closed bounds."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from formal import check_deref_retire_formal_mutations as mutation_check


class MutationLifecycleTest(unittest.TestCase):
    def test_mutants_are_assigned_to_the_first_observable_lifecycle_goal(self) -> None:
        assignments = {item[0]: item[1] for item in mutation_check.MUTATIONS}
        self.assertEqual(assignments["corrupted_result_crc_binding"], "accepted_result_safety")
        self.assertEqual(assignments["duplicate_retirement"], "matching_retire_safety")
        self.assertEqual(assignments["duplicate_completion_pulse"], "post_retire_safety")

    def test_each_solver_is_strictly_inside_outer_bound(self) -> None:
        self.assertEqual(mutation_check.SOLVER_TIMEOUT_SECONDS, 540)
        self.assertLess(mutation_check.SOLVER_TIMEOUT_SECONDS, 600)

    def test_selected_task_is_passed_to_sby(self) -> None:
        completed = mutation_check.subprocess.CompletedProcess([], 0, "PASS")
        with patch.object(mutation_check, "run_bounded", return_value=completed) as run:
            mutation_check.run_formal("baseline", "matching_retire_safety")
        self.assertEqual(run.call_args.args[0][-1], "matching_retire_safety")


if __name__ == "__main__":
    unittest.main()
