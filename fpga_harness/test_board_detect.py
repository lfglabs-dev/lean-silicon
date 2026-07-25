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
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import board_detect
from board_detect import (
    ECP5_IDCODES,
    IOREG_FORBIDDEN_KEYS,
    LEVELS,
    USB_LABEL_MAX_LEN,
    ULX3S_USB_PID,
    ULX3S_USB_VID,
    Environment,
    _enumerate_usb_ioreg,
    _enumerate_usb_sysfs,
    _jtag_scan,
    _tool_version,
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

    def test_partial_build_chain_does_not_satisfy_the_toolchain_level(self) -> None:
        """yosys alone cannot produce a bitstream; nextpnr/ecppack are required."""
        fixture = dict(
            FULL_FIXTURE,
            tools={"yosys": "/usr/bin/yosys", "openFPGALoader": "/usr/bin/openFPGALoader"},
        )
        report = detect(Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("toolchain"))
        build = next(
            item for item in report.findings if item.name == "build-tools"
        )
        self.assertEqual(build.status, "absent")
        self.assertIn("nextpnr-ecp5", build.detail)
        self.assertIn("ecppack", build.detail)

    def test_either_loader_alone_satisfies_the_load_group(self) -> None:
        for loader in ("openFPGALoader", "fujprog"):
            with self.subTest(loader=loader):
                fixture = dict(FULL_FIXTURE, tools={loader: f"/usr/bin/{loader}"})
                report = detect(Environment.from_fixture(fixture))
                load = next(
                    item for item in report.findings if item.name == "load-tools"
                )
                self.assertEqual(load.status, "present")

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


FAKE_SERIAL = "FAKESERIALDONOTLOG0001"

# Shape of `ioreg -p IOUSB -a -l`: a tree of registry entries whose USB nodes
# carry integer idVendor/idProduct alongside identifying strings.
IOREG_TREE = [
    {
        "IOObjectClass": "AppleUSBHostController",
        "IORegistryEntryName": "AppleT8103USBXHCI",
        "IORegistryEntryChildren": [
            {
                "IOObjectClass": "IOUSBHostDevice",
                "IORegistryEntryName": "US1",
                "USB Product Name": "FT231X USB UART",
                "USB Vendor Name": "FTDI",
                "USB Serial Number": FAKE_SERIAL,
                "idVendor": ULX3S_USB_VID,
                "idProduct": ULX3S_USB_PID,
                "bcdDevice": 4096,
            }
        ],
    }
]


def _ioreg_bytes(tree: object) -> bytes:
    return plistlib.dumps(tree, fmt=plistlib.FMT_XML)


def _constant(value: object):
    return lambda _command: value


class DarwinUsbEnumerationTests(unittest.TestCase):
    """macOS reads IOKit directly; `system_profiler` can report an empty list."""

    def test_ioreg_tree_yields_the_ulx3s_identity(self) -> None:
        devices = _enumerate_usb_ioreg(capture=_constant(_ioreg_bytes(IOREG_TREE)))
        self.assertEqual(devices, ((ULX3S_USB_VID, ULX3S_USB_PID, "FT231X USB UART"),))

    def test_serial_number_never_reaches_the_report(self) -> None:
        """A per-board serial in the registry must not leak into any output."""
        devices = _enumerate_usb_ioreg(capture=_constant(_ioreg_bytes(IOREG_TREE)))
        report = detect(Environment(usb_devices=lambda: devices))
        payload = json.dumps(report.as_dict())
        self.assertIn("FT231X USB UART", payload)
        self.assertNotIn(FAKE_SERIAL, payload)
        self.assertNotIn(FAKE_SERIAL, render(report))
        for key in IOREG_FORBIDDEN_KEYS:
            self.assertNotIn(key, payload)

    def test_malformed_plists_yield_no_devices(self) -> None:
        cases = {
            "empty": b"",
            "not-a-plist": b"this is not a plist",
            "truncated": _ioreg_bytes(IOREG_TREE)[:120],
            "html-error-page": b"<html><body>nope</body></html>",
            "binary-garbage": b"\x00\x01\x02\x03bplist-ish",
        }
        for name, raw in cases.items():
            with self.subTest(case=name):
                self.assertEqual(_enumerate_usb_ioreg(capture=_constant(raw)), ())

    def test_untrusted_node_shapes_are_skipped_not_raised(self) -> None:
        cases = {
            "scalar-root": "just a string",
            "list-of-scalars": [1, 2, "three", True],
            "nameless-dict": [{"IOObjectClass": "IOUSBHostDevice"}],
            "string-ids": [{"idVendor": "1027", "idProduct": "24597"}],
            "bool-ids": [{"idVendor": True, "idProduct": False}],
            "out-of-range-ids": [{"idVendor": 70000, "idProduct": -1}],
            "half-identified": [{"idVendor": ULX3S_USB_VID}],
        }
        for name, tree in cases.items():
            with self.subTest(case=name):
                devices = _enumerate_usb_ioreg(capture=_constant(_ioreg_bytes(tree)))
                self.assertEqual(devices, ())

    def test_device_without_a_product_name_falls_back_to_registry_name(self) -> None:
        tree = [{"IORegistryEntryName": "US1", "idVendor": 1, "idProduct": 2}]
        devices = _enumerate_usb_ioreg(capture=_constant(_ioreg_bytes(tree)))
        self.assertEqual(devices, ((1, 2, "US1"),))

    def test_device_with_no_label_at_all_is_still_reported(self) -> None:
        tree = [{"idVendor": ULX3S_USB_VID, "idProduct": ULX3S_USB_PID}]
        devices = _enumerate_usb_ioreg(capture=_constant(_ioreg_bytes(tree)))
        self.assertEqual(devices, ((ULX3S_USB_VID, ULX3S_USB_PID, "0x0403:0x6015"),))

    def test_product_label_is_bounded(self) -> None:
        tree = [{"USB Product Name": "A" * 500, "idVendor": 1, "idProduct": 2}]
        (_vid, _pid, label), = _enumerate_usb_ioreg(
            capture=_constant(_ioreg_bytes(tree))
        )
        self.assertEqual(len(label), USB_LABEL_MAX_LEN)

    def test_deeply_nested_tree_is_bounded_instead_of_recursing_forever(self) -> None:
        node: object = {"idVendor": ULX3S_USB_VID, "idProduct": ULX3S_USB_PID}
        for _ in range(200):
            node = {"IORegistryEntryChildren": [node]}
        devices = _enumerate_usb_ioreg(capture=_constant(_ioreg_bytes(node)))
        self.assertEqual(devices, ())

    def test_platform_dispatch_picks_ioreg_on_darwin_and_sysfs_elsewhere(self) -> None:
        for platform, expected in (("darwin", "ioreg"), ("linux", "sysfs")):
            with self.subTest(platform=platform):
                with mock.patch.object(board_detect.sys, "platform", platform), \
                    mock.patch.object(
                        board_detect, "_enumerate_usb_ioreg", lambda: "ioreg"
                    ), \
                    mock.patch.object(
                        board_detect, "_enumerate_usb_sysfs", lambda: "sysfs"
                    ):
                    self.assertEqual(board_detect._enumerate_usb(), expected)


class LinuxSysfsEnumerationTests(unittest.TestCase):
    """Linux behaviour is unchanged; a tempdir stands in for /sys."""

    def _sysfs(self, entries: dict[str, dict[str, str]]) -> Path:
        directory_handle = tempfile.TemporaryDirectory()
        self.addCleanup(directory_handle.cleanup)
        root = Path(directory_handle.name)
        for name, files in entries.items():
            directory = root / name
            directory.mkdir()
            for filename, content in files.items():
                (directory / filename).write_text(content, encoding="utf-8")
        return root

    def test_sysfs_entries_are_read_as_hexadecimal(self) -> None:
        root = self._sysfs(
            {
                "1-1": {
                    "idVendor": "0403\n",
                    "idProduct": "6015\n",
                    "product": "ULX3S FPGA 85F\n",
                },
                "usb1": {"idVendor": "1d6b", "idProduct": "0002"},
            }
        )
        self.assertEqual(
            _enumerate_usb_sysfs(root=root),
            (
                (ULX3S_USB_VID, ULX3S_USB_PID, "ULX3S FPGA 85F"),
                (0x1D6B, 0x0002, "usb1"),
            ),
        )

    def test_incomplete_or_unparseable_sysfs_entries_are_skipped(self) -> None:
        root = self._sysfs(
            {
                "1-0:1.0": {"idVendor": "0403"},
                "1-2": {"idVendor": "zzzz", "idProduct": "6015"},
            }
        )
        self.assertEqual(_enumerate_usb_sysfs(root=root), ())

    def test_absent_sysfs_root_is_empty(self) -> None:
        self.assertEqual(
            _enumerate_usb_sysfs(root=Path("/nonexistent/sys/bus/usb/devices")), ()
        )


class JtagScanOrderTests(unittest.TestCase):
    """`--detect` alone assumes an FT2232 cable, so `-b ulx3s` has to come first."""

    ULX3S_HIT = "index 0: idcode 0x41113043 manufacturer lattice model LFE5U-85F"

    def _scan(self, responses: dict[tuple[str, ...], str]) -> tuple[str, list[list[str]]]:
        seen: list[list[str]] = []

        def capture(command):
            command = list(command)
            seen.append(command)
            return responses.get(tuple(command[1:]), "")

        with mock.patch.object(board_detect.shutil, "which", lambda _n: "/usr/bin/ofl"):
            return _jtag_scan(capture=capture), seen

    def test_board_profile_is_probed_first_and_short_circuits(self) -> None:
        output, seen = self._scan({("-b", "ulx3s", "--detect"): self.ULX3S_HIT})
        self.assertEqual(output, self.ULX3S_HIT)
        self.assertEqual(seen, [["/usr/bin/ofl", "-b", "ulx3s", "--detect"]])

    def test_bare_detect_is_the_fallback_for_external_cables(self) -> None:
        output, seen = self._scan(
            {
                ("-b", "ulx3s", "--detect"): "unable to open ftdi device\n",
                ("--detect",): self.ULX3S_HIT,
            }
        )
        self.assertEqual(output, self.ULX3S_HIT)
        self.assertEqual(
            seen,
            [
                ["/usr/bin/ofl", "-b", "ulx3s", "--detect"],
                ["/usr/bin/ofl", "--detect"],
            ],
        )

    def test_absent_loader_scans_nothing(self) -> None:
        with mock.patch.object(board_detect.shutil, "which", lambda _n: None):
            called: list[object] = []
            self.assertEqual(_jtag_scan(capture=called.append), "")
            self.assertEqual(called, [])

    def test_both_commands_failing_yields_no_scan_output(self) -> None:
        output, seen = self._scan({})
        self.assertEqual(output, "")
        self.assertEqual(len(seen), 2)
        self.assertFalse(detect(Environment(jtag_scan=lambda: output)).satisfied("jtag"))

    def test_unrecognised_idcode_is_reported_rather_than_discarded(self) -> None:
        """Both probes run, and the wrong-IDCODE evidence still reaches the report."""
        output, seen = self._scan(
            {
                ("-b", "ulx3s", "--detect"): "index 0: idcode 0xdeadbeef",
                ("--detect",): "",
            }
        )
        self.assertEqual(output, "index 0: idcode 0xdeadbeef")
        self.assertEqual(len(seen), 2)
        report = detect(Environment(jtag_scan=lambda: output))
        self.assertFalse(report.satisfied("jtag"))
        finding = next(item for item in report.findings if item.level == "jtag")
        self.assertIn("no recognised ECP5 IDCODE", finding.detail)


class ToolVersionTests(unittest.TestCase):
    def _version(self, name: str, responses: dict[str, str]) -> tuple[str, list[str]]:
        seen: list[str] = []

        def capture(command):
            seen.append(list(command)[1])
            return responses.get(list(command)[1], "")

        with mock.patch.object(
            board_detect.shutil, "which", lambda tool: f"/usr/bin/{tool}"
        ):
            return _tool_version(name, capture=capture), seen

    def test_openfpgaloader_1_1_1_spelling_is_tried_before_the_lowercase_form(
        self,
    ) -> None:
        """1.1.1 answers `--Version` and rejects `--version`."""
        version, seen = self._version(
            "openFPGALoader",
            {
                "--Version": "openFPGALoader v1.1.1\n",
                "--version": "\nunrecognised option '--version'\n",
            },
        )
        self.assertEqual(version, "openFPGALoader v1.1.1")
        self.assertEqual(seen, ["--Version"])

    def test_older_loader_answering_only_the_lowercase_form_is_still_read(self) -> None:
        version, seen = self._version(
            "openFPGALoader",
            {
                "--Version": "\nUnknown option: --Version\n",
                "--version": "openFPGALoader v0.12.0\n",
            },
        )
        self.assertEqual(version, "openFPGALoader v0.12.0")
        self.assertEqual(seen, ["--Version", "--version"])

    def test_option_parser_complaints_are_not_reported_as_versions(self) -> None:
        complaints = (
            "unrecognised option '--version'",
            "Error: unknown option --Version",
            "usage: openFPGALoader [OPTIONS] BITSTREAM",
            "The following argument was not expected: --version 1",
        )
        for complaint in complaints:
            with self.subTest(complaint=complaint):
                version, _ = self._version(
                    "openFPGALoader", {"--Version": complaint, "--version": complaint}
                )
                self.assertEqual(version, "")

    def test_a_line_without_a_digit_is_not_a_version(self) -> None:
        version, _ = self._version("yosys", {"--version": "some banner text\n"})
        self.assertEqual(version, "")

    def test_conventional_tools_are_asked_only_for_lowercase_version(self) -> None:
        version, seen = self._version("yosys", {"--version": "Yosys 0.44 (git sha1)\n"})
        self.assertEqual(version, "Yosys 0.44 (git sha1)")
        self.assertEqual(seen, ["--version"])

    def test_version_output_is_capped_to_one_bounded_line(self) -> None:
        version, _ = self._version(
            "yosys", {"--version": "Yosys 0.44 " + "x" * 500 + "\nsecond line\n"}
        )
        self.assertNotIn("second line", version)
        self.assertLessEqual(len(version), board_detect.VERSION_MAX_LEN)

    def test_absent_tool_has_no_version(self) -> None:
        with mock.patch.object(board_detect.shutil, "which", lambda _n: None):
            self.assertEqual(_tool_version("yosys", capture=_constant("Yosys 0.44")), "")


if __name__ == "__main__":
    unittest.main()
