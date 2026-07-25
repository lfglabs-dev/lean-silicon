"""Tests for the pin-accurate boundary checker, including synthetic violations.

The synthetic cases matter more than the live one: they show the checker
actually rejects a back-driven input pin and a wide bypass, rather than passing
because the current RTL happens to be correct.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import boundary_check
from boundary_check import (
    EXPECTED_UIO_OE,
    Result,
    _is_abbreviation,
    check_asic_top,
    check_harness_width,
    run,
)

GOOD_TOP = """
module lean_silicon_lsc1 (
    input wire [7:0] ui_in, output wire [7:0] uo_out,
    input wire [7:0] uio_in, output wire [7:0] uio_out, output wire [7:0] uio_oe
);
    assign uio_out = {done_pulse, 1'b0, fault, busy, 1'b0, tx_valid, rx_ready, 1'b0};
    assign uio_oe = 8'b10110110;
endmodule
"""

ROLES = {
    0: "RX_VALID",
    1: "RX_READY",
    2: "TX_VALID",
    3: "TX_READY",
    4: "BUSY",
    5: "FAULT",
    6: "ABORT",
    7: "DONE_PULSE",
}


def check(text: str) -> Result:
    result = Result(errors=[], observations=[], facts=[])
    check_asic_top(result, text=text, info_roles=ROLES, doc_roles=ROLES)
    return result


class LiveRepositoryTests(unittest.TestCase):
    def test_current_repository_satisfies_the_boundary(self) -> None:
        result = run()
        self.assertTrue(result.ok, result.errors)

    def test_expected_direction_mask_matches_the_shipped_top(self) -> None:
        text = boundary_check.ASIC_TOP.read_text()
        self.assertEqual(boundary_check._declared_oe(text), EXPECTED_UIO_OE)


class AsicTopViolationTests(unittest.TestCase):
    def test_good_top_has_no_errors(self) -> None:
        self.assertEqual(check(GOOD_TOP).errors, [])

    def test_back_driving_an_input_pin_is_rejected(self) -> None:
        """uio[0] is RX_VALID, an input; the ASIC must not drive it."""
        bad = GOOD_TOP.replace(
            "tx_valid, rx_ready, 1'b0}", "tx_valid, rx_ready, some_signal}"
        )
        errors = check(bad).errors
        self.assertTrue(any("uio[0]" in item for item in errors), errors)
        self.assertTrue(any("back-drive" in item for item in errors), errors)

    def test_tying_a_documented_output_to_zero_is_rejected(self) -> None:
        bad = GOOD_TOP.replace("fault, busy", "1'b0, busy")
        errors = check(bad).errors
        self.assertTrue(any("uio[5]" in item for item in errors), errors)
        self.assertTrue(any("never be observable" in item for item in errors), errors)

    def test_wrong_direction_mask_is_rejected(self) -> None:
        bad = GOOD_TOP.replace("8'b10110110", "8'b11111111")
        self.assertTrue(any("uio_oe" in item for item in check(bad).errors))

    def test_widened_pin_port_is_rejected(self) -> None:
        bad = GOOD_TOP.replace("[7:0] ui_in", "[31:0] ui_in")
        errors = check(bad).errors
        self.assertTrue(any("ui_in" in item for item in errors), errors)

    def test_missing_concatenation_is_reported(self) -> None:
        bad = GOOD_TOP.replace(
            "assign uio_out = {done_pulse, 1'b0, fault, busy, 1'b0, tx_valid, rx_ready, 1'b0};",
            "assign uio_out = status_bus;",
        )
        self.assertTrue(any("concatenation" in item for item in check(bad).errors))

    def test_unexpected_driver_name_is_an_observation_not_an_error(self) -> None:
        renamed = GOOD_TOP.replace("busy,", "occupied_flag,")
        result = check(renamed)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("uio[4]" in item for item in result.observations))


class HarnessWidthTests(unittest.TestCase):
    def test_narrow_harness_passes(self) -> None:
        result = Result(errors=[], observations=[], facts=[])
        check_harness_width(
            result,
            {"ok.sv": "module h (input wire [7:0] asic_uo_out, output wire [7:0] a);"},
        )
        self.assertEqual(result.errors, [])

    def test_wide_bypass_port_is_rejected(self) -> None:
        result = Result(errors=[], observations=[], facts=[])
        check_harness_width(
            result,
            {"bypass.sv": "module h (output wire [127:0] wide_result_bypass);"},
        )
        self.assertTrue(any("wide bypass" in item for item in result.errors))
        self.assertTrue(any("128 bits" in item for item in result.errors))

    def test_empty_harness_directory_is_rejected(self) -> None:
        result = Result(errors=[], observations=[], facts=[])
        check_harness_width(result, {})
        self.assertTrue(any("no harness RTL" in item for item in result.errors))


class HarnessDiscoveryTests(unittest.TestCase):
    """A wide bypass must not escape by choice of directory or file suffix."""

    WIDE = "module h (output wire [127:0] wide_result_bypass);\nendmodule\n"

    def _scan(self, relative: str) -> Result:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.WIDE)
            result = Result(errors=[], observations=[], facts=[])
            with mock.patch.object(boundary_check, "HARNESS_RTL_DIR", root):
                check_harness_width(result)
        return result

    def test_wide_port_in_nested_directory_is_rejected(self) -> None:
        errors = self._scan("sub/deeper/bypass.sv").errors
        self.assertTrue(any("wide bypass" in item for item in errors), errors)

    def test_wide_port_in_plain_verilog_file_is_rejected(self) -> None:
        errors = self._scan("bypass.v").errors
        self.assertTrue(any("wide bypass" in item for item in errors), errors)

    def test_shipped_harness_rtl_is_discovered(self) -> None:
        result = Result(errors=[], observations=[], facts=[])
        check_harness_width(result)
        self.assertEqual(result.errors, [])
        self.assertTrue(result.facts)


class AbbreviationTests(unittest.TestCase):
    def test_leading_token_abbreviation_is_accepted(self) -> None:
        self.assertTrue(_is_abbreviation("DONE", "DONE_PULSE"))
        self.assertTrue(_is_abbreviation("DONE_PULSE", "DONE"))

    def test_different_roles_are_not_abbreviations(self) -> None:
        self.assertFalse(_is_abbreviation("RX_READY", "TX_READY"))
        self.assertFalse(_is_abbreviation("BUSY", "FAULT"))


if __name__ == "__main__":
    unittest.main()
