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
from formal import validate_blake3_pending_contract as validator


class Blake3PendingInvariantHarnessTest(unittest.TestCase):
    def test_independent_validator_semantics(self) -> None:
        baseline = "module x; always @(*) begin if (blake_result_pending) assert(result_pending); cover(blake_result_pending); end endmodule"
        self.assertEqual(validator.validate(baseline),
                         (True, "production_blake_pending_implication_present"))
        self.assertFalse(validator.validate(baseline.replace("assert(result_pending)", "assert(1'b1)"))[0])
        self.assertFalse(validator.validate(baseline.replace("assert(result_pending);", ""))[0])
        self.assertTrue(validator.validate(baseline.replace("cover(blake_result_pending)",
                                                            "cover(blake_result_pending || 1'b0)"))[0])

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
        def fake_validate(work):
            valid, reason = validator.validate((work / check.INVARIANT).read_text())
            return subprocess.CompletedProcess(["validator"], 0 if valid else 1,
                                               json.dumps({"valid": valid, "reason": reason}))

        with mock.patch.object(check, "run", side_effect=fake_run), \
             mock.patch.object(check, "validate_contract", side_effect=fake_validate), \
             contextlib.redirect_stdout(output):
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
        for name, mutation in receipt["mutations"].items():
            self.assertEqual(mutation["anchor_count"], 1)
            self.assertTrue(mutation["isolated"])
            if name != "control_cover_change":
                self.assertTrue(mutation["killed"])
        self.assertTrue(receipt["mutations"]["control_cover_change"]["accepted"])
        self.assertTrue(receipt["mutations"]["weaken_assertion"]["union_intact"])
        self.assertTrue(receipt["mutations"]["remove_assertion"]["union_intact"])


if __name__ == "__main__":
    unittest.main()
