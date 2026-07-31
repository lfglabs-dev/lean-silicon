"""Executable oracle for the fixed-width LSC-1u arithmetic boundary."""

WIDTH = 128
MASK = (1 << WIDTH) - 1


def gf128_mul(a: int, b: int) -> int:
    """LSC-1 GF(2^128), little-endian polynomial basis, modulus low 0x87."""
    result = 0
    for _ in range(WIDTH):
        if b & 1:
            result ^= a
        b >>= 1
        a = ((a << 1) & MASK) ^ (0x87 if (a >> 127) else 0)
    return result


def execute(opcode: int, payload: bytes) -> bytes:
    if opcode == 0x03 and len(payload) == 16:
        return payload
    if opcode == 0x01 and len(payload) == 32:
        return bytes(payload[i] ^ payload[i + 1] for i in range(0, 32, 2))
    if opcode == 0x02 and len(payload) == 32:
        a = int.from_bytes(payload[:16], "little")
        b = int.from_bytes(payload[16:], "little")
        return gf128_mul(a, b).to_bytes(16, "little")
    raise ValueError("unsupported opcode or wrong fixed payload width")
