from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.verify_lsc1_fpga_packet_evidence import ROOT, verify, EvidenceError
import lsc1_transaction as p


class PacketEvidenceTest(unittest.TestCase):
    @staticmethod
    def refresh_checksums(directory: Path) -> None:
        names = sorted(x.name for x in directory.iterdir() if x.is_file() and x.name != "SHA256SUMS")
        text = "".join(f"{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  ./{name}\n" for name in names)
        (directory / "SHA256SUMS").write_text(text)

    def fixture(self, directory: Path) -> None:
        endpoint = p.Lsc1Endpoint()
        requests = [p.build_status_query(), p.build_negotiate(profile=p.Profile.INTERPRETER_COMPAT),
                    p.build_set_constant(txn_id=1, pc=0, fp=0, profile=p.Profile.INTERPRETER_COMPAT,
                                         offset=2, constant=3, cell=p.ABSENT)]
        exchanges = []
        result = None
        for request in requests:
            response, _ = p.drive(endpoint, request.encode())
            exchanges.append({"request_hex": request.encode().hex(), "response_hex": response.hex()})
            result = p.decode_response(response)
        retire = p.build_retire(txn_id=1, result_crc=p.crc32(result.payload))
        response, _ = p.drive(endpoint, retire.encode())
        exchanges.append({"request_hex": retire.encode().hex(), "response_hex": response.hex()})
        capture = {"transport": "ULX3S UART to existing 8-bit ready/valid pins",
                   "reset": "fresh hardware reset before first byte", "exchanges": exchanges}
        (directory / "capture.json").write_text(json.dumps(capture, sort_keys=True) + "\n")
        source_rel = "fpga/ulx3s/ulx3s_packet_top.sv"
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
        source = subprocess.check_output(["git", "show", f"{head}:{source_rel}"], cwd=ROOT)
        manifest = f"=== SOURCE PROVENANCE ===\nrevision: {head}\ninputs-match-revision: yes\n{hashlib.sha256(source).hexdigest()}  {source_rel}\n"
        (directory / "SOURCE_MANIFEST.txt").write_text(manifest)
        (directory / "image.bit").write_bytes(b"synthetic-test-only")
        preflight = {"schema": "lean-silicon.ulx3s-preflight.v1", "git": {"commit": head, "clean": True},
                     "jtag": {"idcode": "0x41113043"},
                     "usb": [{"vid": "0x0403", "pid": "0x6015"}],
                     "uart": {"candidates": [{"path": "/dev/test-ulx3s"}]}}
        (directory / "preflight.json").write_text(json.dumps(preflight) + "\n")
        (directory / "tool_versions.txt").write_text("synthetic test versions\n")
        (directory / "timing.txt").write_text(
            "Input frequency of PLL 'pll' constrained to 25.0 MHz\n"
            "Derived frequency constraint of 10.0 MHz for net core_clk\n"
            "Max frequency for clock '$glbnet$core_clk': 15.21 MHz (PASS at 10.00 MHz)\n"
        )
        (directory / "yosys.log").write_text("synthetic test log\n")
        (directory / "nextpnr.log").write_text("synthetic test log\n")
        (directory / "load.log").write_text("synthetic test only; no loader was run\n")
        sha = lambda name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        receipt = {"schema": "lean-silicon.lsc1-09-ulx3s.v1", "physical_capture": True,
                   "source_head": head, "source_tree": tree, "source_clean": True,
                   "source_status_porcelain": "", "build_inputs_clean": True,
                   "board_revision": "v3.1.8", "ecp5_idcode": "0x41113043", "programming": "SRAM-only",
                   "uart": {"path": "/dev/test-ulx3s", "baud": 1_000_000},
                   "loader": {"name": "openFPGALoader", "version": "test",
                              "command": ["openFPGALoader", "-b", "ulx3s", "image.bit"]},
                   "tools": {"yosys": "test", "nextpnr-ecp5": "test", "ecppack": "test"},
                   "clock_constraint_mhz": 25.0, "core_clock_mhz": 10.0,
                   "timestamps": {"reset": "test", "capture_end": "test"},
                   "bitstream": {"file": "image.bit", "sha256": sha("image.bit")},
                   "artifacts": {"capture.json": sha("capture.json"), "SOURCE_MANIFEST.txt": sha("SOURCE_MANIFEST.txt")}}
        (directory / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
        self.refresh_checksums(directory)

    def mutate_capture(self, d: Path, exchange: int, byte: int, mask: int) -> None:
        path = d / "capture.json"; value = json.loads(path.read_text())
        raw = bytearray.fromhex(value["exchanges"][exchange]["response_hex"]); raw[byte] ^= mask
        value["exchanges"][exchange]["response_hex"] = raw.hex(); path.write_text(json.dumps(value, sort_keys=True) + "\n")
        receipt = json.loads((d / "receipt.json").read_text())
        receipt["artifacts"]["capture.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (d / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
        self.refresh_checksums(d)

    def test_valid_packet(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self.fixture(d); verify(d)

    def test_set_result_value_one_bit_mutation_is_semantic(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self.fixture(d); self.mutate_capture(d, 2, 10 + 17, 1)
            with self.assertRaisesRegex(EvidenceError, "semantic: response 2 differs"): verify(d)

    def test_retired_committed_pc_one_to_zero_is_semantic(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self.fixture(d); self.mutate_capture(d, 3, 6 + 8, 1)
            with self.assertRaisesRegex(EvidenceError, "semantic: RETIRE response differs"): verify(d)

    def test_one_provenance_digest_mutation_is_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self.fixture(d)
            receipt = json.loads((d / "receipt.json").read_text()); receipt["bitstream"]["sha256"] = "0" * 64
            (d / "receipt.json").write_text(json.dumps(receipt) + "\n")
            self.refresh_checksums(d)
            with self.assertRaisesRegex(EvidenceError, "provenance: bitstream digest mismatch"): verify(d)

    def test_missing_core_clock_pass_is_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self.fixture(d)
            (d / "timing.txt").write_text(
                "Input frequency of PLL 'pll' constrained to 25.0 MHz\n"
                "Derived frequency constraint of 10.0 MHz for net core_clk\n"
                "Max frequency for clock '$glbnet$core_clk': 9.99 MHz (FAIL at 10.00 MHz)\n"
            )
            self.refresh_checksums(d)
            with self.assertRaisesRegex(EvidenceError, "provenance: timing report does not pass"): verify(d)


if __name__ == "__main__": unittest.main()
