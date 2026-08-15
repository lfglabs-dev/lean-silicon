#!/usr/bin/env python3
"""Derive the finite Lean/authored-RTL relation from authored-RTL traces."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim import lsc1_transaction as protocol
RTL = [ROOT / path for path in (
    "asic_core/rtl/lsc1_packet_rx.sv",
    "asic_core/rtl/lsc1_packet_tx.sv",
    "asic_core/rtl/gf2n_mul_bitstream.sv",
    "asic_core/rtl/gf128_mul_bitstream.sv",
    "asic_core/rtl/leanvm_b_stream_alu.sv",
    "asic_core/rtl/lsc1_stream_adapter.sv",
    "asic_core/rtl/lsc1_field_encoder.sv",
    "asic_core/rtl/lsc1_packet_frontend.sv",
    "test/packet_frontend/tb_lsc1_packet_vector.sv",
)]


def run(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout + completed.stderr


def expected_exchange(endpoint: protocol.Lsc1Endpoint,
                      frames: list[protocol.RequestFrame]) -> list[bytes]:
    return [protocol.drive(endpoint, frame.encode())[0] for frame in frames]


def retire_for(result: bytes, txn_id: int) -> protocol.RequestFrame:
    payload = protocol.decode_response(result).payload
    return protocol.build_retire(txn_id=txn_id, result_crc=protocol.crc32(payload))


def parse_trace(operation: str, output: str,
                expected: list[bytes]) -> set[tuple[str, str]]:
    responses = [bytes.fromhex(line.removeprefix("RESPONSE "))
                 for line in output.splitlines() if line.startswith("RESPONSE ")]
    if responses != expected:
        raise SystemExit(f"{operation}: authored RTL bytes differ from executable model")
    statuses = [int(protocol.decode_response(raw).status) for raw in responses]
    counts_match = re.search(r"RTL_COUNTS rx_blocked=(\d+) tx_blocked=(\d+) done=(\d+)", output)
    if counts_match is None:
        raise SystemExit(f"{operation}: authored RTL emitted no trace counters")
    rx_blocked, tx_blocked, done = map(int, counts_match.groups())
    facts: set[tuple[str, str]] = set()
    if rx_blocked:
        facts.add((operation, "RX_STALL"))
    if tx_blocked:
        facts.add((operation, "TX_STALL"))
    if 0x00 in statuses:
        facts.add((operation, "RESULT"))
    if 0x01 in statuses:
        facts.add((operation, "SERVICE_REQUIRED"))
    if any(status >= 0x80 for status in statuses):
        facts.add((operation, "FAULT"))
    if 0x02 in statuses and done:
        facts.add((operation, "RETIRE"))
    for control in ("RESET", "ABORT"):
        before = re.search(
            rf"RTL_CONTROL {control} BEFORE result=(\d+) service=(\d+) tx=(\d+)", output)
        after = re.search(
            rf"RTL_CONTROL {control} AFTER result=(\d+) service=(\d+) tx=(\d+)", output)
        if before and after:
            if not (int(before.group(1)) or int(before.group(2))):
                raise SystemExit(f"{operation}: {control} did not target pending RTL work")
            if any(map(int, after.groups())):
                raise SystemExit(f"{operation}: {control} did not discard pending RTL work")
            facts.add((operation, f"{control}_DISCARD"))
    return facts


def run_rtl_case(simulator: Path, temporary: Path, operation: str,
                 frames: list[protocol.RequestFrame], expected: list[bytes],
                 control: str | None = None) -> set[tuple[str, str]]:
    arguments: list[str] = ["+INJECT_RX_STALL"]
    for index, frame in enumerate(frames, 1):
        encoded = frame.encode()
        request = temporary / f"{operation.lower()}-{control or 'normal'}-{index}.hex"
        request.write_text("".join(f"{byte:02x}\n" for byte in encoded))
        suffix = "" if index == 1 else str(index)
        arguments += [f"+REQUEST{suffix}={request}", f"+LENGTH{suffix}={len(encoded)}"]
    if control:
        arguments.append(f"+{control}_AFTER_FIRST")
    output = run(["vvp", str(simulator), *arguments])
    return parse_trace(operation, output, expected)


def authored_rtl_facts() -> set[tuple[str, str]]:
    with tempfile.TemporaryDirectory(prefix="lsc1-contract-") as directory:
        temporary = Path(directory)
        simulator = temporary / "packet-vector.vvp"
        run(["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(simulator), *(str(path) for path in RTL)])
        profile = protocol.Profile.INTERPRETER_COMPAT
        pointer = protocol.Cell(True, protocol.field_encode(40))
        successes: list[tuple[str, int, protocol.RequestFrame]] = [
            ("SET", 1, protocol.build_set_constant(
                txn_id=1, pc=0, fp=0, profile=profile, offset=2,
                constant=0x1234, cell=protocol.ABSENT)),
            ("XOR", 2, protocol.build_binary_op(
                protocol.Opcode.XOR, txn_id=2, pc=0, fp=0, profile=profile,
                offsets=(1, 2, 3), cells=(protocol.Cell(True, 1),
                protocol.Cell(True, 2), protocol.ABSENT))),
            ("MUL", 3, protocol.build_binary_op(
                protocol.Opcode.MUL_NATIVE, txn_id=3, pc=0, fp=0, profile=profile,
                offsets=(1, 2, 3), cells=(protocol.Cell(True, 2),
                protocol.Cell(True, 3), protocol.ABSENT),
                proposed_inverse=protocol.ABSENT)),
            ("DEREF", 4, protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=4, pc=5, fp=64,
                profile=profile, alpha=0, beta=2, gamma=3, pointer=pointer,
                base=40, target=protocol.ABSENT, local=protocol.Cell(True, 9))),
            ("JUMP", 5, protocol.build_jump(
                txn_id=5, pc=12, fp=0, profile=profile, offsets=(10, 11, 10),
                cells=(protocol.Cell(True, 1),
                       protocol.Cell(True, protocol.field_encode(15)),
                       protocol.Cell(True, 1)), taken=True, dest_pc=15, dest_fp=0,
                proposed_inverse=protocol.Cell(True, 1))),
        ]
        facts: set[tuple[str, str]] = set()
        for operation, txn_id, frame in successes:
            endpoint = protocol.Lsc1Endpoint()
            first = expected_exchange(endpoint, [frame])
            retire = retire_for(first[0], txn_id)
            expected = first + expected_exchange(endpoint, [retire])
            facts |= run_rtl_case(simulator, temporary, operation,
                                  [frame, retire], expected)

        deref_fault = protocol.build_deref(
            protocol.Opcode.DEREF_CELL, txn_id=6, pc=5, fp=64, profile=profile,
            alpha=0, beta=2, gamma=3, pointer=pointer, base=40,
            target=protocol.Cell(True, 1), local=protocol.Cell(True, 2))
        jump_fault = protocol.build_jump(
            txn_id=7, pc=12, fp=0, profile=profile, offsets=(10, 11, 10),
            cells=(protocol.Cell(True, 1), protocol.Cell(True, 0xBAD),
                   protocol.Cell(True, 1)), taken=True, dest_pc=15, dest_fp=0,
            proposed_inverse=protocol.Cell(True, 1))
        for operation, frame in (("DEREF", deref_fault), ("JUMP", jump_fault)):
            expected = expected_exchange(protocol.Lsc1Endpoint(), [frame])
            facts |= run_rtl_case(simulator, temporary, operation, [frame], expected)

        blake = protocol.build_blake3(
            txn_id=8, pc=2, fp=64, profile=profile,
            message_offsets=(0, 3, 1, 7), cv_offset=8, out_offset=10,
            metadata=0x40,
            message_cells=tuple(protocol.Cell(True, value) for value in (11, 22, 33, 44)),
            cv_cells=(protocol.Cell(True, 55), protocol.Cell(True, 66)),
            out_cells=(protocol.ABSENT, protocol.ABSENT))
        endpoint = protocol.Lsc1Endpoint()
        required = expected_exchange(endpoint, [blake])
        service_id = int.from_bytes(protocol.decode_response(required[0]).payload[4:8], "little")
        service = protocol.build_service_response(txn_id=8, service_id=service_id,
                                                  digest=(0xAA, 0xBB))
        result = expected_exchange(endpoint, [service])
        retire = retire_for(result[0], 8)
        expected = required + result + expected_exchange(endpoint, [retire])
        facts |= run_rtl_case(simulator, temporary, "BLAKE3",
                              [blake, service, retire], expected)

        wrong = protocol.build_service_response(txn_id=8, service_id=99, digest=(1, 2))
        fault_endpoint = protocol.Lsc1Endpoint()
        fault_expected = expected_exchange(fault_endpoint, [blake, wrong])
        facts |= run_rtl_case(simulator, temporary, "BLAKE3", [blake, wrong], fault_expected)
        status = protocol.build_status_query()
        for control in ("RESET", "ABORT"):
            control_endpoint = protocol.Lsc1Endpoint()
            first = expected_exchange(control_endpoint, [blake])
            if control == "RESET":
                control_endpoint.step(reset_n=False)
            else:
                control_endpoint.step(abort=True)
            control_expected = first + expected_exchange(control_endpoint, [status])
            facts |= run_rtl_case(simulator, temporary, "BLAKE3", [blake, status],
                                  control_expected, control=control)
        return facts


LEAN_OPERATION = {name: name.lower() for name in
                  ("SET", "XOR", "MUL", "DEREF", "JUMP", "BLAKE3")}
LEAN_OBSERVATION = {
    "RESULT": "result", "SERVICE_REQUIRED": "serviceRequired",
    "FAULT": "fault", "RX_STALL": "rxStall", "TX_STALL": "txStall",
    "RESET_DISCARD": "resetDiscard", "ABORT_DISCARD": "abortDiscard",
    "RETIRE": "retire",
}


def validate_in_lean(facts: set[tuple[str, str]]) -> None:
    entries = ",\n  ".join(
        f"(.{LEAN_OPERATION[operation]}, .{LEAN_OBSERVATION[observation]})"
        for operation, observation in sorted(facts))
    source = f"""import LeanVMBMinCore.AuthoredRTLContract
open LeanVMBMinCore.AuthoredRTLContract
def rtlFacts : List Fact := [
  {entries}
]
example : contractHolds rtlFacts := by decide
#eval if contractHolds rtlFacts then IO.println "LEAN_RTL_TRACE_RELATION_PASS"
  else throw (IO.userError "Lean/authored-RTL trace relation failed")
"""
    run(["lake", "build", "LeanVMBMinCore.AuthoredRTLContract"], ROOT / "lean")
    with tempfile.NamedTemporaryFile("w", suffix=".lean") as checker:
        checker.write(source)
        checker.flush()
        output = run(["lake", "env", "lean", checker.name], ROOT / "lean")
    if "LEAN_RTL_TRACE_RELATION_PASS" not in output:
        raise SystemExit("generated Lean trace checker did not run")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", required=True)
    parser.parse_args()
    facts = authored_rtl_facts()
    validate_in_lean(facts)
    print(f"LSC1_AUTHORED_RTL_CONTRACT_PASS observations={len(facts)} source=rtl-traces")


if __name__ == "__main__":
    main()
