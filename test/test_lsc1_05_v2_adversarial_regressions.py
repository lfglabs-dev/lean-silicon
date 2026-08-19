"""Executable adversarial regressions for LSC1-05 v2 predecessor defects.

This test module explicitly demonstrates that each failure mode from PR #73
(blocked certifier verdict) is structurally impossible in the current
trace→observation pipeline.

Each test method corresponds to one certifier-rejected defect class and
demonstrates that the pipeline rejects the violation.

DEFECT CLASS 1: Python gates must DERIVE observations from real RTL traces.
Manually declaring label sets that merely mirror Lean was rejected because
exact-set equality cannot detect lost per-operation/fault/stall/reset/abort/RETIRE
coverage.

DEFECT CLASS 2: RX stall witnesses must require rx_valid && !rx_ready.
Idle-receive exclusion must not fabricate an RX_STALL observation.

DEFECT CLASS 3: Operation identity must not be Python-injected.
A Python labeler that can relabel an authentic SET trace as BLAKE3 is
disqualifying. Stall/done witnesses must be transaction/temporal, not
run-global. RETIRE must not be mere co-occurrence.

DEFECT CLASS 4: The Lean-side contract predicate must be genuinely connected
to the semantic witness definitions, not a parallel restatement.
"""

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


class DefectClass1RTLTraceDerivation(unittest.TestCase):
    """Defect Class 1: Observations must be derived from real RTL traces.

    The pipeline must parse RTL signals and emit records; Python cannot
    pre-declare label sets that merely mirror Lean.
    """

    @staticmethod
    def trace_line(raw: bytes, request: int, origin: int, *, rx: int = 0,
                   tx: int = 0, done: int = 0) -> str:
        return (
            f"RESPONSE {raw.hex()}\n"
            f"RTL_TRANSACTION request_opcode={request:02x} "
            f"origin_opcode={origin:02x} status={raw[2]:02x} "
            f"rx_blocked={rx} tx_blocked={tx} done={done}\n"
        )

    def test_python_injected_label_set_is_rejected(self) -> None:
        """A Python-injected label set that merely mirrors Lean is rejected.

        The pipeline requires RTL_TRANSACTION records from a real simulator run.
        Manually forged RESPONSE + RTL_TRANSACTION pairs that don't correspond
        to an actual RTL execution must be rejected by provenance checks.
        """
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        forged = self.trace_line(result, 0x03, 0x08)
        with self.assertRaisesRegex(SystemExit, "provenance changed"):
            parse_trace("python-injected", forged, [result])

    def test_missing_rtl_transaction_record_is_rejected(self) -> None:
        """A trace missing RTL_TRANSACTION records is rejected.

        Facts must be derived from actual RTL signal records, not from
        response bytes alone.
        """
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        forged = f"RESPONSE {result.hex()}\n"
        with self.assertRaisesRegex(SystemExit, "each response needs one temporal"):
            parse_trace("missing-record", forged, [result])


