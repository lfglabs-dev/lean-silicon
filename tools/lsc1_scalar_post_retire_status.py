#!/usr/bin/env python3
"""Finite full-LSC-1 scalar RETIRE/STATUS model/authored-RTL differential."""

from __future__ import annotations

import argparse
import re
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
from tools.lsc1_scalar_status_host_boundary import normalized_expected, run, scalar_snapshot

ARTIFACT = ROOT / "host/fixtures/assert_set_xor_mul.program.json"
PATTERNS = [([0, 2, 1], [1, 0, 2]), ([1, 0, 2], [2, 1, 0]),
            ([2, 0, 1], [1, 2, 0]), ([1, 2, 0], [2, 0, 1])]


class PostRetireStatusRuntime(HostRuntime):
    """Append STATUS immediately after the host runtime's matching RETIRE."""

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
        if (not self._inserting_status and frame.opcode is protocol.Opcode.RETIRE
                and reply.status is protocol.Status.RETIRED):
            self._inserting_status = True
            self.status_reply = self._exchange(protocol.build_status_query())
            self._inserting_status = False
        return reply


def host_trace():
    memory = HostMemory.with_public_input(1, 0)
    runtime = PostRetireStatusRuntime(load(ARTIFACT), memory=memory, session_epoch=1)
    record = runtime.step()
    if [frame.opcode for frame, _ in runtime.exchanges] != [
            protocol.Opcode.NEGOTIATE, protocol.Opcode.SET_CONSTANT,
            protocol.Opcode.RETIRE, protocol.Opcode.STATUS_QUERY]:
        raise SystemExit("host did not emit exactly NEGOTIATE, SET, RETIRE, STATUS")
    decoded = protocol.decode_request_payload(
        runtime.exchanges[1][0].opcode, runtime.exchanges[1][0].payload)
    if (record.txn_id, decoded.txn_id, decoded.pc, decoded.fp,
            decoded.offsets, decoded.constant) != (1, 1, 0, 0, (2,), 3):
        raise SystemExit("fixture step 0 was not txn 1 proposing m[2]=3, pc=1, fp=0")
    expected_info = (bytes([0]) + protocol.u32le(0) + bytes([protocol.Status.RETIRED])
                     + protocol.u32le(1) + bytes([protocol.Status.OK])
                     + protocol.u32le(1) + protocol.u32le(0) + bytes([1]))
    if (runtime.status_reply.status is not protocol.Status.INFO
            or runtime.status_reply.payload != expected_info):
        raise SystemExit(f"model post-RETIRE STATUS INFO differs: "
                         f"{runtime.status_reply.payload.hex()}")
    retired, queried = runtime.snapshots[2:4]
    expected_state = {
        "state": "IDLE", "state_valid": True, "pc": 1, "fp": 0,
        "retire_seq": 1, "last_fault": 0, "pending": False, "txn_id": 0,
        "result_crc": 0, "next_pc": 0, "next_fp": 0, "writes": (),
    }
    if retired != expected_state or queried != retired or memory.read(2) != 3:
        raise SystemExit(f"model STATUS changed post-RETIRE state: {retired} -> {queried}")
    if record.status != "OK":
        raise SystemExit(f"host did not complete matching RETIRE: {record.status}")
    return runtime.exchanges


def replay_rtl(exchanges, payload_mux: Path | None):
    with tempfile.TemporaryDirectory(prefix="lsc1-scalar-post-retire-") as name:
        directory = Path(name)
        sources = [payload_mux if payload_mux and path.name ==
                   "lsc1_response_payload_mux.sv" else path for path in RTL]
        simulator = directory / "packet-vector.vvp"
        run(["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(simulator), *(str(path) for path in sources)])
        entries = []
        for index, (frame, _) in enumerate(exchanges):
            request = directory / f"request-{index}.hex"
            request.write_text("".join(f"{byte:02x}\n" for byte in frame.encode()))
            entries.append(f"{request} {len(frame.encode())}\n")
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
    transactions = re.findall(
        r"RTL_TRANSACTION request_opcode=[0-9a-f]+ origin_opcode=[0-9a-f]+ "
        r"status=[0-9a-f]+ rx_blocked=\d+ tx_blocked=\d+ done=(\d+)", output)
    counts = re.search(r"RTL_COUNTS rx_blocked=(\d+) tx_blocked=(\d+) done=(\d+)", output)
    stability = re.search(r"RTL_V3_STABILITY rx_checks=(\d+) tx_checks=(\d+)", output)
    if (len(scalar) != 4 or len(states) != 4 or len(transactions) != 4
            or counts is None or stability is None):
        raise SystemExit("authored RTL trace markers are incomplete")
    if states[2] != states[3] or tuple(int(v, 16) for v in states[3]) != (1, 1, 0, 1, 0):
        raise SystemExit(f"RTL STATUS changed post-RETIRE committed state: {states[2:4]}")
    if scalar[2] != scalar[3] or int(scalar[3][0], 16) != 0:
        raise SystemExit(f"RTL STATUS changed post-RETIRE staged state: {scalar[2:4]}")
    if tuple(int(value) for value in transactions) != (0, 0, 1, 0):
        raise SystemExit(f"STATUS emitted DONE or RETIRE DONE count differs: {transactions}")
    if (int(counts.group(1)) == 0 or int(counts.group(2)) == 0
            or int(counts.group(3)) != 1):
        raise SystemExit(f"finite stalls/exactly-once DONE not observed: {counts.groups()}")
    if int(stability.group(1)) == 0 or int(stability.group(2)) == 0:
        raise SystemExit(f"blocked-beat stability not exercised: {stability.groups()}")


def verify(payload_mux: Path | None = None):
    exchanges = host_trace()
    replay_rtl(exchanges, payload_mux)
    print("LSC1_SCALAR_POST_RETIRE_STATUS_PASS "
          "frames=NEGOTIATE,SET_CONSTANT,RETIRE,STATUS_QUERY txn_id=1 "
          "info=IDLE,txn0,RETIRED,retire_seq1,fault_OK,pc1,fp0,state_valid1 "
          "post_retire_state_preserved=PASS done_exactly_once=PASS "
          "model_rtl_bytes=MATCH negotiate_feature_mask=NORMALIZED "
          "finite_rx_tx_stalls=PASS blocked_beat_stability=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-mux", type=Path)
    verify(parser.parse_args().payload_mux)
