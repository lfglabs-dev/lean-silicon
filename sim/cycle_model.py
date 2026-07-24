"""Cycle-accurate Python model of ``leanvm_b_stream_alu.sv``.

The model is an explicit FSM and models the optimized implementation:

* XOR and SET are combinational input/output stream transforms;
* NONZERO emits its answer atomically with the final input byte;
* A is shifted directly into the multiplier's only multiplicand register;
* B's seven unconsumed bits share the eight-bit scratch register with a sentinel;
* the result is destructively shifted out of the accumulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from model import Command, MASK128, mul_by_x


class State(Enum):
    IDLE = auto()
    XOR_A = auto()
    XOR_B = auto()
    SET_STREAM = auto()
    ZERO_STREAM = auto()
    MUL_A_RX = auto()
    MUL_B_RX = auto()
    MUL_BITS = auto()
    MUL_TX = auto()
    STATUS_TX = auto()
    ERROR_TX = auto()


@dataclass(frozen=True)
class Pins:
    rx_ready: bool
    tx_valid: bool
    tx_data: int
    busy: bool
    done_pulse: bool
    fault: bool


@dataclass(frozen=True)
class Controls:
    a_valid: bool = False
    a_last: bool = False
    bit_valid: bool = False
    bit_value: int = 0
    bit_last: bool = False
    result_shift: bool = False


class BitstreamMultiplier:
    def __init__(self) -> None:
        self.a_shift = 0
        self.acc = 0

    @property
    def result_byte(self) -> int:
        return self.acc & 0xFF

    def tick(
        self,
        *,
        a_valid: bool,
        a_byte: int,
        a_last: bool,
        bit_valid: bool,
        bit_value: int,
        bit_last: bool,
        result_shift: bool,
        abort: bool,
    ) -> None:
        if abort:
            self.a_shift = 0
            self.acc = 0
        elif a_valid:
            # Equivalent to RTL shift_in_byte: after bytes A0..A15, byte Ai is
            # in bits 8*i..8*i+7.
            self.a_shift = ((self.a_shift >> 8) | ((a_byte & 0xFF) << 120)) & MASK128
            if a_last:
                self.acc = 0
        elif bit_valid:
            if bit_value:
                self.acc ^= self.a_shift
            if not bit_last:
                self.a_shift = mul_by_x(self.a_shift)
        elif result_shift:
            self.acc >>= 8


class StreamALUCycleModel:
    STATUS = (0x01, 0x01, 0x0F, 0x08)

    def __init__(self) -> None:
        self.state = State.IDLE
        self.byte_index = 0
        self.scratch_byte = 0
        self.fault = False
        self.mul = BitstreamMultiplier()

    @property
    def mul_tail_last(self) -> bool:
        return (self.scratch_byte >> 1) == 1

    def combinational(
        self, *, tx_ready: bool = False, rx_valid: bool = False, rx_data: int = 0
    ) -> tuple[Pins, Controls]:
        rx_ready = False
        tx_valid = False
        tx_data = 0
        controls = Controls()

        if self.state is State.IDLE:
            rx_ready = True
        elif self.state is State.XOR_A:
            rx_ready = True
        elif self.state is State.XOR_B:
            tx_valid = rx_valid
            tx_data = self.scratch_byte ^ (rx_data & 0xFF)
            rx_ready = tx_ready
        elif self.state is State.SET_STREAM:
            tx_valid = rx_valid
            tx_data = rx_data & 0xFF
            rx_ready = tx_ready
        elif self.state is State.ZERO_STREAM:
            if self.byte_index == 15:
                tx_valid = rx_valid
                tx_data = int(bool(self.scratch_byte & 1) or (rx_data & 0xFF) != 0)
                rx_ready = tx_ready
            else:
                rx_ready = True
        elif self.state is State.MUL_A_RX:
            rx_ready = True
            controls = Controls(a_valid=rx_valid, a_last=self.byte_index == 15)
        elif self.state is State.MUL_B_RX:
            rx_ready = True
            controls = Controls(bit_valid=rx_valid, bit_value=rx_data & 1)
        elif self.state is State.MUL_BITS:
            controls = Controls(
                bit_valid=True,
                bit_value=self.scratch_byte & 1,
                bit_last=self.byte_index == 15 and self.mul_tail_last,
            )
        elif self.state is State.MUL_TX:
            tx_valid = True
            tx_data = self.mul.result_byte
            controls = Controls(result_shift=tx_ready)
        elif self.state is State.STATUS_TX:
            tx_valid = True
            tx_data = self.STATUS[self.byte_index]
        elif self.state is State.ERROR_TX:
            tx_valid = True
            tx_data = 0xE0

        rx_fire = rx_valid and rx_ready
        tx_fire = tx_valid and tx_ready
        done = (
            (rx_fire and self.state is State.IDLE and rx_data == Command.CLEAR)
            or (
                tx_fire
                and (
                    (self.state is State.XOR_B and self.byte_index == 15)
                    or (self.state is State.SET_STREAM and self.byte_index == 15)
                    or (self.state is State.ZERO_STREAM and self.byte_index == 15)
                    or (self.state is State.MUL_TX and self.byte_index == 15)
                    or (self.state is State.STATUS_TX and self.byte_index == 3)
                    or self.state is State.ERROR_TX
                )
            )
        )
        return (
            Pins(
                rx_ready=rx_ready,
                tx_valid=tx_valid,
                tx_data=tx_data,
                busy=self.state is not State.IDLE,
                done_pulse=done,
                fault=self.fault,
            ),
            controls,
        )

    def step(
        self,
        *,
        rx_data: int = 0,
        rx_valid: bool = False,
        tx_ready: bool = False,
        abort: bool = False,
    ) -> Pins:
        pins, controls = self.combinational(
            tx_ready=tx_ready, rx_valid=rx_valid, rx_data=rx_data
        )
        rx_fire = rx_valid and pins.rx_ready
        tx_fire = pins.tx_valid and tx_ready

        if abort:
            self.state = State.IDLE
            self.byte_index = 0
            self.scratch_byte = 0
            self.fault = True
        elif self.state is State.IDLE:
            self.byte_index = 0
            self.scratch_byte = 0
            if rx_fire:
                if rx_data == Command.XOR128:
                    self.state = State.XOR_A
                elif rx_data == Command.MUL128:
                    self.state = State.MUL_A_RX
                elif rx_data == Command.SET128:
                    self.state = State.SET_STREAM
                elif rx_data == Command.NONZERO:
                    self.state = State.ZERO_STREAM
                elif rx_data == Command.STATUS:
                    self.state = State.STATUS_TX
                elif rx_data == Command.CLEAR:
                    self.fault = False
                else:
                    self.fault = True
                    self.state = State.ERROR_TX
        elif self.state is State.XOR_A and rx_fire:
            self.scratch_byte = rx_data & 0xFF
            self.state = State.XOR_B
        elif self.state is State.XOR_B and tx_fire:
            if self.byte_index == 15:
                self.state = State.IDLE
            else:
                self.byte_index += 1
                self.state = State.XOR_A
        elif self.state is State.SET_STREAM and tx_fire:
            if self.byte_index == 15:
                self.state = State.IDLE
            else:
                self.byte_index += 1
        elif self.state is State.ZERO_STREAM:
            if self.byte_index == 15:
                if tx_fire:
                    self.state = State.IDLE
            elif rx_fire:
                self.scratch_byte = int(
                    bool(self.scratch_byte & 1) or (rx_data & 0xFF) != 0
                )
                self.byte_index += 1
        elif self.state is State.MUL_A_RX and rx_fire:
            if self.byte_index == 15:
                self.byte_index = 0
                self.state = State.MUL_B_RX
            else:
                self.byte_index += 1
        elif self.state is State.MUL_B_RX and rx_fire:
            self.scratch_byte = 0x80 | ((rx_data & 0xFF) >> 1)
            self.state = State.MUL_BITS
        elif self.state is State.MUL_BITS:
            if self.mul_tail_last:
                if self.byte_index == 15:
                    self.byte_index = 0
                    self.state = State.MUL_TX
                else:
                    self.byte_index += 1
                    self.state = State.MUL_B_RX
            else:
                self.scratch_byte >>= 1
        elif self.state is State.MUL_TX and tx_fire:
            if self.byte_index == 15:
                self.state = State.IDLE
            else:
                self.byte_index += 1
        elif self.state is State.STATUS_TX and tx_fire:
            if self.byte_index == 3:
                self.state = State.IDLE
            else:
                self.byte_index += 1
        elif self.state is State.ERROR_TX and tx_fire:
            self.state = State.IDLE

        self.mul.tick(
            a_valid=controls.a_valid,
            a_byte=rx_data,
            a_last=controls.a_last,
            bit_valid=controls.bit_valid,
            bit_value=controls.bit_value,
            bit_last=controls.bit_last,
            result_shift=controls.result_shift,
            abort=abort,
        )
        return pins