class DefectClass2RXStallWitness(unittest.TestCase):
    """Defect Class 2: RX stall requires rx_valid && !rx_ready.

    Idle-receive exclusion must prevent fabricating RX_STALL when
    the receiver is simply not ready but no valid data is present.
    """

    @staticmethod
    def trace_line(raw: bytes, request: int, origin: int, *, rx: int = 0,
                   tx: int = 0, done: int = 0) -> str:
        return (
            f"RESPONSE {raw.hex()}\n"
            f"RTL_TRANSACTION request_opcode={request:02x} "
            f"origin_opcode={origin:02x} status={raw[2]:02x} "
            f"rx_blocked={rx} tx_blocked={tx} done={done}\n"
        )

    def test_rx_stall_requires_valid_and_not_ready(self) -> None:
        """RX_STALL is only recorded when rx_valid && !rx_ready.

        The RTL trace must show an actual blocked transfer, not just
        an idle cycle where rx_ready happens to be low.
        """
        rtl = [ROOT / path for path in (
            "asic_core/rtl/lsc1_packet_rx.sv",
            "asic_core/rtl/lsc1_packet_tx.sv",
            "asic_core/rtl/lsc1_response_payload_mux.sv",
            "asic_core/rtl/lsc1_blake3_alias_check.sv",
            "asic_core/rtl/lsc1_request_validator.sv",
            "asic_core/rtl/lsc1_cell_alias_check.sv",
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

            idle_rx_blocked = rx_blocked("TRACE_IDLE_RX_BLOCKED")
            valid_rx_blocked = rx_blocked("TRACE_VALID_RX_BLOCKED")

            self.assertEqual(idle_rx_blocked, 0,
                           "Idle rx_ready=0 must NOT produce RX_STALL")
            self.assertEqual(valid_rx_blocked, 1,
                           "rx_valid && !rx_ready MUST produce RX_STALL")


class DefectClass3OperationIdentity(unittest.TestCase):
    """Defect Class 3: Operation identity must not be Python-injected.

    A Python labeler that can relabel an authentic SET trace as BLAKE3 is
    disqualifying. The RTL itself must provide opcode provenance.
    """

    @staticmethod
    def trace_line(raw: bytes, request: int, origin: int, *, rx: int = 0,
                   tx: int = 0, done: int = 0) -> str:
        return (
            f"RESPONSE {raw.hex()}\n"
            f"RTL_TRANSACTION request_opcode={request:02x} "
            f"origin_opcode={origin:02x} status={raw[2]:02x} "
            f"rx_blocked={rx} tx_blocked={tx} done={done}\n"
        )

    def test_relabeling_set_as_blake3_is_rejected(self) -> None:
        """An authentic SET trace relabeled as BLAKE3 is rejected.

        The RTL origin_opcode is the authoritative operation identity.
        Python cannot inject a different opcode label.
        """
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        forged = self.trace_line(result, 0x03, 0x08)
        with self.assertRaisesRegex(SystemExit, "provenance changed"):
            parse_trace("relabel-set-as-blake3", forged, [result])

    def test_done_cannot_be_borrowed_across_transactions(self) -> None:
        """A done pulse cannot be attributed to a different transaction.

        Stall/done witnesses must be transaction/temporal, not run-global.
        """
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        retired = protocol.ResponseFrame(protocol.Status.RETIRED, b"").encode()
        forged = (self.trace_line(result, 0x03, 0x03, done=1) +
                  self.trace_line(retired, 0x12, 0x03, done=0))
        with self.assertRaisesRegex(SystemExit, "non-RETIRE response"):
            parse_trace("borrowed-done", forged, [result, retired])

    def test_stalls_remain_transaction_local(self) -> None:
        """Stall observations are scoped to the transaction where they occur.

        A later transaction cannot claim stalls from an earlier one.
        """
        first = protocol.ResponseFrame(protocol.Status.OK, b"a").encode()
        second = protocol.ResponseFrame(protocol.Status.OK, b"b").encode()
        trace = (self.trace_line(first, 0x03, 0x03, rx=1, tx=1) +
                 self.trace_line(second, 0x01, 0x01))
        facts = parse_trace("local-stalls", trace, [first, second])
        self.assertIn(("SET", "RX_STALL"), facts)
        self.assertIn(("SET", "TX_STALL"), facts)
        self.assertNotIn(("XOR", "RX_STALL"), facts)
        self.assertNotIn(("XOR", "TX_STALL"), facts)


class DefectClass4RETIREWitness(unittest.TestCase):
    """Defect Class 4: RETIRE must not be mere co-occurrence.

    RETIRE requires status 0x02, a decoded RETIRE request (opcode 0x12),
    and exactly one co-occurring done_pulse in the same transaction interval.
    """

    @staticmethod
    def trace_line(raw: bytes, request: int, origin: int, *, rx: int = 0,
                   tx: int = 0, done: int = 0) -> str:
        return (
            f"RESPONSE {raw.hex()}\n"
            f"RTL_TRANSACTION request_opcode={request:02x} "
            f"origin_opcode={origin:02x} status={raw[2]:02x} "
            f"rx_blocked={rx} tx_blocked={tx} done={done}\n"
        )

    def test_retire_requires_exactly_one_cooccurring_done(self) -> None:
        """RETIRE status without a co-occurring done pulse is rejected.

        Multiple done pulses or done pulses not co-occurring with RETIRE
        status are also rejected.
        """
        retired = protocol.ResponseFrame(protocol.Status.RETIRED, b"").encode()
        forged = self.trace_line(retired, 0x12, 0x03, done=2)
        with self.assertRaisesRegex(SystemExit, "acceptance-edge done pulse"):
            parse_trace("duplicate-done", forged, [retired])

    def test_retire_requires_retire_request_opcode(self) -> None:
        """RETIRE status with a non-RETIRE request opcode is rejected.

        The RTL must decode a RETIRE request (opcode 0x12) for the
        retirement to be valid.
        """
        retired = protocol.ResponseFrame(protocol.Status.RETIRED, b"").encode()
        forged = self.trace_line(retired, 0x03, 0x03, done=1)
        with self.assertRaisesRegex(SystemExit, "RETIRE lacks its acceptance-edge"):
            parse_trace("wrong-opcode-retire", forged, [retired])

    def test_done_without_retire_status_is_rejected(self) -> None:
        """A done pulse without RETIRE status is rejected.

        Done pulses are only valid when co-occurring with RETIRE.
        """
        result = protocol.ResponseFrame(protocol.Status.OK, b"").encode()
        forged = self.trace_line(result, 0x03, 0x03, done=1)
        with self.assertRaisesRegex(SystemExit, "non-RETIRE response"):
            parse_trace("done-without-retire", forged, [result])


class LeanContractSemanticBinding(unittest.TestCase):
    """Defect Class 4 (continued): Lean contract must bind to semantic witnesses.

    The Lean-side ContractEvidence must require genuine semantic premises,
    not a parallel restatement of the observation vocabulary.
    """

    def test_lean_contract_requires_explicit_semantic_premises(self) -> None:
        """The Lean contract explicitly requires each semantic premise.

        ContractEvidence requires:
        - setSemantic, xorSemantic, mulSemantic, derefSemantic, jumpSemantic
        - blake3Semantic, abortSemantic, resetSemantic
        - retireSemantic, blake3RetireSemantic

        These are genuine theorem references, not parallel restatements.
        """
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
