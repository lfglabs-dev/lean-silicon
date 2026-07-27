from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hardware_preflight as preflight


class LinuxDiscoveryTests(unittest.TestCase):
    def test_prefers_documented_ftdi_by_id_over_ttyusb(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "usb-FTDI_FT231X_USB_UART_D01623-if00-port0").touch()
            result = preflight.serial_candidates("linux", root, "/fake/ttyUSB*", lambda _: ["/fake/ttyUSB1"])
        self.assertEqual(result, [str(root / "usb-FTDI_FT231X_USB_UART_D01623-if00-port0")])

    def test_linux_fallback_is_sorted_and_bounded(self) -> None:
        result = preflight.serial_candidates("linux", Path("/missing"), "/fake/ttyUSB*", lambda _: [f"/fake/ttyUSB{i}" for i in range(9, -1, -1)])
        self.assertEqual(result, [f"/fake/ttyUSB{i}" for i in range(8)])

    def test_macos_discovery_is_preserved(self) -> None:
        result = preflight.serial_candidates("darwin", globber=lambda pattern: [pattern.replace("*", "D01623")])
        self.assertEqual(len(result), 2)
        self.assertTrue(all("usbserial-D01623" in p for p in result))


class SafetyTests(unittest.TestCase):
    def test_detect_command_is_profiled_and_not_programming(self) -> None:
        with mock.patch.object(preflight.shutil, "which", return_value="/tool/openFPGALoader"), mock.patch.object(preflight, "bounded", return_value=(0, "idcode 0x41113043")) as run:
            result = preflight.safe_loader_detect(1.5)
        self.assertEqual(run.call_args.args[0], ["/tool/openFPGALoader", "-b", "ulx3s", "--detect"])
        self.assertEqual(result["model"], "LFE5U-85F")
        self.assertNotIn("-f", result["command"])

    def test_forbidden_flash_flag_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            preflight.main(["--flash"])

    def test_uart_candidates_are_never_opened(self) -> None:
        with mock.patch.object(preflight, "serial_candidates", return_value=["/dev/ttyUSB0"]), \
             mock.patch.object(preflight, "device_metadata", return_value={"path": "/dev/ttyUSB0"}), \
             mock.patch.object(preflight, "safe_loader_detect", return_value={"idcode": None}), \
             mock.patch.object(preflight.board_detect, "_enumerate_usb", return_value=()), \
             mock.patch.object(preflight, "_git", side_effect=["abc", ""]), \
             mock.patch.object(preflight, "bounded", side_effect=AssertionError("UART command executed")):
            payload = preflight.evidence(0.1)
        self.assertEqual(payload["uart"]["candidates"], [{"path": "/dev/ttyUSB0"}])
        self.assertIn("not opened", payload["uart"]["probe"])

    def test_evidence_records_no_hardware_writes_and_redacts(self) -> None:
        with mock.patch.object(preflight, "serial_candidates", return_value=[]), mock.patch.object(preflight, "safe_loader_detect", return_value={"idcode": None}), mock.patch.object(preflight.board_detect, "_enumerate_usb", return_value=()), mock.patch.object(preflight, "_git", side_effect=["abc", ""]):
            payload = preflight.evidence(1.0)
        self.assertFalse(payload["safety"]["programming"])
        self.assertFalse(payload["safety"]["protocol_writes"])
        self.assertIn("[REDACTED]", preflight.redact("TOKEN=actual-secret"))

    def test_output_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "evidence.json"
            output.write_text("old")
            self.assertEqual(preflight.main(["--output", str(output)]), 2)
            self.assertEqual(output.read_text(), "old")
