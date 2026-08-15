"""Cross-check the full-profile Lean/RTL observable contract."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AuthoredRtlContractTests(unittest.TestCase):
    def test_rx_stall_requires_blocked_valid_transfer(self) -> None:
        rtl = [ROOT / path for path in (
            "asic_core/rtl/lsc1_packet_rx.sv",
            "asic_core/rtl/lsc1_packet_tx.sv",
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
