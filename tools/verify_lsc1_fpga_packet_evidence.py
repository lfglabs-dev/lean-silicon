#!/usr/bin/env python3
"""Verify one source-bound physical ULX3S LSC-1 SET/RETIRE evidence packet."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
sys.path.insert(0, str(ROOT))
import lsc1_transaction as p  # noqa: E402
from host.runtime import decode_result_payload  # noqa: E402


class EvidenceError(RuntimeError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


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


def decode_status(frame: p.ResponseFrame) -> tuple[int, int, int, int, int, int]:
    require(frame.status is p.Status.INFO and len(frame.payload) == 20, "semantic", "pre-STATUS response is not INFO/20")
    b = frame.payload
    return (b[0], int.from_bytes(b[1:5], "little"), int.from_bytes(b[6:10], "little"),
            int.from_bytes(b[11:15], "little"), int.from_bytes(b[15:19], "little"), b[19])


def verify(directory: Path) -> None:
    receipt_path = directory / "receipt.json"
    capture_path = directory / "capture.json"
    source_path = directory / "SOURCE_MANIFEST.txt"
    require(all(x.is_file() for x in (receipt_path, capture_path, source_path)), "infrastructure", "required evidence file is missing")
    receipt = json.loads(receipt_path.read_text())
    capture = json.loads(capture_path.read_text())

    require(receipt.get("schema") == "lean-silicon.lsc1-09-ulx3s.v1", "provenance", "wrong receipt schema")
    require(receipt.get("physical_capture") is True, "provenance", "receipt does not claim a physical capture")
    require(receipt.get("source_head") == git("rev-parse", "HEAD"), "provenance", "source HEAD differs from verifier checkout")
    require(receipt.get("source_tree") == git("rev-parse", "HEAD^{tree}"), "provenance", "source tree differs from verifier checkout")
    require(receipt.get("source_clean") is True and receipt.get("build_inputs_clean") is True, "provenance", "source/build cleanliness is not affirmed")
    require(receipt.get("board_revision") == "v3.1.8", "provenance", "board revision is not v3.1.8")
    require(receipt.get("ecp5_idcode") == "0x41113043", "provenance", "ECP5 IDCODE is not LFE5U-85F")
    require(receipt.get("programming") == "SRAM-only", "provenance", "programming mode is not SRAM-only")
    require(receipt.get("uart", {}).get("baud") == 1_000_000 and receipt.get("uart", {}).get("path"), "provenance", "UART path/baud missing")
    require(receipt.get("loader", {}).get("name") == "openFPGALoader" and receipt.get("loader", {}).get("version"), "provenance", "loader version missing")
    require(receipt.get("tools") and receipt.get("clock_constraint_mhz") == 25.0, "provenance", "tool versions or clock constraint missing")
    require(receipt.get("timestamps", {}).get("reset") and receipt.get("timestamps", {}).get("capture_end"), "provenance", "capture timestamps missing")

    revision, sources = parse_source_manifest(source_path)
    require(revision == receipt["source_head"], "provenance", "manifest revision differs from receipt")
    for rel, expected in sources.items():
        candidate = (ROOT / rel).resolve()
        require(candidate.is_relative_to(ROOT) and candidate.is_file(), "provenance", f"manifest input unavailable: {rel}")
        require(digest(candidate) == expected, "provenance", f"source digest mismatch: {rel}")
    artifacts = receipt.get("artifacts", {})
    require(artifacts.get("capture.json") == digest(capture_path), "provenance", "capture digest mismatch")
    require(artifacts.get("SOURCE_MANIFEST.txt") == digest(source_path), "provenance", "source manifest digest mismatch")
    bit_name = receipt.get("bitstream", {}).get("file", "")
    bit_path = directory / bit_name
    require(bit_path.is_file(), "provenance", "bitstream is missing")
    require(receipt["bitstream"].get("sha256") == digest(bit_path), "provenance", "bitstream digest mismatch")

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
