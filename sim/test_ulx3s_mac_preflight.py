"""Tests for the macOS ULX3S preflight capture.

Every USB and JTAG payload here is **synthetic**: it is hand-written text in
the shape the real tools emit, not a capture from a physical board. No ULX3S
and no Mac were present when these ran, so they test the parsing, the fixture
round-trip and the refusal paths only. They establish nothing about hardware.
"""
import contextlib
import hashlib
import io
import json
import pathlib
import plistlib
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

#: What `system_profiler SPUSBDataType -json` actually returned on macOS
#: 26.5.2 with the board attached and enumerating: an empty tree.
USB_JSON_EMPTY = json.dumps({"SPUSBDataType": []})

#: Shape of `ioreg -p IOUSB -a -l`, the fallback that did see the board.
IOREG_PLIST = plistlib.dumps([{
    "IORegistryEntryName": "Root",
    "IORegistryEntryChildren": [{
        "IORegistryEntryName": "AppleT8103USBXHCI",
        "IORegistryEntryChildren": [{
            "IORegistryEntryName": "ULX3S FPGA 85K v3.0.8",
            "USB Product Name": "ULX3S FPGA 85K v3.0.8",
            "USB Vendor Name": "FER-RADIONA-EMARD",
            "USB Serial Number": "SYNTHETIC0",
            "idVendor": 0x0403,
            "idProduct": 0x6015,
            "locationID": 0x01100000,
        }],
    }],
}]).decode()

#: Shape of plain `ioreg -p IOUSB -l`, used if the plist form is unavailable.
IOREG_TEXT = """\
+-o Root  <class IORegistryEntry, id 0x100000100, retain 15>
  +-o AppleT8103USBXHCI@01000000  <class AppleT8103USBXHCI, id 0x100000445, retain 32>
    +-o ULX3S FPGA 85K v3.0.8@01100000  <class IOUSBHostDevice, id 0x1000004b6, retain 27>
      {
        "idProduct" = 24597
        "idVendor" = 1027
        "USB Product Name" = "ULX3S FPGA 85K v3.0.8"
        "USB Vendor Name" = "FER-RADIONA-EMARD"
        "USB Serial Number" = "SYNTHETIC0"
        "locationID" = 17825792
      }
"""

#: Shape of `openFPGALoader -b ulx3s --detect` against an ECP5-85F.
JTAG_TEXT = (
    "Jtag frequency : requested 6.00MHz   -> real 3.00MHz\n"
    "index 0:\n"
    "\tidcode 0x41113043\n"
    "\tmanufacturer lattice\n"
    "\tfamily ECP5\n"
    "\tmodel  LFE5U-85\n"
    "\tirlength 8\n"
)

#: openFPGALoader 1.1.1 rejects `--version` and exits non-zero.
VERSION_REJECTED = "Error: unknown option --version\n"


def _tool(path: str | None = None, version: str | None = None) -> dict:
    return {"path": path, "version": version, "version_command": None,
            "version_exit_nonzero": False, "probes": []}


def _probe(command, returncode, stdout="", stderr="") -> dict:
    return {"command": list(command), "found": True, "returncode": returncode,
            "stdout": stdout, "stderr": stderr, "truncated": False, "error": None}


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


class IoregParsingTests(unittest.TestCase):
    """The fallback that saw the board when system_profiler saw nothing."""

    def test_plist_form_finds_the_board_under_the_controller(self):
        devices, error = preflight.parse_ioreg_plist(IOREG_PLIST)
        self.assertIsNone(error)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["vendor_id"], preflight.ULX3S_USB_VID)
        self.assertEqual(devices[0]["product_id"], preflight.ULX3S_USB_PID)
        self.assertEqual(devices[0]["name"], "ULX3S FPGA 85K v3.0.8")

    def test_text_form_finds_the_same_board(self):
        devices, error = preflight.parse_ioreg_text(IOREG_TEXT)
        self.assertIsNone(error)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["vendor_id"], preflight.ULX3S_USB_VID)
        self.assertEqual(devices[0]["product_id"], preflight.ULX3S_USB_PID)

    def test_both_forms_agree(self):
        from_plist, _ = preflight.parse_ioreg_plist(IOREG_PLIST)
        from_text, _ = preflight.parse_ioreg_text(IOREG_TEXT)
        for field in ("vendor_id", "product_id", "name", "serial_num", "manufacturer"):
            self.assertEqual(from_plist[0][field], from_text[0][field], field)

    def test_a_node_without_an_identity_is_not_a_device(self):
        devices, _ = preflight.parse_ioreg_text(
            "+-o Root  <class IORegistryEntry, id 0x1, retain 1>\n")
        self.assertEqual(devices, [])

    def test_malformed_plist_is_reported_not_raised(self):
        devices, error = preflight.parse_ioreg_plist("not a plist at all")
        self.assertEqual(devices, [])
        self.assertIn("plist", error)

    def test_text_parser_tolerates_empty_output(self):
        self.assertEqual(preflight.parse_ioreg_text(""), ([], None))


