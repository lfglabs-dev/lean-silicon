"""Tests for the macOS ULX3S preflight capture.

Every USB and JTAG payload here is **synthetic**: it is hand-written text in
the shape the real tools emit, not a capture from a physical board. No ULX3S
and no Mac were present when these ran, so they test the parsing, the fixture
round-trip and the refusal paths only. They establish nothing about hardware.
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(relative: str, name: str) -> types.ModuleType:
    """Load a tracked source file as a module without installing it."""
    path = ROOT / relative
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    finally:
        del sys.modules[name]
    return module


preflight = _load("tools/ulx3s_mac_preflight.py", "_tested_ulx3s_mac_preflight")
board_detect = _load("fpga_harness/board_detect.py", "_tested_board_detect")

#: A real ULX3S-85F answers with this; taken from the harness IDCODE table.
IDCODE_85F = 0x41113043

#: Shape of `system_profiler SPUSBDataType -json` with an FT231X behind a hub.
USB_JSON = json.dumps({
    "SPUSBDataType": [{
        "_name": "USB31Bus",
        "_items": [{
            "_name": "USB3.1 Hub",
            "vendor_id": "0x05e3  (Genesys Logic, Inc.)",
            "product_id": "0x0610",
            "_items": [{
                "_name": "ULX3S FPGA 85K v3.0.8",
                "vendor_id": "0x0403  (Future Technology Devices International Limited)",
                "product_id": "0x6015",
                "manufacturer": "FER-RADIONA-EMARD",
                "serial_num": "K00000",
                "location_id": "0x01100000 / 3",
                "device_speed": "up_to_12_Mb_per_sec",
            }],
        }],
    }],
})

#: Shape of `openFPGALoader --detect` against an ECP5-85F.
JTAG_TEXT = (
    "Jtag frequency : requested 6.00MHz   -> real 6.00MHz\n"
    "index 0:\n"
    "\tidcode 0x41113043\n"
    "\tmanufacturer lattice\n"
    "\tfamily ECP5\n"
    "\tmodel  LFE5U-85\n"
    "\tirlength 8\n"
)


def _tool(path: str | None = None, version: str | None = None) -> dict:
    return {"path": path, "version": version, "version_command": None, "probes": []}


def _main(argv: list[str]) -> int:
    """Run the CLI without its report landing in the test log."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return preflight.main(argv)


class UsbParsingTests(unittest.TestCase):
    def test_flattens_hub_nesting(self):
        devices, error = preflight.parse_usb(USB_JSON)
        self.assertIsNone(error)
        self.assertEqual([device["name"] for device in devices],
                         ["USB3.1 Hub", "ULX3S FPGA 85K v3.0.8"])

    def test_strips_the_vendor_name_from_the_hex_field(self):
        devices, _ = preflight.parse_usb(USB_JSON)
        board = devices[1]
        self.assertEqual(board["vendor_id"], preflight.ULX3S_USB_VID)
        self.assertEqual(board["product_id"], preflight.ULX3S_USB_PID)
        self.assertEqual(board["serial_num"], "K00000")

    def test_keeps_the_raw_field_alongside_the_parse(self):
        devices, _ = preflight.parse_usb(USB_JSON)
        self.assertIn("Future Technology", devices[1]["vendor_id_raw"])

    def test_bus_with_no_devices_parses_to_nothing(self):
        devices, error = preflight.parse_usb(
            json.dumps({"SPUSBDataType": [{"_name": "USB31Bus"}]}))
        self.assertIsNone(error)
        self.assertEqual(devices, [])

    def test_non_json_is_reported_not_raised(self):
        devices, error = preflight.parse_usb("system_profiler: unrecognized option")
        self.assertEqual(devices, [])
        self.assertIn("not JSON", error)

    def test_unparseable_identity_is_skipped_rather_than_guessed(self):
        devices, _ = preflight.parse_usb(json.dumps({"SPUSBDataType": [
            {"_name": "Odd", "vendor_id": "unknown", "product_id": "0x6015"},
        ]}))
        self.assertEqual(devices, [])

    def test_hex_field_parser_rejects_non_strings(self):
        self.assertIsNone(preflight.parse_hex_field(None))
        self.assertIsNone(preflight.parse_hex_field(1027))
        self.assertIsNone(preflight.parse_hex_field(""))


