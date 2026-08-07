"""Executable LSC-1 transaction protocol v1: codec, transaction/service model.

This module is the normative executable companion to
``docs/LSC1_TRANSACTION_PROTOCOL.md``.  It is a *host-and-endpoint* model of
one host-prepared scalar instruction transaction at a time, and it is
deliberately self-contained: it owns its field arithmetic, its CRC, its frame
codec, and its transition rules.  It does not import ``scalar_step_oracle``,
``model``, or ``cycle_model``, so it can serve as an independent oracle for a
later RTL packet executor and for differential comparison against the existing
scalar oracle.

Semantic authority is the frozen upstream
``leanEthereum/leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649``:
``crates/lean_vm/src/cpu/{isa.rs,execute.rs,mod.rs,layout.rs}`` and
``misc/doc.tex``.  Where the executable runner and the document disagree, both
readings are preserved as explicit profiles (``Profile.INTERPRETER_COMPAT`` and
``Profile.FORWARD_ONLY``); nothing is silently chosen.

Nothing here is an RTL claim, a formal-verification claim, or a synthesis
measurement.  The cycle budgets are arithmetic over the stated assumptions in
``BudgetAssumptions``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum

# --- Field: GF(2^128) = F2[x]/(x^128 + x^7 + x^2 + x + 1), generator g = x. ---

MASK128 = (1 << 128) - 1
REDUCTION_LOW = 0x87
U32_MAX = (1 << 32) - 1

#: Host-proposed g-power indices are verified by re-encoding, so v1 bounds them
#: by the frozen minimum memory exponent ``MIN_LOG_MEM = 16`` (`cpu/mod.rs`).
INDEX_BITS = 16
INDEX_LIMIT = 1 << INDEX_BITS

# --- Framing constants. -----------------------------------------------------

PROTOCOL_VERSION = 1
SOF_REQUEST = 0xA1
SOF_RESPONSE = 0x5A
REQUEST_HEADER_BYTES = 6
RESPONSE_HEADER_BYTES = 5
CRC_BYTES = 4
MAX_PAYLOAD_BYTES = 256
DEVICE_ID = 0x4C534331  # "LSC1"
DEVICE_FEATURES = 0b111  # both profiles + BLAKE3 service offload

CELL_BYTES = 17
WRITE_BYTES = 20
DEFERRED_BYTES = 8
ACCESS_BYTES = 4
TRANSACTION_PREAMBLE_BYTES = 14


class Opcode(IntEnum):
    """Request opcodes; coordinate 2 of the request envelope."""

    XOR = 0x01
    MUL_NATIVE = 0x02
    SET_CONSTANT = 0x03
    DEREF_CELL = 0x04
    DEREF_PC = 0x05
    DEREF_FP = 0x06
    JUMP = 0x07
    BLAKE3_REQUEST = 0x08
    NEGOTIATE = 0x10
    SERVICE_RESPONSE = 0x11
    RETIRE = 0x12
    STATUS_QUERY = 0x13


INSTRUCTION_OPCODES = (
    Opcode.XOR,
    Opcode.MUL_NATIVE,
    Opcode.SET_CONSTANT,
    Opcode.DEREF_CELL,
    Opcode.DEREF_PC,
    Opcode.DEREF_FP,
    Opcode.JUMP,
    Opcode.BLAKE3_REQUEST,
)

REQUEST_PAYLOAD_BYTES = {
    Opcode.XOR: 77,
    Opcode.MUL_NATIVE: 94,
    Opcode.SET_CONSTANT: 51,
    Opcode.DEREF_CELL: 81,
    Opcode.DEREF_PC: 81,
    Opcode.DEREF_FP: 81,
    Opcode.JUMP: 103,
    Opcode.BLAKE3_REQUEST: 190,
    Opcode.NEGOTIATE: 7,
    Opcode.SERVICE_RESPONSE: 42,
    Opcode.RETIRE: 8,
    Opcode.STATUS_QUERY: 0,
}


class Status(IntEnum):
    """Response status; codes at or above ``0x80`` are faults."""

    OK = 0x00
    SERVICE_REQUIRED = 0x01
    RETIRED = 0x02
    INFO = 0x03
    BAD_SOF = 0x80
    BAD_VERSION = 0x81
    BAD_OPCODE = 0x82
    BAD_LENGTH = 0x83
    BAD_CRC = 0x84
    BAD_FLAGS = 0x85
    BAD_PROFILE = 0x86
    BAD_STATE = 0x87
    BAD_CELL = 0x88
    U32_OVERFLOW = 0x89
    BAD_POINTER = 0x8A
    BAD_INVERSE = 0x8B
    WRITE_CONFLICT = 0x8C
    DEREF_MISMATCH = 0x8D
    MUL_BACKSOLVE_ZERO = 0x8E
    BAD_BRANCH_PROPOSAL = 0x8F
    UNSUPPORTED_IN_PROFILE = 0x90
    BAD_SERVICE = 0x91
    RETIRE_MISMATCH = 0x92
    ABORTED = 0x93
    STATE_MISMATCH = 0x94
    INDEX_RANGE = 0x95
    ALIAS_INCONSISTENT = 0x96


class Profile(IntEnum):
    """Which frozen reading of the disputed opcodes is in force.

    ``FORWARD_ONLY`` follows ``misc/doc.tex``: XOR/MUL/DEREF are forward
    constraints, so every input a transition consumes must already be written.
    ``INTERPRETER_COMPAT`` follows ``crates/lean_vm/src/cpu/execute.rs``: XOR
    and MUL back-solve one absent operand when the result is present, and
    ``DEREF`` cell mode reconciles four quadrants including a deferred
    equality.
    """

    FORWARD_ONLY = 0x00
    INTERPRETER_COMPAT = 0x01


DEFAULT_PROFILE = Profile.INTERPRETER_COMPAT


class ServiceKind(IntEnum):
    BLAKE3_COMPRESS = 0x01


class TxnState(Enum):
    """Transaction state machine (see the protocol document, §Transaction)."""

    IDLE = "idle"
    RESULT_PENDING = "result_pending"
    SERVICE_PENDING = "service_pending"


class ProtocolFault(Exception):
    """A fault that terminates the current frame or transaction.

    ``status`` is the response status byte; ``detail`` is an opaque
    disambiguator echoed in the fault payload (never load-bearing).
    """

    def __init__(self, status: Status, detail: int = 0) -> None:
        super().__init__(status.name.lower())
        self.status = status
        self.detail = detail & 0xFF


def field_xtime(value: int) -> int:
    """Multiply by the generator g = x."""
    doubled = (value << 1) & MASK128
    return doubled ^ REDUCTION_LOW if value >> 127 else doubled


def field_mul(left: int, right: int) -> int:
    """GHASH product, accumulated through repeated ``field_xtime``."""
    accumulator = 0
    term = left & MASK128
    for bit in range(128):
        if (right >> bit) & 1:
            accumulator ^= term
        term = field_xtime(term)
    return accumulator


def field_encode(index: int) -> int:
    """``g**index`` by square-and-multiply; the endpoint's pointer check."""
    if index < 0 or index >= INDEX_LIMIT:
        raise ProtocolFault(Status.INDEX_RANGE)
    result = 1
    for bit in reversed(range(INDEX_BITS)):
        result = field_mul(result, result)
        if (index >> bit) & 1:
            result = field_xtime(result)
    return result


