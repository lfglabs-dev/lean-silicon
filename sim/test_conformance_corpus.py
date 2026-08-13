"""Focused checks for the immutable conformance corpus and its generator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import unittest

from sim import lsc1_transaction as lsc1

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance/corpus-v2.json"
CORPUS_V3 = ROOT / "conformance/corpus-v3.json"
FROZEN_V1_DIGESTS = {
    "corpus-v1.json": "76ba2ea25dd2f20ea3e50c6d25c774d1fbf45b2960b65d233680c284c0c111d7",
    "schema-v1.json": "69e83e18dac54c6271758a759e28ed60697aa5db906a1f51f2c2bc310ba33876",
}


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
            "schema": "lean-silicon-conformance-v2",
            "frozen_upstream": self.corpus["frozen_upstream"],
            "cases": module.build_cases(),
        }
        expected = json.dumps(regenerated, indent=2, sort_keys=True) + "\n"
        self.assertEqual(CORPUS.read_text(), expected)

    def test_published_v1_artifacts_remain_frozen(self) -> None:
        for name, expected in FROZEN_V1_DIGESTS.items():
            with self.subTest(artifact=name):
                actual = hashlib.sha256((ROOT / "conformance" / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

    def test_ids_fingerprints_and_required_records(self) -> None:
        self.assertEqual(
            self.corpus["frozen_upstream"],
            {
                "repository": "https://github.com/leanEthereum/leanVM-b.git",
                "commit": "c308034ab78619b39a59d26f3dc60e7df5b52649",
            },
        )
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

    def test_reset_case_records_the_actual_pre_edge_state(self) -> None:
        reset = next(
            case for case in self.corpus["cases"]
            if case["case_id"] == "lane.reset.priority"
        )
        self.assertEqual(reset["initial_state"]["last_status"], "ABORTED")
        self.assertEqual(reset["initial_state"]["last_fault"], "ABORTED")
        self.assertEqual(reset["initial_state"]["abort_count"], 1)
        self.assertEqual(reset["final_state"]["abort_count"], 0)


class Blake3ServiceLifecycleV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CORPUS_V3.read_text())

    def test_generator_is_byte_reproducible(self) -> None:
        path = ROOT / "tools/generate_conformance_corpus_v3.py"
        spec = importlib.util.spec_from_file_location("_corpus_generator_v3", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(CORPUS_V3.read_bytes(), module.render_corpus())

    def test_v2_remains_immutable(self) -> None:
        self.assertEqual(
            hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "0c07b8592dbc4212076092ebb8aba81403b50ddd22daa51e91f4fcb4320c7e75",
        )

    def test_nominal_exchange_is_byte_exact(self) -> None:
        nominal = next(case for case in self.corpus["cases"] if case["case_id"] == "blake3.lifecycle.nominal")
        self.assertEqual(nominal["statuses"], ["SERVICE_REQUIRED", "OK", "RETIRED"])
        self.assertEqual(len(bytes.fromhex(nominal["service_required"]["internal_payload_hex"])), 122)
        self.assertEqual(len(bytes.fromhex(nominal["service_required"]["host_envelope_hex"])), 131)
        self.assertEqual(len(bytes.fromhex(nominal["service_response"]["host_envelope_hex"])), 53)
        for field in ("blake3_request_hex", "service_required_frame_hex", "service_response_frame_hex", "result_frame_hex", "retire_request_hex", "retire_response_hex"):
            self.assertTrue(nominal["wire"][field])

    def test_binding_mutations_and_controls_are_frozen(self) -> None:
        by_id = {case["case_id"]: case for case in self.corpus["cases"]}
        required = {
            "blake3.reject.txn_id", "blake3.reject.service_id",
            "blake3.reject.kind", "blake3.reject.digest",
            "blake3.reject.metadata.counter", "blake3.reject.metadata.block_len",
            "blake3.reject.metadata.flags", "blake3.reject.replay",
            "blake3.control.abort", "blake3.control.reset",
        }
        self.assertFalse(required - by_id.keys())
        for case_id in required:
            with self.subTest(case_id=case_id):
                self.assertTrue(by_id[case_id]["detected"])
                self.assertTrue(by_id[case_id]["fingerprint"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