class PlatformRefusalTests(unittest.TestCase):
    """The whole point of this tool: never claim a USB result off Darwin."""

    def test_non_darwin_is_unsupported_not_absent(self):
        usb = preflight.capture_usb("Linux")
        self.assertFalse(usb["supported"])
        self.assertEqual(usb["source"], "unsupported")
        self.assertEqual(usb["matches"], [])

    def test_refusal_names_the_sysfs_limit_of_the_harness_probe(self):
        detail = preflight.capture_usb("Linux")["detail"]
        self.assertIn("/sys/bus/usb/devices", detail)
        self.assertIn("macOS-only", detail)

    def test_the_harness_probe_really_is_sysfs_only(self):
        source = (ROOT / "fpga_harness" / "board_detect.py").read_text()
        self.assertIn("/sys/bus/usb/devices", source)


class FixtureRoundTripTests(unittest.TestCase):
    """A macOS capture must replay through board_detect.py unmodified."""

    def _fixture(self, *, usb_devices, jtag, tools):
        usb = {"supported": True, "devices": usb_devices, "matches": []}
        return preflight.build_fixture(tools, usb, {"scan_text": jtag})

    def test_a_board_capture_raises_the_ladder_to_jtag(self):
        devices, _ = preflight.parse_usb(USB_JSON)
        fixture = self._fixture(
            usb_devices=devices,
            jtag=JTAG_TEXT,
            tools={"openFPGALoader": _tool("/opt/homebrew/bin/openFPGALoader", "v0.12.0"),
                   "yosys": _tool("/opt/homebrew/bin/yosys", "Yosys 0.44"),
                   "nextpnr-ecp5": _tool("/opt/homebrew/bin/nextpnr-ecp5", "nextpnr-0.7"),
                   "ecppack": _tool("/opt/homebrew/bin/ecppack", "Project Trellis 1.4"),
                   "fujprog": _tool(None)},
        )
        report = board_detect.detect(board_detect.Environment.from_fixture(fixture))
        self.assertTrue(report.satisfied("usb"))
        self.assertTrue(report.satisfied("jtag"))

    def test_replay_never_reaches_the_datapath_level(self):
        devices, _ = preflight.parse_usb(USB_JSON)
        fixture = self._fixture(
            usb_devices=devices, jtag=JTAG_TEXT,
            tools={"openFPGALoader": _tool("/opt/homebrew/bin/openFPGALoader", "v0.12.0")})
        report = board_detect.detect(board_detect.Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("datapath"))

    def test_a_charge_only_cable_capture_leaves_usb_absent(self):
        fixture = self._fixture(usb_devices=[], jtag="", tools={"yosys": _tool("/usr/bin/yosys")})
        report = board_detect.detect(board_detect.Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("usb"))

    def test_fixture_carries_only_tools_that_exist(self):
        fixture = self._fixture(
            usb_devices=[], jtag="",
            tools={"yosys": _tool("/usr/bin/yosys", "Yosys 0.44"), "fujprog": _tool(None)})
        self.assertEqual(fixture["tools"], {"yosys": "/usr/bin/yosys"})
        self.assertEqual(fixture["versions"], {"yosys": "Yosys 0.44"})

    def test_fixture_is_json_serialisable_as_written(self):
        devices, _ = preflight.parse_usb(USB_JSON)
        fixture = self._fixture(usb_devices=devices, jtag=JTAG_TEXT, tools={})
        json.loads(json.dumps(fixture))


class JtagParsingTests(unittest.TestCase):
    def _classify(self, text: str) -> dict:
        idcodes = [int(value, 16) for value in preflight.IDCODE_RE.findall(text)]
        return {
            "recognised": [preflight.ECP5_IDCODES[code]
                           for code in idcodes if code in preflight.ECP5_IDCODES],
            "unrecognised": [f"{code:#010x}"
                             for code in idcodes if code not in preflight.ECP5_IDCODES],
        }

    def test_recognises_the_85f_idcode(self):
        self.assertEqual(self._classify(JTAG_TEXT)["recognised"], ["LFE5U-85F"])

    def test_an_unknown_idcode_is_recorded_not_dropped(self):
        result = self._classify("\tidcode 0xdeadbeef\n")
        self.assertEqual(result["recognised"], [])
        self.assertEqual(result["unrecognised"], ["0xdeadbeef"])

    def test_idcode_table_is_imported_from_the_harness(self):
        self.assertEqual(preflight.ECP5_IDCODES, board_detect.ECP5_IDCODES)
        self.assertEqual(preflight.ECP5_IDCODES[IDCODE_85F], "LFE5U-85F")

    def test_usb_identity_is_imported_from_the_harness(self):
        self.assertEqual(preflight.ULX3S_USB_VID, board_detect.ULX3S_USB_VID)
        self.assertEqual(preflight.ULX3S_USB_PID, board_detect.ULX3S_USB_PID)