def checked_add(left: int, right: int) -> int:
    """u32 address arithmetic with an explicit fault instead of a wrap."""
    total = left + right
    if total > U32_MAX:
        raise ProtocolFault(Status.U32_OVERFLOW)
    return total


CRC32_POLYNOMIAL = 0xEDB88320


def crc32(data: bytes) -> int:
    """Reflected CRC-32 (IEEE 802.3), bit at a time, no lookup table."""
    register = 0xFFFFFFFF
    for byte in data:
        register ^= byte
        for _ in range(8):
            register = (register >> 1) ^ (CRC32_POLYNOMIAL if register & 1 else 0)
    return register ^ 0xFFFFFFFF


# --- Payload primitives. ----------------------------------------------------


def u8(value: int) -> bytes:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"u8 out of range: {value}")
    return bytes((value,))


def u16le(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"u16 out of range: {value}")
    return value.to_bytes(2, "little")


def u32le(value: int) -> bytes:
    if not 0 <= value <= U32_MAX:
        raise ValueError(f"u32 out of range: {value}")
    return value.to_bytes(4, "little")


def f128le(value: int) -> bytes:
    if not 0 <= value <= MASK128:
        raise ValueError("field element out of range")
    return value.to_bytes(16, "little")


@dataclass(frozen=True)
class Cell:
    """A host-supplied write-once memory cell: presence bit plus value."""

    present: bool
    value: int = 0

    def encode(self) -> bytes:
        return u8(1 if self.present else 0) + f128le(self.value)


ABSENT = Cell(False, 0)


