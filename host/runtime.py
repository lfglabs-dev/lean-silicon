"""The Mac-side runtime: prepare one transaction, apply one transition.

The loop is deliberately literal about the split in ``docs/ARCHITECTURE.md``.
For every instruction the host reads its own memory, packs every cell the
transition may touch into a self-contained request, hands that request to the
endpoint over the byte lane, and only then applies the writes the endpoint
decided.  The endpoint is never asked to fetch, search or remember anything.

Integrated in this scaffold: SET_CONSTANT, XOR and MUL_NATIVE, including the
MUL inverse witness.  Everything else raises ``UnsupportedCapability`` naming
what is missing.
"""
from dataclasses import dataclass, field

from .errors import TransactionRejected, UnsupportedCapability
from .lean_compiler_adapter import Program
from .memory import HostMemory, field_inverse
from .protocol import protocol

#: The compiler opcode names this runtime knows how to turn into transactions.
_LSC1_OPCODE = {
    "Set": protocol.Opcode.SET_CONSTANT,
    "Xor": protocol.Opcode.XOR,
    "Mul": protocol.Opcode.MUL_NATIVE,
}


@dataclass
class StepRecord:
    """One prepared, executed and retired transition, in comparison-schema form."""

    index: int
    txn_id: int
    source_op: str
    opcode: str | None
    pc: int
    fp: int
    next_pc: int | None = None
    next_fp: int | None = None
    addresses: list[int] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    writes: list[dict] = field(default_factory=list)
    branch: dict | None = None
    deferred: list[dict] = field(default_factory=list)
    accesses: list[int] = field(default_factory=list)
    status: str | None = None
    fault: str | None = None
    retire_seq: int | None = None
    lane_cycles: int = 0

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "txn_id": self.txn_id,
            "source_op": self.source_op,
            "opcode": self.opcode,
            "pc": self.pc,
            "fp": self.fp,
            "next_pc": self.next_pc,
            "next_fp": self.next_fp,
            "addresses": list(self.addresses),
            "inputs": list(self.inputs),
            "writes": list(self.writes),
            "branch": self.branch,
            "deferred": list(self.deferred),
            "accesses": list(self.accesses),
            "status": self.status,
            "fault": self.fault,
            "retire_seq": self.retire_seq,
            "lane_cycles": self.lane_cycles,
        }


@dataclass
class RunResult:
    """Why a run stopped, and everything it decided on the way."""

    records: list[StepRecord]
    terminal: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "records": [record.as_dict() for record in self.records],
            "terminal": self.terminal,
            "reason": self.reason,
        }


def decode_result_payload(payload: bytes) -> dict:
    """Decode an ``OK`` transition result (protocol section 8)."""
    def u32(offset: int) -> int:
        return int.from_bytes(payload[offset:offset + 4], "little")

    txn_id, next_pc, next_fp = u32(0), u32(4), u32(8)
    cursor = 12
    writes = []
    for _ in range(payload[cursor]):
        base = cursor + 1
        writes.append({
            "address": int.from_bytes(payload[base:base + 4], "little"),
            "value": int.from_bytes(payload[base + 4:base + 20], "little"),
        })
        cursor += protocol.WRITE_BYTES
    cursor += 1
    deferred = []
    for _ in range(payload[cursor]):
        base = cursor + 1
        deferred.append({
            "target": int.from_bytes(payload[base:base + 4], "little"),
            "local": int.from_bytes(payload[base + 4:base + 8], "little"),
        })
        cursor += protocol.DEFERRED_BYTES
    cursor += 1
    accesses = []
    for _ in range(payload[cursor]):
        base = cursor + 1
        accesses.append(int.from_bytes(payload[base:base + 4], "little"))
        cursor += protocol.ACCESS_BYTES
    if cursor + 1 != len(payload):
        raise ValueError(f"result payload has {len(payload)} bytes, consumed {cursor + 1}")
    return {
        "txn_id": txn_id,
        "next_pc": next_pc,
        "next_fp": next_fp,
        "writes": writes,
        "deferred": deferred,
        "accesses": accesses,
    }


