#!/usr/bin/env python3
"""Finite LSC1-06 host fetch/memory to authored-RTL validation lane."""

from __future__ import annotations

import argparse
import json
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
from tools.host_upstream_comparison import compare
from tools.lsc1_authored_rtl_contract import RTL

ARTIFACT = ROOT / "host/fixtures/assert_set_xor_mul.program.json"
LEAN_NAME = {
    "SET_CONSTANT": "set", "XOR": "xor", "MUL_NATIVE": "mul",
    "DEREF_CELL": "derefCell", "DEREF_PC": "derefPc",
    "DEREF_FP": "derefFp", "JUMP": "jump", "BLAKE3_REQUEST": "blake3",
}


def command(argv: list[str], cwd: Path = ROOT) -> str:
    done = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    if done.returncode:
        raise SystemExit(f"command failed ({done.returncode}): {' '.join(argv)}\n{done.stdout}{done.stderr}")
    return done.stdout + done.stderr


class RecordingRuntime(HostRuntime):
    def __init__(self, *args, **kwargs):
        self.exchanges: list[tuple[protocol.RequestFrame, bytes]] = []
        self.exchange_memory: list[tuple[dict, dict]] = []
        self.step_evidence: list[dict[str, bool | str]] = []
        super().__init__(*args, **kwargs)

    def _exchange(self, frame):
        before = memory_snapshot(self.memory)
        raw, cycles = protocol.drive(self.endpoint, frame.encode())
        self.lane_cycles += cycles
        self.exchanges.append((frame, raw))
        self.exchange_memory.append((before, memory_snapshot(self.memory)))
        return protocol.decode_response(raw)

    def step(self):
        before = memory_snapshot(self.memory)
        first_exchange = len(self.exchanges)
        record = super().step()
        observations = self.exchange_memory[first_exchange:]
        frames = self.exchanges[first_exchange:]
        request = protocol.decode_request_payload(frames[0][0].opcode, frames[0][0].payload)
        expected_cells = tuple(self.memory_cell(before, address) for address in record.addresses)
        supplied = request.cells == expected_cells
        unchanged_until_retired = bool(observations) and all(
            exchange_before == before and exchange_after == before
            for exchange_before, exchange_after in observations
        )
        retired = (
            bool(frames)
            and frames[-1][0].opcode is protocol.Opcode.RETIRE
            and protocol.decode_response(frames[-1][1]).status is protocol.Status.RETIRED
        )
        expected_after = apply_record(before, record)
        self.step_evidence.append({
            "operation": LEAN_NAME[record.opcode],
            "suppliedCellsMatchHost": supplied,
            "resultAppliedAfterRetire": unchanged_until_retired and retired
                and memory_snapshot(self.memory) == expected_after,
        })
        return record

    @staticmethod
    def memory_cell(snapshot, address):
        value = snapshot["cells"].get(address)
        return protocol.ABSENT if value is None else protocol.Cell(True, value)


def memory_snapshot(memory: HostMemory) -> dict:
    return {
        "cells": dict(memory.cells),
        "access_counts": dict(memory.access_counts),
        "deferred": list(memory.deferred),
    }


def apply_record(snapshot: dict, record) -> dict:
    memory = HostMemory(
        cells=dict(snapshot["cells"]),
        access_counts=dict(snapshot["access_counts"]),
        deferred=list(snapshot["deferred"]),
    )
    for write in record.writes:
        memory.apply_write(write["address"], int(write["value"], 0))
    for address in record.accesses:
        memory.count_access(address)
    for item in record.deferred:
        memory.record_deferred(item["target"], item["local"])
    memory.resolve_deferred()
    return memory_snapshot(memory)


def groups(exchanges):
    negotiate = exchanges[0]
    result = []
    current = None
    for exchange in exchanges[1:]:
        opcode = int(exchange[0].opcode)
        if opcode in range(1, 9):
            if current:
                result.append([negotiate, *current])
            current = [exchange]
        elif current is not None:
            current.append(exchange)
        else:
            raise SystemExit("control frame appeared before a host-prepared instruction")
    if current:
        result.append([negotiate, *current])
    return result


def rtl_replay(simulator: Path, directory: Path, exchanges) -> list[bool]:
    manifest = directory / "requests.txt"
    lines = []
    for frame_index, (frame, _) in enumerate(exchanges, 1):
        request = directory / f"request-{frame_index}.hex"
        request.write_text("".join(f"{byte:02x}\n" for byte in frame.encode()))
        lines.append(f"{request} {len(frame.encode())}\n")
    manifest.write_text("".join(lines))
    output = command(["vvp", str(simulator), f"+MANIFEST={manifest}"])
    actual = [bytes.fromhex(line[9:]) for line in output.splitlines() if line.startswith("RESPONSE ")]
    expected = []
    for frame, raw in exchanges:
        if frame.opcode is protocol.Opcode.NEGOTIATE:
            reply = protocol.decode_response(raw)
            payload = bytearray(reply.payload)
            # The executable endpoint supports both profiles.  The authored RTL
            # intentionally implements only interpreter-compatible semantics,
            # so its independently specified capability mask keeps bit 0 clear.
            payload[6:10] = protocol.u32le(protocol.DEVICE_FEATURES & ~1)
            raw = protocol.ResponseFrame(reply.status, bytes(payload)).encode()
        expected.append(raw)
    if actual != expected:
        mismatch = next((i for i, pair in enumerate(zip(actual, expected, strict=False))
                         if pair[0] != pair[1]), min(len(actual), len(expected)))
        got = actual[mismatch].hex() if mismatch < len(actual) else "<missing>"
        want = expected[mismatch].hex() if mismatch < len(expected) else "<none>"
        raise SystemExit(f"authored RTL bytes differ from executable model at exchange {mismatch}: {got} != {want}")
    return [got == want for got, want in zip(actual, expected, strict=True)]


