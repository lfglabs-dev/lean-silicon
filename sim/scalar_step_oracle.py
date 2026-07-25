"""Independent executable model of the frozen leanVM-b scalar runner subset.

This deliberately owns its field arithmetic, memory, program counter, and
write-once rules.  It does not import the M0 models or invoke the upstream
interpreter.  ``tools/frozen_upstream_differential.py`` compares this model to
an adapter compiled from the pinned upstream source.
"""
from dataclasses import dataclass, field

MASK = (1 << 128) - 1
REDUCTION = 0x87
U32_MAX = (1 << 32) - 1


class Fault(Exception):
    pass


def xtime(value: int) -> int:
    return ((value << 1) & MASK) ^ (REDUCTION if value >> 127 else 0)


def multiply(left: int, right: int) -> int:
    """Carry-less multiply and polynomial long reduction over GF(2^128)."""
    product = 0
    for bit in range(128):
        if (right >> bit) & 1:
            product ^= left << bit
    modulus = (1 << 128) | REDUCTION
    for bit in range(254, 127, -1):
        if (product >> bit) & 1:
            product ^= modulus << (bit - 128)
    return product & MASK


def encode(index: int) -> int:
    value = 1
    for _ in range(index):
        value = xtime(value)
    return value


def checked_add(left: int, right: int) -> int:
    value = left + right
    if value > U32_MAX:
        raise Fault("u32_overflow")
    return value


@dataclass
class Machine:
    memory: dict[int, int] = field(default_factory=dict)
    written: set[int] = field(default_factory=set)
    pc: int = 0
    fp: int = 0
    cycles: int = 0

    @classmethod
    def with_public_input(cls, first: int, second: int) -> "Machine":
        return cls(memory={0: first, 1: second}, written={0, 1})

    def read(self, address: int) -> int:
        return self.memory.get(address, 0) if address in self.written else 0

    def write_once(self, address: int, value: int) -> None:
        value &= MASK
        if address in self.written and self.memory[address] != value:
            raise Fault("write_conflict")
        self.memory[address] = value
        self.written.add(address)

    def local(self, offset: int) -> int:
        return checked_add(self.fp, offset)

    def step(self, instruction: tuple) -> None:
        opcode, *args = instruction
        if opcode == "set":
            offset, value = args
            self.write_once(self.local(offset), value)
            self.pc = checked_add(self.pc, 1)
        elif opcode == "xor":
            a, b, c = (self.local(offset) for offset in args)
            # Frozen runner fills exactly one absent input if C is already set.
            absent = [address not in self.written for address in (a, b)]
            if c in self.written and absent[0] != absent[1]:
                known = b if absent[0] else a
                missing = a if absent[0] else b
                self.write_once(missing, self.read(c) ^ self.read(known))
            self.write_once(c, self.read(a) ^ self.read(b))
            self.pc = checked_add(self.pc, 1)
        elif opcode == "mul":
            a, b, c = (self.local(offset) for offset in args)
            absent = [address not in self.written for address in (a, b)]
            if c in self.written and absent[0] != absent[1]:
                known = self.read(b if absent[0] else a)
                if known == 0:
                    raise Fault("mul_backsolve_zero_divisor")
                missing = a if absent[0] else b
                self.write_once(missing, multiply(self.read(c), inverse(known)))
            self.write_once(c, multiply(self.read(a), self.read(b)))
            self.pc = checked_add(self.pc, 1)
        elif opcode in ("deref_pc", "deref_fp"):
            alpha, beta, _gamma = args
            pointer = self.read(self.local(alpha))
            base = reverse(pointer, 1 << 16)
            target = checked_add(base, beta)
            value = encode(checked_add(self.pc, 2)) if opcode == "deref_pc" else encode(self.fp)
            self.write_once(target, value)
            self.pc = checked_add(self.pc, 1)
        elif opcode == "jump":
            condition, destination, frame = (self.local(offset) for offset in args)
            if self.read(condition) == 0:
                self.pc = checked_add(self.pc, 1)
            else:
                self.pc = reverse(self.read(destination), 1 << 16)
                self.fp = reverse(self.read(frame), 1 << 16)
        else:
            raise Fault(f"unsupported_opcode:{opcode}")
        self.cycles += 1


def inverse(value: int) -> int:
    if value == 0:
        return 0
    result, base, exponent = 1, value, (1 << 128) - 2
    while exponent:
        if exponent & 1:
            result = multiply(result, base)
        base = multiply(base, base)
        exponent >>= 1
    return result


def reverse(value: int, limit: int) -> int:
    candidate = 1
    for index in range(limit):
        if candidate == value:
            return index
        candidate = xtime(candidate)
    raise Fault("invalid_g_power")


def run(program: list[tuple], public_input: tuple[int, int]) -> Machine:
    if len(program) == 0 or len(program) & (len(program) - 1):
        raise Fault("bytecode_not_power_of_two")
    machine = Machine.with_public_input(*public_input)
    sentinel = len(program) - 1
    while machine.pc != sentinel:
        if machine.pc >= len(program):
            raise Fault("pc_out_of_range")
        machine.step(program[machine.pc])
    if machine.fp != 0:
        raise Fault("bad_halt_state")
    return machine
