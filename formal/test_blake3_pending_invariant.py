#!/usr/bin/env python3
"""Harness regressions for independent BLAKE3 pending-invariant mutants."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from formal import check_blake3_pending_invariant as check
from formal import validate_blake3_pending_contract as validator


class Blake3PendingInvariantHarnessTest(unittest.TestCase):
    def test_emitted_yosys_representation_fixtures(self) -> None:
        fixtures = check.FORMAL / "fixtures" / "blake3_pending_oracle"
        expected = {
            "yosys-0.33-assert.json": ("Yosys 0.33", "legacy_formal_cell"),
            "yosys-0.68-check.json": ("Yosys 0.68+40", "check_flavor_cell"),
        }
        for filename, (version, representation) in expected.items():
            design = json.loads((fixtures / filename).read_text())
            self.assertTrue(design["creator"].startswith(version))
            valid, reason, meta = validator.validate_design(design)
            self.assertTrue(valid, f"{filename}: {reason}")
            self.assertGreater(meta["representation_classification"][representation], 0)

    def test_unknown_check_representation_fails_closed(self) -> None:
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.68-check.json"
        design = json.loads(fixture.read_text())
        cells = design["modules"][validator.TOP]["cells"]
        assertion = next(cell for cell in cells.values()
                         if cell.get("type") == "$check"
                         and cell.get("parameters", {}).get("FLAVOR") == "assert")
        assertion["parameters"]["FLAVOR"] = "future_assert_encoding"
        valid, reason, _ = validator.validate_design(design)
        self.assertFalse(valid)
        self.assertEqual(reason, "unsupported_formal_cell_representation")

    def test_independent_validator_semantics(self) -> None:
        production = (check.FORMAL / check.INVARIANT).read_text()
        pending_block = """    always @(*) begin
        if (blake_result_pending) assert(result_pending);
        cover(blake_result_pending);
    end
"""
        variants = {
            "baseline": (production, True),
            "always_at_star": (production.replace("always @(*) begin", "always @* begin : pending_check"), True),
            "extra_parentheses": (production.replace("assert(result_pending)", "assert(((result_pending)))"), True),
            "weakened": (production.replace(check.PENDING_ASSERTION, check.WEAK_PENDING_ASSERTION), False),
            "removed": (production.replace(check.PENDING_ASSERTION, check.REMOVED_PENDING_ASSERTION), False),
            "disabled_generate": (production.replace(pending_block, """    generate if (1'b0) begin : disabled
        always @* if (blake_result_pending) assert(result_pending);
    end endgenerate
    always @* cover(blake_result_pending);
"""), False),
            "string_literal": (production.replace(pending_block, """    localparam [8*64-1:0] NOTE = "if (blake_result_pending) assert(result_pending);";
    always @* cover(blake_result_pending);
"""), False),
            "unrelated_module": (production.replace(check.PENDING_ASSERTION, "") + "\nmodule decoy(input blake_result_pending, result_pending); always @* if (blake_result_pending) assert(result_pending); endmodule\n", False),
            "benign_control": (production.replace(check.CONTROL_COVER, check.CONTROL_COVER_MUTATION), True),
        }
        with tempfile.TemporaryDirectory() as raw:
            for name, (text, expected) in variants.items():
                path = Path(raw) / f"{name}.sv"
                path.write_text(text)
                valid, reason, _ = validator.validate(path)
                self.assertEqual(valid, expected, f"{name}: {reason}")

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
            valid, reason, _ = validator.validate(work / check.INVARIANT)
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