class NextStageTests(unittest.TestCase):
    def test_fails_closed_in_the_current_tree(self):
        stage = preflight.next_stage(ROOT)
        self.assertFalse(stage["ready"])
        self.assertEqual(
            sorted(stage["missing"]),
            ["board_top", "host_byte_driver", "lpf_constraints", "timing_clean_bitstream"],
        )

    def test_every_prerequisite_says_what_it_wants(self):
        for item in preflight.next_stage(ROOT)["prerequisites"]:
            self.assertTrue(item["requires"].strip())

    def test_commands_are_printed_never_executed(self):
        stage = preflight.next_stage(ROOT)
        self.assertTrue(stage["commands"])
        self.assertIn("command shape", stage["policy"])

    def test_a_satisfied_prerequisite_flips_to_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "fpga_harness" / "rtl").mkdir(parents=True)
            (root / "host").mkdir()
            (root / "fpga_harness" / "ulx3s.lpf").write_text("LOCATE COMP \"clk\";\n")
            stage = preflight.next_stage(root)
        by_key = {item["key"]: item for item in stage["prerequisites"]}
        self.assertTrue(by_key["lpf_constraints"]["present"])
        self.assertFalse(by_key["board_top"]["present"])
        self.assertFalse(stage["ready"])


class ChecklistTests(unittest.TestCase):
    def test_unconfirmed_by_default(self):
        entries = preflight.checklist({})
        self.assertTrue(all(entry["status"] == "unconfirmed" for entry in entries))
        self.assertTrue(all(entry["value"] is None for entry in entries))

    def test_covers_the_physical_facts_software_cannot_see(self):
        keys = {entry["key"] for entry in preflight.checklist({})}
        self.assertEqual(
            keys,
            {"board_revision", "fpga_density", "sdram_part",
             "us1_connector", "cable_type", "power_source"},
        )

    def test_a_confirmation_is_recorded_verbatim(self):
        entries = {entry["key"]: entry
                   for entry in preflight.checklist({"board_revision": "v3.0.8"})}
        self.assertEqual(entries["board_revision"]["status"], "confirmed")
        self.assertEqual(entries["board_revision"]["value"], "v3.0.8")

    def test_every_entry_says_where_to_look(self):
        for entry in preflight.checklist({}):
            self.assertTrue(entry["where_to_look"].strip())


class ArtifactTests(unittest.TestCase):
    def test_runs_end_to_end_and_writes_both_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory) / "preflight.json"
            fixture_out = pathlib.Path(directory) / "board.fixture.json"
            code = _main(["--out", str(out), "--fixture-out", str(fixture_out),
                                   "--confirm", "board_revision=v3.0.8", "--json"])
            artifact = json.loads(out.read_text())
            fixture = json.loads(fixture_out.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(artifact["schema"], preflight.SCHEMA)
        self.assertEqual(artifact["board_detect_fixture"], fixture)

    def test_the_emitted_fixture_is_accepted_by_board_detect(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_out = pathlib.Path(directory) / "board.fixture.json"
            _main(["--fixture-out", str(fixture_out), "--json"])
            fixture = json.loads(fixture_out.read_text())
        report = board_detect.detect(board_detect.Environment.from_fixture(fixture))
        self.assertFalse(report.satisfied("datapath"))

    def test_artifact_states_what_it_does_not_establish(self):
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory) / "preflight.json"
            _main(["--out", str(out), "--json"])
            claims = json.loads(out.read_text())["claims"]
        joined = " ".join(claims["does_not_establish"])
        self.assertIn("ready/valid", joined)
        self.assertIn("equivalence", joined)
        self.assertTrue(any("/sys/bus/usb/devices" in limit
                            for limit in claims["known_limits"]))

    def test_next_stage_flag_exits_non_zero_while_closed(self):
        self.assertEqual(_main(["--next-stage", "--json"]), 1)

    def test_unknown_checklist_key_is_rejected(self):
        with self.assertRaises(SystemExit):
            _main(["--confirm", "colour=blue"])

    def test_malformed_confirmation_is_rejected(self):
        with self.assertRaises(SystemExit):
            _main(["--confirm", "board_revision"])


class ProbeTests(unittest.TestCase):
    def test_a_missing_program_is_recorded_not_raised(self):
        probe = preflight.run(("definitely-not-a-real-program-9f6e",))
        self.assertFalse(probe["found"])
        self.assertIsNone(probe["returncode"])
        self.assertIn("not on PATH", probe["error"])

    def test_output_beyond_the_limit_is_clipped_and_flagged(self):
        text, clipped = preflight.clip("x" * (preflight.RAW_LIMIT + 1))
        self.assertTrue(clipped)
        self.assertEqual(len(text), preflight.RAW_LIMIT)

    def test_short_output_is_kept_whole(self):
        self.assertEqual(preflight.clip("idcode"), ("idcode", False))


if __name__ == "__main__":
    unittest.main()
