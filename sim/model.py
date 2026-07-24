"""Executable reference models for leanVM-b MinCore.

The GHASH field representation matches leanVM-b: bit i is x^i and the
irreducible polynomial is x^128 + x^7 + x^2 + x + 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

MASK128 = (1 << 128) - 1
REDUCTION_LOW = 0x87
POLY128 = (1 << 128) | REDUCTION_LOW


class Command(IntEnum):
    XOR128 = 0x01
    MUL128 = 0x02
    SET128 = 0x03
    NONZERO = 0x04
    CLEAR = 0x7D
    STATUS = 0x7E


def mul_by_x(value: int, width: int = 128, reduction_low: int = REDUCTION_LOW) -> int:
    """Multiply a polynomial-basis field element by x."""
    if value < 0 or value >= 1 << width:
        raise ValueError(f"value does not fit in {width} bits")
    carry = (value >> (width - 1)) & 1
    shifted = (value << 1) & ((1 << width) - 1)
    return shifted ^ (reduction_low if carry else 0)


def gf_mul_bitserial(a: int, b: int, width: int = 128, reduction_low: int = REDUCTION_LOW) -> int:
    """The exact LSB-first algorithm implemented by gf128_mul_bitstream.sv."""
    mask = (1 << width) - 1
    if not (0 <= a <= mask and 0 <= b <= mask):
        raise ValueError("operand does not fit field width")
    acc = 0
    shifted = a
    for i in range(width):
        if (b >> i) & 1:
            acc ^= shifted
        shifted = mul_by_x(shifted, width, reduction_low)
    return acc


def gf_mul_polynomial(a: int, b: int, width: int = 128, reduction_low: int = REDUCTION_LOW) -> int:
    """Independent schoolbook carry-less product followed by long reduction."""
    mask = (1 << width) - 1
    if not (0 <= a <= mask and 0 <= b <= mask):
        raise ValueError("operand does not fit field width")

    product = 0
    for i in range(width):
        if (b >> i) & 1:
            product ^= a << i

    modulus = (1 << width) | reduction_low
    for degree in range(2 * width - 2, width - 1, -1):
        if (product >> degree) & 1:
            product ^= modulus << (degree - width)
    return product & mask


def int_to_le_bytes(value: int, length: int) -> bytes:
    if value < 0 or value >= 1 << (8 * length):
        raise ValueError("integer does not fit requested byte length")
    return value.to_bytes(length, "little")


def le_bytes_to_int(data: bytes | bytearray | Iterable[int]) -> int:
    return int.from_bytes(bytes(data), "little")


@dataclass(frozen=True)
class CommandResult:
    output: bytes
    input_data_beats: int
    output_data_beats: int
    multiplier_bit_steps: int = 0


class StreamALUModel:
    """Transaction-level model of the minimal byte protocol.

    It deliberately counts payload beats separately from the command byte so
    the information-theoretic lower bounds are explicit.
    """

    STATUS = bytes((0x01, 0x01, 0x0F, 0x08))

    @staticmethod
    def execute(command: int, payload: bytes) -> CommandResult:
        try:
            cmd = Command(command)
        except ValueError:
            return CommandResult(bytes((0xE0,)), 0, 1)

        if cmd is Command.XOR128:
            if len(payload) != 32:
                raise ValueError("XOR128 requires 32 interleaved payload bytes")
            result = bytes(payload[2 * i] ^ payload[2 * i + 1] for i in range(16))
            return CommandResult(result, 32, 16)

        if cmd is Command.MUL128:
            if len(payload) != 32:
                raise ValueError("MUL128 requires 16 A bytes followed by 16 B bytes")
            a = le_bytes_to_int(payload[:16])
            b = le_bytes_to_int(payload[16:])
            result = int_to_le_bytes(gf_mul_bitserial(a, b), 16)
            return CommandResult(result, 32, 16, multiplier_bit_steps=128)

        if cmd is Command.SET128:
            if len(payload) != 16:
                raise ValueError("SET128 requires 16 bytes")
            return CommandResult(bytes(payload), 16, 16)

        if cmd is Command.NONZERO:
            if len(payload) != 16:
                raise ValueError("NONZERO requires 16 bytes")
            return CommandResult(bytes((int(any(payload)),)), 16, 1)

        if cmd is Command.STATUS:
            if payload:
                raise ValueError("STATUS takes no payload")
            return CommandResult(StreamALUModel.STATUS, 0, 4)

        if cmd is Command.CLEAR:
            if payload:
                raise ValueError("CLEAR takes no payload")
            return CommandResult(b"", 0, 0)

        raise AssertionError("unreachable")
