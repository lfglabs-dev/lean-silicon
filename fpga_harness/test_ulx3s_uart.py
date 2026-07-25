"""Tests for the ULX3S UART driver's response checking.

The negative cases carry the weight here. A driver that prints a board's reply
and exits zero looks identical to a working one in CI logs, so these tests feed
the driver a complete, well-formed, *wrong* 16-byte MUL response and require a
non-zero exit. No serial port and no board are involved.
"""

from __future__ import annotations

import unittest
from unittest import mock

import ulx3s_uart
from ulx3s_uart import expected_mul

# Same vector the RTL testbench uses, so the host tool and the simulation are
# checked against one shared expectation.
MUL_A = bytes.fromhex("112233445566778899aabbccddeeff01")
MUL_B = bytes.fromhex("02000000000000000000000000000000")
MUL_EXPECTED = bytes.fromhex("22446688aaccee1033557799bbddff03")


class FakeSerial:
    """Minimal stand-in that replays a canned reply once a command is complete."""

    def __init__(self, response: bytes, command_len: int) -> None:
        self._response = response
        self._command_len = command_len
        self._written = bytearray()
        self._pending = bytearray()
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self._pending)

    def write(self, data: bytes) -> int:
        self._written.extend(data)
        if len(self._written) == self._command_len:
            self._pending.extend(self._response)
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, n: int = 1) -> bytes:
        chunk = bytes(self._pending[:n])
        del self._pending[:n]
        return chunk

    def reset_input_buffer(self) -> None:
        self._pending.clear()

    def reset_output_buffer(self) -> None:
        self._written.clear()

    def close(self) -> None:
        self.closed = True

    @property
    def written(self) -> bytes:
        return bytes(self._written)


class IdleSerial:
    """An idle port whose configured blocking read must never be called."""

    in_waiting = 0

    def read(self, _n: int = 1) -> bytes:
        raise AssertionError("drain attempted a blocking read on an idle port")


def run_mul(response: bytes) -> int:
    """Run the driver's mul path against a canned 16-byte reply."""
    fake = FakeSerial(response, command_len=1 + 32)
    with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
        return ulx3s_uart.main(
            ["--port", "/dev/null", "--tx", "mul", "--payload", (MUL_A + MUL_B).hex()]
        )


class ExpectedMulTest(unittest.TestCase):
    def test_matches_independent_vector(self):
        self.assertEqual(expected_mul(MUL_A, MUL_B), MUL_EXPECTED)

    def test_multiplication_by_one_is_identity(self):
        one = bytes([1]) + bytes(15)
        self.assertEqual(expected_mul(MUL_A, one), MUL_A)

    def test_is_commutative(self):
        self.assertEqual(expected_mul(MUL_A, MUL_B), expected_mul(MUL_B, MUL_A))

    def test_rejects_wrong_operand_length(self):
        with self.assertRaises(ValueError):
            expected_mul(MUL_A[:15], MUL_B)


class DrainTest(unittest.TestCase):
    def test_idle_port_is_polled_without_a_blocking_read(self):
        with mock.patch.object(ulx3s_uart.time, "sleep"), mock.patch.object(
            ulx3s_uart.time, "time", side_effect=[0.0, 0.01, 0.06]
        ):
            self.assertEqual(ulx3s_uart.drain(IdleSerial()), b"")


class MulExitStatusTest(unittest.TestCase):
    def test_correct_product_succeeds(self):
        self.assertEqual(run_mul(MUL_EXPECTED), 0)

    def test_single_flipped_bit_is_rejected(self):
        wrong = bytearray(MUL_EXPECTED)
        wrong[0] ^= 0x01
        self.assertEqual(len(wrong), 16)
        self.assertEqual(run_mul(bytes(wrong)), 1)

    def test_flipped_bit_in_last_byte_is_rejected(self):
        wrong = bytearray(MUL_EXPECTED)
        wrong[15] ^= 0x80
        self.assertEqual(run_mul(bytes(wrong)), 1)

    def test_all_zero_response_is_rejected(self):
        self.assertEqual(run_mul(bytes(16)), 1)

    def test_operands_echoed_back_are_rejected(self):
        # A bridge that loops input to output returns a plausible 16 bytes.
        self.assertEqual(run_mul(MUL_A), 1)

    def test_driver_sends_the_documented_command_framing(self):
        fake = FakeSerial(MUL_EXPECTED, command_len=1 + 32)
        with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
            ulx3s_uart.main(
                ["--port", "/dev/null", "--tx", "mul", "--payload", (MUL_A + MUL_B).hex()]
            )
        self.assertEqual(fake.written, bytes([ulx3s_uart.MUL128]) + MUL_A + MUL_B)


if __name__ == "__main__":
    unittest.main()
