"""Transport-neutral host driver for the exact LSC-1u Tiny Tapeout pins.

Backends may target an FPGA ASIC-simulator transport, a simulator bridge, or a
future physical demoboard.  This module never claims which backend was used.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol

RX_VALID = 1 << 0
RX_READY = 1 << 1
TX_VALID = 1 << 2
TX_READY = 1 << 3
BUSY = 1 << 4
FAULT = 1 << 5
DONE = 1 << 7
OUTPUT_ENABLES = 0b10110110
OPCODES = {"XOR": 0x01, "MUL": 0x02, "SET": 0x03}


@dataclass(frozen=True)
class Pins:
    uo_out: int
    uio_out: int
    uio_oe: int

    def __post_init__(self):
        for name, value in vars(self).items():
            if type(value) is not int or not 0 <= value <= 0xFF:
                raise AssertionError(f"{name} is not a known 8-bit value: {value!r}")

    def bit(self, mask: int) -> bool:
        return bool(self.uio_out & mask)


class PinBackend(Protocol):
    def drive(self, *, ui_in: int, uio_in: int, ena: bool, rst_n: bool) -> None: ...
    def cycle(self) -> Pins: ...


def gf128_mul(a: bytes, b: bytes) -> bytes:
    """Independent, integer GF(2^128) oracle; coefficients are little-endian."""
    x = int.from_bytes(a, "little")
    y = int.from_bytes(b, "little")
    product = 0
    for _ in range(128):
        if y & 1:
            product ^= x
        y >>= 1
        x = ((x << 1) & ((1 << 128) - 1)) ^ (0x87 if x >> 127 else 0)
    return product.to_bytes(16, "little")


def expected(case: dict) -> bytes:
    a = bytes.fromhex(case["a"])
    if case["opcode"] == "SET":
        return a
    b = bytes.fromhex(case["b"])
    if case["opcode"] == "XOR":
        return bytes(x ^ y for x, y in zip(a, b))
    if case["opcode"] == "MUL":
        return gf128_mul(a, b)
    raise ValueError(case["opcode"])


def payload(case: dict) -> bytes:
    a = bytes.fromhex(case["a"])
    if case["opcode"] == "SET":
        return a
    b = bytes.fromhex(case["b"])
    if case["opcode"] == "XOR":
        return b"".join(bytes((x, y)) for x, y in zip(a, b))
    return a + b


def load_corpus(path: Path | None = None) -> list[dict]:
    path = path or Path(__file__).with_name("lsc1u_vectors.json")
    document = json.loads(path.read_text())
    assert document["schema"] == "lsc1u-pin-corpus-v1"
    assert document["byte_order"] == "little" and document["reduction_low"] == "0x87"
    return document["cases"]


class LSC1UPinDriver:
    """Strict ready/valid driver; all functional bytes cross ui/uio pins."""

    def __init__(self, backend: PinBackend, timeout: int = 400):
        self.backend = backend
        self.timeout = timeout
        self.ui_in = 0
        self.uio_in = 0
        self.ena = True
        self.rst_n = True

    def _drive(self) -> None:
        self.backend.drive(ui_in=self.ui_in, uio_in=self.uio_in,
                           ena=self.ena, rst_n=self.rst_n)

    def cycle(self) -> Pins:
        self._drive()
        pins = self.backend.cycle()
        expected_oe = OUTPUT_ENABLES if self.ena else 0
        assert pins.uio_oe == expected_oe, (pins.uio_oe, expected_oe)
        if not self.ena:
            assert pins.uo_out == 0 and pins.uio_out == 0
        return pins

    def reset(self, cycles: int = 3) -> Pins:
        self.ui_in = self.uio_in = 0
        self.ena, self.rst_n = True, False
        for _ in range(cycles):
            pins = self.cycle()
            assert not pins.bit(TX_VALID | BUSY | FAULT | DONE)
        self.rst_n = True
        pins = self.cycle()
        assert pins.bit(RX_READY) and not pins.bit(TX_VALID | BUSY | FAULT | DONE)
        return pins

    def send(self, value: int, stall: int = 0) -> int:
        self.ui_in, self.uio_in = value, 0
        for _ in range(stall):
            self.cycle()
        self.uio_in = RX_VALID
        for waited in range(self.timeout):
            pins = self.cycle()
            if pins.bit(RX_READY):
                self.uio_in = 0
                return waited + 1
        raise AssertionError(f"RX_READY timeout sending 0x{value:02x}")

    def receive(self, stall: int = 0) -> tuple[int, bool, int]:
        self.uio_in = 0
        for waited in range(self.timeout):
            pins = self.cycle()
            if pins.bit(TX_VALID):
                held = pins.uo_out
                break
        else:
            raise AssertionError("TX_VALID timeout")
        for _ in range(stall):
            pins = self.cycle()
            assert pins.bit(TX_VALID) and pins.uo_out == held
        self.uio_in = TX_READY
        pins = self.cycle()
        assert pins.bit(TX_VALID) and pins.uo_out == held
        self.uio_in = 0
        after = self.cycle()
        return held, after.bit(DONE), waited + 1
