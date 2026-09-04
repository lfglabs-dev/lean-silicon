#!/usr/bin/env python3
"""Bounded host-prepared scalar RESULT_PENDING/STATUS differential.

This is a four-frame executable-model/authored-RTL simulation observation.  It
does not make a Lean-to-RTL, netlist, P&R, FPGA, hardware, LSC-1µ, unbounded,
or end-to-end claim.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from host.lean_compiler_adapter import load
from host.memory import HostMemory
from host.protocol import protocol
from host.runtime import HostRuntime
from tools.lsc1_authored_rtl_contract import RTL

ARTIFACT = ROOT / "host/fixtures/assert_set_xor_mul.program.json"
PATTERNS = [([0, 2, 1], [1, 0, 2]), ([1, 0, 2], [2, 1, 0]),
            ([2, 0, 1], [1, 2, 0]), ([1, 2, 0], [2, 0, 1])]


def run(argv: list[str]) -> str:
    completed = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout + completed.stderr


def scalar_snapshot(endpoint):
    staged = endpoint.staged
    return {
        "state": endpoint.state.name,
        "state_valid": endpoint.state_valid,
        "pc": endpoint.committed_pc,
        "fp": endpoint.committed_fp,
        "retire_seq": endpoint.retire_seq,
        "last_fault": int(endpoint.last_fault),
        "pending": staged is not None,
        "txn_id": staged.txn_id if staged else 0,
        "result_crc": staged.result_crc if staged else 0,
        "next_pc": staged.next_pc if staged else 0,
        "next_fp": staged.next_fp if staged else 0,
        "writes": tuple((write.address, write.value) for write in staged.writes)
                  if staged else (),
    }


class StatusRecordingRuntime(HostRuntime):
    """Insert STATUS after scalar RESULT while retaining HostRuntime RETIRE."""

    def __init__(self, *args, **kwargs):
        self.exchanges = []
        self.snapshots = []
        self.status_reply = None
        self._inserting_status = False
        super().__init__(*args, **kwargs)

    def _exchange(self, frame):
        index = len(self.exchanges)
        if index >= len(PATTERNS):
            raise SystemExit("host emitted more than the required four frames")
        rx_gaps, tx_gaps = PATTERNS[index]
        raw, cycles = protocol.drive(self.endpoint, frame.encode(),
                                     rx_gaps=rx_gaps, tx_gaps=tx_gaps)
        self.lane_cycles += cycles
        reply = protocol.decode_response(raw)
        self.exchanges.append((frame, raw))
        self.snapshots.append(scalar_snapshot(self.endpoint))
        if (not self._inserting_status and frame.opcode is protocol.Opcode.SET_CONSTANT
                and reply.status is protocol.Status.OK):
            self._inserting_status = True
            self.status_reply = self._exchange(protocol.build_status_query())
            self._inserting_status = False
        return reply


def host_trace():
    program = load(ARTIFACT)
    runtime = StatusRecordingRuntime(
        program, memory=HostMemory.with_public_input(1, 0), session_epoch=1,
    )
    record = runtime.step()
    if [frame.opcode for frame, _ in runtime.exchanges] != [
            protocol.Opcode.NEGOTIATE, protocol.Opcode.SET_CONSTANT,
            protocol.Opcode.STATUS_QUERY, protocol.Opcode.RETIRE]:
        raise SystemExit("host did not emit exactly NEGOTIATE, SET, STATUS, RETIRE")
    set_frame = runtime.exchanges[1][0]
    decoded = protocol.decode_request_payload(set_frame.opcode, set_frame.payload)
    if (record.txn_id, decoded.txn_id, decoded.pc, decoded.fp,
            decoded.offsets, decoded.constant) != (1, 1, 0, 0, (2,), 3):
        raise SystemExit("fixture step 0 was not txn 1 proposing m[2]=3, pc=1, fp=0")
    info = runtime.status_reply
    expected_info = (bytes([1]) + protocol.u32le(1) + bytes([protocol.Status.OK])
                     + protocol.u32le(0) + bytes([protocol.Status.OK])
                     + protocol.u32le(0) + protocol.u32le(0) + bytes([0]))
    if info.status is not protocol.Status.INFO or info.payload != expected_info:
        raise SystemExit(f"model STATUS INFO differs: {info.payload.hex()}")
    before, after = runtime.snapshots[1], runtime.snapshots[2]
    if before != after or after != {
            "state": "RESULT_PENDING", "state_valid": False, "pc": 0, "fp": 0,
            "retire_seq": 0, "last_fault": 0, "pending": True, "txn_id": 1,
            "result_crc": before["result_crc"], "next_pc": 1, "next_fp": 0,
            "writes": ((2, 3),)}:
        raise SystemExit(f"model STATUS changed staged scalar result: {before} -> {after}")
    final = runtime.snapshots[3]
    if (final["state"], final["state_valid"], final["pc"], final["fp"],
            final["retire_seq"], final["pending"], runtime.memory.read(2),
            record.status) != ("IDLE", True, 1, 0, 1, False, 3, "OK"):
        raise SystemExit(f"model RETIRE did not commit exactly once: {final}")
    return runtime.exchanges


def normalized_expected(exchanges):
    expected = []
    for frame, raw in exchanges:
        if frame.opcode is protocol.Opcode.NEGOTIATE:
            reply = protocol.decode_response(raw)
            payload = bytearray(reply.payload)
            payload[6:10] = protocol.u32le(protocol.DEVICE_FEATURES & ~1)
            raw = protocol.ResponseFrame(reply.status, bytes(payload)).encode()
        expected.append(raw)
    return expected


def replay_rtl(exchanges, frontend: Path | None):
    with tempfile.TemporaryDirectory(prefix="lsc1-scalar-status-") as name:
        directory = Path(name)
        sources = [frontend if frontend and path.name == "lsc1_packet_frontend.sv" else path
                   for path in RTL]
        simulator = directory / "packet-vector.vvp"
        run(["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(simulator), *(str(path) for path in sources)])
        entries = []
        for index, (frame, _) in enumerate(exchanges):
            path = directory / f"request-{index}.hex"
            path.write_text("".join(f"{byte:02x}\n" for byte in frame.encode()))
            entries.append(f"{path} {len(frame.encode())}\n")
        manifest = directory / "requests.txt"
        manifest.write_text("".join(entries))
        output = run(["vvp", str(simulator), f"+MANIFEST={manifest}",
                      "+V3_FINITE_STALLS"])
    actual = [bytes.fromhex(line.removeprefix("RESPONSE "))
              for line in output.splitlines() if line.startswith("RESPONSE ")]
    if actual != normalized_expected(exchanges):
        raise SystemExit("authored RTL response bytes differ from executable model")
    scalar = re.findall(
        r"RTL_SCALAR_RESULT pending=(\d+) txn_id=([0-9a-f]+) result_crc=([0-9a-f]+) "
        r"next_pc=([0-9a-f]+) next_fp=([0-9a-f]+) write_count=(\d+) "
        r"write_address=([0-9a-f]+) write_value=([0-9a-f]+)", output)
    states = re.findall(r"RTL_STATE valid=(\d+) pc=([0-9a-f]+) fp=([0-9a-f]+) "
                        r"retire_seq=([0-9a-f]+) result_pending=(\d+)", output)
    counts = re.search(r"RTL_COUNTS rx_blocked=(\d+) tx_blocked=(\d+) done=(\d+)", output)
    stability = re.search(r"RTL_V3_STABILITY rx_checks=(\d+) tx_checks=(\d+)", output)
    transactions = re.findall(
        r"RTL_TRANSACTION request_opcode=[0-9a-f]+ origin_opcode=[0-9a-f]+ "
        r"status=[0-9a-f]+ rx_blocked=\d+ tx_blocked=\d+ done=(\d+)", output)
    if (len(scalar) != 4 or len(states) != 4 or len(transactions) != 4
            or counts is None or stability is None):
        raise SystemExit("authored RTL trace markers are incomplete")
    staged = tuple(int(value, 16) for value in scalar[1])
    if staged != (1, 1, staged[2], 1, 0, 1, 2, 3) or scalar[2] != scalar[1]:
        raise SystemExit(f"RTL STATUS changed staged scalar fields: {scalar[1]} -> {scalar[2]}")
    if tuple(int(value, 16) for value in states[2]) != (0, 0, 0, 0, 1):
        raise SystemExit(f"RTL STATUS changed pending/committed state: {states[2]}")
    if tuple(int(value, 16) for value in states[3]) != (1, 1, 0, 1, 0):
        raise SystemExit(f"RTL RETIRE did not commit exactly once: {states[3]}")
    if tuple(int(value) for value in transactions) != (0, 0, 0, 1):
        raise SystemExit(f"STATUS produced DONE or RETIRE did not: {transactions}")
    if int(counts.group(1)) == 0 or int(counts.group(2)) == 0 or int(counts.group(3)) != 1:
        raise SystemExit(f"finite stalls/exactly-once DONE not observed: {counts.groups()}")
    if int(stability.group(1)) == 0 or int(stability.group(2)) == 0:
        raise SystemExit(f"blocked-byte stability not exercised: {stability.groups()}")


def verify(frontend: Path | None = None):
    exchanges = host_trace()
    replay_rtl(exchanges, frontend)
    print("LSC1_SCALAR_STATUS_HOST_BOUNDARY_PASS frames=NEGOTIATE,SET_CONSTANT,STATUS_QUERY,RETIRE txn_id=1 info=RESULT_PENDING,OK,retire_seq0,fault0,committed0 status_preserves_scalar=PASS retire_commits_once=PASS model_rtl_bytes=MATCH negotiate_feature_mask=NORMALIZED finite_stalls=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", type=Path)
    verify(parser.parse_args().frontend)