class HostRuntime:
    """Drives one compiled program through an LSC-1 endpoint."""

    def __init__(
        self,
        program: Program,
        *,
        memory: HostMemory | None = None,
        endpoint=None,
        profile: "protocol.Profile" = protocol.Profile.INTERPRETER_COMPAT,
    ) -> None:
        self.program = program
        self.memory = memory or HostMemory.with_public_input(1, 0)
        self.endpoint = endpoint or protocol.Lsc1Endpoint()
        self.profile = profile
        self.pc = program.pc0
        self.fp = program.fp0
        self.txn_id = 0
        self.step_index = 0
        self.lane_cycles = 0
        self.faulted = False
        self._negotiate()

    # --- byte lane ----------------------------------------------------------

    def _exchange(self, frame: "protocol.RequestFrame") -> "protocol.ResponseFrame":
        raw, cycles = protocol.drive(self.endpoint, frame.encode())
        self.lane_cycles += cycles
        return protocol.decode_response(raw)

    def _negotiate(self) -> None:
        reply = self._exchange(protocol.build_negotiate(profile=self.profile))
        if reply.status is not protocol.Status.OK:
            raise TransactionRejected(reply.status, reply.payload)

    # --- request preparation ------------------------------------------------

    def _cells(self, addresses):
        return tuple(self.memory.cell(address) for address in addresses)

    def _inputs(self, addresses) -> list[dict]:
        return [
            {
                "address": address,
                "present": self.memory.written(address),
                "value": self.memory.read(address),
            }
            for address in addresses
        ]

    def _prepare(self, operation) -> tuple["protocol.RequestFrame", list[int]]:
        """Build one self-contained request, or refuse and say why."""
        if not operation.integrated:
            raise UnsupportedCapability(
                f"pc {operation.index}: {operation.kind} is not integrated. "
                f"{operation.reason_unsupported()}"
            )
        self.txn_id += 1
        if operation.kind == "Set":
            offset = operation.operands["o"]
            address = protocol.checked_add(self.fp, offset)
            frame = protocol.build_set_constant(
                txn_id=self.txn_id,
                pc=self.pc,
                fp=self.fp,
                profile=self.profile,
                offset=offset,
                constant=operation.operands["k"],
                cell=self.memory.cell(address),
            )
            return frame, [address]

        offsets = (operation.operands["a"], operation.operands["b"], operation.operands["c"])
        addresses = [protocol.checked_add(self.fp, offset) for offset in offsets]
        cells = self._cells(addresses)
        opcode = _LSC1_OPCODE[operation.kind]
        frame = protocol.build_binary_op(
            opcode,
            txn_id=self.txn_id,
            pc=self.pc,
            fp=self.fp,
            profile=self.profile,
            offsets=offsets,
            cells=cells,
            proposed_inverse=self._inverse_witness(opcode, cells),
        )
        return frame, addresses

    def _inverse_witness(self, opcode, cells) -> "protocol.Cell":
        """Propose ``known**-1`` only when the endpoint will actually back-solve.

        A witness is needed exactly when the destination is written and exactly
        one operand is absent, and only in INTERPRETER_COMPAT.  Anywhere else
        the endpoint ignores the field, so the host sends nothing.
        """
        if opcode is not protocol.Opcode.MUL_NATIVE:
            return protocol.ABSENT
        if self.profile is not protocol.Profile.INTERPRETER_COMPAT:
            return protocol.ABSENT
        left, right, destination = cells
        if not destination.present or left.present == right.present:
            return protocol.ABSENT
        known = left if left.present else right
        if known.value == 0:
            # The endpoint answers MUL_BACKSOLVE_ZERO; no witness exists.
            return protocol.ABSENT
        return protocol.Cell(True, field_inverse(known.value))

    # --- transition ---------------------------------------------------------

    def step(self) -> StepRecord:
        operation = self.program.at(self.pc)
        frame, addresses = self._prepare(operation)
        record = StepRecord(
            index=self.step_index,
            txn_id=self.txn_id,
            source_op=operation.kind,
            opcode=protocol.Opcode(frame.opcode).name,
            pc=self.pc,
            fp=self.fp,
        )
        self.step_index += 1
        record.addresses = addresses
        record.inputs = self._inputs(addresses)

        before = self.lane_cycles
        reply = self._exchange(frame)
        if reply.status is not protocol.Status.OK:
            record.status = reply.status.name
            record.fault = reply.status.name
            record.lane_cycles = self.lane_cycles - before
            self.faulted = True
            return record

        result = decode_result_payload(reply.payload)
        retire = self._exchange(
            protocol.build_retire(
                txn_id=result["txn_id"],
                result_crc=protocol.crc32(reply.payload),
            )
        )
        if retire.status is not protocol.Status.RETIRED:
            record.status = retire.status.name
            record.fault = retire.status.name
            record.lane_cycles = self.lane_cycles - before
            self.faulted = True
            return record

        for write in result["writes"]:
            self.memory.apply_write(write["address"], write["value"])
        for address in result["accesses"]:
            self.memory.count_access(address)
        for item in result["deferred"]:
            self.memory.record_deferred(item["target"], item["local"])

        self.pc = result["next_pc"]
        self.fp = result["next_fp"]
        record.next_pc = result["next_pc"]
        record.next_fp = result["next_fp"]
        record.writes = [
            {"address": write["address"], "value": f"{write['value']:#034x}"}
            for write in result["writes"]
        ]
        record.deferred = result["deferred"]
        record.accesses = result["accesses"]
        record.status = protocol.Status.OK.name
        record.retire_seq = int.from_bytes(retire.payload[4:8], "little")
        record.lane_cycles = self.lane_cycles - before
        return record

    def run(self, *, max_steps: int = 1024) -> RunResult:
        """Step until the sentinel, a fault, an unsupported opcode or the limit."""
        records: list[StepRecord] = []
        for _ in range(max_steps):
            if self.pc == self.program.halt_pc:
                return RunResult(records, "halted", f"reached sentinel pc {self.pc}")
            try:
                record = self.step()
            except UnsupportedCapability as error:
                return RunResult(records, "unsupported", str(error))
            records.append(record)
            if record.fault is not None:
                return RunResult(records, "fault", f"pc {record.pc} answered {record.fault}")
        return RunResult(records, "step_limit", f"stopped after {max_steps} steps")

    # --- reporting ----------------------------------------------------------

    def final_state(self, memory_cells: int) -> dict:
        return {
            "pc": self.pc,
            "fp": self.fp,
            "cycles": self.step_index,
            "lane_cycles": self.lane_cycles,
            "memory": [f"{value:#034x}" for value in self.memory.image(memory_cells)],
            "written": sorted(self.memory.cells),
            "open_deferred": [
                {"target": target, "local": local} for target, local in self.memory.deferred
            ],
        }
