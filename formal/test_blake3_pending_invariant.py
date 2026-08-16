#!/usr/bin/env python3
"""Harness regressions for independent BLAKE3 pending-invariant mutants."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

from formal import check_blake3_pending_invariant as check


class Blake3PendingInvariantHarnessTest(unittest.TestCase):
    def test_each_mutant_starts_from_the_exact_baseline(self) -> None:
        observations: list[tuple[str, str, bool, bool]] = []

        def fake_run(work, mode):
            frontend = (work / "lsc1_packet_frontend.sv").read_text()
            invariant = (work / check.INVARIANT).read_text()
            observations.append((work.name, mode,
                                 check.UNION_BINDING in frontend,
                                 check.PENDING_ASSERTION in invariant))
            omitted_union = check.UNION_BINDING not in frontend
            return subprocess.CompletedProcess(
                ["sby"], 1 if omitted_union and mode == "bmc" else 0,
                "DONE (FAIL, rc=1)" if omitted_union and mode == "bmc" else "DONE (PASS)",
            )

        output = io.StringIO()
        with mock.patch.object(check, "run", side_effect=fake_run), contextlib.redirect_stdout(output):
            self.assertEqual(check.main(), 0)

        receipt = json.loads(output.getvalue().splitlines()[0])
        self.assertTrue(receipt["baseline_proof"])
        self.assertTrue(receipt["blake_pending_cover"])
        self.assertEqual(
            {(name, mode, union, assertion) for name, mode, union, assertion in observations},
            {
                ("baseline", "bmc", True, True),
                ("baseline", "cover", True, True),
                ("omit_union", "bmc", False, True),
                ("weaken_assertion", "bmc", True, False),
                ("weaken_assertion", "cover", True, False),
                ("remove_assertion", "bmc", True, False),
                ("remove_assertion", "cover", True, False),
            },
        )
        for mutation in receipt["mutations"].values():
            self.assertEqual(mutation["anchor_count"], 1)
            self.assertTrue(mutation["isolated"])
            self.assertTrue(mutation["killed"])
        self.assertTrue(receipt["mutations"]["weaken_assertion"]["union_intact"])
        self.assertTrue(receipt["mutations"]["remove_assertion"]["union_intact"])


if __name__ == "__main__":
    unittest.main()
