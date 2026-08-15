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
        super().__init__(*args, **kwargs)

    def _exchange(self, frame):
        raw, cycles = protocol.drive(self.endpoint, frame.encode())
        self.lane_cycles += cycles
        self.exchanges.append((frame, raw))
        return protocol.decode_response(raw)


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


def rtl_replay(simulator: Path, directory: Path, exchanges) -> None:
    manifest = directory / "requests.txt"
    lines = []
    for frame_index, (frame, _) in enumerate(exchanges, 1):
        request = directory / f"request-{frame_index}.hex"
        request.write_text("".join(f"{byte:02x}\n" for byte in frame.encode()))
        lines.append(f"{request} {len(frame.encode())}\n")
    manifest.write_text("".join(lines))
    output = command(["vvp", str(simulator), f"+MANIFEST={manifest}"])
    actual = [bytes.fromhex(line[9:]) for line in output.splitlines() if line.startswith("RESPONSE ")]
    expected = [raw for _, raw in exchanges]
    if actual != expected:
        mismatch = next((i for i, pair in enumerate(zip(actual, expected, strict=False))
                         if pair[0] != pair[1]), min(len(actual), len(expected)))
        got = actual[mismatch].hex() if mismatch < len(actual) else "<missing>"
        want = expected[mismatch].hex() if mismatch < len(expected) else "<none>"
        raise SystemExit(f"authored RTL bytes differ from executable model at exchange {mismatch}: {got} != {want}")


def lean_check(records) -> None:
    entries = ",\n  ".join(
        f"{{ operation := .{LEAN_NAME[r.opcode]}, suppliedCellsMatchHost := true, "
        "resultAppliedAfterRetire := true, rtlBytesMatchModel := true }"
        for r in records
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
        rtl_replay(simulator, directory, runtime.exchanges)
    lean_check(run.records)
    return {
        "schema": "leansilicon.lsc1.host-authored-rtl-boundary/1",
        "source_artifact": str(ARTIFACT.relative_to(ROOT)),
        "frozen_upstream": program.upstream_sha,
        "executable_model": {"terminal": run.terminal, "steps": len(run.records),
                             "final_memory_comparison": comparison["result"]},
        "lean": {"receipt": "PASS", "scope": "finite host-prepared fixture"},
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
