#!/usr/bin/env python3
"""Bounded host-prepared BLAKE3 RESULT_PENDING/STATUS differential.

This is a four-frame executable-model/authored-RTL simulation observation.  It
does not involve or make claims about Lean, a netlist, P&R, FPGA, hardware,
LSC-1u, unbounded refinement, or end-to-end verification.
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

from host.blake3_service import ModelServiceAdapter, SoftwareBlake3HostService
from host.lean_compiler_adapter import Operation, Program
from host.memory import HostMemory
from host.protocol import protocol
from host.runtime import HostRuntime
from tools.lsc1_authored_rtl_contract import RTL

TXN_ID = 0x10203040
SESSION_EPOCH = 0x0102030405060708


def run(argv: list[str]) -> str:
    completed = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout + completed.stderr


def host_prepared_frames():
    """Use HostRuntime's full-LSC-1 preparation path for one BLAKE3 slot."""
    operation = Operation(0, "Blake3", {
        "ins": [0, 1, 2, 3], "cv": 4, "out": 6,
        "metadata": (64 << 64) | (1 << 96),
    })
    program = Program((operation,), 0, 0, (), "bounded BLAKE3 fixture",
                      "c308034ab78619b39a59d26f3dc60e7df5b52649", "", None)
    memory = HostMemory(cells={index: index + 1 for index in range(6)})
    runtime = HostRuntime(program, memory=memory, session_epoch=SESSION_EPOCH)
    runtime.txn_id = TXN_ID - 1
    request, addresses, branch = runtime._prepare(operation)
    if (addresses != list(range(8)) or branch is not None or
            protocol.Opcode(request.opcode) is not protocol.Opcode.BLAKE3_REQUEST):
        raise SystemExit("host did not prepare the expected full-LSC-1 BLAKE3 request")

    endpoint = protocol.Lsc1Endpoint()
    required_raw, _ = protocol.drive(endpoint, request.encode(),
                                     rx_gaps=[0, 2, 1], tx_gaps=[1, 0, 2])
    required_reply = protocol.decode_response(required_raw)
    adapter = ModelServiceAdapter(SESSION_EPOCH)
    required = adapter.accept_required(required_reply.payload)
    response = adapter.compute(required, service=SoftwareBlake3HostService().compress)
    service = adapter.to_v1(response)
    result_raw, _ = protocol.drive(endpoint, service.encode(),
                                   rx_gaps=[1, 0, 2], tx_gaps=[2, 1, 0])
    result = protocol.decode_response(result_raw)
    status = protocol.build_status_query()
    retire = protocol.build_retire(txn_id=TXN_ID,
                                   result_crc=protocol.crc32(result.payload))
    return [request, service, status, retire]


def replay_model(frames):
    endpoint = protocol.Lsc1Endpoint()
    responses = []
    snapshots = []
    patterns = [([0, 2, 1], [1, 0, 2]), ([1, 0, 2], [2, 1, 0]),
                ([2, 0, 1], [1, 2, 0]), ([1, 2, 0], [2, 0, 1])]
    staged_result = None
    for index, (frame, (rx_gaps, tx_gaps)) in enumerate(zip(frames, patterns, strict=True)):
        raw, _ = protocol.drive(endpoint, frame.encode(), rx_gaps=rx_gaps,
                                tx_gaps=tx_gaps)
        responses.append(raw)
        snapshots.append((endpoint.state.name, endpoint.staged, endpoint.state_valid,
                          endpoint.committed_pc, endpoint.committed_fp,
                          endpoint.retire_seq, endpoint.last_fault))
        if index == 1:
            staged_result = endpoint.staged
        if index == 2 and endpoint.staged != staged_result:
            raise SystemExit("model STATUS did not preserve the staged BLAKE3 result")
    statuses = [protocol.decode_response(raw).status for raw in responses]
    if statuses != [protocol.Status.SERVICE_REQUIRED, protocol.Status.OK,
                    protocol.Status.INFO, protocol.Status.RETIRED]:
        raise SystemExit(f"model status sequence differs: {statuses}")
    info = protocol.decode_response(responses[2]).payload
    expected_info = (bytes([1]) + protocol.u32le(TXN_ID) + bytes([protocol.Status.OK]) +
                     protocol.u32le(0) + bytes([protocol.Status.OK]) +
                     protocol.u32le(0) + protocol.u32le(0) + bytes([0]))
    if info != expected_info:
        raise SystemExit(f"model INFO differs: {info.hex()} != {expected_info.hex()}")
    if snapshots[2][0] != "RESULT_PENDING" or snapshots[2][2:6] != (False, 0, 0, 0):
        raise SystemExit(f"model STATUS changed committed state: {snapshots[2]}")
    if snapshots[3][0] != "IDLE" or snapshots[3][2:6] != (True, 1, 0, 1):
        raise SystemExit(f"model RETIRE did not commit exactly once: {snapshots[3]}")
    return responses