class UsbFallbackTests(unittest.TestCase):
    """system_profiler returning an empty tree must not read as 'no board'."""

    def _capture(self, responses: dict, include_detail=False) -> dict:
        def fake_run(command, timeout=30):
            return responses[command[0]]
        original = preflight.run
        preflight.run = fake_run
        try:
            return preflight.capture_usb("Darwin", include_detail=include_detail)
        finally:
            preflight.run = original

    def test_falls_back_to_ioreg_when_system_profiler_is_empty(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        self.assertEqual(usb["source"], "ioreg-plist")
        self.assertEqual(len(usb["matches"]), 1)
        self.assertIn("system_profiler", usb["empty_probes"])

    def test_system_profiler_wins_when_it_actually_answers(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        self.assertEqual(usb["source"], "system_profiler")

    def test_every_probe_is_recorded_even_when_it_answers_nothing(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        self.assertEqual([entry["source"] for entry in usb["probes"]],
                         ["system_profiler", "ioreg-plist", "ioreg-text"])

    def test_a_failed_probe_records_its_exit_rather_than_a_parse(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 1, "", "boom"),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        first = usb["probes"][0]
        self.assertEqual(first["device_count"], 0)
        self.assertIn("exited 1", first["parse_error"])

    def test_no_probe_seeing_anything_is_reported_as_such(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 1, "", "not permitted"),
        })
        self.assertEqual(usb["source"], "none")
        self.assertEqual(usb["matches"], [])
        self.assertTrue(usb["supported"])

    def test_the_board_serial_is_withheld_by_default(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        self.assertTrue(usb["detail_redacted"])
        self.assertEqual(usb["matches"][0]["serial_num"], preflight.REDACTED)
        self.assertNotIn("SYNTHETIC0", json.dumps(usb))

    def test_raw_usb_output_is_replaced_by_a_digest(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        probe = usb["probes"][1]["probe"]
        self.assertEqual(probe["stdout"], "")
        self.assertEqual(probe["stdout_bytes"], len(IOREG_PLIST.encode()))
        self.assertEqual(probe["stdout_sha256"],
                         hashlib.sha256(IOREG_PLIST.encode()).hexdigest())

    def test_raw_usb_output_is_kept_when_explicitly_asked_for(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        }, include_detail=True)
        self.assertEqual(usb["probes"][1]["probe"]["stdout"], IOREG_PLIST)

    def test_the_serial_is_recorded_when_explicitly_asked_for(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON_EMPTY),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        }, include_detail=True)
        self.assertFalse(usb["detail_redacted"])
        self.assertEqual(usb["matches"][0]["serial_num"], "SYNTHETIC0")

    def test_devices_that_are_not_the_board_are_reduced_to_an_identity(self):
        usb = self._capture({
            "system_profiler": _probe(("system_profiler",), 0, USB_JSON),
            "ioreg": _probe(("ioreg",), 0, IOREG_PLIST),
        })
        hub = [device for device in usb["devices"] if device["vendor_id"] == 0x05E3][0]
        self.assertEqual(hub["name"], preflight.REDACTED)
        self.assertIsNone(hub["serial_num"])
        self.assertNotIn("Genesys", json.dumps(usb))


