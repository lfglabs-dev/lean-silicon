"""UI-independent execution model and structured event vocabulary."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import json

MASK128 = (1 << 128) - 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "results/fpga-lsc1-20260726/program-run.json"
DEFAULT_PROGRAM = ROOT / "host/fixtures/assert_set_xor_mul.program.json"


class EventKind(str, Enum):
    PREPARE = "prepare"
    UART_SEND = "uart_send"
    FPGA_COMPUTE = "fpga_compute"
    RESPONSE = "response"
    VALIDATE = "validate"
    MEMORY_WRITE = "memory_write"
    HALT = "halt"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    pc: int
    actor: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Instruction:
    pc: int
    op: str
    text: str
    reads: tuple[int, ...]
    writes: tuple[int, ...]


@dataclass(frozen=True)
class Step:
    pc: int
    kind: str
    addresses: tuple[int, ...]
    inputs: tuple[int, ...]
    result: int
    request: bytes
    response: bytes

    @property
    def reads(self) -> tuple[int, ...]:
        return self.addresses[:-1] if self.kind != "Set" else ()

    @property
    def writes(self) -> tuple[int, ...]:
        return self.addresses[-1:]


@dataclass
class ProgramEvidence:
    source_path: str
    source: str
    instructions: list[Instruction]
    steps: list[Step]
    expected_memory: list[int]
    result: str
    reason: str
    fp: int


def _value(raw: str | int) -> int:
    value = int(raw, 0) if isinstance(raw, str) else raw
    if not 0 <= value <= MASK128:
        raise ValueError("VM cell is not an unsigned 128-bit value")
    return value


def load_evidence(evidence_path: Path = DEFAULT_EVIDENCE,
                  program_path: Path = DEFAULT_PROGRAM) -> ProgramEvidence:
    run = json.loads(evidence_path.read_text())
    artifact = json.loads(program_path.read_text())
    bytecode = artifact["program"]["bytecode"]
    lines = artifact["program"]["disassembly"].splitlines()
    instructions = []
    for op, text in zip(bytecode, lines):
        kind = op["op"]
        if kind in {"Xor", "Mul"}:
            reads, writes = (op["a"], op["b"]), (op["c"],)
        elif kind == "Set":
            reads, writes = (), (op["o"],)
        else:
            reads, writes = (op.get("oc", 0), op.get("od", 0)), (op.get("of", 0),)
        instructions.append(Instruction(op["index"], kind, text.strip(), reads, writes))
    steps = [
        Step(
            pc=s["pc"], kind=s["kind"], addresses=tuple(s["addresses"]),
            inputs=tuple(_value(v) for v in s["inputs"]), result=_value(s["result"]),
            request=b"", response=bytes.fromhex(s["response_hex"]),
        )
        for s in run["steps"]
    ]
    # Reconstruct request bytes through the reviewed operation grammar. Evidence
    # hashes remain visible in the raw artifact; the UI displays deterministic bytes.
    from .transport import encode_request
    steps = [
        Step(s.pc, s.kind, s.addresses, s.inputs, s.result,
             encode_request(s.kind, s.inputs), s.response) for s in steps
    ]
    return ProgramEvidence(
        artifact["source"]["path"], artifact["source"]["text"], instructions, steps,
        [_value(v) for v in run["memory"]], run["comparison"]["result"],
        run["reason"], run["fp"],
    )


def events_for(step: Step) -> list[Event]:
    common = {"kind": step.kind, "reads": step.reads, "writes": step.writes}
    expected = step.result.to_bytes(16, "little")
    valid = step.response == expected
    events = [
        Event(EventKind.PREPARE, step.pc, "HOST", f"prepare {step.kind}", common),
        Event(EventKind.UART_SEND, step.pc, "HOST", f"send {len(step.request)} bytes",
              {**common, "request": step.request.hex()}),
        Event(EventKind.FPGA_COMPUTE, step.pc, "FPGA", f"compute {step.kind}", common),
        Event(EventKind.RESPONSE, step.pc, "FPGA", f"return {len(step.response)} bytes",
              {**common, "response": step.response.hex()}),
        Event(EventKind.VALIDATE, step.pc, "HOST",
              "response matches" if valid else "response mismatch",
              {**common, "valid": valid}),
    ]
    if valid:
        events.append(Event(EventKind.MEMORY_WRITE, step.pc, "HOST",
                            f"write mem[{step.writes[0]}]", {**common, "value": step.result}))
    else:
        events.append(Event(EventKind.ERROR, step.pc, "HOST", "hardware mismatch", common))
    return events


def fault_event(error: BaseException, pc: int) -> Event:
    """Normalize transport failures for every UI and adapter."""
    label = "TIMEOUT" if isinstance(error, TimeoutError) else (
        "PROTOCOL FAULT" if isinstance(error, (ValueError, UnicodeError)) else "TRANSPORT FAULT"
    )
    return Event(EventKind.ERROR, pc, "HOST", f"{label}: {error}",
                 {"fault": label.lower().replace(" ", "_")})


@dataclass
class Replay:
    evidence: ProgramEvidence
    cursor: int = 0
    memory: dict[int, int] = field(default_factory=lambda: {0: 1, 1: 0})
    events: list[Event] = field(default_factory=list)
    state: str = "READY"
    terminal: str = ""

    def restart(self) -> None:
        self.cursor, self.memory, self.events = 0, {0: 1, 1: 0}, []
        self.state, self.terminal = "READY", ""

    def advance(self) -> bool:
        if self.cursor >= len(self.evidence.steps):
            self.finish()
            return False
        step = self.evidence.steps[self.cursor]
        generated = events_for(step)
        self.events.extend(generated)
        mismatch = next((e for e in generated if e.kind == EventKind.ERROR), None)
        if mismatch:
            self.state, self.terminal = "ERROR", "MISMATCH"
            return False
        self.memory[step.writes[0]] = step.result
        self.cursor += 1
        self.state = "RUNNING"
        if self.cursor == len(self.evidence.steps):
            self.finish()
        return True

    def finish(self) -> None:
        actual = [self.memory.get(i, 0) for i in range(len(self.evidence.expected_memory))]
        if self.evidence.result == "PREFIX_MATCH" and actual == self.evidence.expected_memory:
            self.state, self.terminal = "COMPLETE", "PREFIX MATCH ✓"
            message = f"validated {len(self.evidence.steps)}-step hardware prefix"
            self.events.append(Event(EventKind.HALT, self.cursor, "HOST", message,
                                     {"reason": self.evidence.reason, "prefix": True}))
        else:
            self.state, self.terminal = "ERROR", "MISMATCH"
            self.events.append(Event(EventKind.ERROR, self.cursor, "HOST",
                                     "evidence memory mismatch", {}))
