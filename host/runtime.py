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

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import (
    PreparationFault,
    ProtocolViolation,
    TransactionRejected,
    UnsupportedCapability,
)
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


#: Protocol section 8.6: ``u32le`` txn_id plus one non-normative detail byte.
FAULT_PAYLOAD_BYTES = 5

#: Section 9.1 frame-level rejections: the framing faults ``BAD_SOF``..
#: ``BAD_FLAGS``, which never reach a handler, plus the two guard faults that
#: fire *because* the endpoint holds a transaction the host did not expect.
#: None of them decided anything, so none can be a transition's outcome.  The
#: remaining guard faults (``BAD_PROFILE``, ``STATE_MISMATCH``, ``INDEX_RANGE``
#: on a preamble) are checked only after the endpoint has confirmed it is
#: ``IDLE``, so they leave nothing outstanding and are real refusals.
FRAME_ONLY_FAULTS = frozenset({
    protocol.Status.BAD_SOF,
    protocol.Status.BAD_VERSION,
    protocol.Status.BAD_OPCODE,
    protocol.Status.BAD_LENGTH,
    protocol.Status.BAD_CRC,
    protocol.Status.BAD_FLAGS,
    protocol.Status.BAD_STATE,
    protocol.Status.BAD_SERVICE,
})

#: Section 9.1, third class: the only fault that reaches ``RETIRE`` after the
#: endpoint folded the host's result in, and therefore the only one that
#: discards the staged transition rather than leaving it ``RESULT_PENDING``.
RETIRE_DISCARDING_FAULTS = frozenset({protocol.Status.RETIRE_MISMATCH})


def check_fault_response(
    reply: "protocol.ResponseFrame",
    *,
    expected_txn_id: int,
    where: str = "instruction",
    staged: bool = False,
) -> None:
    """Refuse a non-``OK`` response that cannot be this step's fault.

    A well-framed response is not evidence on its own: only a defined fault
    status carrying the section 8.6 payload and echoing the transaction in
    flight may be recorded against this step.  Anything else is a protocol
    violation, and treating it as a fault would end the run while the real
    transaction is still staged on the endpoint.

    Echoing the right transaction is necessary but not sufficient.  Section 9.1
    splits faults by what they do to an outstanding transaction, and the split
    depends on what is in flight.  ``staged`` says the endpoint is known to hold
    a decided transition -- true only at ``RETIRE``.  Then a fault ends the run
    honestly only if it discarded that transition; every other fault leaves it
    ``RESULT_PENDING`` and needs retry or recovery, which this scaffold does not
    implement.  With nothing staged the weaker test applies: a frame-level
    rejection decided nothing, so it cannot be the transition's outcome.
    """
    if int(reply.status) < 0x80:
        raise ProtocolViolation(
            f"{where} answered {reply.status.name}, which is not a fault status"
        )
    if len(reply.payload) != FAULT_PAYLOAD_BYTES:
        raise ProtocolViolation(
            f"{where} fault payload has {len(reply.payload)} bytes, "
            f"expected {FAULT_PAYLOAD_BYTES}"
        )
    echoed = int.from_bytes(reply.payload[0:4], "little")
    if echoed != expected_txn_id:
        raise ProtocolViolation(
            f"{where} fault echoed txn_id {echoed}, expected {expected_txn_id}"
        )
    if staged:
        if reply.status not in RETIRE_DISCARDING_FAULTS:
            raise ProtocolViolation(
                f"{where} answered {reply.status.name}, which does not discard "
                "the staged transition under section 9.1; it would be left "
                "outstanding, so it is not this step's outcome"
            )
    elif reply.status in FRAME_ONLY_FAULTS:
        raise ProtocolViolation(
            f"{where} answered {reply.status.name}, a section 9.1 frame-level "
            "rejection that decided nothing; it is not this step's outcome"
        )


