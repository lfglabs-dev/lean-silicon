"""Independent Phase-3 byte-stream packet executor for the scalar core.

The model intentionally implements only the currently executable scalar
packet subset: ``XOR``, ``MUL_NATIVE``, ``SET_CONSTANT``, and ``RETIRE``.
It owns its codec, CRC, field arithmetic, bounded receive storage, staging,
and ready/valid behavior.  In particular, it does not import the pre-existing
transaction model or scalar oracle; tests compare those independent paths.

Normative sources are frozen at:

* ``docs/LSC1_TRANSACTION_PROTOCOL.md`` (wire and transaction contract)
* ``sim/lsc1_transaction.py`` (v1 executable protocol companion)
* ``sim/scalar_step_oracle.py`` and leanVM-b commit
  ``c308034ab78619b39a59d26f3dc60e7df5b52649`` (scalar behavior)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

MASK128 = (1 << 128) - 1
U32_MAX = (1 << 32) - 1
INDEX_LIMIT = 1 << 16
REDUCTION = 0x87

VERSION = 1
REQUEST_SOF = 0xA1
RESPONSE_SOF = 0x5A
REQUEST_HEADER = 6
CRC_BYTES = 4
MAX_PAYLOAD = 256
MAX_REQUEST_BYTES = REQUEST_HEADER + MAX_PAYLOAD + CRC_BYTES


class Opcode(IntEnum):
    XOR = 0x01
    MUL_NATIVE = 0x02
    SET_CONSTANT = 0x03
    RETIRE = 0x12


PAYLOAD_LENGTH = {
    Opcode.XOR: 77,
    Opcode.MUL_NATIVE: 94,
    Opcode.SET_CONSTANT: 51,
    Opcode.RETIRE: 8,
}


class Status(IntEnum):
    OK = 0x00
    RETIRED = 0x02
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
    BAD_INVERSE = 0x8B
    WRITE_CONFLICT = 0x8C
    MUL_BACKSOLVE_ZERO = 0x8E
    UNSUPPORTED_IN_PROFILE = 0x90
    RETIRE_MISMATCH = 0x92
    ABORTED = 0x93
    STATE_MISMATCH = 0x94
    INDEX_RANGE = 0x95
    ALIAS_INCONSISTENT = 0x96


class Profile(IntEnum):
    FORWARD_ONLY = 0
    INTERPRETER_COMPAT = 1


class State(Enum):
    IDLE = "idle"
    RESULT_PENDING = "result_pending"


@dataclass(frozen=True)
class Gap:
    feature: str
    wire_source: str
    semantic_source: str
    reason: str


# An executable, source-located scope boundary.  These entries deliberately
# carry no opcode implementation or inferred behavior.
FUTURE_GAPS = (
    Gap(
        "DEREF",
        "docs/LSC1_TRANSACTION_PROTOCOL.md §§7.4,12.3,16.1-16.3",
        "leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649 crates/lean_vm/src/cpu/execute.rs; misc/doc.tex",
        "Pointer verification, three modes, and profile-dependent reconciliation need a later packet-model phase.",
    ),
    Gap(
        "JUMP",
        "docs/LSC1_TRANSACTION_PROTOCOL.md §§7.5,14.1,16.5",
        "leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649 crates/lean_vm/src/cpu/execute.rs; misc/doc.tex",
        "Branch proposal, inverse witness, and destination checks are intentionally not guessed here.",
    ),
    Gap(
        "witness/deferred equality",
        "docs/LSC1_TRANSACTION_PROTOCOL.md §§8.1,12.3,14",
        "leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649 crates/lean_vm/src/cpu/layout.rs; misc/doc.tex",
        "Witness ownership and deferred equality retirement require an explicit future contract.",
    ),
    Gap(
        "BLAKE3",
        "docs/LSC1_TRANSACTION_PROTOCOL.md §§7.6,8.2,11,14.3",
        "leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649 crates/lean_vm/src/cpu/execute.rs",
        "Service sequencing and unverified digest delegation are outside the current scalar executor.",
    ),
)


class PacketFault(Exception):
    def __init__(self, status: Status, detail: int = 0, txn_id: int = 0) -> None:
        super().__init__(status.name.lower())
        self.status = status
        self.detail = detail & 0xFF
        self.txn_id = txn_id


@dataclass(frozen=True)
class Cell:
    present: bool
    value: int = 0


@dataclass(frozen=True)
class Write:
    address: int
    value: int


@dataclass
class Staged:
    txn_id: int
    next_pc: int
    next_fp: int
    writes: list[Write]
    accesses: list[int]
    result_crc: int = 0


@dataclass(frozen=True)
class Pins:
    rx_ready: bool
    tx_valid: bool
    tx_data: int
    busy: bool
    fault: bool
    done_pulse: bool


@dataclass(frozen=True)
class LaneRecord:
    pins: Pins
    rx_committed: bool
    tx_committed: bool


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def crc32(data: bytes) -> int:
    register = 0xFFFFFFFF
    for byte in data:
        register ^= byte
        for _ in range(8):
            register = (register >> 1) ^ (0xEDB88320 if register & 1 else 0)
    return register ^ 0xFFFFFFFF


def multiply(left: int, right: int) -> int:
    """Carry-less product reduced by x^128+x^7+x^2+x+1."""
    product = 0
    for bit in range(128):
        if (right >> bit) & 1:
            product ^= left << bit
    modulus = (1 << 128) | REDUCTION
    for bit in range(254, 127, -1):
        if (product >> bit) & 1:
            product ^= modulus << (bit - 128)
    return product & MASK128


def checked_add(left: int, right: int) -> int:
    total = left + right
    if total > U32_MAX:
        raise PacketFault(Status.U32_OVERFLOW)
    return total


class Reader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.position = 0

    def take(self, count: int) -> bytes:
        end = self.position + count
        if end > len(self.payload):
            raise PacketFault(Status.BAD_LENGTH)
        value = self.payload[self.position:end]
        self.position = end
        return value

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def f128(self) -> int:
        return int.from_bytes(self.take(16), "little")

    def cell(self) -> Cell:
        presence = self.u8()
        value = self.f128()
        if presence not in (0, 1) or (presence == 0 and value != 0):
            raise PacketFault(Status.BAD_CELL)
        return Cell(bool(presence), value)

    def finish(self) -> None:
        if self.position != len(self.payload):
            raise PacketFault(Status.BAD_LENGTH)


class FrameMemory:
    def __init__(self) -> None:
        self.cells: dict[int, Cell] = {}
        self.writes: list[Write] = []

    def supply(self, address: int, cell: Cell) -> None:
        previous = self.cells.get(address)
        if previous is not None and previous != cell:
            raise PacketFault(Status.ALIAS_INCONSISTENT)
        self.cells[address] = cell

    def present(self, address: int) -> bool:
        return self.cells[address].present

    def read(self, address: int) -> int:
        cell = self.cells[address]
        return cell.value if cell.present else 0

    def write_once(self, address: int, value: int) -> None:
        value &= MASK128
        cell = self.cells[address]
        if cell.present:
            if cell.value != value:
                raise PacketFault(Status.WRITE_CONFLICT)
            return
        self.cells[address] = Cell(True, value)
        self.writes.append(Write(address, value))


class PacketExecutor:
    """Cycle-stepped bounded byte-stream executor for the supported subset."""

    def __init__(self) -> None:
        self._power_on()

    def _power_on(self) -> None:
        self.state = State.IDLE
        self.profile = Profile.INTERPRETER_COMPAT
        self.committed_pc = 0
        self.committed_fp = 0
        self.state_valid = False
        self.retire_seq = 0
        self.last_status = Status.OK
        self.last_fault = Status.OK
        self.staged: Staged | None = None
        self._rx = bytearray()
        self._expected = 0
        self._tx = bytearray()
        self._done = False
        self.abort_count = 0

    def pins(self) -> Pins:
        return Pins(
            rx_ready=not self._tx,
            tx_valid=bool(self._tx),
            tx_data=self._tx[0] if self._tx else 0,
            busy=bool(self._rx or self._tx) or self.state is not State.IDLE,
            fault=int(self.last_status) >= 0x80,
            done_pulse=self._done,
        )

    @property
    def buffered_bytes(self) -> int:
        return len(self._rx)

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
            self._power_on()
            return LaneRecord(pins, False, False)
        if abort:
            self.state = State.IDLE
            self.staged = None
            self._rx.clear()
            self._expected = 0
            self._tx.clear()
            self._done = False
            self.last_status = Status.ABORTED
            self.last_fault = Status.ABORTED
            self.abort_count += 1
            return LaneRecord(pins, False, False)

        self._done = False
        rx_committed = bool(rx_valid and pins.rx_ready)
        tx_committed = bool(tx_ready and pins.tx_valid)
        if tx_committed:
            del self._tx[0]
        if rx_committed:
            self._accept(rx_data & 0xFF)
        return LaneRecord(pins, rx_committed, tx_committed)

    def _emit(self, status: Status, payload: bytes) -> None:
        body = (
            bytes((RESPONSE_SOF, VERSION, int(status)))
            + len(payload).to_bytes(2, "little")
            + payload
        )
        self._tx.extend(body + _u32(crc32(body)))
        self.last_status = status
        if int(status) >= 0x80:
            self.last_fault = status

    def _fault(self, status: Status, txn_id: int = 0, detail: int = 0) -> None:
        self._emit(status, _u32(txn_id) + bytes((detail & 0xFF,)))

    def _accept(self, byte: int) -> None:
        if not self._rx:
            if byte != REQUEST_SOF:
                self._fault(Status.BAD_SOF)
                return
            self._rx.append(byte)
            return
        if len(self._rx) >= MAX_REQUEST_BYTES:
            raise AssertionError("bounded receive buffer exceeded")
        self._rx.append(byte)
        if len(self._rx) == REQUEST_HEADER:
            length = int.from_bytes(self._rx[4:6], "little")
            if length > MAX_PAYLOAD:
                self._rx.clear()
                self._expected = 0
                self._fault(Status.BAD_LENGTH, detail=1)
                return
            self._expected = REQUEST_HEADER + length + CRC_BYTES
        if self._expected and len(self._rx) == self._expected:
            frame = bytes(self._rx)
            self._rx.clear()
            self._expected = 0
            self._dispatch(frame)

    def _dispatch(self, frame: bytes) -> None:
        length = int.from_bytes(frame[4:6], "little")
        body = frame[: REQUEST_HEADER + length]
        if int.from_bytes(frame[-4:], "little") != crc32(body):
            self._fault(Status.BAD_CRC)
            return
        if frame[1] != VERSION:
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
        if length != PAYLOAD_LENGTH[opcode]:
            self._fault(Status.BAD_LENGTH, detail=2)
            return
        reader = Reader(body[REQUEST_HEADER:])
        txn_id = 0
        try:
            if opcode is Opcode.RETIRE:
                txn_id = reader.u32()
                result_crc = reader.u32()
                reader.finish()
                self._retire(txn_id, result_crc)
            else:
                txn_id = self._instruction(opcode, reader)
        except PacketFault as fault:
            self._fault(fault.status, fault.txn_id or txn_id, fault.detail)

    def _instruction(self, opcode: Opcode, reader: Reader) -> int:
        txn_id = reader.u32()
        try:
            pc, fp = reader.u32(), reader.u32()
            profile_code = reader.u8()
            if profile_code not in (0, 1):
                raise PacketFault(Status.BAD_PROFILE)
            profile = Profile(profile_code)
            if reader.u8() != 0:
                raise PacketFault(Status.BAD_FLAGS, 1)

            # Decode the complete fixed payload before considering transaction
            # state.  Malformed frames are rejected by their codec fault even
            # when a prior transaction is awaiting retirement.
            if opcode is Opcode.SET_CONSTANT:
                offset, constant, supplied_cell = reader.u32(), reader.f128(), reader.cell()
            else:
                offsets = tuple(reader.u32() for _ in range(3))
                cells = tuple(reader.cell() for _ in range(3))
                inverse = reader.cell() if opcode is Opcode.MUL_NATIVE else Cell(False)
            reader.finish()

            if self.state is not State.IDLE:
                raise PacketFault(Status.BAD_STATE)
            if profile is not self.profile:
                raise PacketFault(Status.BAD_PROFILE)
            if self.state_valid and (pc, fp) != (self.committed_pc, self.committed_fp):
                raise PacketFault(Status.STATE_MISMATCH)
            if pc >= INDEX_LIMIT or fp >= INDEX_LIMIT:
                raise PacketFault(Status.INDEX_RANGE)

            memory = FrameMemory()
            if opcode is Opcode.SET_CONSTANT:
                address = checked_add(fp, offset)
                memory.supply(address, supplied_cell)
                memory.write_once(address, constant)
                accesses = [address]
            else:
                addresses = tuple(checked_add(fp, offset) for offset in offsets)
                for address, cell in zip(addresses, cells):
                    memory.supply(address, cell)
                absent_a = not memory.present(addresses[0])
                absent_b = not memory.present(addresses[1])
                if (absent_a or absent_b) and profile is Profile.FORWARD_ONLY:
                    raise PacketFault(Status.UNSUPPORTED_IN_PROFILE)
                if memory.present(addresses[2]) and absent_a != absent_b:
                    known_address = addresses[1] if absent_a else addresses[0]
                    missing_address = addresses[0] if absent_a else addresses[1]
                    known = memory.read(known_address)
                    if opcode is Opcode.XOR:
                        solved = memory.read(addresses[2]) ^ known
                    else:
                        if known == 0:
                            raise PacketFault(Status.MUL_BACKSOLVE_ZERO)
                        if not inverse.present or multiply(known, inverse.value) != 1:
                            raise PacketFault(Status.BAD_INVERSE, 1 if not inverse.present else 2)
                        solved = multiply(memory.read(addresses[2]), inverse.value)
                    memory.write_once(missing_address, solved)
                result = (
                    memory.read(addresses[0]) ^ memory.read(addresses[1])
                    if opcode is Opcode.XOR
                    else multiply(memory.read(addresses[0]), memory.read(addresses[1]))
                )
                memory.write_once(addresses[2], result)
                accesses = list(addresses)
        except PacketFault as fault:
            fault.txn_id = txn_id
            raise

        staged = Staged(
            txn_id=txn_id,
            next_pc=checked_add(pc, 1),
            next_fp=fp,
            writes=memory.writes,
            accesses=accesses,
        )
        payload = self._result_payload(staged)
        staged.result_crc = crc32(payload)
        self.staged = staged
        self.state = State.RESULT_PENDING
        self._emit(Status.OK, payload)
        return txn_id

    @staticmethod
    def _result_payload(staged: Staged) -> bytes:
        payload = _u32(staged.txn_id) + _u32(staged.next_pc) + _u32(staged.next_fp)
        payload += bytes((len(staged.writes),))
        for write in staged.writes:
            payload += _u32(write.address) + write.value.to_bytes(16, "little")
        payload += b"\x00"  # no deferred equalities in the supported subset
        payload += bytes((len(staged.accesses),))
        payload += b"".join(_u32(address) for address in staged.accesses)
        return payload

    def _retire(self, txn_id: int, result_crc: int) -> None:
        staged = self.staged
        if self.state is not State.RESULT_PENDING or staged is None:
            raise PacketFault(Status.BAD_STATE)
        if txn_id != staged.txn_id or result_crc != staged.result_crc:
            detail = 1 if txn_id != staged.txn_id else 2
            self.state = State.IDLE
            self.staged = None
            raise PacketFault(Status.RETIRE_MISMATCH, detail)
        self.committed_pc = staged.next_pc
        self.committed_fp = staged.next_fp
        self.state_valid = True
        self.retire_seq += 1
        self.state = State.IDLE
        self.staged = None
        self._done = True
        payload = _u32(txn_id) + _u32(self.retire_seq)
        payload += _u32(self.committed_pc) + _u32(self.committed_fp)
        self._emit(Status.RETIRED, payload)