def require_evidence(facts) -> None:
    for index, fact in enumerate(facts):
        for predicate in ("suppliedCellsMatchHost", "resultAppliedAfterRetire", "rtlBytesMatchModel"):
            if not fact[predicate]:
                raise SystemExit(f"boundary predicate {predicate} was not established at step {index}")


def lean_check(facts) -> None:
    require_evidence(facts)
    entries = ",\n  ".join(
        f"{{ operation := .{fact['operation']}, "
        f"suppliedCellsMatchHost := {str(fact['suppliedCellsMatchHost']).lower()}, "
        f"resultAppliedAfterRetire := {str(fact['resultAppliedAfterRetire']).lower()}, "
        f"rtlBytesMatchModel := {str(fact['rtlBytesMatchModel']).lower()} }}"
        for fact in facts
    )
    source = f"""import LeanVMBMinCore.HostPreparedBoundary
open LeanVMBMinCore.HostPreparedBoundary
def hostFacts : List StepFact := [
  {entries}
]
example : BoundaryEvidence hostFacts := receiptHolds hostFacts (by decide)
#eval if receiptValid hostFacts then IO.println \"LEAN_HOST_BOUNDARY_PASS\"
  else throw (IO.userError \"invalid host boundary receipt\")
"""
    command(["lake", "build", "LeanVMBMinCore.HostPreparedBoundary"], ROOT / "lean")
    with tempfile.NamedTemporaryFile("w", suffix=".lean") as checker:
        checker.write(source)
        checker.flush()
        output = command(["lake", "env", "lean", checker.name], ROOT / "lean")
    if "LEAN_HOST_BOUNDARY_PASS" not in output:
        raise SystemExit("Lean did not accept the host boundary receipt")


def verify() -> dict:
    program = load(ARTIFACT)
    runtime = RecordingRuntime(program, memory=HostMemory.with_public_input(1, 0), session_epoch=1)
    run = runtime.run()
    comparison = compare(runtime, run, program.upstream_execution)
    if run.terminal != "halted" or comparison["result"] != "MATCH":
        raise SystemExit("host executable-model run does not match the recorded frozen upstream result")
    step_groups = groups(runtime.exchanges)
    if len(step_groups) != len(run.records):
        raise SystemExit("host exchanges do not partition one-for-one by fetched instruction")
    with tempfile.TemporaryDirectory(prefix="lsc1-host-boundary-") as name:
        directory = Path(name)
        simulator = directory / "packet-vector.vvp"
        command(["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o", str(simulator),
                 *(str(path) for path in RTL)])
        rtl_matches = rtl_replay(simulator, directory, runtime.exchanges)
    exchange_groups = groups(list(zip((frame for frame, _ in runtime.exchanges), rtl_matches)))
    if len(exchange_groups) != len(runtime.step_evidence):
        raise SystemExit("RTL comparisons do not partition one-for-one by host step")
    facts = []
    for evidence, exchange_group in zip(runtime.step_evidence, exchange_groups, strict=True):
        facts.append({**evidence, "rtlBytesMatchModel": all(match for _, match in exchange_group)})
    lean_check(facts)
    return {
        "schema": "leansilicon.lsc1.host-authored-rtl-boundary/1",
        "source_artifact": str(ARTIFACT.relative_to(ROOT)),
        "frozen_upstream": program.upstream_sha,
        "executable_model": {"terminal": run.terminal, "steps": len(run.records),
                             "final_memory_comparison": comparison["result"]},
        "lean": {"receipt": "PASS", "scope": "finite host-prepared fixture",
                 "derived_step_predicates": facts},
        "authored_rtl": {"response_bytes": "MATCH", "instruction_lifecycles": len(step_groups)},
        "excluded": ["netlist", "place-and-route", "FPGA", "hardware", "LSC-1u", "end-to-end verification"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", required=True)
    parser.add_argument("--receipt")
    args = parser.parse_args()
    receipt = verify()
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        Path(args.receipt).write_text(text)
    print("LSC1_HOST_AUTHORED_RTL_BOUNDARY_PASS steps=13 model=MATCH lean=PASS rtl=MATCH")


if __name__ == "__main__":
    main()
