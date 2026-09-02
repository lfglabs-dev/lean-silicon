#!/usr/bin/env python3
"""Finite first-SET RETIRE_MISMATCH discard/recovery regression.

This is one host-prepared full-LSC-1 protocol-v1 lifecycle from the checked-in
fixture.  It is executable-model and authored-RTL simulation evidence only.
It makes no Lean, netlist, P&R, FPGA, hardware, LSC-1u, or unbounded claim.
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
from host.errors import ProtocolViolation
from host.memory import HostMemory
from host.protocol import protocol
from host.runtime import HostRuntime, decode_result_payload
from tools.lsc1_authored_rtl_contract import RTL

ARTIFACT = ROOT / "host/fixtures/assert_set_xor_mul.program.json"


def run(argv: list[str]) -> str:
    completed = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout + completed.stderr


class CorruptFirstRetireRuntime(HostRuntime):
    """Record real host preparation while flipping one RETIRE bit."""

    def __init__(self, *args, corrupt_txn_id=False, **kwargs):
        self.frames: list[protocol.RequestFrame] = []
        self.replies: list[protocol.ResponseFrame] = []
        self.host_retire: protocol.RequestFrame | None = None
        self.corrupt_txn_id = corrupt_txn_id
        super().__init__(*args, **kwargs)

    def _exchange(self, frame):
        sent = frame
        if protocol.Opcode(frame.opcode) is protocol.Opcode.RETIRE:
            if self.host_retire is not None:
                raise AssertionError("bounded lane expected exactly one host RETIRE")
            self.host_retire = frame
            payload = bytearray(frame.payload)
            payload[0 if self.corrupt_txn_id else 4] ^= 1
            sent = protocol.RequestFrame(frame.opcode, bytes(payload))
        self.frames.append(sent)
        reply = super()._exchange(sent)
        self.replies.append(reply)
        return reply


def record_host_frames(*, corrupt_txn_id: bool):
    program = load(ARTIFACT)
    initial = HostMemory.with_public_input(1, 0)
    runtime = CorruptFirstRetireRuntime(
        program, memory=initial, session_epoch=1,
        endpoint=protocol.Lsc1Endpoint(), corrupt_txn_id=corrupt_txn_id,
    )
    violation = None
    try:
        record = runtime.step()
    except ProtocolViolation as error:
        violation = error
        record = None
    if (program.at(program.pc0).kind != "Set" or len(runtime.frames) < 2 or
            protocol.Opcode(runtime.frames[1].opcode) is not protocol.Opcode.SET_CONSTANT):
        raise SystemExit("fixture no longer begins with SET_CONSTANT")
    if corrupt_txn_id:
        if violation is None or "retire fault echoed txn_id 0, expected 1" not in str(violation):
            raise SystemExit(f"host did not reject mismatched echo as ProtocolViolation: {violation}")
    elif record is None or record.fault != "RETIRE_MISMATCH":
        raise SystemExit(f"host did not observe RETIRE_MISMATCH: {record}")
    if (runtime.memory.cells != {0: 1, 1: 0} or runtime.memory.access_counts or
            runtime.memory.deferred or (runtime.pc, runtime.fp) != (0, 0)):
        raise SystemExit("host committed the proposed SET write/scalar transition")
    endpoint = runtime.endpoint
    if (endpoint.state.name != "IDLE" or endpoint.staged is not None or
            endpoint.state_valid or endpoint.committed_pc != 0 or
            endpoint.committed_fp != 0 or endpoint.retire_seq != 0):
        raise SystemExit("host-bound endpoint did not discard the staged transition")
    if runtime.host_retire is None or len(runtime.frames) != 3:
        raise SystemExit("host did not record NEGOTIATE, SET, corrupted RETIRE")
    corrupt = runtime.frames[-1]
    original = runtime.host_retire
    if (int.from_bytes(original.payload[:4], "little") != 1 or
            int.from_bytes(corrupt.payload[:4], "little") !=
            (0 if corrupt_txn_id else 1)):
        raise SystemExit("host RETIRE transaction IDs differ from the bounded case")
    differing = sum((left ^ right).bit_count()
                    for left, right in zip(corrupt.payload, original.payload, strict=True))
    unchanged = (corrupt.payload[4:] == original.payload[4:] if corrupt_txn_id
                 else corrupt.payload[:4] == original.payload[:4])
    if differing != 1 or not unchanged:
        field = "txn_id" if corrupt_txn_id else "result_crc"
        raise SystemExit(f"corrupted RETIRE is not exactly one {field} bit flip")
    fault = runtime.replies[-1]
    expected_fault = protocol.u32le(0 if corrupt_txn_id else 1) + bytes(
        [1 if corrupt_txn_id else 2])
    if (fault.status is not protocol.Status.RETIRE_MISMATCH or
            fault.payload != expected_fault):
        raise SystemExit("endpoint did not return the exact RETIRE_MISMATCH echo/detail")
    # RETIRE_MISMATCH discards the endpoint transaction. Re-stage the exact same
    # host-prepared SET frame, then recover with the untouched host RETIRE.
    frames = [*runtime.frames, runtime.frames[1], original]
    return frames


def replay_model(frames, *, corrupt_txn_id: bool):
    endpoint = protocol.Lsc1Endpoint()
    responses = []
    states = []
    for frame in frames:
        raw, _ = protocol.drive(endpoint, frame.encode())
        responses.append(raw)
        states.append((endpoint.state_valid, endpoint.committed_pc,
                       endpoint.committed_fp, endpoint.retire_seq,
                       endpoint.state.name))
    statuses = [protocol.decode_response(raw).status for raw in responses]
    expected = [protocol.Status.OK, protocol.Status.OK,
                protocol.Status.RETIRE_MISMATCH, protocol.Status.OK,
                protocol.Status.RETIRED]
    if statuses != expected:
        raise SystemExit(f"model statuses differ: {statuses}")
    mismatch = protocol.decode_response(responses[2])
    expected_fault = protocol.u32le(0 if corrupt_txn_id else 1) + bytes(
        [1 if corrupt_txn_id else 2])
    if mismatch.payload != expected_fault:
        raise SystemExit("model RETIRE_MISMATCH echo/detail differs")
    result = protocol.decode_response(responses[1])
    decoded = protocol.decode_request_payload(frames[1].opcode, frames[1].payload)
    result_payload = decode_result_payload(result.payload, expected_txn_id=1)
    # The first fixture instruction proposes fp[2] := 3 and pc := 1.
    if decoded.offsets != (2,) or decoded.constant != 3:
        raise SystemExit("first host-prepared SET operands changed")
    if result_payload["writes"] != [{"address": 2, "value": 3}]:
        raise SystemExit("first SET result no longer proposes the expected write")
    if states[2] != (False, 0, 0, 0, "IDLE"):
        raise SystemExit(f"model committed corrupted RETIRE: {states[2]}")
    if states[4] != (True, 1, 0, 1, "IDLE"):
        raise SystemExit(f"model did not recover on unmodified RETIRE: {states[4]}")
    return responses, states


def replay_rtl(frames, model_responses):
    with tempfile.TemporaryDirectory(prefix="lsc1-retire-mismatch-") as name:
        directory = Path(name)
        simulator = directory / "packet-vector.vvp"
        run(["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(simulator), *(str(path) for path in RTL)])
        manifest = directory / "requests.txt"
        entries = []
        for index, frame in enumerate(frames):
            path = directory / f"request-{index}.hex"
            path.write_text("".join(f"{byte:02x}\n" for byte in frame.encode()))
            entries.append(f"{path} {len(frame.encode())}\n")
        manifest.write_text("".join(entries))
        output = run(["vvp", str(simulator), f"+MANIFEST={manifest}"])
    actual = [bytes.fromhex(line.removeprefix("RESPONSE "))
              for line in output.splitlines() if line.startswith("RESPONSE ")]
    expected = list(model_responses)
    negotiate = protocol.decode_response(expected[0])
    payload = bytearray(negotiate.payload)
    payload[6:10] = protocol.u32le(protocol.DEVICE_FEATURES & ~1)
    expected[0] = protocol.ResponseFrame(negotiate.status, bytes(payload)).encode()
    if actual != expected:
        raise SystemExit("authored RTL response bytes differ from executable model")
    states = [tuple(int(value, 16) for value in match)
              for match in re.findall(
                  r"RTL_STATE valid=(\d+) pc=([0-9a-fA-F]+) fp=([0-9a-fA-F]+) "
                  r"retire_seq=([0-9a-fA-F]+) result_pending=(\d+)", output)]
    if len(states) != len(frames):
        raise SystemExit("authored RTL did not report one state per recorded frame")
    if states[2] != (0, 0, 0, 0, 0):
        raise SystemExit(f"authored RTL committed corrupted RETIRE: {states[2]}")
    if states[4] != (1, 1, 0, 1, 0):
        raise SystemExit(f"authored RTL did not recover on unmodified RETIRE: {states[4]}")
    return states


def verify(*, corrupt_txn_id: bool = False) -> None:
    frames = record_host_frames(corrupt_txn_id=corrupt_txn_id)
    model_responses, _ = replay_model(frames, corrupt_txn_id=corrupt_txn_id)
    replay_rtl(frames, model_responses)
    field = "txn_id" if corrupt_txn_id else "result_crc"
    print(
        "LSC1_RETIRE_MISMATCH_HOST_BOUNDARY_PASS "
        f"fixture_step=0 opcode=SET_CONSTANT {field}_bit_flips=1 "
        "model=DISCARD_THEN_COMMIT authored_rtl=DISCARD_THEN_COMMIT"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--txn-id", action="store_true")
    verify(corrupt_txn_id=parser.parse_args().txn_id)
