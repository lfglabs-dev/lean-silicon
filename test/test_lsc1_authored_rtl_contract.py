"""Cross-check the full-profile Lean/RTL observable contract."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim import lsc1_transaction as protocol
from tools.lsc1_authored_rtl_contract import parse_trace


class AuthoredRtlContractTests(unittest.TestCase):
    @staticmethod
    def trace_line(raw: bytes, request: int, origin: int, *, rx: int = 0,
                   tx: int = 0, done: int = 0) -> str:
        return (
            f"RESPONSE {raw.hex()}\n"
            f"RTL_TRANSACTION request_opcode={request:02x} "
            f"origin_opcode={origin:02x} status={raw[2]:02x} "
            f"rx_blocked={rx} tx_blocked={tx} done={done}\n"
        )

    def test_trace_relabeling_is_rejected(self) -> None:
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        forged = self.trace_line(result, 0x03, 0x08)
        with self.assertRaisesRegex(SystemExit, "provenance changed"):
            parse_trace("relabel", forged, [result])

    def test_done_cannot_be_borrowed_across_transactions(self) -> None:
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        retired = protocol.ResponseFrame(protocol.Status.RETIRED, b"").encode()
        forged = (self.trace_line(result, 0x03, 0x03, done=1) +
                  self.trace_line(retired, 0x12, 0x03, done=0))
        with self.assertRaisesRegex(SystemExit, "non-RETIRE response"):
            parse_trace("borrowed-done", forged, [result, retired])

    def test_stalls_remain_transaction_local(self) -> None:
        first = protocol.ResponseFrame(protocol.Status.OK, b"a").encode()
        second = protocol.ResponseFrame(protocol.Status.OK, b"b").encode()
        trace = (self.trace_line(first, 0x03, 0x03, rx=1, tx=1) +
                 self.trace_line(second, 0x01, 0x01))
        facts = parse_trace("local-stalls", trace, [first, second])
        self.assertIn(("SET", "RX_STALL"), facts)
        self.assertIn(("SET", "TX_STALL"), facts)
        self.assertNotIn(("XOR", "RX_STALL"), facts)
        self.assertNotIn(("XOR", "TX_STALL"), facts)

    def test_retire_requires_exactly_one_cooccurring_done(self) -> None:
        retired = protocol.ResponseFrame(protocol.Status.RETIRED, b"").encode()
        forged = self.trace_line(retired, 0x12, 0x03, done=2)
        with self.assertRaisesRegex(SystemExit, "acceptance-edge done pulse"):
            parse_trace("duplicate-done", forged, [retired])

    def test_rx_stall_requires_blocked_valid_transfer(self) -> None:
        rtl = [ROOT / path for path in (
            "asic_core/rtl/lsc1_packet_rx.sv",
            "asic_core/rtl/lsc1_packet_tx.sv",
            "asic_core/rtl/lsc1_response_payload_mux.sv",
            "asic_core/rtl/lsc1_blake3_alias_check.sv",
            "asic_core/rtl/lsc1_request_validator.sv",
            "asic_core/rtl/lsc1_blake3_lifecycle.sv",
            "asic_core/rtl/gf2n_mul_bitstream.sv",
            "asic_core/rtl/gf128_mul_bitstream.sv",
            "asic_core/rtl/leanvm_b_stream_alu.sv",
            "asic_core/rtl/lsc1_stream_adapter.sv",
            "asic_core/rtl/lsc1_field_encoder.sv",
            "asic_core/rtl/lsc1_packet_frontend.sv",
            "test/packet_frontend/tb_lsc1_packet_vector.sv",
        )]
        with tempfile.TemporaryDirectory(prefix="lsc1-rx-stall-") as directory:
            simulator = Path(directory) / "packet-vector.vvp"
            request = Path(directory) / "empty.hex"
            request.write_text("")
            compiled = subprocess.run(
                ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
                 str(simulator), *(str(path) for path in rtl)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

            def rx_blocked(probe: str) -> int:
                completed = subprocess.run(
                    ["vvp", str(simulator), f"+REQUEST={request}", "+LENGTH=0",
                     f"+{probe}"],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(completed.returncode, 0,
                                 completed.stdout + completed.stderr)
                marker = "RTL_COUNTS rx_blocked="
                line = next(line for line in completed.stdout.splitlines()
                            if line.startswith(marker))
                return int(line.removeprefix(marker).split()[0])

            self.assertEqual(rx_blocked("TRACE_IDLE_RX_BLOCKED"), 0)
            self.assertEqual(rx_blocked("TRACE_VALID_RX_BLOCKED"), 1)

    def test_lean_and_authored_rtl_share_the_checked_observations(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/lsc1_authored_rtl_contract.py", "--verify"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("LSC1_AUTHORED_RTL_CONTRACT_PASS", completed.stdout)
        self.assertIn("source=rtl-traces", completed.stdout)
        self.assertIn("observations=30", completed.stdout)


if __name__ == "__main__":
    unittest.main()