class VersionProbeTests(unittest.TestCase):
    """openFPGALoader 1.1.1 rejects --version; that must not lose the version."""

    def _capture(self, present: str, answers: dict) -> dict:
        def fake_which(name):
            return f"/opt/homebrew/bin/{name}" if name == present else None

        def fake_run(command, timeout=30):
            return answers[command[1]]

        original_which, original_run = preflight.shutil.which, preflight.run
        preflight.shutil.which, preflight.run = fake_which, fake_run
        try:
            return preflight.capture_tools()[present]
        finally:
            preflight.shutil.which, preflight.run = original_which, original_run

    def test_records_which_flag_answered(self):
        entry = self._capture("openFPGALoader", {
            "--Version": _probe(("openFPGALoader", "--Version"), 0, "openFPGALoader v1.1.1\n"),
            "-V": _probe(("openFPGALoader", "-V"), 1, "", VERSION_REJECTED),
            "--version": _probe(("openFPGALoader", "--version"), 1, "", VERSION_REJECTED),
        })
        self.assertEqual(entry["version"], "openFPGALoader v1.1.1")
        self.assertEqual(entry["version_command"], ["openFPGALoader", "--Version"])
        self.assertFalse(entry["version_exit_nonzero"])

    def test_a_rejected_flag_does_not_become_the_version(self):
        entry = self._capture("openFPGALoader", {
            "--Version": _probe(("openFPGALoader", "--Version"), 1, "", VERSION_REJECTED),
            "-V": _probe(("openFPGALoader", "-V"), 0, "openFPGALoader v1.1.1\n"),
            "--version": _probe(("openFPGALoader", "--version"), 1, "", VERSION_REJECTED),
        })
        self.assertEqual(entry["version"], "openFPGALoader v1.1.1")
        self.assertEqual(entry["version_command"], ["openFPGALoader", "-V"])

    def test_a_version_printed_before_a_non_zero_exit_is_salvaged_and_flagged(self):
        entry = self._capture("openFPGALoader", {
            "--Version": _probe(("openFPGALoader", "--Version"), 2, "", "openFPGALoader v1.1.1\n"),
            "-V": _probe(("openFPGALoader", "-V"), 2, "", "openFPGALoader v1.1.1\n"),
            "--version": _probe(("openFPGALoader", "--version"), 1, "", VERSION_REJECTED),
        })
        self.assertEqual(entry["version"], "openFPGALoader v1.1.1")
        self.assertTrue(entry["version_exit_nonzero"])

    def test_every_flag_being_rejected_leaves_no_version(self):
        entry = self._capture("openFPGALoader", {
            flag: _probe(("openFPGALoader", flag), 1, "", VERSION_REJECTED)
            for flag in preflight.VERSION_FLAGS
        })
        self.assertIsNone(entry["version"])
        self.assertEqual(len(entry["probes"]), len(preflight.VERSION_FLAGS))

    def test_an_absent_tool_is_not_probed_at_all(self):
        def fake_which(name):
            return None
        original = preflight.shutil.which
        preflight.shutil.which = fake_which
        try:
            entry = preflight.capture_tools()["openFPGALoader"]
        finally:
            preflight.shutil.which = original
        self.assertIsNone(entry["path"])
        self.assertEqual(entry["probes"], [])


class JtagCommandTests(unittest.TestCase):
    """A bare --detect exits 1 on a ULX3S; the board profile must come first."""

    def test_the_board_profile_is_tried_first(self):
        self.assertEqual(preflight.JTAG_COMMANDS[0],
                         ("openFPGALoader", "-b", "ulx3s", "--detect"))

    def test_a_bare_detect_is_still_attempted_and_recorded(self):
        self.assertIn(("openFPGALoader", "--detect"), preflight.JTAG_COMMANDS)

    def test_the_answering_command_is_recorded(self):
        def fake_run(command, timeout=30):
            if command[:3] == ("openFPGALoader", "-b", "ulx3s"):
                return _probe(command, 0, JTAG_TEXT)
            return _probe(command, 1, "", "Error: cable not found\n")
        original = preflight.run
        preflight.run = fake_run
        try:
            jtag = preflight.capture_jtag()
        finally:
            preflight.run = original
        self.assertEqual(jtag["answered"], [["openFPGALoader", "-b", "ulx3s", "--detect"]])
        self.assertEqual(jtag["recognised"], [{"idcode": "0x41113043", "device": "LFE5U-85F"}])


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
