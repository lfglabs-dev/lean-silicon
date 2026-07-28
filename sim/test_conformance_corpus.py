"""Focused checks for the immutable conformance corpus and its generator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import unittest

import lsc1_transaction as lsc1

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance/corpus-v1.json"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class ConformanceCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CORPUS.read_text())

    def test_generator_is_byte_reproducible(self) -> None:
        path = ROOT / "tools/generate_conformance_corpus.py"
        spec = importlib.util.spec_from_file_location("_corpus_generator", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        regenerated = {
            "schema": "lean-silicon-conformance-v1",
            "frozen_upstream": self.corpus["frozen_upstream"],
            "cases": module.build_cases(),
        }
        expected = json.dumps(regenerated, indent=2, sort_keys=True) + "\n"
        self.assertEqual(CORPUS.read_text(), expected)

    def test_ids_fingerprints_and_required_records(self) -> None:
        ids = [case["case_id"] for case in self.corpus["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for case in self.corpus["cases"]:
            with self.subTest(case_id=case["case_id"]):
                body = {key: value for key, value in case.items() if key != "fingerprint"}
                digest = hashlib.sha256(canonical(body)).hexdigest()
                self.assertEqual(case["fingerprint"], f"sha256:{digest}")
                self.assertIn("request_hex", case["raw"])
                self.assertIn("response_hex", case["raw"])
                self.assertIn("initial_state", case)
                self.assertIn("final_state", case)
                self.assertIn("retire", case)
                if case["retire"]["attempted"]:
                    self.assertTrue(case["retire"]["done_pulse"])
                if case["upstream"]["mode"] == "program_execute":
                    staged = case["staged_transition"]
                    self.assertEqual(
                        case["upstream"]["transition"],
                        {
                            "next_pc": staged["next_pc"],
                            "next_fp": staged["next_fp"],
                            "writes": staged["writes"],
                        },
                    )

    def test_coverage_contract(self) -> None:
        covered = {label for case in self.corpus["cases"] for label in case["coverage"]}
        required = {
            "SET", "XOR", "MUL", "backsolve_a", "backsolve_b", "Cell", "Pc", "Fp",
            "taken", "not_taken", "inverse", "deferred", "malformed", "precedence",
            "abort", "reset", "stall", "backpressure",
        }
        self.assertEqual(required - covered, set())

    def test_raw_exchanges_replay(self) -> None:
        for case in self.corpus["cases"]:
            if not case["raw"]["response_hex"] or case["case_id"].startswith("lane."):
                continue
            with self.subTest(case_id=case["case_id"]):
                endpoint = lsc1.Lsc1Endpoint()
                response, _ = lsc1.drive(endpoint, bytes.fromhex(case["raw"]["request_hex"]))
                self.assertEqual(response.hex(), case["raw"]["response_hex"])
                if case["retire"]["attempted"]:
                    retired, _ = lsc1.drive(
                        endpoint, bytes.fromhex(case["retire"]["request_hex"])
                    )
                    self.assertEqual(retired.hex(), case["retire"]["response_hex"])

    def test_protocol_only_scope_is_explicit(self) -> None:
        protocol_only = [
            case for case in self.corpus["cases"]
            if case["upstream"]["mode"] == "protocol_only"
        ]
        self.assertTrue(protocol_only)
        for case in protocol_only:
            self.assertIn("reason", case["upstream"])


if __name__ == "__main__":
    unittest.main()
