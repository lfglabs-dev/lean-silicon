"""Bounded v3 lifecycle replay: executable model versus authored RTL.

This covers only ``blake3.lifecycle.nominal``, the five frozen
``blake3.reject.{txn_id,service_id,kind,digest,metadata.block_len}`` mutations, and
``blake3.control.{abort,reset}`` with their frozen bytes.  It does not claim
coverage of the other v3 negative cases, arbitrary ready/valid schedules,
universal Lean-to-RTL refinement, synthesized netlists, physical
implementation, or hardware.
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
        cls.controls = {
            case["case_id"].removeprefix("blake3.control."): case
            for case in corpus["cases"]
            if case["case_id"] in {
                "blake3.control.abort", "blake3.control.reset"
            }
        }
        cls.binding_rejections = {
            case["case_id"].removeprefix("blake3.reject."): case
            for case in corpus["cases"]
            if case["case_id"] in {
                "blake3.reject.txn_id",
                "blake3.reject.service_id",
                "blake3.reject.kind",
            }
        }
        cls.digest_rejection = next(
            case for case in corpus["cases"]
            if case["case_id"] == "blake3.reject.digest")
        cls.block_len_rejection = next(
            case for case in corpus["cases"]
            if case["case_id"] == "blake3.reject.metadata.block_len")
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

    def test_binding_rejections_preserve_service_then_recover_and_retire(self) -> None:
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        expected_required = bytes.fromhex(wire["service_required_frame_hex"])
        expected_result = bytes.fromhex(wire["result_frame_hex"])
        expected_retired = bytes.fromhex(wire["retire_response_hex"])

        for field, detail in (("txn_id", 1), ("service_id", 1), ("kind", 2)):
            with self.subTest(field=field):
                case = self.binding_rejections[field]
                host_envelope = bytes.fromhex(case["evidence"]["host_envelope_hex"])
                self.assertEqual(host_envelope[0], protocol.PROTOCOL_VERSION)
                self.assertEqual(host_envelope[1:9], bytes.fromhex("8877665544332211"))
                self.assertEqual(int.from_bytes(host_envelope[19:21], "little"), 32)
                mutated_service = protocol.RequestFrame(
                    protocol.Opcode.SERVICE_RESPONSE,
                    host_envelope[9:19] + host_envelope[21:]).encode()
                requests = [request, mutated_service, good_service, retire]
                frames = [request_from_wire(raw) for raw in requests]

                endpoint = protocol.Lsc1Endpoint()
                model_responses = []
                for index, frame in enumerate(frames):
                    model_responses.append(protocol.drive(endpoint, frame.encode())[0])
                    if index == 1:
                        self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                        self.assertIsNotNone(endpoint.staged)
                        self.assertIsNotNone(endpoint.staged.service)

                decoded_model = [protocol.decode_response(raw) for raw in model_responses]
                self.assertEqual([reply.status for reply in decoded_model], [
                    protocol.Status.SERVICE_REQUIRED,
                    protocol.Status.BAD_SERVICE,
                    protocol.Status.OK,
                    protocol.Status.RETIRED,
                ])
                self.assertEqual(decoded_model[1].payload,
                                 host_envelope[9:13] + bytes([detail]))
                self.assertEqual(model_responses[0], expected_required)
                self.assertEqual(model_responses[2:], [expected_result, expected_retired])

                manifest = Path(self.temporary.name) / f"{field}.manifest"
                manifest_lines = []
                for index, raw in enumerate(requests):
                    path = Path(self.temporary.name) / f"{field}-request-{index}.hex"
                    path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
                    manifest_lines.append(f"{path} {len(raw)}")
                manifest.write_text("\n".join(manifest_lines) + "\n")
                run = subprocess.run(
                    ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
                     "+V3_FINITE_STALLS"],
                    cwd=ROOT, check=True, capture_output=True, text=True)
                rtl_responses = [
                    bytes.fromhex(line.removeprefix("RESPONSE "))
                    for line in run.stdout.splitlines() if line.startswith("RESPONSE ")
                ]
                self.assertEqual(rtl_responses, model_responses)
                for raw in rtl_responses:
                    protocol.decode_response(raw)  # includes the complete RTL CRC

                transactions = [line for line in run.stdout.splitlines()
                                if line.startswith("RTL_TRANSACTION ")]
                self.assertEqual(len(transactions), 4)
                self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                                 ["01", "91", "00", "02"])
                pending = next(line for line in run.stdout.splitlines()
                               if line.startswith("RTL_V3_BAD_SERVICE "))
                self.assertEqual(pending, "RTL_V3_BAD_SERVICE service_pending=1")
                counts = next(line for line in run.stdout.splitlines()
                              if line.startswith("RTL_COUNTS "))
                self.assertEqual(int(counts.split("done=")[1]), 1, counts)

    def test_block_len_retry_preserves_service_then_recovers_and_retires(self) -> None:
        case = self.block_len_rejection
        self.assertEqual(
            case["fingerprint"],
            "sha256:89c7905cca8d24c000ba2b2812af883be44f442ed4614a5c6d47df7c4a5cae8d",
        )
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])

        retry = protocol.build_blake3(
            txn_id=0x10203040, pc=2, fp=64,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
            metadata=63 << 64,
            message_cells=tuple(protocol.Cell(True, value)
                                for value in (11, 22, 33, 44)),
            cv_cells=tuple(protocol.Cell(True, value) for value in (55, 66)),
            out_cells=(protocol.Cell(False, 0), protocol.Cell(False, 0)),
        ).encode()
        retry_frame = request_from_wire(retry)
        expected_retry_service = bytes.fromhex(case["evidence"]["internal_payload_hex"])
        self.assertEqual(len(expected_retry_service), 122)
        retry_probe = protocol.Lsc1Endpoint()
        retry_required = protocol.decode_response(
            protocol.drive(retry_probe, retry_frame.encode())[0])
        self.assertIs(retry_required.status, protocol.Status.SERVICE_REQUIRED)
        self.assertEqual(retry_required.payload, expected_retry_service)

        requests = [request, retry, good_service, retire]
        frames = [request_from_wire(raw) for raw in requests]
        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        original_staged = None
        original_service = None
        for index, frame in enumerate(frames):
            model_responses.append(protocol.drive(endpoint, frame.encode())[0])
            if index == 0:
                original_staged = endpoint.staged
                original_service = endpoint.staged.service
            elif index == 1:
                self.assertIs(endpoint.staged, original_staged)
                self.assertIs(endpoint.staged.service, original_service)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertEqual(endpoint.retire_seq, 0)
            elif index == 2:
                self.assertEqual(endpoint.state, protocol.TxnState.RESULT_PENDING)
                self.assertEqual(endpoint.retire_seq, 0)

        decoded_model = [protocol.decode_response(raw) for raw in model_responses]
        self.assertEqual([reply.status for reply in decoded_model], [
            protocol.Status.SERVICE_REQUIRED,
            protocol.Status.BAD_STATE,
            protocol.Status.OK,
            protocol.Status.RETIRED,
        ])
        self.assertEqual(decoded_model[1].payload,
                         int(0x10203040).to_bytes(4, "little") + b"\x00")
        self.assertEqual(model_responses[0], bytes.fromhex(
            wire["service_required_frame_hex"]))
        self.assertEqual(model_responses[2], bytes.fromhex(wire["result_frame_hex"]))
        self.assertEqual(model_responses[3], bytes.fromhex(wire["retire_response_hex"]))
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "block-len.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"block-len-request-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS"],
            cwd=ROOT, check=True, capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "87", "00", "02"])
        rejected = next(line for line in run.stdout.splitlines()
                        if line.startswith("RTL_V3_BAD_STATE "))
        self.assertEqual(
            rejected,
            "RTL_V3_BAD_STATE origin_opcode=08 service_pending=1 result_pending=0 done=0",
        )
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        self.assertEqual(int(counts.split("done=")[1]), 1, counts)
        final = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_V3_FINAL "))
        final_fields = dict(field.split("=") for field in final.split()[1:])
        self.assertEqual(int(final_fields["rx_accepted"]),
                         sum(len(raw) for raw in requests), final)
        self.assertEqual(final_fields["rx_valid"], "0", final)
        self.assertEqual(final_fields["parser_state"], "0", final)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
        self.assertGreater(int(stability.split("rx_checks=")[1].split()[0]), 0)
        self.assertGreater(int(stability.split("tx_checks=")[1]), 0)

    def test_digest_write_conflict_discards_and_replay_is_bad_state(self) -> None:
        case = self.digest_rejection
        nominal_wire = self.nominal["wire"]
        nominal_host = bytes.fromhex(
            self.nominal["service_response"]["host_envelope_hex"])
        conflicting_host = bytes.fromhex(case["evidence"]["host_envelope_hex"])

        # Reconstruct the corpus's conflict-bearing request: both output cells
        # already contain the nominal digest, while the otherwise correctly
        # bound response flips only bit zero of digest byte zero.
        nominal_digest = nominal_host[21:]
        self.assertEqual(len(nominal_digest), 32)
        mutated_digest = bytes([nominal_digest[0] ^ 1]) + nominal_digest[1:]
        reconstructed_host = (
            bytes([protocol.PROTOCOL_VERSION])
            + int(0x1122334455667788).to_bytes(8, "little")
            + int(0x10203040).to_bytes(4, "little")
            + int(1).to_bytes(4, "little")
            + bytes([int(protocol.ServiceKind.BLAKE3_COMPRESS), 0])
            + int(32).to_bytes(2, "little")
            + mutated_digest
        )
        self.assertEqual(reconstructed_host, conflicting_host)
        self.assertEqual(conflicting_host[:21], nominal_host[:21])
        self.assertEqual(conflicting_host[21:], mutated_digest)
        request = protocol.build_blake3(
            txn_id=0x10203040, pc=2, fp=64,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
            metadata=64 << 64,
            message_cells=tuple(protocol.Cell(True, value)
                                for value in (11, 22, 33, 44)),
            cv_cells=tuple(protocol.Cell(True, value) for value in (55, 66)),
            out_cells=(
                protocol.Cell(True, int.from_bytes(nominal_digest[:16], "little")),
                protocol.Cell(True, int.from_bytes(nominal_digest[16:], "little")),
            ),
        ).encode()
        conflicting_service = protocol.RequestFrame(
            protocol.Opcode.SERVICE_RESPONSE,
            conflicting_host[9:19] + conflicting_host[21:]).encode()
        requests = [request, conflicting_service, conflicting_service]
        frames = [request_from_wire(raw) for raw in requests]

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        for index, frame in enumerate(frames):
            model_responses.append(protocol.drive(endpoint, frame.encode())[0])
            if index == 1:
                self.assertEqual(endpoint.state, protocol.TxnState.IDLE)
                self.assertIsNone(endpoint.staged)
                self.assertFalse(endpoint.state_valid)

        decoded_model = [protocol.decode_response(raw) for raw in model_responses]
        self.assertEqual([reply.status for reply in decoded_model], [
            protocol.Status.SERVICE_REQUIRED,
            protocol.Status.WRITE_CONFLICT,
            protocol.Status.BAD_STATE,
        ])
        self.assertEqual([reply.payload[-1] for reply in decoded_model[1:]], [0, 0])
        self.assertEqual(model_responses[0], bytes.fromhex(
            nominal_wire["service_required_frame_hex"]))
        self.assertEqual(model_responses[1], bytes.fromhex(
            case["evidence"]["response_frame_hex"]))

        manifest = Path(self.temporary.name) / "digest-conflict.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"digest-conflict-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS"],
            cwd=ROOT, check=True, capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 3)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "8c", "87"])
        conflict = next(line for line in run.stdout.splitlines()
                        if line.startswith("RTL_V3_WRITE_CONFLICT "))
        self.assertEqual(conflict,
                         "RTL_V3_WRITE_CONFLICT service_pending=0 result_pending=0 done=0")
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        self.assertEqual(int(counts.split("done=")[1]), 0, counts)
        final = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_V3_FINAL "))
        final_fields = dict(field.split("=") for field in final.split()[1:])
        self.assertEqual(int(final_fields["rx_accepted"]),
                         sum(len(raw) for raw in requests), final)
        self.assertEqual(final_fields["rx_valid"], "0", final)
        self.assertEqual(final_fields["parser_state"], "0", final)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
        self.assertGreater(int(stability.split("rx_checks=")[1].split()[0]), 0)
        self.assertGreater(int(stability.split("tx_checks=")[1]), 0)

    def test_control_cases_clear_service_and_reject_frozen_stale_response(self) -> None:
        nominal_wire = self.nominal["wire"]
        request = bytes.fromhex(nominal_wire["blake3_request_hex"])
        stale_request = bytes.fromhex(nominal_wire["service_response_frame_hex"])
        expected_required = bytes.fromhex(nominal_wire["service_required_frame_hex"])
        expected_host_envelope = self.nominal["service_response"]["host_envelope_hex"]

        # The two frozen controls name the same already-computed host response.
        # Its LSC-1 wire representation is the nominal SERVICE_RESPONSE frame;
        # validate both complete encodings before either implementation sees it.
        request_from_wire(request)
        request_from_wire(stale_request)
        for case in self.controls.values():
            self.assertEqual(case["evidence"]["stale_host_envelope_hex"],
                             expected_host_envelope)
            self.assertEqual(case["evidence"]["endpoint_state"], "idle")

        for action in ("abort", "reset"):
            with self.subTest(action=action):
                endpoint = protocol.Lsc1Endpoint()
                model_required = protocol.drive(endpoint, request)[0]
                self.assertEqual(model_required, expected_required)
                if action == "abort":
                    endpoint.step(abort=True)
                else:
                    endpoint.step(reset_n=False)
                self.assertEqual(endpoint.state, protocol.TxnState.IDLE)
                self.assertIsNone(endpoint.staged)
                model_stale_rejection = protocol.drive(endpoint, stale_request)[0]
                decoded_model = protocol.decode_response(model_stale_rejection)
                self.assertEqual(decoded_model.status, protocol.Status.BAD_STATE)
                self.assertEqual(decoded_model.payload,
                                 int(0x10203040).to_bytes(4, "little") + b"\x00")

                request_path = Path(self.temporary.name) / f"{action}-request.hex"
                stale_path = Path(self.temporary.name) / f"{action}-stale.hex"
                for path, raw in ((request_path, request), (stale_path, stale_request)):
                    path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
                control_arg = "+ABORT_AFTER_FIRST" if action == "abort" else "+RESET_AFTER_FIRST"
                run = subprocess.run(
                    ["vvp", str(self.simulator), f"+REQUEST={request_path}",
                     f"+LENGTH={len(request)}", f"+REQUEST2={stale_path}",
                     f"+LENGTH2={len(stale_request)}", control_arg,
                     "+V3_FINITE_STALLS"],
                    cwd=ROOT, check=True, capture_output=True, text=True)
                rtl_responses = [
                    bytes.fromhex(line.removeprefix("RESPONSE "))
                    for line in run.stdout.splitlines() if line.startswith("RESPONSE ")
                ]
                self.assertEqual(rtl_responses,
                                 [expected_required, model_stale_rejection])
                for raw in rtl_responses:
                    protocol.decode_response(raw)

                before = next(line for line in run.stdout.splitlines()
                              if line.startswith(f"RTL_CONTROL {action.upper()} BEFORE"))
                after = next(line for line in run.stdout.splitlines()
                             if line.startswith(f"RTL_CONTROL {action.upper()} AFTER"))
                self.assertIn("origin_opcode=08 result=0 service=1", before)
                self.assertIn("result=0 service=0 tx=0", after)
                transactions = [line for line in run.stdout.splitlines()
                                if line.startswith("RTL_TRANSACTION ")]
                self.assertEqual(len(transactions), 2)
                self.assertIn("request_opcode=08 origin_opcode=08 status=01",
                              transactions[0])
                self.assertIn("request_opcode=11", transactions[1])
                self.assertIn("status=87", transactions[1])
                counts = next(line for line in run.stdout.splitlines()
                              if line.startswith("RTL_COUNTS "))
                self.assertEqual(int(counts.split("done=")[1]), 0, counts)


if __name__ == "__main__":
    unittest.main()
