#!/usr/bin/env python3
"""Verify one source-bound physical ULX3S LSC-1 SET/RETIRE evidence packet."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
sys.path.insert(0, str(ROOT))
import lsc1_transaction as p  # noqa: E402
from host.runtime import decode_result_payload  # noqa: E402


class EvidenceError(RuntimeError):
    pass


# Every tracked input consumed by fpga/ulx3s/build_packet_uart.sh.  Keeping this
# list in the independent evidence verifier makes omission fail closed; the
# build's self-reported manifest is not allowed to define its own completeness.
PACKET_BUILD_INPUTS = frozenset({
    "asic_core/rtl/gf128_mul_bitstream.sv",
    "asic_core/rtl/gf2n_mul_bitstream.sv",
    "asic_core/rtl/lean_silicon_lsc1.sv",
    "asic_core/rtl/lean_silicon_lsc1_mincore.sv",
    "asic_core/rtl/leanvm_b_stream_alu.sv",
    "asic_core/rtl/lsc1_blake3_alias_check.sv",
    "asic_core/rtl/lsc1_blake3_lifecycle.sv",
    "asic_core/rtl/lsc1_cell_alias_check.sv",
    "asic_core/rtl/lsc1_field_encoder.sv",
    "asic_core/rtl/lsc1_packet_frontend.sv",
    "asic_core/rtl/lsc1_packet_rx.sv",
    "asic_core/rtl/lsc1_packet_tx.sv",
    "asic_core/rtl/lsc1_request_validator.sv",
    "asic_core/rtl/lsc1_response_payload_mux.sv",
    "asic_core/rtl/lsc1_stream_adapter.sv",
    "fpga/ulx3s/build_packet_uart.sh",
    "fpga/ulx3s/uart_bridge.sv",
    "fpga/ulx3s/uart_rx.sv",
    "fpga/ulx3s/uart_tx.sv",
    "fpga/ulx3s/ulx3s_core_pll.sv",
    "fpga/ulx3s/ulx3s_packet_top.sv",
    "fpga/ulx3s/ulx3s_v318_smoke.lpf",
    "tools/atomic_publish.py",
    "tools/portable_build_support.py",
    "tools/source_provenance.py",
})

SUPPORTED_CAD_VERSIONS = {
    "yosys": "Yosys 0.33 (git sha1 2584903a060)",
    "nextpnr-ecp5": '"nextpnr-ecp5" -- Next Generation Place and Route (Version nextpnr-0.11.1)',
    "ecppack": "Project Trellis ecppack Version 1.4-2build4",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_bytes(*args: str) -> bytes:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT)
    except subprocess.CalledProcessError as error:
        raise EvidenceError(f"provenance: unavailable Git object {' '.join(args)}") from error


def require(condition: bool, category: str, message: str) -> None:
    if not condition:
        raise EvidenceError(f"{category}: {message}")


def parse_source_manifest(path: Path) -> tuple[str, dict[str, str]]:
    revision = ""
    matched = ""
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith("revision: "):
            revision = line.removeprefix("revision: ")
        elif line.startswith("inputs-match-revision: "):
            matched = line.removeprefix("inputs-match-revision: ")
        else:
            fields = line.split()
            if len(fields) == 2 and len(fields[0]) == 64:
                entries[fields[1]] = fields[0]
    require(len(revision) == 40 and matched == "yes", "provenance", "source manifest is not pinned to clean revision inputs")
    require(bool(entries), "provenance", "source manifest has no inputs")
    return revision, entries


def verify_load_log(path: Path, expected_command: list[str]) -> None:
    """Require a machine-readable command/exit receipt inside the raw log."""
    commands: list[list[str]] = []
    exit_codes: list[int] = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("loader-command: "):
            try:
                commands.append(shlex.split(line.removeprefix("loader-command: ")))
            except ValueError as error:
                raise EvidenceError("provenance: malformed loader command in load.log") from error
        elif line.startswith("loader-exit-code: "):
            try:
                exit_codes.append(int(line.removeprefix("loader-exit-code: ")))
            except ValueError as error:
                raise EvidenceError("provenance: malformed loader exit code in load.log") from error
    require(commands == [expected_command], "provenance",
            "load.log does not record the exact receipt loader command")
    require(exit_codes == [0], "provenance",
            "load.log does not record one successful loader execution")


def parse_tool_versions(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(len(lines) == 5 and lines[0] == "=== TOOL VERSIONS (LSC-1 PACKET UART) ===",
            "provenance", "tool_versions.txt is malformed or unrelated")
    require(re.fullmatch(r"date: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", lines[4]) is not None,
            "provenance", "tool_versions.txt has a malformed UTC timestamp")
    versions = dict(zip(SUPPORTED_CAD_VERSIONS, lines[1:4]))
    require(versions == SUPPORTED_CAD_VERSIONS, "provenance",
            "tool_versions.txt does not contain the exact supported CAD versions")
    return versions


def verify_checksums(directory: Path, required_bitstream: str) -> None:
    checksum_path = directory / "SHA256SUMS"
    require(checksum_path.is_file(), "provenance", "SHA256SUMS is missing")
    listed: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        fields = line.split()
        require(len(fields) == 2 and len(fields[0]) == 64, "provenance", "malformed SHA256SUMS entry")
        name = fields[1].removeprefix("./")
        candidate = (directory / name).resolve()
        require(candidate.parent == directory.resolve() and candidate.is_file(), "provenance", f"invalid checksum target: {name}")
        require(name not in listed, "provenance", f"duplicate checksum target: {name}")
        listed[name] = fields[0]
        require(digest(candidate) == fields[0], "provenance", f"evidence checksum mismatch: {name}")
    require(required_bitstream in listed, "provenance", "archived bitstream is not listed in SHA256SUMS")
    actual = {x.name for x in directory.iterdir() if x.is_file() and x.name != "SHA256SUMS"}
    require(set(listed) == actual, "provenance", "SHA256SUMS coverage is incomplete or unexpected")


def decode_status(frame: p.ResponseFrame) -> tuple[int, int, int, int, int, int]:
    require(frame.status is p.Status.INFO and len(frame.payload) == 20, "semantic", "pre-STATUS response is not INFO/20")
    b = frame.payload
    return (b[0], int.from_bytes(b[1:5], "little"), int.from_bytes(b[6:10], "little"),
            int.from_bytes(b[11:15], "little"), int.from_bytes(b[15:19], "little"), b[19])


def verify(directory: Path) -> None:
    receipt_path = directory / "receipt.json"
    capture_path = directory / "capture.json"
    source_path = directory / "SOURCE_MANIFEST.txt"
    required_names = {
        "receipt.json", "capture.json", "preflight.json", "SOURCE_MANIFEST.txt",
        "tool_versions.txt", "timing.txt", "yosys.log", "nextpnr.log", "load.log",
        "SHA256SUMS",
    }
    require(all((directory / name).is_file() for name in required_names), "infrastructure", "required evidence file is missing")
    receipt = json.loads(receipt_path.read_text())
    capture = json.loads(capture_path.read_text())

    require(receipt.get("schema") == "lean-silicon.lsc1-09-ulx3s.v1", "provenance", "wrong receipt schema")
    require(receipt.get("physical_capture") is True, "provenance", "receipt does not claim a physical capture")
    source_head = receipt.get("source_head", "")
    require(len(source_head) == 40, "provenance", "source HEAD is not a full object ID")
    require(receipt.get("source_tree") == git("rev-parse", f"{source_head}^{{tree}}"), "provenance", "source tree differs from pinned source commit")
    require(receipt.get("source_clean") is True and receipt.get("source_status_porcelain") == "" and receipt.get("build_inputs_clean") is True,
            "provenance", "source/build cleanliness is not affirmed")
    require(receipt.get("board_revision") == "v3.1.8", "provenance", "board revision is not v3.1.8")
    require(receipt.get("ecp5_idcode") == "0x41113043", "provenance", "ECP5 IDCODE is not LFE5U-85F")
    require(receipt.get("programming") == "SRAM-only", "provenance", "programming mode is not SRAM-only")
    require(receipt.get("uart", {}).get("baud") == 1_000_000 and receipt.get("uart", {}).get("path"), "provenance", "UART path/baud missing")
    require(receipt.get("loader", {}).get("name") == "openFPGALoader" and receipt.get("loader", {}).get("version"), "provenance", "loader version missing")
    archived_versions = parse_tool_versions(directory / "tool_versions.txt")
    require(receipt.get("tools") == archived_versions, "provenance",
            "receipt tools do not exactly match archived supported CAD versions")
    require(receipt.get("clock_constraint_mhz") == 25.0
            and receipt.get("core_clock_mhz") == 10.0,
            "provenance", "tool versions or board/core clock constraint missing")
    require(receipt.get("timestamps", {}).get("reset") and receipt.get("timestamps", {}).get("capture_end"), "provenance", "capture timestamps missing")
    load_command = receipt.get("loader", {}).get("command")
    require(load_command == ["openFPGALoader", "-b", "ulx3s", receipt.get("bitstream", {}).get("file")],
            "provenance", "loader command is not the exact SRAM-only form")
    require(not any("flash" in str(arg).lower() or arg == "-f" for arg in load_command),
            "provenance", "persistent programming option is forbidden")
    verify_load_log(directory / "load.log", load_command)

    preflight = json.loads((directory / "preflight.json").read_text())
    require(preflight.get("schema") == "lean-silicon.ulx3s-preflight.v1", "provenance", "wrong preflight schema")
    require(preflight.get("git", {}).get("commit") == source_head and preflight.get("git", {}).get("clean") is True,
            "provenance", "preflight is not bound to the clean source commit")
    require(preflight.get("jtag", {}).get("idcode") == "0x41113043", "provenance", "preflight JTAG IDCODE mismatch")
    require(any(item.get("vid") == "0x0403" and item.get("pid") == "0x6015" for item in preflight.get("usb", [])),
            "provenance", "preflight lacks the ULX3S USB identity")
    require(any(item.get("path") == receipt["uart"]["path"] for item in preflight.get("uart", {}).get("candidates", [])),
            "provenance", "preflight does not contain the captured UART path")
    timing = (directory / "timing.txt").read_text(errors="replace")
    require("constrained to 25.0 MHz" in timing,
            "provenance", "timing report does not bind the PLL input to the 25 MHz board clock")
    require("Derived frequency constraint of 10.0 MHz for net core_clk" in timing,
            "provenance", "timing report does not bind the full-LSC1 core clock to 10 MHz")
    require("PASS at 10.00 MHz" in timing,
            "provenance", "timing report does not pass the full-LSC1 core clock constraint")

    revision, sources = parse_source_manifest(source_path)
    require(revision == receipt["source_head"], "provenance", "manifest revision differs from receipt")
    require(set(sources) == PACKET_BUILD_INPUTS, "provenance",
            "source manifest does not contain exactly every packet build input")
    for rel, expected in sources.items():
        candidate = (ROOT / rel).resolve()
        require(candidate.is_relative_to(ROOT), "provenance", f"manifest path escapes repository: {rel}")
        require(hashlib.sha256(git_bytes("show", f"{revision}:{rel}")).hexdigest() == expected,
                "provenance", f"source digest mismatch: {rel}")
    artifacts = receipt.get("artifacts", {})
    require(artifacts.get("capture.json") == digest(capture_path), "provenance", "capture digest mismatch")
    require(artifacts.get("SOURCE_MANIFEST.txt") == digest(source_path), "provenance", "source manifest digest mismatch")
    bit_name = receipt.get("bitstream", {}).get("file", "")
    require(isinstance(bit_name, str) and bit_name not in ("", ".", "..")
            and not PurePath(bit_name).is_absolute()
            and not PureWindowsPath(bit_name).is_absolute()
            and len(PurePath(bit_name).parts) == 1
            and len(PureWindowsPath(bit_name).parts) == 1,
            "provenance", "bitstream path is not a direct child of the evidence directory")
    bit_path = (directory / bit_name).resolve()
    require(bit_path.parent == directory.resolve(), "provenance",
            "bitstream path is not a direct child of the evidence directory")
    require(bit_path.is_file(), "provenance", "bitstream is missing")
    require(receipt["bitstream"].get("sha256") == digest(bit_path), "provenance", "bitstream digest mismatch")
    verify_checksums(directory, bit_name)

    require(capture.get("transport") == "ULX3S UART to existing 8-bit ready/valid pins", "semantic", "capture does not bind the pin boundary")
    require(capture.get("reset") == "fresh hardware reset before first byte", "semantic", "fresh reset is not recorded")
    exchanges = capture.get("exchanges", [])
    require(len(exchanges) == 4, "semantic", "trace must contain exactly STATUS, NEGOTIATE, SET, RETIRE")
    requests = [bytes.fromhex(x["request_hex"]) for x in exchanges]
    responses = [bytes.fromhex(x["response_hex"]) for x in exchanges]
    expected_set = p.build_set_constant(txn_id=1, pc=0, fp=0, profile=p.Profile.INTERPRETER_COMPAT,
                                        offset=2, constant=3, cell=p.ABSENT).encode()
    require(requests[0] == p.build_status_query().encode(), "semantic", "first request is not exact STATUS_QUERY")
    require(requests[1] == p.build_negotiate(profile=p.Profile.INTERPRETER_COMPAT).encode(), "semantic", "second request is not exact NEGOTIATE")
    require(requests[2] == expected_set, "semantic", "third request is not exact txn1 pc0 fp0 SET m[2]=3")

    endpoint = p.Lsc1Endpoint()
    decoded: list[p.ResponseFrame] = []
    for index in range(3):
        model_bytes, _ = p.drive(endpoint, requests[index])
        require(model_bytes == responses[index], "semantic", f"response {index} differs from executable model replay")
        decoded.append(p.decode_response(responses[index]))
    require(decode_status(decoded[0]) == (0, 0, 0, 0, 0, 0), "semantic", "pre-STATUS is not INFO/IDLE/txn0/seq0/pc0/fp0/invalid")
    caps = decoded[1]
    require(caps.status is p.Status.OK and len(caps.payload) == 14 and caps.payload[0] == 1 and caps.payload[1] == int(p.Profile.INTERPRETER_COMPAT), "semantic", "NEGOTIATE version/profile subset mismatch")
    require(int.from_bytes(caps.payload[6:10], "little") & 0b010, "semantic", "NEGOTIATE lacks scalar feature subset")
    result = decode_result_payload(decoded[2].payload, expected_txn_id=1)
    require(result == {"txn_id": 1, "next_pc": 1, "next_fp": 0, "writes": [{"address": 2, "value": 3}], "deferred": [], "accesses": [2]}, "semantic", "SET result transition mismatch")
    expected_retire = p.build_retire(txn_id=1, result_crc=p.crc32(decoded[2].payload)).encode()
    require(requests[3] == expected_retire, "semantic", "RETIRE request/CRC does not bind SET result")
    model_bytes, _ = p.drive(endpoint, requests[3])
    require(model_bytes == responses[3], "semantic", "RETIRE response differs from executable model replay")
    retired = p.decode_response(responses[3])
    values = tuple(int.from_bytes(retired.payload[i:i+4], "little") for i in range(0, 16, 4))
    require(retired.status is p.Status.RETIRED and values == (1, 1, 1, 0), "semantic", "RETIRED txn/seq/committed pc/fp mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        verify(args.evidence.resolve())
    except (EvidenceError, ValueError, KeyError, json.JSONDecodeError, p.ProtocolFault) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS source-bound physical ULX3S LSC-1 trace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