class _Reader:
    """Bounds-checked little-endian payload reader."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, count: int) -> bytes:
        end = self.offset + count
        if end > len(self.data):
            raise ProtocolFault(Status.BAD_LENGTH)
        chunk = self.data[self.offset : end]
        self.offset = end
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), "little")

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def f128(self) -> int:
        return int.from_bytes(self.take(16), "little")

    def cell(self) -> Cell:
        present = self.u8()
        value = self.f128()
        if present > 1:
            raise ProtocolFault(Status.BAD_CELL)
        if present == 0 and value != 0:
            # An absent cell has no value; a nonzero one would smuggle data
            # past the write-once bookkeeping the host owns.
            raise ProtocolFault(Status.BAD_CELL)
        return Cell(bool(present), value)

    def done(self) -> None:
        if self.offset != len(self.data):
            raise ProtocolFault(Status.BAD_LENGTH)


# --- Frame codec. -----------------------------------------------------------


@dataclass(frozen=True)
class RequestFrame:
    opcode: Opcode
    payload: bytes
    flags: int = 0
    version: int = PROTOCOL_VERSION
    sof: int = SOF_REQUEST

    def encode(self) -> bytes:
        body = (
            u8(self.sof)
            + u8(self.version)
            + u8(int(self.opcode))
            + u8(self.flags)
            + u16le(len(self.payload))
            + self.payload
        )
        return body + u32le(crc32(body))


@dataclass(frozen=True)
class ResponseFrame:
    status: Status
    payload: bytes
    version: int = PROTOCOL_VERSION
    sof: int = SOF_RESPONSE

    def encode(self) -> bytes:
        body = (
            u8(self.sof)
            + u8(self.version)
            + u8(int(self.status))
            + u16le(len(self.payload))
            + self.payload
        )
        return body + u32le(crc32(body))


def decode_response(frame: bytes) -> ResponseFrame:
    """Host-side response decoder; raises ``ProtocolFault`` on malformation."""
    if len(frame) < RESPONSE_HEADER_BYTES + CRC_BYTES:
        raise ProtocolFault(Status.BAD_LENGTH)
    if frame[0] != SOF_RESPONSE:
        raise ProtocolFault(Status.BAD_SOF)
    if frame[1] != PROTOCOL_VERSION:
        raise ProtocolFault(Status.BAD_VERSION)
    length = int.from_bytes(frame[3:5], "little")
    if len(frame) != RESPONSE_HEADER_BYTES + length + CRC_BYTES:
        raise ProtocolFault(Status.BAD_LENGTH)
    body = frame[: RESPONSE_HEADER_BYTES + length]
    if int.from_bytes(frame[-CRC_BYTES:], "little") != crc32(body):
        raise ProtocolFault(Status.BAD_CRC)
    return ResponseFrame(Status(frame[2]), body[RESPONSE_HEADER_BYTES:])


def request_frame_bytes(opcode: Opcode) -> int:
    return REQUEST_HEADER_BYTES + REQUEST_PAYLOAD_BYTES[opcode] + CRC_BYTES


def response_frame_bytes(payload_bytes: int) -> int:
    return RESPONSE_HEADER_BYTES + payload_bytes + CRC_BYTES


# --- Request payload builders (host side). ----------------------------------


def transaction_preamble(txn_id: int, pc: int, fp: int, profile: Profile) -> bytes:
    return u32le(txn_id) + u32le(pc) + u32le(fp) + u8(int(profile)) + u8(0)


def build_binary_op(
    opcode: Opcode,
    *,
    txn_id: int,
    pc: int,
    fp: int,
    profile: Profile,
    offsets: tuple[int, int, int],
    cells: tuple[Cell, Cell, Cell],
    proposed_inverse: Cell = ABSENT,
) -> RequestFrame:
    payload = transaction_preamble(txn_id, pc, fp, profile)
    payload += b"".join(u32le(offset) for offset in offsets)
    payload += b"".join(cell.encode() for cell in cells)
    if opcode is Opcode.MUL_NATIVE:
        payload += proposed_inverse.encode()
    return RequestFrame(opcode, payload)


def build_set_constant(
    *,
    txn_id: int,
    pc: int,
    fp: int,
    profile: Profile,
    offset: int,
    constant: int,
    cell: Cell,
) -> RequestFrame:
    payload = transaction_preamble(txn_id, pc, fp, profile)
    payload += u32le(offset) + f128le(constant) + cell.encode()
    return RequestFrame(Opcode.SET_CONSTANT, payload)


def build_deref(
    opcode: Opcode,
    *,
    txn_id: int,
    pc: int,
    fp: int,
    profile: Profile,
    alpha: int,
    beta: int,
    gamma: int,
    pointer: Cell,
    base: int,
    target: Cell,
    local: Cell,
) -> RequestFrame:
    payload = transaction_preamble(txn_id, pc, fp, profile)
    payload += u32le(alpha) + u32le(beta) + u32le(gamma)
    payload += pointer.encode() + u32le(base) + target.encode() + local.encode()
    return RequestFrame(opcode, payload)


def build_jump(
    *,
    txn_id: int,
    pc: int,
    fp: int,
    profile: Profile,
    offsets: tuple[int, int, int],
    cells: tuple[Cell, Cell, Cell],
    taken: bool,
    dest_pc: int,
    dest_fp: int,
    proposed_inverse: Cell,
) -> RequestFrame:
    payload = transaction_preamble(txn_id, pc, fp, profile)
    payload += b"".join(u32le(offset) for offset in offsets)
    payload += b"".join(cell.encode() for cell in cells)
    payload += u8(1 if taken else 0) + u32le(dest_pc) + u32le(dest_fp)
    payload += proposed_inverse.encode()
    return RequestFrame(Opcode.JUMP, payload)


def build_blake3(
    *,
    txn_id: int,
    pc: int,
    fp: int,
    profile: Profile,
    message_offsets: tuple[int, int, int, int],
    cv_offset: int,
    out_offset: int,
    metadata: int,
    message_cells: tuple[Cell, Cell, Cell, Cell],
    cv_cells: tuple[Cell, Cell],
    out_cells: tuple[Cell, Cell],
) -> RequestFrame:
    payload = transaction_preamble(txn_id, pc, fp, profile)
    payload += b"".join(u32le(offset) for offset in message_offsets)
    payload += u32le(cv_offset) + u32le(out_offset) + f128le(metadata)
    payload += b"".join(cell.encode() for cell in message_cells)
    payload += b"".join(cell.encode() for cell in cv_cells)
    payload += b"".join(cell.encode() for cell in out_cells)
    return RequestFrame(Opcode.BLAKE3_REQUEST, payload)


def build_negotiate(
    *, version_min: int = PROTOCOL_VERSION, version_max: int = PROTOCOL_VERSION,
    profile: Profile = DEFAULT_PROFILE, host_features: int = 0,
) -> RequestFrame:
    payload = u8(version_min) + u8(version_max) + u8(int(profile)) + u32le(host_features)
    return RequestFrame(Opcode.NEGOTIATE, payload)


def build_service_response(
    *, txn_id: int, service_id: int, digest: tuple[int, int],
    kind: ServiceKind = ServiceKind.BLAKE3_COMPRESS,
) -> RequestFrame:
    payload = u32le(txn_id) + u32le(service_id) + u8(int(kind)) + u8(0)
    payload += f128le(digest[0]) + f128le(digest[1])
    return RequestFrame(Opcode.SERVICE_RESPONSE, payload)


def build_retire(*, txn_id: int, result_crc: int) -> RequestFrame:
    return RequestFrame(Opcode.RETIRE, u32le(txn_id) + u32le(result_crc))


def build_status_query() -> RequestFrame:
    return RequestFrame(Opcode.STATUS_QUERY, b"")


# --- Transition result records. ---------------------------------------------


@dataclass(frozen=True)
class Write:
    """A cell that this transition turns from unwritten to written."""

    address: int
    value: int

    def encode(self) -> bytes:
        return u32le(self.address) + f128le(self.value)


@dataclass(frozen=True)
class DeferredEquality:
    """An unresolved ``DEREF`` cell equality the host must finalize."""

    target: int
    local: int

    def encode(self) -> bytes:
        return u32le(self.target) + u32le(self.local)


@dataclass(frozen=True)
class ServiceRequest:
    service_id: int
    kind: ServiceKind
    message: tuple[int, int, int, int]
    chaining_value: tuple[int, int]
    metadata: int

    def encode(self, txn_id: int) -> bytes:
        payload = u32le(txn_id) + u32le(self.service_id) + u8(int(self.kind)) + u8(0)
        payload += b"".join(f128le(word) for word in self.message)
        payload += b"".join(f128le(word) for word in self.chaining_value)
        payload += f128le(self.metadata)
        return payload


@dataclass
class StagedTransaction:
    """A decided but *uncommitted* scalar transition.

    Nothing in this record has taken effect: the endpoint's committed
    ``(pc, fp)`` and its retirement counter only move when a matching
    ``RETIRE`` frame is accepted.
    """

    txn_id: int
    opcode: Opcode
    profile: Profile
    pc: int
    fp: int
    next_pc: int = 0
    next_fp: int = 0
    writes: list[Write] = field(default_factory=list)
    deferred: list[DeferredEquality] = field(default_factory=list)
    accesses: list[int] = field(default_factory=list)
    service: ServiceRequest | None = None
    execute_cycles: int = 0
    result_crc: int = 0
    pending_frame: _Frame | None = None

    def result_payload(self) -> bytes:
        payload = u32le(self.txn_id) + u32le(self.next_pc) + u32le(self.next_fp)
        payload += u8(len(self.writes))
        payload += b"".join(write.encode() for write in self.writes)
        payload += u8(len(self.deferred))
        payload += b"".join(item.encode() for item in self.deferred)
        payload += u8(len(self.accesses))
        payload += b"".join(u32le(address) for address in self.accesses)
        return payload


def result_payload_bytes(writes: int, deferred: int, accesses: int) -> int:
    return (
        12
        + 1
        + writes * WRITE_BYTES
        + 1
        + deferred * DEFERRED_BYTES
        + 1
        + accesses * ACCESS_BYTES
    )


# --- Scalar transition. -----------------------------------------------------


class _Frame:
    """The transition's private view of the cells the host supplied.

    Mirrors the frozen runner's ``mem``/``written`` pair over exactly the
    addresses this instruction touches, so operand aliasing behaves as it does
    upstream (a back-solved operand is visible to the forward step).
    """

    def __init__(self) -> None:
        self.cells: dict[int, Cell] = {}
        self.writes: list[Write] = []

    def supply(self, address: int, cell: Cell) -> None:
        existing = self.cells.get(address)
        if existing is not None and existing != cell:
            # Two operands naming one address must agree; the endpoint holds no
            # memory image and cannot pick a winner.
            raise ProtocolFault(Status.ALIAS_INCONSISTENT)
        self.cells[address] = cell

    def present(self, address: int) -> bool:
        return self.cells[address].present

    def read(self, address: int) -> int:
        cell = self.cells[address]
        return cell.value if cell.present else 0

    def write_once(self, address: int, value: int) -> None:
        cell = self.cells[address]
        if cell.present:
            if cell.value != value:
                raise ProtocolFault(Status.WRITE_CONFLICT)
            return
        self.cells[address] = Cell(True, value)
        self.writes.append(Write(address, value))


@dataclass(frozen=True)
class BudgetAssumptions:
    """Stated assumptions behind every cycle number in this module.

    These are assumptions, not measurements: no simulation, synthesis, or
    silicon result is implied.  One committed ready/valid beat carries one
    byte per clock at full rate; the field multiplier is the bit-serial
    datapath already exercised in ``asic_core/rtl``; squaring reuses it.
    """

    beat: int = 1
    field_mul: int = 128
    field_xor: int = 1
    xtime: int = 1
    compare: int = 1
    decode: int = 2

    def encode_index(self) -> int:
        """Cost of re-deriving ``g**index`` for a host-proposed index."""
        return INDEX_BITS * self.field_mul + INDEX_BITS * self.xtime


ASSUMPTIONS = BudgetAssumptions()


def _verify_index(base: int, pointer: int) -> int:
    """Check a host-proposed g-power index against the pointer it decodes."""
    if base >= INDEX_LIMIT:
        raise ProtocolFault(Status.INDEX_RANGE)
    if field_encode(base) != pointer:
        raise ProtocolFault(Status.BAD_POINTER)
    return ASSUMPTIONS.encode_index()


def _execute_binary(request: _DecodedRequest, staged: StagedTransaction) -> None:
    is_xor = request.opcode is Opcode.XOR
    frame = _Frame()
    addresses = [checked_add(staged.fp, offset) for offset in request.offsets]
    for address, cell in zip(addresses, request.cells):
        frame.supply(address, cell)
    address_a, address_b, address_c = addresses
    cycles = 0

    absent = [not frame.present(address) for address in (address_a, address_b)]
    if request.profile is Profile.FORWARD_ONLY:
        if any(absent):
            # doc.tex states a forward constraint; an absent input has no value.
            raise ProtocolFault(Status.UNSUPPORTED_IN_PROFILE)
    elif frame.present(address_c) and absent[0] != absent[1]:
        known_address = address_b if absent[0] else address_a
        missing_address = address_a if absent[0] else address_b
        known = frame.read(known_address)
        if is_xor:
            frame.write_once(missing_address, frame.read(address_c) ^ known)
            cycles += ASSUMPTIONS.field_xor
        else:
            if known == 0:
                raise ProtocolFault(Status.MUL_BACKSOLVE_ZERO)
            if not request.proposed_inverse.present:
                raise ProtocolFault(Status.BAD_INVERSE, 1)
            inverse = request.proposed_inverse.value
            if field_mul(known, inverse) != 1:
                raise ProtocolFault(Status.BAD_INVERSE, 2)
            frame.write_once(missing_address, field_mul(frame.read(address_c), inverse))
            cycles += 2 * ASSUMPTIONS.field_mul

    left = frame.read(address_a)
    right = frame.read(address_b)
    if is_xor:
        frame.write_once(address_c, left ^ right)
        cycles += ASSUMPTIONS.field_xor
    else:
        frame.write_once(address_c, field_mul(left, right))
        cycles += ASSUMPTIONS.field_mul

    staged.writes = frame.writes
    staged.accesses = [address_a, address_b, address_c]
    staged.next_pc = checked_add(staged.pc, 1)
    staged.next_fp = staged.fp
    staged.execute_cycles = cycles


def _execute_set(request: _DecodedRequest, staged: StagedTransaction) -> None:
    frame = _Frame()
    address = checked_add(staged.fp, request.offsets[0])
    frame.supply(address, request.cells[0])
    frame.write_once(address, request.constant)
    staged.writes = frame.writes
    staged.accesses = [address]
    staged.next_pc = checked_add(staged.pc, 1)
    staged.next_fp = staged.fp
    staged.execute_cycles = 0


def _execute_deref(request: _DecodedRequest, staged: StagedTransaction) -> None:
    frame = _Frame()
    alpha, beta, gamma = request.offsets
    pointer_address = checked_add(staged.fp, alpha)
    local_address = checked_add(staged.fp, gamma)
    frame.supply(pointer_address, request.cells[0])
    cycles = _verify_index(request.base, frame.read(pointer_address))
    target_address = checked_add(request.base, beta)
    frame.supply(target_address, request.cells[1])
    frame.supply(local_address, request.cells[2])

    if request.opcode is Opcode.DEREF_CELL:
        has_target = frame.present(target_address)
        has_local = frame.present(local_address)
        if request.profile is Profile.FORWARD_ONLY:
            # doc.tex asserts v2 = v3 forward, so the local cell must exist.
            if not has_local:
                raise ProtocolFault(Status.UNSUPPORTED_IN_PROFILE)
            if has_target and frame.read(target_address) != frame.read(local_address):
                raise ProtocolFault(Status.DEREF_MISMATCH)
            frame.write_once(target_address, frame.read(local_address))
            cycles += ASSUMPTIONS.compare
        elif has_target and has_local:
            if frame.read(target_address) != frame.read(local_address):
                raise ProtocolFault(Status.DEREF_MISMATCH)
            cycles += ASSUMPTIONS.compare
        elif has_target:
            frame.write_once(local_address, frame.read(target_address))
        elif has_local:
            frame.write_once(target_address, frame.read(local_address))
        else:
            # Both sides unwritten: the frozen runner patches this row after the
            # walk, so the endpoint hands the obligation back to the host.
            staged.deferred = [DeferredEquality(target_address, local_address)]
    elif request.opcode is Opcode.DEREF_PC:
        # execute.rs writes gpow[pc + 2]; the isa.rs "pc+gamma" comment is stale.
        frame.write_once(target_address, field_encode(checked_add(staged.pc, 2)))
        cycles += ASSUMPTIONS.encode_index()
    else:
        frame.write_once(target_address, field_encode(staged.fp))
        cycles += ASSUMPTIONS.encode_index()

    staged.writes = frame.writes
    staged.accesses = [pointer_address, target_address, local_address]
    staged.next_pc = checked_add(staged.pc, 1)
    staged.next_fp = staged.fp
    staged.execute_cycles = cycles


def _execute_jump(request: _DecodedRequest, staged: StagedTransaction) -> None:
    frame = _Frame()
    addresses = [checked_add(staged.fp, offset) for offset in request.offsets]
    for address, cell in zip(addresses, request.cells):
        frame.supply(address, cell)
    condition_address, destination_address, frame_address = addresses
    condition = frame.read(condition_address)
    destination = frame.read(destination_address)
    new_frame = frame.read(frame_address)
    cycles = ASSUMPTIONS.compare

    taken = condition != 0
    if taken != request.taken:
        raise ProtocolFault(Status.BAD_BRANCH_PROPOSAL, 1)
    witness = request.proposed_inverse
    if taken:
        if not witness.present or field_mul(condition, witness.value) != 1:
            raise ProtocolFault(Status.BAD_INVERSE)
        cycles += ASSUMPTIONS.field_mul
        cycles += _verify_index(request.dest_pc, destination)
        cycles += _verify_index(request.dest_fp, new_frame)
        staged.next_pc = request.dest_pc
        staged.next_fp = request.dest_fp
    else:
        # doc.tex constrains w only through b = c*w; a zero condition forces
        # b = 0 and leaves w free, so v1 pins it to the frozen trace value 0.
        if witness.present and witness.value != 0:
            raise ProtocolFault(Status.BAD_INVERSE, 3)
        if request.dest_pc != 0 or request.dest_fp != 0:
            raise ProtocolFault(Status.BAD_BRANCH_PROPOSAL, 2)
        staged.next_pc = checked_add(staged.pc, 1)
        staged.next_fp = staged.fp

    staged.writes = frame.writes
    staged.accesses = [condition_address, destination_address, frame_address]
    staged.execute_cycles = cycles


def _blake3_addresses(request: _DecodedRequest, staged: StagedTransaction) -> list[int]:
    message = [checked_add(staged.fp, offset) for offset in request.message_offsets]
    cv_base = checked_add(staged.fp, request.cv_offset)
    out_base = checked_add(staged.fp, request.out_offset)
    return message + [
        cv_base,
        checked_add(cv_base, 1),
        out_base,
        checked_add(out_base, 1),
    ]


def _execute_blake3(request: _DecodedRequest, staged: StagedTransaction, service_id: int) -> None:
    frame = _Frame()
    addresses = _blake3_addresses(request, staged)
    for address, cell in zip(addresses, request.cells):
        frame.supply(address, cell)
    staged.accesses = addresses
    staged.next_pc = checked_add(staged.pc, 1)
    staged.next_fp = staged.fp
    staged.execute_cycles = 0
    staged.service = ServiceRequest(
        service_id=service_id,
        kind=ServiceKind.BLAKE3_COMPRESS,
        message=tuple(frame.read(address) for address in addresses[:4]),
        chaining_value=(frame.read(addresses[4]), frame.read(addresses[5])),
        metadata=request.metadata,
    )
    staged.pending_frame = frame


def _resume_blake3(staged: StagedTransaction, digest: tuple[int, int]) -> None:
    frame = staged.pending_frame
    if frame is None:
        raise ProtocolFault(Status.BAD_SERVICE, 4)
    out0, out1 = staged.accesses[6], staged.accesses[7]
    frame.write_once(out0, digest[0])
    frame.write_once(out1, digest[1])
    staged.writes = frame.writes
    staged.service = None


# --- Request decoding. ------------------------------------------------------


@dataclass
class _DecodedRequest:
    opcode: Opcode
    txn_id: int = 0
    pc: int = 0
    fp: int = 0
    profile: Profile = DEFAULT_PROFILE
    offsets: tuple[int, ...] = ()
    cells: tuple[Cell, ...] = ()
    constant: int = 0
    base: int = 0
    taken: bool = False
    dest_pc: int = 0
    dest_fp: int = 0
    proposed_inverse: Cell = ABSENT
    message_offsets: tuple[int, ...] = ()
    cv_offset: int = 0
    out_offset: int = 0
    metadata: int = 0
    service_id: int = 0
    service_kind: int = 0
    digest: tuple[int, int] = (0, 0)
    result_crc: int = 0
    version_min: int = 0
    version_max: int = 0
    host_features: int = 0


def _read_preamble(reader: _Reader, decoded: _DecodedRequest) -> None:
    decoded.txn_id = reader.u32()
    decoded.pc = reader.u32()
    decoded.fp = reader.u32()
    profile = reader.u8()
    if profile not in (int(Profile.FORWARD_ONLY), int(Profile.INTERPRETER_COMPAT)):
        raise ProtocolFault(Status.BAD_PROFILE)
    decoded.profile = Profile(profile)
    if reader.u8() != 0:
        raise ProtocolFault(Status.BAD_FLAGS, 1)


def decode_request_payload(opcode: Opcode, payload: bytes) -> _DecodedRequest:
    """Parse a payload whose length already matched the opcode's fixed size."""
    reader = _Reader(payload)
    decoded = _DecodedRequest(opcode)
    if opcode in (Opcode.XOR, Opcode.MUL_NATIVE):
        _read_preamble(reader, decoded)
        decoded.offsets = tuple(reader.u32() for _ in range(3))
        decoded.cells = tuple(reader.cell() for _ in range(3))
        if opcode is Opcode.MUL_NATIVE:
            decoded.proposed_inverse = reader.cell()
    elif opcode is Opcode.SET_CONSTANT:
        _read_preamble(reader, decoded)
        decoded.offsets = (reader.u32(),)
        decoded.constant = reader.f128()
        decoded.cells = (reader.cell(),)
    elif opcode in (Opcode.DEREF_CELL, Opcode.DEREF_PC, Opcode.DEREF_FP):
        _read_preamble(reader, decoded)
        decoded.offsets = tuple(reader.u32() for _ in range(3))
        pointer = reader.cell()
        decoded.base = reader.u32()
        target = reader.cell()
        local = reader.cell()
        decoded.cells = (pointer, target, local)
    elif opcode is Opcode.JUMP:
        _read_preamble(reader, decoded)
        decoded.offsets = tuple(reader.u32() for _ in range(3))
        decoded.cells = tuple(reader.cell() for _ in range(3))
        taken = reader.u8()
        if taken > 1:
            raise ProtocolFault(Status.BAD_BRANCH_PROPOSAL, 3)
        decoded.taken = bool(taken)
        decoded.dest_pc = reader.u32()
        decoded.dest_fp = reader.u32()
        decoded.proposed_inverse = reader.cell()
    elif opcode is Opcode.BLAKE3_REQUEST:
        _read_preamble(reader, decoded)
        decoded.message_offsets = tuple(reader.u32() for _ in range(4))
        decoded.cv_offset = reader.u32()
        decoded.out_offset = reader.u32()
        decoded.metadata = reader.f128()
        decoded.cells = tuple(reader.cell() for _ in range(8))
    elif opcode is Opcode.NEGOTIATE:
        decoded.version_min = reader.u8()
        decoded.version_max = reader.u8()
        profile = reader.u8()
        if profile not in (int(Profile.FORWARD_ONLY), int(Profile.INTERPRETER_COMPAT)):
            raise ProtocolFault(Status.BAD_PROFILE)
        decoded.profile = Profile(profile)
        decoded.host_features = reader.u32()
    elif opcode is Opcode.SERVICE_RESPONSE:
        decoded.txn_id = reader.u32()
        decoded.service_id = reader.u32()
        decoded.service_kind = reader.u8()
        if reader.u8() != 0:
            raise ProtocolFault(Status.BAD_FLAGS, 2)
        decoded.digest = (reader.f128(), reader.f128())
    elif opcode is Opcode.RETIRE:
        decoded.txn_id = reader.u32()
        decoded.result_crc = reader.u32()
    elif opcode is Opcode.STATUS_QUERY:
        pass
    else:  # pragma: no cover - REQUEST_PAYLOAD_BYTES gates the opcode set
        raise ProtocolFault(Status.BAD_OPCODE)
    reader.done()
    return decoded


