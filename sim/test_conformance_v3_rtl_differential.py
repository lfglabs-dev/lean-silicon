"""Bounded v3 nominal-lifecycle replay: executable model versus authored RTL.

This covers only ``blake3.lifecycle.nominal`` and its frozen wire frames.  It
does not claim coverage of v3 negative cases, arbitrary ready/valid schedules,
or universal Lean-to-RTL refinement.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sim import lsc1_transaction as protocol

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance/corpus-v3.json"
RTL = [
    "asic_core/rtl/lsc1_packet_rx.sv",
    "asic_core/rtl/lsc1_packet_tx.sv",
    "asic_core/rtl/gf2n_mul_bitstream.sv",
    "asic_core/rtl/gf128_mul_bitstream.sv",
    "asic_core/rtl/leanvm_b_stream_alu.sv",
    "asic_core/rtl/lsc1_stream_adapter.sv",
    "asic_core/rtl/lsc1_field_encoder.sv",
    "asic_core/rtl/lsc1_packet_frontend.sv",
    "test/packet_frontend/tb_lsc1_packet_vector.sv",
]


def request_from_wire(raw: bytes) -> protocol.RequestFrame:
    """Decode a frozen request after independently checking its envelope CRC."""
    if len(raw) < protocol.REQUEST_HEADER_BYTES + protocol.CRC_BYTES:
        raise ValueError("short request frame")
    payload_length = int.from_bytes(raw[4:6], "little")
    if len(raw) != protocol.REQUEST_HEADER_BYTES + payload_length + protocol.CRC_BYTES:
        raise ValueError("request length mismatch")
    if int.from_bytes(raw[-4:], "little") != protocol.crc32(raw[:-4]):
        raise ValueError("request CRC mismatch")
    return protocol.RequestFrame(
        protocol.Opcode(raw[2]), raw[6:-4], flags=raw[3],
        version=raw[1], sof=raw[0])


class ConformanceV3RtlDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("iverilog") is None or shutil.which("vvp") is None:
            raise unittest.SkipTest("Icarus Verilog is required for authored-RTL replay")
        corpus = json.loads(CORPUS.read_text())
        cls.nominal = next(
            case for case in corpus["cases"]
            if case["case_id"] == "blake3.lifecycle.nominal")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.simulator = Path(cls.temporary.name) / "conformance-v3-vector.vvp"
        subprocess.run(
            ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(cls.simulator), *[str(ROOT / source) for source in RTL]],
            cwd=ROOT, check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_nominal_lifecycle_wire_frames_match_model_and_authored_rtl(self) -> None:
        wire = self.nominal["wire"]
        request_names = (
            "blake3_request_hex", "service_response_frame_hex", "retire_request_hex")
        response_names = (
            "service_required_frame_hex", "result_frame_hex", "retire_response_hex")
        requests = [bytes.fromhex(wire[name]) for name in request_names]
        corpus_responses = [bytes.fromhex(wire[name]) for name in response_names]

        # Frozen boundary sizes include the payloads and complete envelopes.
        internal = bytes.fromhex(self.nominal["service_required"]["internal_payload_hex"])
        required_envelope = bytes.fromhex(
            self.nominal["service_required"]["host_envelope_hex"])
        service_envelope = bytes.fromhex(
            self.nominal["service_response"]["host_envelope_hex"])
        self.assertEqual((len(internal), len(required_envelope), len(service_envelope)),
                         (122, 131, 53))
        self.assertEqual(internal, required_envelope[9:])
        self.assertEqual(internal, corpus_responses[0][5:-4])
        service_payload = requests[1][6:-4]
        self.assertEqual(service_envelope[9:19], service_payload[:10])
        self.assertEqual(int.from_bytes(service_envelope[19:21], "little"), 32)
        self.assertEqual(service_envelope[21:], service_payload[10:])

        # Decoding verifies every response CRC; request_from_wire verifies every
        # request CRC before the executable model consumes the same bytes.
        frames = [request_from_wire(raw) for raw in requests]
        decoded_corpus = [protocol.decode_response(raw) for raw in corpus_responses]
        self.assertEqual([reply.status for reply in decoded_corpus], [
            protocol.Status.SERVICE_REQUIRED,
            protocol.Status.OK,
            protocol.Status.RETIRED,
        ])
        self.assertEqual(self.nominal["statuses"],
                         [status.name for status in (reply.status for reply in decoded_corpus)])

        endpoint = protocol.Lsc1Endpoint()
        model_responses = [protocol.drive(endpoint, frame.encode())[0] for frame in frames]
        self.assertEqual(model_responses, corpus_responses)

        manifest = Path(self.temporary.name) / "requests.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"request-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}", "+V3_FINITE_STALLS"],
            cwd=ROOT, check=True, capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, corpus_responses)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)  # re-check complete authored-RTL CRCs

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 3)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "00", "02"])
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        done_count = int(counts.split("done=")[1])
        self.assertEqual(done_count, 1, counts)
        final = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_V3_FINAL "))
        final_fields = dict(field.split("=") for field in final.split()[1:])
        self.assertEqual(int(final_fields["rx_accepted"]),
                         sum(len(raw) for raw in requests), final)
        self.assertEqual(final_fields["rx_valid"], "0", final)
        self.assertEqual(final_fields["parser_state"], "0", final)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
        rx_checks = int(stability.split("rx_checks=")[1].split()[0])
        tx_checks = int(stability.split("tx_checks=")[1])
        self.assertGreater(rx_checks, 0, stability)
        self.assertGreater(tx_checks, 0, stability)


if __name__ == "__main__":
    unittest.main()