def replay_rtl(frames, expected, frontend: Path | None):
    with tempfile.TemporaryDirectory(prefix="lsc1-blake3-status-") as name:
        directory = Path(name)
        sources = [frontend if frontend and path.name == "lsc1_packet_frontend.sv" else path
                   for path in RTL]
        simulator = directory / "packet-vector.vvp"
        run(["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(simulator), *(str(path) for path in sources)])
        entries = []
        for index, frame in enumerate(frames):
            path = directory / f"request-{index}.hex"
            path.write_text("".join(f"{byte:02x}\n" for byte in frame.encode()))
            entries.append(f"{path} {len(frame.encode())}\n")
        manifest = directory / "requests.txt"
        manifest.write_text("".join(entries))
        output = run(["vvp", str(simulator), f"+MANIFEST={manifest}",
                      "+V3_FINITE_STALLS"])
    actual = [bytes.fromhex(line.removeprefix("RESPONSE "))
              for line in output.splitlines() if line.startswith("RESPONSE ")]
    if actual != expected:
        raise SystemExit("authored RTL response bytes differ from executable model")
    states = re.findall(r"RTL_STATE valid=(\d+) pc=([0-9a-f]+) fp=([0-9a-f]+) "
                        r"retire_seq=([0-9a-f]+) result_pending=(\d+)", output)
    blake = re.findall(r"RTL_BLAKE_RESULT pending=(\d+) txn_id=([0-9a-f]+) "
                       r"result_crc=([0-9a-f]+) next_pc=([0-9a-f]+) next_fp=([0-9a-f]+) "
                       r"last_status=([0-9a-f]+) last_fault=([0-9a-f]+)", output)
    counts = re.search(r"RTL_COUNTS rx_blocked=(\d+) tx_blocked=(\d+) done=(\d+)", output)
    stability = re.search(r"RTL_V3_STABILITY rx_checks=(\d+) tx_checks=(\d+)", output)
    if len(states) != 4 or len(blake) != 4 or counts is None or stability is None:
        raise SystemExit("authored RTL trace markers are incomplete")
    if tuple(int(value, 16) for value in states[2]) != (0, 0, 0, 0, 1):
        raise SystemExit(f"RTL STATUS changed pending/committed state: {states[2]}")
    if (int(blake[2][0]), int(blake[2][1], 16), int(blake[2][5], 16),
            int(blake[2][6], 16)) != (1, TXN_ID, int(protocol.Status.INFO), 0):
        raise SystemExit(f"RTL STATUS did not preserve the staged BLAKE3 result: {blake[2]}")
    if blake[1][:5] != blake[2][:5]:
        raise SystemExit(f"RTL STATUS changed staged BLAKE3 fields: {blake[1]} -> {blake[2]}")
    if tuple(int(value, 16) for value in states[3]) != (1, 1, 0, 1, 0):
        raise SystemExit(f"RTL RETIRE did not commit exactly once: {states[3]}")
    if int(counts.group(1)) == 0 or int(counts.group(2)) == 0 or int(counts.group(3)) != 1:
        raise SystemExit(f"finite stalls/exactly-once DONE not observed: {counts.groups()}")
    if int(stability.group(1)) == 0 or int(stability.group(2)) == 0:
        raise SystemExit(f"stalled beat stability not exercised: {stability.groups()}")


def verify(frontend: Path | None = None):
    frames = host_prepared_frames()
    expected = replay_model(frames)
    replay_rtl(frames, expected, frontend)
    print("LSC1_BLAKE3_STATUS_HOST_BOUNDARY_PASS frames=BLAKE3_REQUEST,SERVICE_RESPONSE,STATUS_QUERY,RETIRE txn_id=10203040 info=RESULT_PENDING,OK,retire_seq0,fault0,committed0 status_preserves_result=PASS retire_commits_once=PASS model_rtl_bytes=MATCH finite_stalls=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", type=Path)
    verify(parser.parse_args().frontend)