def _available_txn_id(opcode: Opcode, payload: bytes) -> int:
    """Return the zero-extended transaction prefix accumulated by the RTL."""
    if opcode in (Opcode.NEGOTIATE, Opcode.STATUS_QUERY):
        return 0
    return int.from_bytes(payload[:4], "little")


# --- Endpoint pins and byte lane. -------------------------------------------


@dataclass(frozen=True)
class Pins:
    """Observable ASIC-to-host pins, sampled before the clock edge."""

    rx_ready: bool
    tx_valid: bool
    tx_data: int
    busy: bool
    fault: bool
    done_pulse: bool


@dataclass(frozen=True)
class LaneRecord:
    """Pins plus the transfers actually committed at one rising edge."""

    pins: Pins
    rx_committed: bool
    tx_committed: bool


class Lsc1Endpoint:
    """Byte-lane LSC-1 v1 endpoint: framing, transaction, and service states.

    The endpoint accepts request bytes only while it has no response bytes
    outstanding, which is how "one outstanding transaction or service request"
    is enforced on the wire.  ``ABORT`` and reset are synchronous and take
    priority over a same-edge candidate transfer, matching the byte/cycle
    contract already recorded in ``docs/PROTOCOL_BYTE_CYCLE_AUDIT.md``.
    """

    def __init__(self) -> None:
        self._reset()

    # -- lifecycle ---------------------------------------------------------

    def _reset(self) -> None:
        self.state = TxnState.IDLE
        self.profile = DEFAULT_PROFILE
        self.committed_pc = 0
        self.committed_fp = 0
        self.state_valid = False
        self.retire_seq = 0
        self.service_seq = 0
        self.last_status = Status.OK
        self.last_fault = Status.OK
        self.staged: StagedTransaction | None = None
        self._rx = bytearray()
        self._tx = bytearray()
        self._expected = 0
        self._done = False
        self.abort_count = 0

    def _discard(self) -> None:
        """Abandon the staged transition without committing any of it."""
        self.state = TxnState.IDLE
        self.staged = None

    def _abort(self) -> None:
        self.state = TxnState.IDLE
        self.staged = None
        self._rx.clear()
        self._tx.clear()
        self._expected = 0
        self._done = False
        self.last_status = Status.ABORTED
        self.last_fault = Status.ABORTED
        self.abort_count += 1

    # -- pins --------------------------------------------------------------

    def pins(self) -> Pins:
        return Pins(
            rx_ready=not self._tx,
            tx_valid=bool(self._tx),
            tx_data=self._tx[0] if self._tx else 0,
            busy=bool(self._tx or self._rx) or self.state is not TxnState.IDLE,
            fault=int(self.last_status) >= 0x80,
            done_pulse=self._done,
        )

    def step(
        self,
        *,
        rx_data: int = 0,
        rx_valid: bool = False,
        tx_ready: bool = False,
        abort: bool = False,
        reset_n: bool = True,
    ) -> LaneRecord:
        pins = self.pins()
        if not reset_n:
            self._reset()
            return LaneRecord(pins, False, False)
        if abort:
            self._abort()
            return LaneRecord(pins, False, False)
        self._done = False
        rx_committed = bool(rx_valid and pins.rx_ready)
        tx_committed = bool(pins.tx_valid and tx_ready)
        if tx_committed:
            del self._tx[0]
        if rx_committed:
            self._accept(rx_data & 0xFF)
        return LaneRecord(pins, rx_committed, tx_committed)

    # -- framing -----------------------------------------------------------

    def _emit(self, response: ResponseFrame) -> None:
        self.last_status = response.status
        if int(response.status) >= 0x80:
            self.last_fault = response.status
        self._tx.extend(response.encode())

    def _fault(self, status: Status, txn_id: int = 0, detail: int = 0) -> None:
        self._emit(ResponseFrame(status, u32le(txn_id) + u8(detail)))

    def _accept(self, byte: int) -> None:
        if not self._rx:
            if byte != SOF_REQUEST:
                self._fault(Status.BAD_SOF)
                return
            self._rx.append(byte)
            self._expected = 0
            return
        self._rx.append(byte)
        if len(self._rx) == REQUEST_HEADER_BYTES:
            length = int.from_bytes(self._rx[4:6], "little")
            if length > MAX_PAYLOAD_BYTES:
                # The frame boundary cannot be recovered; the host must
                # abandon the in-flight frame and restart from SOF.
                self._rx.clear()
                self._fault(Status.BAD_LENGTH, detail=1)
                return
            self._expected = REQUEST_HEADER_BYTES + length + CRC_BYTES
        if self._expected and len(self._rx) == self._expected:
            frame = bytes(self._rx)
            self._rx.clear()
            self._expected = 0
            self._dispatch(frame)

    def _dispatch(self, frame: bytes) -> None:
        length = int.from_bytes(frame[4:6], "little")
        body = frame[: REQUEST_HEADER_BYTES + length]
        if int.from_bytes(frame[-CRC_BYTES:], "little") != crc32(body):
            self._fault(Status.BAD_CRC)
            return
        if frame[1] != PROTOCOL_VERSION:
            self._fault(Status.BAD_VERSION)
            return
        if frame[3] != 0:
            self._fault(Status.BAD_FLAGS)
            return
        try:
            opcode = Opcode(frame[2])
        except ValueError:
            self._fault(Status.BAD_OPCODE)
            return
        payload = body[REQUEST_HEADER_BYTES:]
        if length != REQUEST_PAYLOAD_BYTES[opcode]:
            self._fault(Status.BAD_LENGTH, _available_txn_id(opcode, payload), detail=2)
            return
        decoded: _DecodedRequest | None = None
        try:
            decoded = decode_request_payload(opcode, payload)
            self._handle(decoded)
        except ProtocolFault as fault:
            # Framing and guard faults are rejections of *this frame*: they must
            # not disturb a transaction the endpoint already decided.  Handlers
            # that fault after touching a staged transition discard it
            # themselves, so there is nothing to unwind here.
            self._fault(fault.status, decoded.txn_id if decoded is not None else 0, fault.detail)

    # -- transaction handling ---------------------------------------------

    def _handle(self, request: _DecodedRequest) -> None:
        opcode = request.opcode
        if opcode is Opcode.NEGOTIATE:
            self._handle_negotiate(request)
        elif opcode is Opcode.STATUS_QUERY:
            self._handle_status_query()
        elif opcode is Opcode.SERVICE_RESPONSE:
            self._handle_service_response(request)
        elif opcode is Opcode.RETIRE:
            self._handle_retire(request)
        else:
            self._handle_instruction(request)

    def _handle_negotiate(self, request: _DecodedRequest) -> None:
        if self.state is not TxnState.IDLE:
            raise ProtocolFault(Status.BAD_STATE)
        if not request.version_min <= PROTOCOL_VERSION <= request.version_max:
            raise ProtocolFault(Status.BAD_VERSION)
        self.profile = request.profile
        payload = (
            u8(PROTOCOL_VERSION)
            + u8(int(self.profile))
            + u16le(MAX_PAYLOAD_BYTES)
            + u8(INDEX_BITS)
            + u8(0)
            + u32le(DEVICE_FEATURES)
            + u32le(DEVICE_ID)
        )
        self._emit(ResponseFrame(Status.OK, payload))

    def _handle_status_query(self) -> None:
        payload = (
            u8(_STATE_CODES[self.state])
            + u32le(self.staged.txn_id if self.staged else 0)
            + u8(int(self.last_status))
            + u32le(self.retire_seq)
            + u8(int(self.last_fault))
            + u32le(self.committed_pc)
            + u32le(self.committed_fp)
            + u8(1 if self.state_valid else 0)
        )
        self._emit(ResponseFrame(Status.INFO, payload))

    def _handle_instruction(self, request: _DecodedRequest) -> None:
        if self.state is not TxnState.IDLE:
            raise ProtocolFault(Status.BAD_STATE)
        if request.profile is not self.profile:
            raise ProtocolFault(Status.BAD_PROFILE)
        if self.state_valid and (request.pc, request.fp) != (self.committed_pc, self.committed_fp):
            # The endpoint retains the transition it decided; a host that
            # rewinds or forks the scalar state is rejected, not followed.
            raise ProtocolFault(Status.STATE_MISMATCH)
        if request.pc >= INDEX_LIMIT or request.fp >= INDEX_LIMIT:
            raise ProtocolFault(Status.INDEX_RANGE)
        staged = StagedTransaction(
            txn_id=request.txn_id,
            opcode=request.opcode,
            profile=request.profile,
            pc=request.pc,
            fp=request.fp,
        )
        opcode = request.opcode
        if opcode in (Opcode.XOR, Opcode.MUL_NATIVE):
            _execute_binary(request, staged)
        elif opcode is Opcode.SET_CONSTANT:
            _execute_set(request, staged)
        elif opcode in (Opcode.DEREF_CELL, Opcode.DEREF_PC, Opcode.DEREF_FP):
            _execute_deref(request, staged)
        elif opcode is Opcode.JUMP:
            _execute_jump(request, staged)
        else:
            self.service_seq += 1
            _execute_blake3(request, staged, self.service_seq)

        self.staged = staged
        if staged.service is not None:
            self.state = TxnState.SERVICE_PENDING
            self._emit(
                ResponseFrame(Status.SERVICE_REQUIRED, staged.service.encode(staged.txn_id))
            )
            return
        self._finish_transaction(staged)

    def _finish_transaction(self, staged: StagedTransaction) -> None:
        payload = staged.result_payload()
        staged.result_crc = crc32(payload)
        self.state = TxnState.RESULT_PENDING
        self._emit(ResponseFrame(Status.OK, payload))

    def _handle_service_response(self, request: _DecodedRequest) -> None:
        staged = self.staged
        if self.state is not TxnState.SERVICE_PENDING or staged is None:
            raise ProtocolFault(Status.BAD_STATE)
        service = staged.service
        assert service is not None
        if request.txn_id != staged.txn_id or request.service_id != service.service_id:
            raise ProtocolFault(Status.BAD_SERVICE, 1)
        if request.service_kind != int(service.kind):
            raise ProtocolFault(Status.BAD_SERVICE, 2)
        try:
            _resume_blake3(staged, request.digest)
        except ProtocolFault:
            # The digest is already folded into the staged writes; the host does
            # not get to propose a second one for the same transaction.
            self._discard()
            raise
        self._finish_transaction(staged)

    def _handle_retire(self, request: _DecodedRequest) -> None:
        staged = self.staged
        if self.state is not TxnState.RESULT_PENDING or staged is None:
            raise ProtocolFault(Status.BAD_STATE)
        if request.txn_id != staged.txn_id or request.result_crc != staged.result_crc:
            # Host and endpoint disagree about what was decided, so the endpoint
            # abandons the transition rather than retire a result the host may
            # never have read correctly.
            detail = 1 if request.txn_id != staged.txn_id else 2
            self._discard()
            raise ProtocolFault(Status.RETIRE_MISMATCH, detail)
        self.committed_pc = staged.next_pc
        self.committed_fp = staged.next_fp
        self.state_valid = True
        self.retire_seq += 1
        self.state = TxnState.IDLE
        self.staged = None
        self._done = True
        payload = (
            u32le(request.txn_id)
            + u32le(self.retire_seq)
            + u32le(self.committed_pc)
            + u32le(self.committed_fp)
        )
        self._emit(ResponseFrame(Status.RETIRED, payload))


