"""Regression checks for the historical PR #19 physical-evidence archive."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from fpga_harness import ulx3s_uart


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "results" / "fpga-lsc1-20260726"
README = EVIDENCE / "README.md"
EXCHANGES = EVIDENCE / "exchanges.jsonl"
PHYSICAL_DIGEST = "87b204ec01e0ff495b102f0ea6f934033f47c8c8b70f858b67f8c5a908cf5795"
REPLAY_DIGEST = "827d6f1e3e429a85035005fdff52057fcba14d96f6b757c9b4240e446ff966fb"

ORACLE = {
    "status": ulx3s_uart.STATUS_SIGNATURE,
    "set": bytes(range(16)),
    "xor": bytes([0xF0] * 16),
    "mul": ulx3s_uart.expected_mul(
        bytes.fromhex("00112233445566778899aabbccddeeff"),
        bytes.fromhex("ffeeddccbbaa99887766554433221100"),
    ),
}

REQUESTS = {
    "status": ulx3s_uart.encode_request("status", include_resync=False),
    "set": ulx3s_uart.encode_request(
        "set", value=bytes(range(16)), include_resync=False
    ),
    "xor": ulx3s_uart.encode_request(
        "xor",
        a=bytes(range(16)),
        b=bytes(range(0xF0, 0x100)),
        include_resync=False,
    ),
    "mul": ulx3s_uart.encode_request(
        "mul",
        a=bytes.fromhex("00112233445566778899aabbccddeeff"),
        b=bytes.fromhex("ffeeddccbbaa99887766554433221100"),
        include_resync=False,
    ),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ExchangeEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            json.loads(line) for line in EXCHANGES.read_text().splitlines()
        ]

    def test_five_verbatim_records_match_frozen_oracle(self) -> None:
        self.assertEqual([r["operation"] for r in self.records],
                         ["status", "set", "xor", "mul", "status"])
        for record in self.records:
            self.assertIs(record["repo_dirty"], True)
            self.assertEqual(
                record["repo_head"],
                "618b39923862e660589cc6258e258783904b3861",
            )
            for field in ("request", "response"):
                raw = bytes.fromhex(record[f"{field}_hex"])
                self.assertEqual(len(raw), record[f"{field}_length"])
                self.assertEqual(digest(raw), record[f"{field}_sha256"])
            self.assertEqual(bytes.fromhex(record["request_hex"]),
                             REQUESTS[record["operation"]])
            expected = ORACLE[record["operation"]]
            self.assertEqual(bytes.fromhex(record["response_hex"]), expected)
            if record["expected_hex"] is not None:
                declared = bytes.fromhex(record["expected_hex"])
                self.assertEqual(declared, expected)
                self.assertEqual(len(declared), record["expected_length"])
                self.assertEqual(digest(declared), record["expected_sha256"])

    def test_status_is_not_rewritten_as_a_boolean_pass(self) -> None:
        statuses = [r for r in self.records if r["operation"] == "status"]
        self.assertEqual(len(statuses), 2)
        for record in statuses:
            self.assertIsNone(record["pass"])
            self.assertEqual(bytes.fromhex(record["response_hex"]), ORACLE["status"])


class ArchiveQualificationTest(unittest.TestCase):
    def test_evidence_checksums(self) -> None:
        lines = (EVIDENCE / "EVIDENCE_SHA256SUMS").read_text().splitlines()
        entries = {
            name: expected for expected, name in
            (line.split("  ", 1) for line in lines)
        }
        self.assertEqual(
            set(entries),
            {"candidate-harness.patch", "exchanges.jsonl",
             "openfpgaloader-sram.txt", "program-run.json"},
        )
        for name, expected in entries.items():
            self.assertEqual(digest((EVIDENCE / name).read_bytes()), expected)

    def test_metadata_carries_required_non_overclaims(self) -> None:
        text = README.read_text()
        required = (
            "repo_dirty: true",
            "observed PCB is an ULX3S v3.1.8",
            "identifies the LFE5U-85F FPGA, not the ULX3S PCB",
            "physical bitstream is not committed",
            "candidate reconstruction",
            "does not prove packet-v1",
            "not binary identity",
            "not, by itself, source provenance",
            PHYSICAL_DIGEST,
            REPLAY_DIGEST,
        )
        for phrase in required:
            self.assertIn(phrase, text)
        self.assertNotEqual(PHYSICAL_DIGEST, REPLAY_DIGEST)

    def test_candidate_patch_is_self_contained_but_not_claimed_exact(self) -> None:
        patch = (EVIDENCE / "candidate-harness.patch").read_text()
        for path in (
            "fpga_harness/build_ulx3s.sh",
            "fpga_harness/rtl/uart_rx.sv",
            "fpga_harness/rtl/uart_tx.sv",
            "fpga_harness/rtl/ulx3s_lsc1_top.sv",
            "fpga_harness/ulx3s_v308.lpf",
            "test/tb_ulx3s_uart.sv",
        ):
            self.assertIn(f"diff --git a/{path} b/{path}", patch)
        self.assertIn("115200", patch)
        self.assertIn("candidate reconstruction", README.read_text())

    def test_physical_bitstream_is_absent(self) -> None:
        self.assertFalse(any(EVIDENCE.glob("*.bit")))


if __name__ == "__main__":
    unittest.main()