def decode_result_payload(payload: bytes, *, expected_txn_id: int | None = None) -> dict:
    """Decode an ``OK`` transition result (protocol section 8)."""
    def u32(offset: int) -> int:
        return int.from_bytes(payload[offset:offset + 4], "little")

    if len(payload) < 12:
        raise ProtocolViolation("result payload too short for header")
    txn_id, next_pc, next_fp = u32(0), u32(4), u32(8)
    if expected_txn_id is not None and txn_id != expected_txn_id:
        raise ProtocolViolation(
            f"result echoed txn_id {txn_id}, expected {expected_txn_id}"
        )
    cursor = 12
    if cursor >= len(payload):
        raise ProtocolViolation("result payload truncated before write count")
    writes = []
    try:
        for _ in range(payload[cursor]):
            base = cursor + 1
            if base + 20 > len(payload):
                raise ProtocolViolation("result payload truncated in writes")
            writes.append({
                "address": int.from_bytes(payload[base:base + 4], "little"),
                "value": int.from_bytes(payload[base + 4:base + 20], "little"),
            })
            cursor += protocol.WRITE_BYTES
    except IndexError as e:
        raise ProtocolViolation("result payload truncated in writes") from e
    cursor += 1
    if cursor >= len(payload):
        raise ProtocolViolation("result payload truncated before deferred count")
    deferred = []
    try:
        for _ in range(payload[cursor]):
            base = cursor + 1
            if base + 8 > len(payload):
                raise ProtocolViolation("result payload truncated in deferred")
            deferred.append({
                "target": int.from_bytes(payload[base:base + 4], "little"),
                "local": int.from_bytes(payload[base + 4:base + 8], "little"),
            })
            cursor += protocol.DEFERRED_BYTES
    except IndexError as e:
        raise ProtocolViolation("result payload truncated in deferred") from e
    cursor += 1
    if cursor >= len(payload):
        raise ProtocolViolation("result payload truncated before access count")
    accesses = []
    try:
        for _ in range(payload[cursor]):
            base = cursor + 1
            if base + 4 > len(payload):
                raise ProtocolViolation("result payload truncated in accesses")
            accesses.append(int.from_bytes(payload[base:base + 4], "little"))
            cursor += protocol.ACCESS_BYTES
    except IndexError as e:
        raise ProtocolViolation("result payload truncated in accesses") from e
    if cursor + 1 != len(payload):
        raise ProtocolViolation(f"result payload has {len(payload)} bytes, consumed {cursor + 1}")
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
        rx_gaps: list[int] | None = None,
        tx_gaps: list[int] | None = None,
    ) -> None:
        self.program = program
        self.memory = memory or HostMemory.with_public_input(1, 0)
        self.endpoint = endpoint or protocol.Lsc1Endpoint()
        self.profile = profile
        self.rx_gaps = list(rx_gaps) if rx_gaps else None
        self.tx_gaps = list(tx_gaps) if tx_gaps else None
        self.pc = program.pc0
        self.fp = program.fp0
        self.txn_id = 0
        self.step_index = 0
        self.lane_cycles = 0
        self.faulted = False
        self._negotiate()

    # --- byte lane ----------------------------------------------------------

    def _exchange(self, frame: "protocol.RequestFrame") -> "protocol.ResponseFrame":
        raw, cycles = protocol.drive(
            self.endpoint, frame.encode(),
            rx_gaps=self.rx_gaps,
            tx_gaps=self.tx_gaps,
        )
        self.lane_cycles += cycles
        return protocol.decode_response(raw)

    def _negotiate(self) -> None:
        reply = self._exchange(protocol.build_negotiate(profile=self.profile))
        if reply.status is not protocol.Status.OK:
            raise TransactionRejected(reply.status, reply.payload)
        expected = (
            bytes((protocol.PROTOCOL_VERSION, int(self.profile)))
            + protocol.u16le(protocol.MAX_PAYLOAD_BYTES)
            + bytes((protocol.INDEX_BITS, 0))
            + protocol.u32le(protocol.DEVICE_FEATURES)
            + protocol.u32le(protocol.DEVICE_ID)
        )
        if reply.payload != expected:
            raise ProtocolViolation(
                "NEGOTIATE response does not match the required 14-byte schema: "
                f"got {reply.payload.hex()}, expected {expected.hex()}"
            )

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

    def _address(self, offset: int) -> int:
        """``fp + offset`` as a host refusal, not as a lane-level fault.

        ``checked_add`` signals with the same ``ProtocolFault`` type that
        ``decode_response`` uses for a corrupted frame, so it is translated
        here: only this one, raised before anything is sent, may end a run.
        """
        try:
            return protocol.checked_add(self.fp, offset)
        except protocol.ProtocolFault as fault:
            raise PreparationFault(fault.status) from fault

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
            address = self._address(offset)
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
        addresses = [self._address(offset) for offset in offsets]
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
            check_fault_response(reply, expected_txn_id=self.txn_id)
            record.status = reply.status.name
            record.fault = reply.status.name
            record.lane_cycles = self.lane_cycles - before
            self.faulted = True
            return record

        result = decode_result_payload(reply.payload, expected_txn_id=self.txn_id)

        # The whole write batch is checked before RETIRE goes out, because RETIRE is
        # what makes the endpoint commit its pc/fp. Rejecting afterwards would leave
        # the endpoint advanced against host state that never moved, and the retry
        # would only ever see STATE_MISMATCH. Refusing first leaves the transaction
        # RESULT_PENDING, which is recoverable.
        writes = result["writes"]
        proposed: dict[int, int] = {}
        for write in writes:
            prior = proposed.get(write["address"])
            if prior is not None and prior != write["value"]:
                raise ProtocolViolation(
                    "result payload contains conflicting writes to address "
                    f"{write['address']}: {prior:#034x} != {write['value']:#034x}"
                )
            proposed[write["address"]] = write["value"]
            self.memory.prevalidate_write(write["address"], write["value"])

        # Deferred equalities can also write cells while they are reconciled.
        # Exercise the exact post-RETIRED order on isolated state before RETIRE
        # commits the endpoint.  This includes deferred pairs from earlier steps:
        # a new direct write may make one of those pairs contradictory.
        staged = HostMemory(
            cells=dict(self.memory.cells),
            deferred=list(self.memory.deferred),
        )
        for write in writes:
            staged.apply_write(write["address"], write["value"])
        for item in result["deferred"]:
            staged.record_deferred(item["target"], item["local"])
        staged.resolve_deferred()

        # The host packed this frame, so it knows every address the transition
        # was handed. Section 14 leaves the transition *decision* to the
        # endpoint, and none of this second-guesses it, but an effect on a cell
        # that was never in the request is outside the frame rather than a
        # decision about it: the host never sent that cell, so the endpoint
        # cannot have reasoned about its current value, and applying it would
        # corrupt a memory image section 14 makes the host's own.  A deferred
        # equality is such an effect too, just a delayed one: resolving it writes
        # whichever side is still unknown.
        in_frame = set(addresses)
        for write in writes:
            if write["address"] not in in_frame:
                raise ProtocolViolation(
                    f"result writes address {write['address']}, which "
                    f"{record.opcode} did not carry; frame addresses are "
                    f"{sorted(in_frame)}"
                )
        for item in result["deferred"]:
            for role in ("target", "local"):
                if item[role] not in in_frame:
                    raise ProtocolViolation(
                        f"result defers an equality whose {role} is address "
                        f"{item[role]}, which {record.opcode} did not carry; "
                        f"frame addresses are {sorted(in_frame)}"
                    )
        for address in result["accesses"]:
            if address not in in_frame:
                raise ProtocolViolation(
                    f"result counts an access to address {address}, which "
                    f"{record.opcode} did not carry; frame addresses are "
                    f"{sorted(in_frame)}"
                )

        retire = self._exchange(
            protocol.build_retire(
                txn_id=result["txn_id"],
                result_crc=protocol.crc32(reply.payload),
            )
        )
        if retire.status is not protocol.Status.RETIRED:
            check_fault_response(
                retire, expected_txn_id=self.txn_id, where="retire", staged=True
            )
            record.status = retire.status.name
            record.fault = retire.status.name
            record.lane_cycles = self.lane_cycles - before
            self.faulted = True
            return record
        if len(retire.payload) != 16:
            raise ProtocolViolation(
                f"retire payload has {len(retire.payload)} bytes, expected 16"
            )
        retired_txn_id = int.from_bytes(retire.payload[0:4], "little")
        if retired_txn_id != self.txn_id:
            raise ProtocolViolation(
                f"retire echoed txn_id {retired_txn_id}, expected {self.txn_id}"
            )
        committed_pc = int.from_bytes(retire.payload[8:12], "little")
        committed_fp = int.from_bytes(retire.payload[12:16], "little")
        if (committed_pc, committed_fp) != (result["next_pc"], result["next_fp"]):
            raise ProtocolViolation(
                "retire committed scalar state "
                f"{(committed_pc, committed_fp)}, expected "
                f"{(result['next_pc'], result['next_fp'])}"
            )

        # Prevalidated above and nothing has mutated memory since, so this cannot
        # leave a partial batch behind.
        for write in writes:
            self.memory.apply_write(write["address"], write["value"])
        for address in result["accesses"]:
            self.memory.count_access(address)
        for item in result["deferred"]:
            self.memory.record_deferred(item["target"], item["local"])

        # Reach fixpoint on deferred equalities before the next step (or future DEREF).
        self.memory.resolve_deferred()

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
                if self.fp != 0:
                    return RunResult(
                        records,
                        "fault",
                        f"bad_halt_state: sentinel pc {self.pc} reached with fp {self.fp}",
                    )
                return RunResult(records, "halted", f"reached sentinel pc {self.pc}")
            try:
                record = self.step()
            except UnsupportedCapability as error:
                return RunResult(records, "unsupported", str(error))
            except PreparationFault as fault:
                # Only a refusal raised before the request was sent: nothing is
                # staged, so ending the run here strands nothing. A frame that
                # fails to decode on the way back is not this, and must not be
                # reported as one -- the endpoint may hold a pending or an
                # already-committed transaction, so it keeps propagating.
                self.faulted = True
                return RunResult(
                    records,
                    "fault",
                    f"pc {self.pc} raised {fault.status.name.lower()} preparing the transaction",
                )
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