_STATE_CODES = {
    TxnState.IDLE: 0x00,
    TxnState.RESULT_PENDING: 0x01,
    TxnState.SERVICE_PENDING: 0x02,
}


# --- Host-side driver over the byte lane. -----------------------------------


def drive(
    endpoint: Lsc1Endpoint,
    frame: bytes,
    *,
    rx_gaps: list[int] | None = None,
    tx_gaps: list[int] | None = None,
    max_cycles: int = 100_000,
) -> tuple[bytes, int]:
    """Push ``frame`` through the lane and collect one response frame.

    ``rx_gaps``/``tx_gaps`` are repeating stall patterns (cycles of deasserted
    ``RX_VALID`` / ``TX_READY``), so a caller can exercise arbitrary input
    stalls and output backpressure without a second scheduler.  Returns the
    response bytes and the number of clock edges consumed.
    """
    rx_pattern = list(rx_gaps or [0])
    tx_pattern = list(tx_gaps or [0])
    sent = 0
    response = bytearray()
    rx_hold = rx_pattern[0]
    tx_hold = tx_pattern[0]
    cycles = 0
    while cycles < max_cycles:
        rx_valid = sent < len(frame) and rx_hold == 0
        tx_ready = tx_hold == 0
        record = endpoint.step(
            rx_data=frame[sent] if sent < len(frame) else 0,
            rx_valid=rx_valid,
            tx_ready=tx_ready,
        )
        cycles += 1
        if record.rx_committed:
            sent += 1
            rx_hold = rx_pattern[sent % len(rx_pattern)]
        elif rx_hold:
            rx_hold -= 1
        if record.tx_committed:
            response.append(record.pins.tx_data)
            tx_hold = tx_pattern[len(response) % len(tx_pattern)]
        elif tx_hold:
            tx_hold -= 1
        if sent == len(frame) and response and not endpoint.pins().tx_valid:
            return bytes(response), cycles
    raise RuntimeError("lane did not settle")


