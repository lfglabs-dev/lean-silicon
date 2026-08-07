from __future__ import annotations

import json
import unittest
from pathlib import Path

from silicon_bringup.bringup import BUSY, DONE, FAULT, RX_READY, TX_VALID, Driver, DryRunBackend, receipt, validate_receipt


class BringupTest(unittest.TestCase):
    def test_deterministic_vectors_match_independent_oracle(self):
        result = receipt()
        self.assertTrue(result["outcome"]["passed"])
        self.assertTrue(result["oracle"]["matched"])
        self.assertEqual({x["opcode"] for x in result["observations"]}, {"SET", "XOR", "MUL"})
        fixture = json.loads((Path(__file__).parent / "fixtures" / "dry-run-receipt.json").read_text())
        self.assertEqual(result, fixture)

    def test_documented_mapping_matches_the_implemented_wrapper(self):
        top = (Path(__file__).parents[1] / "src" / "tt_um_lfglabs_lsc1u.sv").read_text()
        self.assertIn(".rx_valid(uio_in[0])", top)
        self.assertIn(".tx_ready(uio_in[3])", top)
        self.assertIn("8'b10110110", top)
        self.assertIn("{done_pulse, 1'b0, fault, busy, 1'b0, tx_valid, rx_ready, 1'b0}", top)

    def test_fault_is_observable_until_error_byte_is_accepted(self):
        driver = Driver(DryRunBackend()); driver.reset(); driver.send(0x7F)
        pins = driver.backend.pins()
        self.assertTrue(pins.uio_out & (TX_VALID | BUSY | FAULT))
        value, done = driver.receive_all()
        self.assertEqual(value, b"\xe0"); self.assertTrue(done)
        self.assertTrue(driver.backend.pins().uio_out & RX_READY)

    def test_reused_backend_retires_each_transaction(self):
        driver = Driver(DryRunBackend()); driver.reset()
        for value in (0x12, 0x34):
            driver.send(3)
            received = bytearray(); done = False
            for _ in range(16):
                driver.send(value)
                part, retired = driver.receive_all()
                received.extend(part); done |= retired
            self.assertEqual(received, bytes((value,)) * 16)
            self.assertTrue(done)
            self.assertTrue(driver.backend.pins().uio_out & RX_READY)

    def test_driver_run_preserves_progressive_responses(self):
        cases = json.loads((Path(__file__).parent / "vectors.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                driver = Driver(DryRunBackend()); driver.reset()
                result = driver.run(case)
                self.assertEqual(result["answer"].hex(), case["expected"])
                self.assertTrue(result["done"])

    def test_final_tx_ack_cannot_accept_same_edge_input(self):
        backend = DryRunBackend(); driver = Driver(backend); driver.reset(); driver.send(0x7F)
        self.assertTrue(backend.pins().uio_out & TX_VALID)
        driver._cycle(ui=3, uio=(1 << 3) | 1)
        self.assertIsNone(backend.command)
        self.assertTrue(backend.pins().uio_out & DONE)
        driver._cycle()
        self.assertTrue(backend.pins().uio_out & RX_READY)

    def test_reset_and_deselect_abort_partial_work_and_uio6_is_ignored(self):
        driver = Driver(DryRunBackend()); driver.reset(); driver.send(3); driver.send(0x12)
        self.assertTrue(driver.backend.pins().uio_out & BUSY)
        self.assertTrue(driver.reset().uio_out & RX_READY)
        driver.send(3); driver.send(0x34); driver.deselect_abort()
        self.assertTrue(driver.backend.pins().uio_out & RX_READY)
        driver._cycle(uio=1 << 6)
        self.assertTrue(driver.backend.pins().uio_out & RX_READY)

    def test_schema_accepts_dry_run_and_rejects_hardware_lie(self):
        validate_receipt(receipt())
        dishonest = receipt(); dishonest["execution"] = {"kind": "hardware", "real_silicon": False, "transport": "none"}
        with self.assertRaises(ValueError): validate_receipt(dishonest)
        relabelled = receipt(); relabelled["execution"].update(kind="hardware", real_silicon=True)
        with self.assertRaises(ValueError): validate_receipt(relabelled)

    def test_schema_rejects_forged_or_incomplete_results(self):
        for mutate in (
            lambda value: value["observations"][0].update(received="ff" * 16),
            lambda value: value["observations"][0].update(received="ff" * 16, expected="ff" * 16),
            lambda value: value["observations"][0].update(retire_done_pulse=False),
            lambda value: value.update(vectors=value["vectors"][:-1]),
            lambda value: value["outcome"].update(passed=False),
        ):
            with self.subTest(mutate=mutate):
                forged = receipt(); mutate(forged)
                with self.assertRaises(ValueError): validate_receipt(forged)

if __name__ == "__main__": unittest.main()
