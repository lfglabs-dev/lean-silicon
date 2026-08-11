#!/usr/bin/env python3
"""Focused regression for the depth-2788 mutation gate's resource bound."""

from __future__ import annotations

import threading
import time
import unittest
from math import ceil
from unittest.mock import patch

from formal import check_deref_retire_formal_mutations as mutation_check


class MutationConcurrencyTest(unittest.TestCase):
    def test_depth_2788_mutants_never_exceed_worker_bound(self) -> None:
        lock = threading.Lock()
        active = 0
        peak = 0

        def observe(mutation: tuple[str, str, str, str]) -> tuple[str, bool, str]:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return mutation[0], True, ""

        mutations = [
            (f"mutant_{index}", "source.sv", "old", "new")
            for index in range(7)
        ]
        with patch.object(mutation_check, "check_mutation", side_effect=observe):
            results = mutation_check.check_mutations(mutations)

        self.assertEqual(peak, mutation_check.MAX_PARALLEL_MUTATIONS)
        self.assertEqual(
            [result[0] for result in results],
            [item[0] for item in mutations],
        )
        worst_case_seconds = mutation_check.SOLVER_TIMEOUT_SECONDS * (
            1 + ceil(len(mutations) / mutation_check.MAX_PARALLEL_MUTATIONS)
        )
        self.assertLessEqual(worst_case_seconds, 75 * 60)


if __name__ == "__main__":
    unittest.main()