# --- Byte and cycle budgets. ------------------------------------------------


@dataclass(frozen=True)
class Budget:
    """Worst-case byte and cycle accounting for one opcode, no stalls."""

    opcode: Opcode
    profile: Profile
    request_bytes: int
    result_bytes: int
    service_bytes: int
    execute_cycles: int

    @property
    def round_trip_cycles(self) -> int:
        """Request in, execute, result out, retire round trip."""
        return (
            self.request_bytes * ASSUMPTIONS.beat
            + ASSUMPTIONS.decode
            + self.execute_cycles
            + self.result_bytes * ASSUMPTIONS.beat
            + self.service_bytes * ASSUMPTIONS.beat
            + request_frame_bytes(Opcode.RETIRE) * ASSUMPTIONS.beat
            + ASSUMPTIONS.decode
            + response_frame_bytes(16) * ASSUMPTIONS.beat
        )


_WORST_SHAPE = {
    # opcode: (writes, deferred, accesses, execute cycles by profile)
    Opcode.XOR: (2, 0, 3),
    Opcode.MUL_NATIVE: (2, 0, 3),
    Opcode.SET_CONSTANT: (1, 0, 1),
    Opcode.DEREF_CELL: (1, 0, 3),
    Opcode.DEREF_PC: (1, 0, 3),
    Opcode.DEREF_FP: (1, 0, 3),
    Opcode.JUMP: (0, 0, 3),
    Opcode.BLAKE3_REQUEST: (2, 0, 8),
}


