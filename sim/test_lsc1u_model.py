import random
import unittest

from lsc1u_model import execute, gf128_mul
from scalar_step_oracle import multiply as full_lsc1_mul


class LSC1uOracleTests(unittest.TestCase):
    def test_retained_boundary_matches_full_lsc1_oracle(self):
        rng = random.Random(0x1C51)
        for _ in range(500):
            a = rng.getrandbits(128)
            b = rng.getrandbits(128)
            self.assertEqual(gf128_mul(a, b), full_lsc1_mul(a, b))
            ab = a.to_bytes(16, "little") + b.to_bytes(16, "little")
            interleaved = b"".join(
                bytes(pair) for pair in zip(ab[:16], ab[16:])
            )
            self.assertEqual(
                execute(0x01, interleaved),
                (a ^ b).to_bytes(16, "little"),
            )
            self.assertEqual(execute(0x02, ab),
                             full_lsc1_mul(a, b).to_bytes(16, "little"))
            self.assertEqual(execute(0x03, ab[:16]), ab[:16])

    def test_fixed_framing_is_enforced(self):
        for opcode in (0x01, 0x02, 0x03, 0x04):
            with self.assertRaises(ValueError):
                execute(opcode, b"")


if __name__ == "__main__":
    unittest.main()
