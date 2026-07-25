import random
import unittest

from scalar_step_oracle import Fault, encode, multiply, run


class ScalarStepOracleTests(unittest.TestCase):
    def test_seeded_field_differential_algorithms(self):
        rng = random.Random(0xC308034A)
        for _ in range(128):
            a, b = rng.getrandbits(128), rng.getrandbits(128)
            self.assertEqual(multiply(a, b), multiply(b, a))

    def test_runner_profile_and_edges(self):
        program = [("set", 2, 0x12), ("set", 3, 0x34), ("xor", 2, 3, 4),
                   ("mul", 2, 3, 5), ("deref_pc", 0, 6, 7), ("deref_fp", 0, 7, 7),
                   ("jump", 1, 0, 0), ("set", 0, 0)]
        machine = run(program, (1, 0))
        self.assertEqual((machine.cycles, machine.read(4), machine.read(5)), (7, 0x26, multiply(0x12, 0x34)))
        self.assertEqual(machine.read(6), encode(6))
        self.assertEqual(machine.read(7), 1)
        with self.assertRaisesRegex(Fault, "write_conflict"):
            run([("set", 2, 1), ("set", 2, 2), ("jump", 1, 0, 0), ("set", 0, 0)], (1, 0))