def _worst_execute_cycles(opcode: Opcode, profile: Profile) -> int:
    backsolving = profile is Profile.INTERPRETER_COMPAT
    encode = ASSUMPTIONS.encode_index()
    if opcode is Opcode.XOR:
        return 2 * ASSUMPTIONS.field_xor if backsolving else ASSUMPTIONS.field_xor
    if opcode is Opcode.MUL_NATIVE:
        return 3 * ASSUMPTIONS.field_mul if backsolving else ASSUMPTIONS.field_mul
    if opcode is Opcode.SET_CONSTANT:
        return 0
    if opcode is Opcode.DEREF_CELL:
        return encode + ASSUMPTIONS.compare
    if opcode in (Opcode.DEREF_PC, Opcode.DEREF_FP):
        return 2 * encode
    if opcode is Opcode.JUMP:
        return ASSUMPTIONS.compare + ASSUMPTIONS.field_mul + 2 * encode
    return 0


def budget(opcode: Opcode, profile: Profile = DEFAULT_PROFILE) -> Budget:
    writes, deferred, accesses = _WORST_SHAPE[opcode]
    result_bytes = response_frame_bytes(result_payload_bytes(writes, deferred, accesses))
    service_bytes = 0
    if opcode is Opcode.BLAKE3_REQUEST:
        service_bytes = response_frame_bytes(122) + request_frame_bytes(
            Opcode.SERVICE_RESPONSE
        )
    return Budget(
        opcode=opcode,
        profile=profile,
        request_bytes=request_frame_bytes(opcode),
        result_bytes=result_bytes,
        service_bytes=service_bytes,
        execute_cycles=_worst_execute_cycles(opcode, profile),
    )


def budget_table(profile: Profile = DEFAULT_PROFILE) -> list[Budget]:
    return [budget(opcode, profile) for opcode in INSTRUCTION_OPCODES]
