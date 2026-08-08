from __future__ import annotations

import json
import unittest
from pathlib import Path

from silicon_bringup.bringup import BUSY, DONE, FAULT, RX_READY, RX_VALID, TX_VALID, Driver, DryRunBackend, receipt, validate_receipt


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
        self.assertEqual(pins.uio_out & (TX_VALID | BUSY | FAULT), TX_VALID | BUSY | FAULT)
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

    def test_mul_b_bytes_observe_rtl_backpressure(self):
        driver = Driver(DryRunBackend()); driver.reset(); driver.send(2)
        for _ in range(16): driver.send(0)
        driver._cycle(ui=0, uio=1)
        self.assertFalse(driver.backend.pins().uio_out & RX_READY)
        for _ in range(6):
            driver._cycle()
            self.assertFalse(driver.backend.pins().uio_out & RX_READY)
        driver._cycle()
        self.assertTrue(driver.backend.pins().uio_out & RX_READY)

    def test_mul_result_waits_for_tail_bits_and_transmit_edge(self):
        driver = Driver(DryRunBackend()); driver.reset(); driver.send(2)
        for _ in range(31): driver.send(0)
        while not driver.backend.pins().uio_out & RX_READY: driver._cycle()
        driver._cycle(ui=0, uio=RX_VALID)
        for _ in range(7):
            self.assertFalse(driver.backend.pins().uio_out & (RX_READY | TX_VALID))
            driver._cycle()
        self.assertFalse(driver.backend.pins().uio_out & (RX_READY | TX_VALID))
        driver._cycle()
        self.assertTrue(driver.backend.pins().uio_out & TX_VALID)

    def test_mul_response_has_rtl_transmit_valid_bubbles(self):
        cases = json.loads((Path(__file__).parent / "vectors.json").read_text())["cases"]
        case = next(item for item in cases if item["opcode"] == "MUL")
        driver = Driver(DryRunBackend()); driver.reset()
        driver.send(2)
        for value in bytes.fromhex(case["a"] + case["b"]): driver.send(value)
        while not driver.backend.pins().uio_out & TX_VALID: driver._cycle()
        first = driver.backend.pins().uo_out
        driver._cycle(uio=1 << 3)
        self.assertFalse(driver.backend.pins().uio_out & (RX_READY | TX_VALID))
        driver._cycle()
        self.assertTrue(driver.backend.pins().uio_out & TX_VALID)
        tail, done = driver.receive_all()
        self.assertEqual(bytes((first,)) + tail, bytes.fromhex(case["expected"]))
        self.assertTrue(done)

    def test_final_tx_ack_cannot_accept_same_edge_input(self):
        backend = DryRunBackend(); driver = Driver(backend); driver.reset(); driver.send(0x7F)
        self.assertTrue(backend.pins().uio_out & TX_VALID)
        driver._cycle(ui=3, uio=(1 << 3) | 1)
        self.assertIsNone(backend.command)
        self.assertTrue(backend.pins().uio_out & DONE)
        driver._cycle()
        self.assertTrue(backend.pins().uio_out & RX_READY)

    def test_reset_suppresses_pending_done_immediately(self):
        backend = DryRunBackend(); driver = Driver(backend); driver.reset(); driver.send(0x7F)
        driver._cycle(uio=1 << 3)
        self.assertTrue(backend.pins().uio_out & DONE)
        backend.drive(ui_in=0, uio_in=0, ena=True, rst_n=False)
        self.assertFalse(backend.pins().uio_out & DONE)

    def test_reset_and_deselect_abort_partial_work_and_uio6_is_ignored(self):
        driver = Driver(DryRunBackend()); driver.reset(); driver.send(3); driver.send(0x12)
        self.assertTrue(driver.backend.pins().uio_out & BUSY)
        driver._cycle(uio=1 << 6)
        self.assertEqual(driver.backend.command, 3)
        self.assertEqual(driver.backend.pins().uio_out & (BUSY | TX_VALID), BUSY | TX_VALID)
        self.assertTrue(driver.reset().uio_out & RX_READY)
        driver.send(3); driver.send(0x34); driver.deselect_abort()
        self.assertTrue(driver.backend.pins().uio_out & RX_READY)

    def test_schema_accepts_dry_run_and_rejects_hardware_lie(self):
        validate_receipt(receipt())
        dishonest = receipt(); dishonest["execution"] = {"kind": "hardware", "real_silicon": False, "transport": "none"}
        with self.assertRaises(ValueError): validate_receipt(dishonest)
        relabelled = receipt(); relabelled["execution"].update(kind="hardware", real_silicon=True)
        with self.assertRaises(ValueError): validate_receipt(relabelled)
        disguised = receipt(); disguised["execution"].update(kind="hardware", real_silicon=True, transport="deterministic Python pin-model ")
        with self.assertRaises(ValueError): validate_receipt(disguised)
        schema = json.loads((Path(__file__).parent / "receipt.schema.json").read_text())
        execution = schema["properties"]["execution"]["properties"]
        self.assertNotIn("hardware", execution["kind"]["enum"])
        self.assertEqual(execution["real_silicon"], {"const": False})
        numeric = receipt(); numeric["execution"]["real_silicon"] = 0
        with self.assertRaises(ValueError): validate_receipt(numeric)
        empty_transport = receipt(); empty_transport["execution"]["transport"] = ""
        with self.assertRaises(ValueError): validate_receipt(empty_transport)
        numeric_oracle = receipt(); numeric_oracle["oracle"]["matched"] = 1
        with self.assertRaises(ValueError): validate_receipt(numeric_oracle)
        numeric_outcome = receipt(); numeric_outcome["outcome"]["passed"] = 1
        with self.assertRaises(ValueError): validate_receipt(numeric_outcome)

    def test_json_schema_requires_complete_ordered_corpus(self):
        schema = json.loads((Path(__file__).parent / "receipt.schema.json").read_text())
        vector_ids = [case["id"] for case in json.loads((Path(__file__).parent / "vectors.json").read_text())["cases"]]
        self.assertEqual(schema["properties"]["vectors"], {"const": vector_ids})
        observations = schema["properties"]["observations"]
        self.assertEqual(observations["minItems"], len(vector_ids))
        self.assertEqual(observations["maxItems"], len(vector_ids))
        constrained_ids = [item["allOf"][1]["properties"]["id"]["const"] for item in observations["prefixItems"]]
        self.assertEqual(constrained_ids, vector_ids)
        expected = [case["expected"] for case in json.loads((Path(__file__).parent / "vectors.json").read_text())["cases"]]
        constrained_expected = [item["allOf"][1]["properties"]["expected"]["const"] for item in observations["prefixItems"]]
        self.assertEqual(constrained_expected, expected)
        self.assertTrue(all("if" in item["allOf"][2] and "else" in item["allOf"][2] for item in observations["prefixItems"]))
        self.assertEqual(len(schema["allOf"]), 7)
        self.assertEqual(schema["properties"]["execution"]["properties"]["transport"]["minLength"], 1)

    def test_schema_rejects_forged_or_incomplete_results(self):
        for mutate in (
            lambda value: value["observations"][0].update(received="ff" * 16),
            lambda value: value["observations"][0].update(received="ff" * 16, expected="ff" * 16),
            lambda value: value["observations"][0].update(received=value["observations"][0]["received"].upper()),
            lambda value: value["observations"][0].update(expected="00 " * 15 + "00"),
            lambda value: value["observations"][0].update(retire_done_pulse=False),
            lambda value: value.update(vectors=value["vectors"][:-1]),
            lambda value: (value.update(vectors=value["vectors"][:-1]), value.update(observations=value["observations"][:-1])),
            lambda value: value["outcome"].update(passed=False),
        ):
            with self.subTest(mutate=mutate):
                forged = receipt(); mutate(forged)
                with self.assertRaises(ValueError): validate_receipt(forged)

if __name__ == "__main__": unittest.main()
