import unittest

from fpga_harness.lsc1u_protocol import expected, gf128_mul, load_corpus, payload


class OracleAndCorpusTest(unittest.TestCase):
    def test_corpus_is_unique_complete_and_well_formed(self):
        cases = load_corpus()
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertEqual({case["opcode"] for case in cases}, {"SET", "XOR", "MUL"})
        for case in cases:
            self.assertEqual(len(bytes.fromhex(case["a"])), 16)
            self.assertEqual(len(payload(case)), 16 if case["opcode"] == "SET" else 32)
            self.assertEqual(len(expected(case)), 16)
            self.assertGreater(max(case["rx_stalls"] + case["tx_stalls"]), 0)

    def test_polynomial_reduction_and_identities(self):
        zero = bytes(16)
        one = bytes([1]) + bytes(15)
        top = bytes(15) + bytes([0x80])
        two = bytes([2]) + bytes(15)
        self.assertEqual(gf128_mul(top, two), bytes([0x87]) + bytes(15))
        self.assertEqual(gf128_mul(bytes([0xff]) * 16, one), bytes([0xff]) * 16)
        self.assertEqual(gf128_mul(bytes([0xff]) * 16, zero), zero)


if __name__ == "__main__":
    unittest.main()
