from __future__ import annotations

import random
import unittest

from model import (
    Command,
    StreamALUModel,
    gf_mul_bitserial,
    gf_mul_polynomial,
    int_to_le_bytes,
    mul_by_x,
)


class FieldTests(unittest.TestCase):
    def test_known_identities(self) -> None:
        samples = [0, 1, 2, 0x87, 1 << 127, (1 << 128) - 1]
        for a in samples:
            self.assertEqual(gf_mul_bitserial(a, 0), 0)
            self.assertEqual(gf_mul_bitserial(a, 1), a)
            self.assertEqual(gf_mul_bitserial(a, 2), mul_by_x(a))

    def test_random_gf128_against_independent_reference(self) -> None:
        rng = random.Random(0x1EA7BEEF)
        for _ in range(100_000):
            a = rng.getrandbits(128)
            b = rng.getrandbits(128)
            self.assertEqual(gf_mul_bitserial(a, b), gf_mul_polynomial(a, b))

    def test_exhaustive_simplified_gf8(self) -> None:
        # AES polynomial x^8 + x^4 + x^3 + x + 1 (low byte 0x1b).
        for a in range(256):
            for b in range(256):
                self.assertEqual(
                    gf_mul_bitserial(a, b, width=8, reduction_low=0x1B),
                    gf_mul_polynomial(a, b, width=8, reduction_low=0x1B),
                )


class ProtocolTests(unittest.TestCase):
    def test_xor_stream(self) -> None:
        a = bytes(range(16))
        b = bytes(255 - i for i in range(16))
        payload = bytes(x for pair in zip(a, b) for x in pair)
        result = StreamALUModel.execute(Command.XOR128, payload)
        self.assertEqual(result.output, bytes(x ^ y for x, y in zip(a, b)))
        self.assertEqual(result.input_data_beats, 32)

    def test_mul_stream(self) -> None:
        a = 0x0123456789ABCDEF_FEDCBA9876543210
        b = 0xDEADBEEFCAFEBABE_1020304050607080
        payload = int_to_le_bytes(a, 16) + int_to_le_bytes(b, 16)
        result = StreamALUModel.execute(Command.MUL128, payload)
        expected = int_to_le_bytes(gf_mul_polynomial(a, b), 16)
        self.assertEqual(result.output, expected)
        self.assertEqual(result.multiplier_bit_steps, 128)

    def test_nonzero(self) -> None:
        self.assertEqual(StreamALUModel.execute(Command.NONZERO, bytes(16)).output, b"\x00")
        self.assertEqual(
            StreamALUModel.execute(Command.NONZERO, bytes(15) + b"\x80").output,
            b"\x01",
        )

    def test_status(self) -> None:
        self.assertEqual(StreamALUModel.execute(Command.STATUS, b"").output, b"\x01\x01\x0f\x08")


if __name__ == "__main__":
    unittest.main()
