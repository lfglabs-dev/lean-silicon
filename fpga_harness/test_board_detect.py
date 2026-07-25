"""Board-free tests for the detection ladder.

Every case injects an :class:`Environment`, so no test touches PATH, USB, or a
JTAG cable.  The load-bearing test is
``test_full_visibility_still_reports_datapath_unvalidated``: it is what stops
tool, USB, or JTAG visibility from being read as working hardware.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from board_detect import (
    ECP5_IDCODES,
    LEVELS,
    ULX3S_USB_PID,
    ULX3S_USB_VID,
    Environment,
    detect,
    main,
    render,
)

FULL_FIXTURE = {
    "tools": {
        "yosys": "/usr/bin/yosys",
        "nextpnr-ecp5": "/usr/bin/nextpnr-ecp5",
        "ecppack": "/usr/bin/ecppack",
        "openFPGALoader": "/usr/bin/openFPGALoader",
    },
    "versions": {"yosys": "Yosys 0.44", "openFPGALoader": "openFPGALoader v0.12.0"},
    "usb_devices": [[ULX3S_USB_VID, ULX3S_USB_PID, "ULX3S FPGA 85F"]],
    "jtag_scan": "index 0: idcode 0x41113043 manufacturer lattice model LFE5U-85F",
}


class EmptyEnvironmentTests(unittest.TestCase):
    def test_default_environment_satisfies_nothing(self) -> None:
        report = detect(Environment())
        for level in LEVELS:
            self.assertFalse(report.satisfied(level), level)
        self.assertIsNone(report.highest_satisfied)
        self.assertFalse(report.datapath_validated)

    def test_absent_toolchain_is_reported_per_group(self) -> None:
        report = detect(Environment())
        names = {item.name for item in report.findings if item.level == "toolchain"}
        self.assertEqual(names, {"build-tools", "load-tools"})


class FullVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = detect(Environment.from_fixture(FULL_FIXTURE))

    def test_lower_levels_are_satisfied(self) -> None:
        for level in ("toolchain", "usb", "jtag"):
            self.assertTrue(self.report.satisfied(level), level)

    def test_full_visibility_still_reports_datapath_unvalidated(self) -> None:
        """Tools plus USB plus a real IDCODE must not imply a working data path."""
        self.assertFalse(self.report.datapath_validated)
        self.assertFalse(self.report.satisfied("datapath"))
        self.assertEqual(self.report.highest_satisfied, "jtag")
        finding = next(
            item for item in self.report.findings if item.level == "datapath"
        )
        self.assertEqual(finding.status, "not-validated")
        self.assertIn("no data-path evidence", finding.detail)

    def test_jtag_detail_names_the_recognised_part(self) -> None:
        finding = next(item for item in self.report.findings if item.level == "jtag")
        self.assertEqual(finding.status, "present")
        self.assertIn("LFE5U-85F", finding.detail)

    def test_serialised_report_marks_datapath_false(self) -> None:
        payload = self.report.as_dict()
        self.assertFalse(payload["datapath_validated"])
        self.assertFalse(payload["satisfied"]["datapath"])
        self.assertIn("NOT validated", payload["verdict"])

    def test_rendered_report_states_datapath_is_not_validated(self) -> None:
        self.assertIn("data-path behaviour validated: NO", render(self.report))


class LevelIsolationTests(unittest.TestCase):
    def test_wrong_usb_identity_is_absent(self) -> None:
        fixture = dict(FULL_FIXTURE, usb_devices=[[0x1234, 0x5678, "some hub"]])
        report = detect(Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("usb"))
        self.assertEqual(report.highest_satisfied, "toolchain")

    def test_unrecognised_idcode_is_absent(self) -> None:
        fixture = dict(FULL_FIXTURE, jtag_scan="index 0: idcode 0xdeadbeef")
        report = detect(Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("jtag"))
        self.assertEqual(report.highest_satisfied, "usb")

    def test_empty_jtag_scan_is_absent(self) -> None:
        fixture = dict(FULL_FIXTURE, jtag_scan="   ")
        report = detect(Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("jtag"))

    def test_every_documented_ecp5_idcode_is_recognised(self) -> None:
        for code, part in ECP5_IDCODES.items():
            with self.subTest(part=part):
                fixture = dict(FULL_FIXTURE, jtag_scan=f"idcode {code:#010x}")
                report = detect(Environment.from_fixture(fixture))
                self.assertTrue(report.satisfied("jtag"))

    def test_load_tools_alone_satisfy_the_toolchain_level_partially(self) -> None:
        """A loader without a synthesis flow must not satisfy the level."""
        fixture = dict(FULL_FIXTURE, tools={"openFPGALoader": "/usr/bin/openFPGALoader"})
        report = detect(Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("toolchain"))
        statuses = {
            item.name: item.status
            for item in report.findings
            if item.level == "toolchain"
        }
        self.assertEqual(statuses, {"build-tools": "absent", "load-tools": "present"})


class CommandLineTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = main(argv)
        return code, stream.getvalue()

    def _fixture_file(self, payload: dict) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_require_none_succeeds_without_any_hardware(self) -> None:
        path = self._fixture_file({})
        code, _ = self._run(["--fixture", str(path), "--require", "none"])
        self.assertEqual(code, 0)

    def test_require_datapath_always_fails_even_with_full_visibility(self) -> None:
        path = self._fixture_file(FULL_FIXTURE)
        code, _ = self._run(["--fixture", str(path), "--require", "datapath"])
        self.assertEqual(code, 1)

    def test_require_jtag_tracks_the_fixture(self) -> None:
        full = self._fixture_file(FULL_FIXTURE)
        empty = self._fixture_file({})
        self.assertEqual(self._run(["--fixture", str(full), "--require", "jtag"])[0], 0)
        self.assertEqual(self._run(["--fixture", str(empty), "--require", "jtag"])[0], 1)

    def test_json_output_is_parseable(self) -> None:
        path = self._fixture_file(FULL_FIXTURE)
        code, out = self._run(["--fixture", str(path), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["datapath_validated"])
        self.assertEqual(payload["highest_satisfied_level"], "jtag")


if __name__ == "__main__":
    unittest.main()
