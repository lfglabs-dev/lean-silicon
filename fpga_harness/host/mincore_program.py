#!/usr/bin/env python3
"""Run the SET/XOR/MUL prefix of a compiled leanVM-b program on MinCore.

The Mac owns bytecode, pc/fp and write-once memory. Each integrated arithmetic
instruction is evaluated by the physical MinCore UART endpoint, checked against
an independent host result, and only then committed to host memory. Unsupported
instructions stop the run before any bytes for that instruction are sent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Protocol, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

# ``unittest discover -s fpga_harness`` may import ``fpga_harness/host`` as a
# top-level package named ``host`` before reaching this module. The program
# runner needs the repository's actual ``host/`` package instead. Remove only
# that discovery alias; ``fpga_harness.host`` remains loaded under its real name.
host_alias = sys.modules.get("host")
if host_alias is not None:
    alias_file = pathlib.Path(getattr(host_alias, "__file__", "")).resolve()
    if alias_file.parent == ROOT / "fpga_harness" / "host":
        del sys.modules["host"]

from fpga_harness import ulx3s_uart

from host import lean_compiler_adapter
from host.errors import HostError, UnsupportedCapability
from host.memory import HostMemory
from host.protocol import protocol

SCHEMA = "leansilicon.mincore-program-run/1"
MASK = (1 << 128) - 1


def repo_provenance(evidence: pathlib.Path | None = None) -> tuple[str, bool | None]:
    """Record HEAD/dirty state without counting a new evidence destination."""
    command = ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if evidence is not None:
            try:
                relative = evidence.resolve().relative_to(ROOT).as_posix()
            except (OSError, ValueError):
                relative = ""
            if relative and not subprocess.check_output(
                ["git", "ls-files", "--", relative], cwd=ROOT, text=True
            ).strip():
                command += ["--", ".", f":(exclude,literal,top){relative}"]
        status = subprocess.check_output(command, cwd=ROOT, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown", None
    return head, bool(status.strip())


def close_quietly(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


class ArithmeticDriver(Protocol):
    def exchange(
        self, operation: str, *, a: bytes = b"", b: bytes = b"", value: bytes = b""
    ) -> tuple[bytes, bytes]: ...


class HardwareMismatch(HostError):
    """MinCore returned a well-sized value different from the host oracle."""


@dataclass
class SeedStep:
    pc: int
    kind: str
    addresses: list[int]
    inputs: list[int]
    result: int
    request: bytes
    response: bytes

    def as_dict(self) -> dict:
        digest = lambda data: hashlib.sha256(data).hexdigest()
        return {
            "pc": self.pc,
            "kind": self.kind,
            "addresses": self.addresses,
            "inputs": [f"{value:#034x}" for value in self.inputs],
            "result": f"{self.result:#034x}",
            "request_length": len(self.request),
            "request_sha256": digest(self.request),
            "response_length": len(self.response),
            "response_sha256": digest(self.response),
            "response_hex": self.response.hex(),
        }


@dataclass
class SeedRun:
    terminal: str
    reason: str
    pc: int
    fp: int
    steps: list[SeedStep] = field(default_factory=list)


class MinCoreProgramRunner:
    """Host-owned restricted leanVM-b interpreter backed by MinCore arithmetic."""

    def __init__(
        self,
        program: lean_compiler_adapter.Program,
        driver: ArithmeticDriver,
        *,
        memory: HostMemory | None = None,
    ) -> None:
        self.program = program
        self.driver = driver
        self.memory = memory or HostMemory.with_public_input(1, 0)
        self.pc = program.pc0
        self.fp = program.fp0
        self.steps: list[SeedStep] = []

    @staticmethod
    def _bytes(value: int) -> bytes:
        return (value & MASK).to_bytes(16, "little")

    def _address(self, offset: int) -> int:
        address = self.fp + offset
        if address > 0xFFFFFFFF:
            raise UnsupportedCapability(
                f"pc {self.pc}: fp {self.fp} + offset {offset} overflows u32"
            )
        return address

    def _required(self, address: int, role: str) -> int:
        value = self.memory.read(address)
        if value is None:
            raise UnsupportedCapability(
                f"pc {self.pc}: seed-0 {role} cell {address} is unwritten; "
                "the raw arithmetic endpoint cannot back-solve absent operands"
            )
        return value

    def check_status(self) -> None:
        _request, response = self.driver.exchange("status")
        if response != ulx3s_uart.STATUS_SIGNATURE:
            raise HardwareMismatch(
                f"STATUS returned {response.hex()}, expected {ulx3s_uart.STATUS_SIGNATURE.hex()}"
            )

    def step(self) -> SeedStep:
        operation = self.program.at(self.pc)
        if operation.kind not in lean_compiler_adapter.INTEGRATED_OPS:
            raise UnsupportedCapability(
                f"pc {self.pc}: {operation.kind} is not supported by the "
                "seed-0 UART program runner"
            )

        if operation.kind == "Set":
            address = self._address(operation.operands["o"])
            result = operation.operands["k"] & MASK
            addresses, inputs = [address], [result]
            exchange = ("set", {"value": self._bytes(result)})
        else:
            addresses = [
                self._address(operation.operands[name]) for name in ("a", "b", "c")
            ]
            left = self._required(addresses[0], "left operand")
            right = self._required(addresses[1], "right operand")
            inputs = [left, right]
            if operation.kind == "Xor":
                result = left ^ right
                exchange = ("xor", {"a": self._bytes(left), "b": self._bytes(right)})
            else:
                result = protocol.field_mul(left, right)
                exchange = ("mul", {"a": self._bytes(left), "b": self._bytes(right)})

        destination = addresses[-1]
        self.memory.prevalidate_write(destination, result)
        request, response = self.driver.exchange(exchange[0], **exchange[1])
        expected = self._bytes(result)
        if response != expected:
            raise HardwareMismatch(
                f"pc {self.pc}: {operation.kind} returned {response.hex()}, "
                f"expected {expected.hex()}"
            )

        self.memory.apply_write(destination, result)
        for address in addresses:
            self.memory.count_access(address)
        record = SeedStep(
            pc=self.pc,
            kind=operation.kind,
            addresses=addresses,
            inputs=inputs,
            result=result,
            request=request,
            response=response,
        )
        self.steps.append(record)
        self.pc += 1
        return record

    def run(self, *, max_steps: int = 1024, check_status: bool = True) -> SeedRun:
        if check_status:
            self.check_status()
        for _ in range(max_steps):
            if self.pc == self.program.halt_pc:
                return SeedRun("halted", f"reached sentinel pc {self.pc}", self.pc, self.fp, self.steps)
            try:
                self.step()
            except UnsupportedCapability as error:
                return SeedRun("unsupported", str(error), self.pc, self.fp, self.steps)
        return SeedRun(
            "step_limit", f"stopped after {max_steps} steps", self.pc, self.fp, self.steps
        )


def compare_upstream_prefix(
    program: lean_compiler_adapter.Program, runner: MinCoreProgramRunner, run: SeedRun
) -> dict | None:
    upstream = program.upstream_execution
    if upstream is None:
        return None
    expected = [int(value, 16) for value in upstream["mem"]]
    compared, mismatches = [], []
    for address in sorted(runner.memory.cells):
        if address >= len(expected):
            mismatches.append({"address": address, "reason": "outside recorded upstream prefix"})
            continue
        compared.append(address)
        actual = runner.memory.read(address)
        if actual != expected[address]:
            mismatches.append(
                {
                    "address": address,
                    "hardware_prefix": f"{actual:#034x}",
                    "upstream": f"{expected[address]:#034x}",
                }
            )
    missing = sorted(set(range(upstream["mem_used"])) - set(compared))
    if mismatches:
        result = "MISMATCH"
    elif run.terminal == "halted" and not missing:
        result = "MATCH"
    else:
        result = "PREFIX_MATCH"
    return {
        "result": result,
        "compared_memory_addresses": compared,
        "missing_upstream_addresses": missing,
        "mismatches": mismatches,
        "upstream_cycles": upstream["cycles"],
        "hardware_prefix_steps": len(run.steps),
    }


def run_document(
    artifact: pathlib.Path,
    program: lean_compiler_adapter.Program,
    runner: MinCoreProgramRunner,
    run: SeedRun,
    *,
    provenance: tuple[str, bool | None],
) -> dict:
    head, dirty = provenance
    memory_size = program.upstream_execution["mem_used"] if program.upstream_execution else 0
    try:
        artifact_path = artifact.relative_to(ROOT).as_posix()
    except ValueError:
        artifact_path = artifact.name
    return {
        "schema": SCHEMA,
        "artifact": {
            "path": artifact_path,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "upstream_sha": program.upstream_sha,
        },
        "repo_head": head,
        "repo_dirty": dirty,
        "execution_attempted": True,
        "terminal": run.terminal,
        "reason": run.reason,
        "pc": run.pc,
        "fp": run.fp,
        "steps": [step.as_dict() for step in run.steps],
        "memory": [f"{value:#034x}" for value in runner.memory.image(memory_size)],
        "written": sorted(runner.memory.cells),
        "comparison": compare_upstream_prefix(program, runner, run),
    }


def _positive(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a compiled leanVM-b SET/XOR/MUL prefix on physical MinCore"
    )
    parser.add_argument(
        "--artifact",
        type=pathlib.Path,
        default=ROOT / "host" / "fixtures" / "assert_set_xor_mul.program.json",
    )
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=ulx3s_uart.BAUD)
    parser.add_argument("--timeout", type=_positive, default=3.0)
    parser.add_argument("--max-steps", type=int, default=1024)
    parser.add_argument("--execute", action="store_true", help="required physical-execution guard")
    parser.add_argument("--evidence", type=pathlib.Path)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("physical program execution requires --execute")
    if args.max_steps <= 0:
        parser.error("--max-steps must be positive")
    if not 1 <= args.baud <= 4_000_000:
        parser.error("--baud must be an integer from 1 through 4000000")

    evidence_stream = None
    transport = None
    try:
        artifact = args.artifact.resolve()
        program = lean_compiler_adapter.load(artifact)
        provenance = repo_provenance(args.evidence)
        if args.evidence:
            # Physical evidence is append-only in spirit. Refuse to truncate a
            # prior run, especially one already archived and checksummed.
            evidence_stream = args.evidence.open("x")
        transport = ulx3s_uart.open_port(args.port, baud=args.baud, timeout=args.timeout)
        runner = MinCoreProgramRunner(
            program, ulx3s_uart.MinCoreSerialDriver(transport, args.timeout)
        )
        run = runner.run(max_steps=args.max_steps)
        document = run_document(artifact, program, runner, run, provenance=provenance)
        rendered = json.dumps(document, indent=2, sort_keys=True)
        if evidence_stream:
            evidence_stream.write(rendered + "\n")
            evidence_stream.flush()
        print(rendered)
        comparison = document["comparison"]
        return 0 if comparison is None or comparison["result"] != "MISMATCH" else 1
    except (HostError, OSError, RuntimeError, ValueError, TimeoutError) + ulx3s_uart.COMMUNICATION_ERRORS as error:
        print(f"mincore-program: {error}", file=sys.stderr)
        return 2
    finally:
        close_quietly(transport)
        close_quietly(evidence_stream)


if __name__ == "__main__":
    raise SystemExit(main())
