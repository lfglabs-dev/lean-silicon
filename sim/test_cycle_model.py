from __future__ import annotations

import random
import unittest

from cycle_model import StreamALUCycleModel
from model import Command, StreamALUModel


def run_transaction(command: int, payload: bytes, seed: int) -> tuple[bytes, int]:
    rng = random.Random(seed)
    dut = StreamALUCycleModel()
    tx = bytes((command,)) + payload
    tx_pos = 0
    output = bytearray()

    for cycle in range(100_000):
        send = tx_pos < len(tx) and rng.random() < 0.72
        ready = rng.random() < 0.67
        rx_data = tx[tx_pos] if send else 0

        pins = dut.step(rx_data=rx_data, rx_valid=send, tx_ready=ready)
        if send and pins.rx_ready:
            tx_pos += 1
        if pins.tx_valid and ready:
            output.append(pins.tx_data)

        if tx_pos == len(tx) and dut.state.name == "IDLE":
            return bytes(output), cycle + 1

    raise TimeoutError("cycle model did not return to IDLE")


def run_ideal(command: int, payload: bytes) -> tuple[bytes, int]:
    """Run with a continuously-valid source and always-ready sink."""
    dut = StreamALUCycleModel()
    transaction = bytes((command,)) + payload
    position = 0
    output = bytearray()

    for cycle in range(10_000):
        send = position < len(transaction)
        rx_data = transaction[position] if send else 0
        pins = dut.step(rx_data=rx_data, rx_valid=send, tx_ready=True)
        if send and pins.rx_ready:
            position += 1
        if pins.tx_valid:
            output.append(pins.tx_data)
        if position == len(transaction) and dut.state.name == "IDLE":
            return bytes(output), cycle + 1
    raise TimeoutError("ideal cycle model did not return to IDLE")


class RandomBackpressureTests(unittest.TestCase):
    def test_commands(self) -> None:
        rng = random.Random(0xC1AC017)
        commands = [Command.XOR128, Command.MUL128, Command.SET128, Command.NONZERO, Command.STATUS]
        for case in range(1_000):
            command = commands[case % len(commands)]
            if command is Command.XOR128:
                payload = rng.randbytes(32)
            elif command is Command.MUL128:
                payload = rng.randbytes(32)
            elif command in (Command.SET128, Command.NONZERO):
                payload = rng.randbytes(16)
            else:
                payload = b""
            expected = StreamALUModel.execute(command, payload).output
            actual, _ = run_transaction(command, payload, seed=case * 17 + 3)
            self.assertEqual(actual, expected)

    def test_exact_no_stall_latencies(self) -> None:
        zero = bytes(16)
        xor_payload = bytes(range(32))
        mul_payload = (1).to_bytes(16, "little") + (1).to_bytes(16, "little")
        cases = [
            (Command.XOR128, xor_payload, 33),
            (Command.MUL128, mul_payload, 161),
            (Command.SET128, zero, 17),
            (Command.NONZERO, zero, 17),
            (Command.STATUS, b"", 5),
            (Command.CLEAR, b"", 1),
        ]
        for command, payload, expected_cycles in cases:
            with self.subTest(command=command):
                _, cycles = run_ideal(command, payload)
                self.assertEqual(cycles, expected_cycles)

    def test_invalid_command(self) -> None:
        actual, _ = run_transaction(0x99, b"", seed=4)
        self.assertEqual(actual, b"\xe0")


if __name__ == "__main__":
    unittest.main()
