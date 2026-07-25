"""Adapter from a frozen ``lean_compiler`` program artifact to host operations.

The pinned interface lives in ``leanEthereum/leanVM-b`` at
``c308034ab78619b39a59d26f3dc60e7df5b52649``:

* ``lean_compiler::parse(&str) -> Result<Ast, String>``
  (``crates/lean_compiler/src/parser.rs``)
* ``lean_compiler::compile(&Ast) -> lean_vm::cpu::Program``
  (``crates/lean_compiler/src/lib.rs``)
* ``lean_compiler::disassemble(&[Op]) -> String``
* ``lean_vm::cpu::Program`` public fields ``prog: Vec<Op>``, ``pc0``, ``fp0``,
  ``fn_ranges``
* ``lean_vm::cpu::isa::Op``: ``Xor``, ``Mul``, ``Set``, ``Deref``, ``Jump``,
  ``Blake3``

Three ``Program`` fields that a full host runtime eventually needs are
``pub(crate)`` at that commit and therefore not reachable from outside the
crate: ``hints``, ``main_frame`` and ``witness``.  ``Execution::trace`` is
``pub(crate)`` as well.  ``tools/lean_compiler_export.py`` records that limit
in every artifact it writes rather than working around it.

This module does not import Rust and does not shell out.  It reads the JSON
artifact that the export tool produced from the real compiler, so tests run
with no toolchain present.
"""
import json
import pathlib
from dataclasses import dataclass

from .errors import AdapterError

SCHEMA = "leansilicon.host.program/1"
FROZEN_LEANVM_B = "c308034ab78619b39a59d26f3dc60e7df5b52649"

#: Opcodes this scaffold prepares as LSC-1 transactions.
INTEGRATED_OPS = ("Set", "Xor", "Mul")

#: Opcodes the artifact may legitimately contain that the host does not drive
#: yet, with the reason each one is still out of scope.
DEFERRED_OPS = {
    "Deref": (
        "DEREF needs the host pointer map plus the deferred-equality "
        "reconciliation loop; the LSC-1 transaction exists but the host does "
        "not prepare it yet"
    ),
    "Jump": (
        "JUMP needs host-side branch proposal and destination re-encoding; "
        "the LSC-1 transaction exists but the host does not prepare it yet"
    ),
    "Blake3": (
        "BLAKE3 is a host service (D-004) and this scaffold has no BLAKE3 "
        "compression implementation to answer SERVICE_REQUIRED with"
    ),
}


@dataclass(frozen=True)
class Operation:
    """One decoded bytecode slot."""

    index: int
    kind: str
    operands: dict

    @property
    def integrated(self) -> bool:
        return self.kind in INTEGRATED_OPS

    def reason_unsupported(self) -> str:
        return DEFERRED_OPS.get(self.kind, f"unknown opcode {self.kind!r}")


@dataclass(frozen=True)
class Program:
    """A compiled program plus the provenance of the compiler that made it."""

    operations: tuple[Operation, ...]
    pc0: int
    fp0: int
    fn_ranges: tuple[tuple[str, int, int], ...]
    source: str
    upstream_sha: str
    disassembly: str
    upstream_execution: dict | None

    @property
    def halt_pc(self) -> int:
        """The sentinel slot; reaching it ends the run (frozen state rule)."""
        return len(self.operations) - 1

    def at(self, pc: int) -> Operation:
        if not 0 <= pc < len(self.operations):
            raise AdapterError(f"pc {pc} is outside the {len(self.operations)}-slot program")
        return self.operations[pc]


#: Operand names the artifact carries as ``0x``-prefixed 128-bit hex strings.
FIELD_OPERANDS = ("k", "metadata")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdapterError(message)


def _field(text: str, where: str) -> int:
    _require(
        isinstance(text, str) and len(text) == 34 and text.startswith("0x"),
        f"{where} is not a 0x-prefixed 128-bit hex literal: {text!r}",
    )
    try:
        return int(text, 16)
    except ValueError as error:
        raise AdapterError(f"{where} is not hexadecimal: {text!r}") from error


def load(path: str | pathlib.Path) -> Program:
    """Load and validate a program artifact written by the export tool."""
    document = json.loads(pathlib.Path(path).read_text())
    _require(
        document.get("schema") == SCHEMA,
        f"artifact schema {document.get('schema')!r} is not {SCHEMA!r}",
    )
    upstream = document.get("upstream", {})
    _require(
        upstream.get("sha") == FROZEN_LEANVM_B,
        f"artifact was not produced from the frozen commit {FROZEN_LEANVM_B}",
    )
    program = document["program"]
    slots = program["bytecode"]
    _require(bool(slots), "artifact carries no bytecode")
    _require(
        len(slots) & (len(slots) - 1) == 0,
        f"bytecode length {len(slots)} is not a power of two",
    )

    operations = []
    for expected_index, slot in enumerate(slots):
        _require(
            slot["index"] == expected_index,
            f"bytecode slot {expected_index} is labelled {slot['index']}",
        )
        kind = slot["op"]
        _require(
            kind in INTEGRATED_OPS or kind in DEFERRED_OPS,
            f"slot {expected_index} carries unknown opcode {kind!r}",
        )
        operands = {key: value for key, value in slot.items() if key not in ("index", "op")}
        for name in FIELD_OPERANDS:
            if name in operands:
                operands[name] = _field(operands[name], f"slot {expected_index} operand {name!r}")
        operations.append(Operation(expected_index, kind, operands))

    return Program(
        operations=tuple(operations),
        pc0=program["pc0"],
        fp0=program["fp0"],
        fn_ranges=tuple(tuple(item) for item in program.get("fn_ranges", [])),
        source=document.get("source", {}).get("text", ""),
        upstream_sha=upstream["sha"],
        disassembly=program.get("disassembly", ""),
        upstream_execution=document.get("upstream_execution"),
    )
