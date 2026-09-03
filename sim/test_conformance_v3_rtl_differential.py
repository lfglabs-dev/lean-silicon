"""Bounded v3 lifecycle replay: executable model versus authored RTL.

This covers only ``blake3.lifecycle.nominal``, the seven frozen
``blake3.reject.{txn_id,service_id,kind,digest,metadata.counter,metadata.block_len,metadata.flags}``
mutations, ``blake3.control.{abort,reset}`` with their frozen bytes, and one
additional duplicate ``SERVICE_RESPONSE`` differential derived from the nominal
wire frames, plus one trailing-CRC-bit rejection followed by an unchanged valid
``SERVICE_RESPONSE`` retry, and one identical ``BLAKE3_REQUEST`` rejected while
the original service is pending before that original request completes, plus one
CRC-valid one-byte-short ``SERVICE_RESPONSE`` rejected before the unchanged
response and matching ``RETIRE`` complete the original request, plus the
corresponding CRC-valid one-byte-oversized response with an appended ``0xa5``.
It also covers an exact-length, CRC-valid ``SERVICE_RESPONSE`` whose reserved
payload byte 9 is nonzero, followed by the unchanged valid response and RETIRE.
Two further exact-length vectors change only one outer request-envelope byte
(plus the recomputed CRC): flags byte 3 to ``0x01`` for ``BAD_FLAGS``, and
version byte 1 from ``0x01`` to ``0x02`` for ``BAD_VERSION``.  Each proves the
pending service survives before the untouched response and RETIRE succeed.
One final exact-length vector changes outer opcode byte 2 from ``0x11`` to
``0xff`` and sanitizes the would-be compute profile/flags payload bytes 12--13
from opaque digest bytes ``0xa5 0xdd`` to ``0x00 0x00`` (plus the recomputed
CRC).  This proves ``BAD_OPCODE`` takes priority over ``BAD_STATE`` while the
service is pending, without an incorrect priority implementation being
intercepted by ``BAD_PROFILE``, and that the valid retry still retires.
The nominal request and service response also feed one matching ``RETIRE`` with
only the trailing CRC bit flipped, without recomputation, before the untouched
matching ``RETIRE``.  That bounded case checks that an envelope rejection cannot
be mistaken for a lifecycle retire attempt.  The duplicate response is not the adapter-level
``blake3.reject.replay`` corpus case.  This module does not claim
coverage of the other v3 negative cases, arbitrary ready/valid schedules,
universal Lean-to-RTL refinement, synthesized netlists, physical
implementation, or hardware.  The valid counter, block_len, and flags mutations are
compared only from IDLE through SERVICE_REQUIRED, followed by reset recovery; a
second BLAKE3 request while SERVICE_PENDING is rejected as BAD_STATE before
either implementation inspects its metadata.
"""

from __future__ import annotations

import json
import os
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


def rtl_path(path: str) -> Path:
    """Allow the mutation lane to substitute only authored RTL sources."""
    override = os.environ.get("LSC1_RTL_DIR")
    if override and path.startswith("asic_core/rtl/"):
        return Path(override) / Path(path).name
    return ROOT / path


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
        cls.counter_rejection = next(
            case for case in corpus["cases"]
            if case["case_id"] == "blake3.reject.metadata.counter")
        cls.flags_rejection = next(
            case for case in corpus["cases"]
            if case["case_id"] == "blake3.reject.metadata.flags")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.simulator = Path(cls.temporary.name) / "conformance-v3-vector.vvp"
        subprocess.run(
            ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o",
             str(cls.simulator), *[str(rtl_path(source)) for source in RTL]],
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

    def test_block_len_variant_at_idle_then_reset_recovers_and_retires(self) -> None:
        case = self.block_len_rejection
        self.assertEqual(
            case["fingerprint"],
            "sha256:89c7905cca8d24c000ba2b2812af883be44f442ed4614a5c6d47df7c4a5cae8d",
        )
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])

        variant = protocol.build_blake3(
            txn_id=0x10203040, pc=2, fp=64,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
            metadata=63 << 64,
            message_cells=tuple(protocol.Cell(True, value)
                                for value in (11, 22, 33, 44)),
            cv_cells=tuple(protocol.Cell(True, value) for value in (55, 66)),
            out_cells=(protocol.Cell(False, 0), protocol.Cell(False, 0)),
        ).encode()
        variant_frame = request_from_wire(variant)
        expected_variant_service = bytes.fromhex(
            case["evidence"]["internal_payload_hex"])
        self.assertEqual(len(expected_variant_service), 122)

        # A second instruction cannot reach BLAKE3 metadata handling while the
        # endpoint is SERVICE_PENDING: both implementations reject it first as
        # BAD_STATE.  Exercise the frozen valid block_len=63 mutation at IDLE,
        # where authored RTL can actually emit and compare its service payload,
        # then reset it before replaying the frozen nominal lifecycle (ABORT
        # intentionally preserves service_seq, so service_id=1 would be stale).
        requests = [variant, request, good_service, retire]
        frames = [request_from_wire(raw) for raw in requests]
        endpoint = protocol.Lsc1Endpoint()
        model_responses = [protocol.drive(endpoint, variant_frame.encode())[0]]
        decoded_variant = protocol.decode_response(model_responses[0])
        self.assertIs(decoded_variant.status, protocol.Status.SERVICE_REQUIRED)
        self.assertEqual(decoded_variant.payload, expected_variant_service)
        self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
        endpoint.step(reset_n=False)
        endpoint.step(reset_n=True)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)
        self.assertIsNone(endpoint.staged)
        for frame in frames[1:]:
            model_responses.append(protocol.drive(endpoint, frame.encode())[0])

        decoded_model = [protocol.decode_response(raw) for raw in model_responses]
        self.assertEqual([reply.status for reply in decoded_model], [
            protocol.Status.SERVICE_REQUIRED,
            protocol.Status.SERVICE_REQUIRED,
            protocol.Status.OK,
            protocol.Status.RETIRED,
        ])
        self.assertEqual(model_responses[1], bytes.fromhex(
            wire["service_required_frame_hex"]))
        self.assertEqual(model_responses[2], bytes.fromhex(wire["result_frame_hex"]))
        self.assertEqual(model_responses[3], bytes.fromhex(wire["retire_response_hex"]))
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"block-len-request-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
        paths = [Path(self.temporary.name) / f"block-len-request-{index}.hex"
                 for index in range(len(requests))]
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+REQUEST={paths[0]}",
             f"+LENGTH={len(requests[0])}", "+RESET_AFTER_FIRST",
             f"+REQUEST2={paths[1]}", f"+LENGTH2={len(requests[1])}",
             f"+REQUEST3={paths[2]}", f"+LENGTH3={len(requests[2])}",
             f"+REQUEST4={paths[3]}", f"+LENGTH4={len(requests[3])}",
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
                         ["01", "01", "00", "02"])
        before = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_CONTROL RESET BEFORE"))
        after = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_CONTROL RESET AFTER"))
        self.assertIn("origin_opcode=08 result=0 service=1", before)
        self.assertIn("result=0 service=0 tx=0", after)
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        self.assertEqual(int(counts.split("done=")[1]), 1, counts)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
        # The reset-control harness drains each response before the next frame,
        # so only the fixed TX backpressure is expected to create held beats.
        self.assertGreater(int(stability.split("tx_checks=")[1]), 0)

    def test_counter_variant_at_idle_then_reset_recovers_and_retires(self) -> None:
        case = self.counter_rejection
        self.assertEqual(
            case["fingerprint"],
            "sha256:67032dfa278dc6ccd6c87173789f197663cb28767bfcd4e7089d66c6f048979b",
        )
        wire = self.nominal["wire"]
        nominal_request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])

        counter_one_request = protocol.build_blake3(
            txn_id=0x10203040, pc=2, fp=64,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
            metadata=(64 << 64) | 1,
            message_cells=tuple(protocol.Cell(True, value)
                                for value in (11, 22, 33, 44)),
            cv_cells=tuple(protocol.Cell(True, value) for value in (55, 66)),
            out_cells=(protocol.Cell(False, 0), protocol.Cell(False, 0)),
        ).encode()
        expected_counter_service = bytes.fromhex(
            case["evidence"]["internal_payload_hex"])
        nominal_frame = request_from_wire(nominal_request)
        counter_one_frame = request_from_wire(counter_one_request)

        # Pin mutation sensitivity at the request boundary: only the little-
        # endian 64-bit BLAKE3 counter changes, from zero to one.  The envelope
        # CRC necessarily changes with it and is independently decoded above.
        changed = [
            index for index, (nominal, variant) in
            enumerate(zip(nominal_request[:-4], counter_one_request[:-4]))
            if nominal != variant
        ]
        self.assertEqual(len(nominal_request), len(counter_one_request))
        self.assertEqual(changed, [44])
        self.assertEqual(nominal_request[44:52], bytes(8))
        self.assertEqual(counter_one_request[44:52], b"\x01" + bytes(7))
        self.assertEqual(counter_one_frame.payload[38:46], b"\x01" + bytes(7))
        self.assertEqual(nominal_frame.payload[38:46], bytes(8))

        endpoint = protocol.Lsc1Endpoint()
        model_responses = [protocol.drive(endpoint, counter_one_frame.encode())[0]]
        counter_reply = protocol.decode_response(model_responses[0])
        self.assertIs(counter_reply.status, protocol.Status.SERVICE_REQUIRED)
        self.assertEqual(counter_reply.payload, expected_counter_service)
        self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
        endpoint.step(reset_n=False)
        endpoint.step(reset_n=True)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)
        self.assertIsNone(endpoint.staged)

        requests = [counter_one_request, nominal_request, good_service, retire]
        for raw in requests[1:]:
            model_responses.append(
                protocol.drive(endpoint, request_from_wire(raw).encode())[0])
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.SERVICE_REQUIRED,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(model_responses[1], bytes.fromhex(
            wire["service_required_frame_hex"]))
        self.assertEqual(model_responses[2], bytes.fromhex(wire["result_frame_hex"]))
        self.assertEqual(model_responses[3], bytes.fromhex(wire["retire_response_hex"]))
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        paths = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"counter-request-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            paths.append(path)
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+REQUEST={paths[0]}",
             f"+LENGTH={len(requests[0])}", "+RESET_AFTER_FIRST",
             f"+REQUEST2={paths[1]}", f"+LENGTH2={len(requests[1])}",
             f"+REQUEST3={paths[2]}", f"+LENGTH3={len(requests[2])}",
             f"+REQUEST4={paths[3]}", f"+LENGTH4={len(requests[3])}",
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
                         ["01", "01", "00", "02"])
        before = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_CONTROL RESET BEFORE"))
        after = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_CONTROL RESET AFTER"))
        self.assertIn("origin_opcode=08 result=0 service=1", before)
        self.assertIn("result=0 service=0 tx=0", after)
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        self.assertEqual(int(counts.split("done=")[1]), 1, counts)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
        self.assertGreater(int(stability.split("tx_checks=")[1]), 0)

    def test_flags_variant_at_idle_then_reset_recovers_and_retires(self) -> None:
        case = self.flags_rejection
        self.assertEqual(
            case["fingerprint"],
            "sha256:213f6a88d73dbd51870329210a6136adbc32653c07425e995fafa3581367e7fe",
        )
        wire = self.nominal["wire"]
        nominal_request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])

        flags_one_request = protocol.build_blake3(
            txn_id=0x10203040, pc=2, fp=64,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
            metadata=(1 << 96) | (64 << 64),
            message_cells=tuple(protocol.Cell(True, value)
                                for value in (11, 22, 33, 44)),
            cv_cells=tuple(protocol.Cell(True, value) for value in (55, 66)),
            out_cells=(protocol.Cell(False, 0), protocol.Cell(False, 0)),
        ).encode()
        expected_flags_service = bytes.fromhex(
            case["evidence"]["internal_payload_hex"])
        nominal_frame = request_from_wire(nominal_request)
        flags_one_frame = request_from_wire(flags_one_request)

        # Pin mutation sensitivity at the request boundary: only the low byte
        # of the little-endian 32-bit flags field changes, from zero to one.
        # The envelope CRC necessarily changes and is decoded independently.
        changed = [
            index for index, (nominal, variant) in
            enumerate(zip(nominal_request[:-4], flags_one_request[:-4]))
            if nominal != variant
        ]
        self.assertEqual(len(nominal_request), len(flags_one_request))
        self.assertEqual(changed, [56])
        self.assertEqual(nominal_request[56:60], bytes(4))
        self.assertEqual(flags_one_request[56:60], b"\x01" + bytes(3))
        self.assertEqual(flags_one_frame.payload[50:54], b"\x01" + bytes(3))
        self.assertEqual(nominal_frame.payload[50:54], bytes(4))

        endpoint = protocol.Lsc1Endpoint()
        model_responses = [protocol.drive(endpoint, flags_one_frame.encode())[0]]
        flags_reply = protocol.decode_response(model_responses[0])
        self.assertIs(flags_reply.status, protocol.Status.SERVICE_REQUIRED)
        self.assertEqual(flags_reply.payload, expected_flags_service)
        self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
        endpoint.step(reset_n=False)
        endpoint.step(reset_n=True)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)
        self.assertIsNone(endpoint.staged)

        requests = [flags_one_request, nominal_request, good_service, retire]
        for raw in requests[1:]:
            model_responses.append(
                protocol.drive(endpoint, request_from_wire(raw).encode())[0])
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.SERVICE_REQUIRED,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(model_responses[1], bytes.fromhex(
            wire["service_required_frame_hex"]))
        self.assertEqual(model_responses[2], bytes.fromhex(wire["result_frame_hex"]))
        self.assertEqual(model_responses[3], bytes.fromhex(wire["retire_response_hex"]))
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        paths = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"flags-request-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            paths.append(path)
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+REQUEST={paths[0]}",
             f"+LENGTH={len(requests[0])}", "+RESET_AFTER_FIRST",
             f"+REQUEST2={paths[1]}", f"+LENGTH2={len(requests[1])}",
             f"+REQUEST3={paths[2]}", f"+LENGTH3={len(requests[2])}",
             f"+REQUEST4={paths[3]}", f"+LENGTH4={len(requests[3])}",
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
                         ["01", "01", "00", "02"])
        before = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_CONTROL RESET BEFORE"))
        after = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_CONTROL RESET AFTER"))
        self.assertIn("origin_opcode=08 result=0 service=1", before)
        self.assertIn("result=0 service=0 tx=0", after)
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        self.assertEqual(int(counts.split("done=")[1]), 1, counts)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
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

    def test_duplicate_blake3_request_preserves_original_pending_then_retires(self) -> None:
        """Reject one exact duplicate while the original service remains pending.

        ``FullProfile.pending_service_start_is_bad_state`` proves the analogous
        abstract service-controller step.  This finite wire replay is separate
        executable-model/authored-RTL evidence, not universal Lean-to-RTL
        refinement or netlist, P&R, hardware, or end-to-end evidence.
        """
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        requests = [request, request, service, retire]
        frames = [request_from_wire(raw) for raw in requests]
        self.assertEqual(requests[0], requests[1])

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, frame in enumerate(frames):
            model_responses.append(protocol.drive(endpoint, frame.encode())[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (endpoint.staged, endpoint.service_seq,
                                    endpoint.state_valid, endpoint.committed_pc,
                                    endpoint.committed_fp, endpoint.retire_seq,
                                    endpoint.pins().done_pulse)
                self.assertEqual(endpoint.staged.service.service_id, 1)
            elif index == 1:
                duplicate = protocol.decode_response(model_responses[-1])
                self.assertIs(duplicate.status, protocol.Status.BAD_STATE)
                self.assertEqual(duplicate.payload,
                                 int(0x10203040).to_bytes(4, "little") + b"\x00")
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot)
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            bytes.fromhex("5a018705004030201000893d568b"),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_STATE,
             protocol.Status.OK, protocol.Status.RETIRED])
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "duplicate-pending-request.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"duplicate-pending-request-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS"], cwd=ROOT, check=True,
            capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "87", "00", "02"])
        self.assertEqual([line.split("done=")[1] for line in transactions],
                         ["0", "0", "0", "1"])
        duplicate_state = next(
            line for line in run.stdout.splitlines()
            if line.startswith("RTL_V3_DUPLICATE_PENDING "))
        self.assertEqual(
            duplicate_state,
            "RTL_V3_DUPLICATE_PENDING service_pending=1 service_seq=00000001 "
            "txn_id=10203040 service_id=00000001 state_valid=0 pc=00000000 "
            "fp=00000000 retire_seq=00000000 done=0")
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        self.assertEqual(int(counts.split("done=")[1]), 1, counts)
        final_states = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_STATE ")]
        self.assertEqual(final_states[-1],
                         "RTL_STATE valid=1 pc=00000003 fp=00000040 "
                         "retire_seq=00000001 result_pending=0")

    def test_completed_service_response_replay_preserves_result_then_retires(self) -> None:
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        requests = [request, service, service, retire]
        frames = [request_from_wire(raw) for raw in requests]
        self.assertEqual(requests[1], requests[2])

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        for index, frame in enumerate(frames):
            model_responses.append(protocol.drive(endpoint, frame.encode())[0])
            if index == 1:
                self.assertEqual(endpoint.state, protocol.TxnState.RESULT_PENDING)
                self.assertIsNotNone(endpoint.staged)
            elif index == 2:
                replay = protocol.decode_response(model_responses[-1])
                self.assertIs(replay.status, protocol.Status.BAD_STATE)
                self.assertEqual(replay.payload,
                                 int(0x10203040).to_bytes(4, "little") + b"\x00")
                self.assertEqual(endpoint.state, protocol.TxnState.RESULT_PENDING)
                self.assertIsNotNone(endpoint.staged)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex("5a018705004030201000893d568b"),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.OK,
             protocol.Status.BAD_STATE, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "service-replay.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"service-replay-{index}.hex"
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
                         ["01", "00", "87", "02"])
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

    def test_service_response_bad_crc_preserves_pending_then_retry_retires(self) -> None:
        """Replay one concrete full-LSC-1 CRC rejection/retry trace."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        bad_service = good_service[:-1] + bytes([good_service[-1] ^ 0x01])
        requests = [request, bad_service, good_service, retire]

        # Pin the mutation to exactly one bit of only the trailing CRC byte.
        self.assertEqual(len(bad_service), len(good_service))
        self.assertEqual(bad_service[:-1], good_service[:-1])
        self.assertEqual(bad_service[-1] ^ good_service[-1], 0x01)
        self.assertEqual(
            int.from_bytes(bad_service[-4:], "little")
            ^ int.from_bytes(good_service[-4:], "little"),
            0x01000000,
        )
        request_from_wire(request)
        request_from_wire(good_service)
        request_from_wire(retire)
        with self.assertRaisesRegex(ValueError, "request CRC mismatch"):
            request_from_wire(bad_service)

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 1:
                bad_crc = protocol.decode_response(model_responses[-1])
                self.assertIs(bad_crc.status, protocol.Status.BAD_CRC)
                self.assertEqual(bad_crc.payload, bytes(5))
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                self.assertIsNotNone(endpoint.staged.service)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            bytes.fromhex("5a01840500000000000033ce8edf"),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_CRC,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "service-bad-crc-retry.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"service-bad-crc-retry-{index}.hex"
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
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "84", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_BAD_CRC "))
        self.assertEqual(pending, "RTL_V3_BAD_CRC service_pending=1 done=0")
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

    def test_retire_bad_crc_preserves_result_then_retry_retires(self) -> None:
        """A receiver CRC fault must not become a lifecycle RETIRE attempt."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        service = bytes.fromhex(wire["service_response_frame_hex"])
        good_retire = bytes.fromhex(wire["retire_request_hex"])
        bad_retire = good_retire[:-1] + bytes([good_retire[-1] ^ 0x01])
        requests = [request, service, bad_retire, good_retire]

        # Exactly one bit of only the final CRC byte changes.  In particular,
        # this is not a semantically changed RETIRE with a recomputed CRC.
        self.assertEqual(len(bad_retire), len(good_retire))
        self.assertEqual(bad_retire[:-1], good_retire[:-1])
        self.assertEqual(bad_retire[-1] ^ good_retire[-1], 0x01)
        self.assertEqual(
            int.from_bytes(bad_retire[-4:], "little")
            ^ int.from_bytes(good_retire[-4:], "little"),
            0x01000000,
        )
        request_from_wire(request)
        request_from_wire(service)
        request_from_wire(good_retire)
        with self.assertRaisesRegex(ValueError, "request CRC mismatch"):
            request_from_wire(bad_retire)

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 1:
                staged = endpoint.staged
                self.assertIsNotNone(staged)
                pending_snapshot = (
                    staged.txn_id, staged.result_crc, staged.next_pc,
                    staged.next_fp, tuple(staged.writes),
                )
                self.assertEqual(endpoint.state, protocol.TxnState.RESULT_PENDING)
                self.assertEqual((endpoint.committed_pc, endpoint.committed_fp,
                                  endpoint.retire_seq, endpoint.state_valid),
                                 (0, 0, 0, False))
            elif index == 2:
                bad_crc = protocol.decode_response(model_responses[-1])
                self.assertIs(bad_crc.status, protocol.Status.BAD_CRC)
                self.assertEqual(bad_crc.payload, bytes(5))
                staged = endpoint.staged
                self.assertIsNotNone(staged)
                self.assertEqual(
                    (staged.txn_id, staged.result_crc, staged.next_pc,
                     staged.next_fp, tuple(staged.writes)),
                    pending_snapshot,
                )
                self.assertEqual(endpoint.state, protocol.TxnState.RESULT_PENDING)
                self.assertEqual((endpoint.committed_pc, endpoint.committed_fp,
                                  endpoint.retire_seq, endpoint.state_valid),
                                 (0, 0, 0, False))
                self.assertFalse(endpoint.pins().done_pulse)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex("5a01840500000000000033ce8edf"),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.OK,
             protocol.Status.BAD_CRC, protocol.Status.RETIRED],
        )
        self.assertEqual((endpoint.committed_pc, endpoint.committed_fp,
                          endpoint.retire_seq, endpoint.state_valid),
                         (3, 0x40, 1, True))
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)
        self.assertIsNone(endpoint.staged)

        manifest = Path(self.temporary.name) / "retire-bad-crc-retry.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"retire-bad-crc-retry-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS", "+V3_BAD_CRC_RETIRE"],
            cwd=ROOT, check=True, capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "00", "84", "02"])
        self.assertEqual([line.split("done=")[1] for line in transactions],
                         ["0", "0", "0", "1"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_BAD_CRC_RETIRE "))
        self.assertEqual(
            pending,
            "RTL_V3_BAD_CRC_RETIRE result_pending=1 txn_id=10203040 "
            "result_crc=9d78969c next_pc=00000003 next_fp=00000040 "
            "state_valid=0 pc=00000000 fp=00000000 retire_seq=00000000 "
            "done=0 parser_state=0",
        )
        states = [line for line in run.stdout.splitlines()
                  if line.startswith("RTL_STATE ")]
        self.assertEqual(states[2],
                         "RTL_STATE valid=0 pc=00000000 fp=00000000 "
                         "retire_seq=00000000 result_pending=1")
        self.assertEqual(states[3],
                         "RTL_STATE valid=1 pc=00000003 fp=00000040 "
                         "retire_seq=00000001 result_pending=0")
        counts = next(line for line in run.stdout.splitlines()
                      if line.startswith("RTL_COUNTS "))
        count_fields = dict(field.split("=") for field in counts.split()[1:])
        self.assertGreater(int(count_fields["rx_blocked"]), 0, counts)
        self.assertGreater(int(count_fields["tx_blocked"]), 0, counts)
        self.assertEqual(int(count_fields["done"]), 1, counts)
        final = next(line for line in run.stdout.splitlines()
                     if line.startswith("RTL_V3_FINAL "))
        final_fields = dict(field.split("=") for field in final.split()[1:])
        self.assertEqual(int(final_fields["rx_accepted"]),
                         sum(len(raw) for raw in requests), final)
        self.assertEqual(final_fields["rx_valid"], "0", final)
        self.assertEqual(final_fields["parser_state"], "0", final)
        stability = next(line for line in run.stdout.splitlines()
                         if line.startswith("RTL_V3_STABILITY "))
        stability_fields = dict(field.split("=")
                                for field in stability.split()[1:])
        self.assertGreater(int(stability_fields["rx_checks"]), 0, stability)
        self.assertGreater(int(stability_fields["tx_checks"]), 0, stability)

    def test_nonzero_reserved_service_response_preserves_pending_then_retry_retires(self) -> None:
        """Reject payload byte 9 before binding, then accept the unchanged retry."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        good_frame = request_from_wire(good_service)
        mutated_payload = bytearray(good_frame.payload)
        mutated_payload[9] = 0x01
        bad_service = protocol.RequestFrame(
            protocol.Opcode.SERVICE_RESPONSE, bytes(mutated_payload)).encode()
        requests = [request, bad_service, good_service, retire]

        # Only payload byte 9 changes semantically; encode() recomputes the CRC,
        # so the guard is reached through a valid complete LSC-1 envelope.
        bad_frame = request_from_wire(bad_service)
        self.assertEqual(len(bad_frame.payload), 42)
        self.assertEqual(bad_frame.payload[:9], good_frame.payload[:9])
        self.assertEqual(bad_frame.payload[9], 1)
        self.assertEqual(bad_frame.payload[10:], good_frame.payload[10:])
        self.assertEqual(bad_service[:6], good_service[:6])
        self.assertEqual(
            int.from_bytes(bad_service[-4:], "little"),
            protocol.crc32(bad_service[:-4]),
        )
        self.assertNotEqual(bad_service[-4:], good_service[-4:])

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (
                    endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                    endpoint.committed_pc, endpoint.committed_fp,
                    endpoint.retire_seq, endpoint.pins().done_pulse,
                )
            elif index == 1:
                rejected = protocol.decode_response(model_responses[-1])
                self.assertIs(rejected.status, protocol.Status.BAD_FLAGS)
                self.assertEqual(rejected.payload, bytes(4) + b"\x02")
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot,
                )
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            protocol.ResponseFrame(
                protocol.Status.BAD_FLAGS, bytes(4) + b"\x02").encode(),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_FLAGS,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "reserved-service-response.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"reserved-service-response-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS"], cwd=ROOT, check=True,
            capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "85", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_RESERVED_SERVICE "))
        self.assertEqual(
            pending,
            "RTL_V3_RESERVED_SERVICE service_pending=1 service_seq=00000001 "
            "txn_id=10203040 service_id=00000001 state_valid=0 pc=00000000 "
            "fp=00000000 retire_seq=00000000 done=0",
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

    def test_service_response_envelope_flags_preserve_pending_then_retry_retires(self) -> None:
        """Reject outer flags 0x01, then accept the byte-identical valid retry."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        good_frame = request_from_wire(good_service)
        bad_service = protocol.RequestFrame(
            good_frame.opcode, good_frame.payload, flags=0x01).encode()
        requests = [request, bad_service, good_service, retire]

        # Pin this slice to outer envelope byte 3 and its necessarily recomputed
        # CRC.  Opcode, declared length, and all 42 payload bytes stay identical.
        self.assertEqual(len(bad_service), len(good_service))
        self.assertEqual(
            [index for index, (good, bad) in
             enumerate(zip(good_service[:-4], bad_service[:-4])) if good != bad],
            [3],
        )
        self.assertEqual(good_service[2], protocol.Opcode.SERVICE_RESPONSE)
        self.assertEqual(bad_service[2], protocol.Opcode.SERVICE_RESPONSE)
        self.assertEqual(good_service[3], 0x00)
        self.assertEqual(bad_service[3], 0x01)
        self.assertEqual(good_service[4:6], bad_service[4:6])
        self.assertEqual(int.from_bytes(bad_service[4:6], "little"), 42)
        self.assertEqual(good_service[6:-4], bad_service[6:-4])
        self.assertEqual(len(bad_service[6:-4]), 42)
        self.assertEqual(
            int.from_bytes(bad_service[-4:], "little"),
            protocol.crc32(bad_service[:-4]),
        )
        self.assertNotEqual(bad_service[-4:], good_service[-4:])
        with self.assertRaisesRegex(ValueError, "request CRC mismatch"):
            request_from_wire(good_service[:3] + b"\x01" + good_service[4:])
        decoded_bad_frame = request_from_wire(bad_service)
        self.assertEqual(decoded_bad_frame.flags, 0x01)
        self.assertEqual(decoded_bad_frame.payload, good_frame.payload)

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (
                    endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                    endpoint.committed_pc, endpoint.committed_fp,
                    endpoint.retire_seq, endpoint.pins().done_pulse,
                )
            elif index == 1:
                rejected = protocol.decode_response(model_responses[-1])
                self.assertIs(rejected.status, protocol.Status.BAD_FLAGS)
                self.assertEqual(rejected.payload, bytes(5))
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot,
                )
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            protocol.ResponseFrame(protocol.Status.BAD_FLAGS, bytes(5)).encode(),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_FLAGS,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "envelope-flags-service-response.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"envelope-flags-service-response-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS", "+V3_ENVELOPE_FLAGS_SERVICE"], cwd=ROOT, check=True,
            capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "85", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_ENVELOPE_FLAGS_SERVICE "))
        self.assertEqual(
            pending,
            "RTL_V3_ENVELOPE_FLAGS_SERVICE service_pending=1 service_seq=00000001 "
            "txn_id=10203040 service_id=00000001 state_valid=0 pc=00000000 "
            "fp=00000000 retire_seq=00000000 done=0",
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

    def test_service_response_bad_version_preserves_pending_then_retry_retires(self) -> None:
        """Reject CRC-valid version 0x02, then accept the untouched valid retry."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        good_frame = request_from_wire(good_service)
        bad_service = protocol.RequestFrame(
            good_frame.opcode, good_frame.payload, flags=good_frame.flags,
            version=0x02).encode()
        requests = [request, bad_service, good_service, retire]

        # Pin this slice to envelope byte 1 and its recomputed CRC.  Opcode,
        # flags, declared length, and the complete payload remain untouched.
        self.assertEqual(len(bad_service), len(good_service))
        self.assertEqual(
            [index for index, (good, bad) in
             enumerate(zip(good_service[:-4], bad_service[:-4])) if good != bad],
            [1],
        )
        self.assertEqual((good_service[1], bad_service[1]), (0x01, 0x02))
        self.assertEqual(good_service[2:6], bad_service[2:6])
        self.assertEqual(good_service[2], protocol.Opcode.SERVICE_RESPONSE)
        self.assertEqual(good_service[3], 0x00)
        self.assertEqual(int.from_bytes(good_service[4:6], "little"), 42)
        self.assertEqual(good_service[6:-4], bad_service[6:-4])
        self.assertEqual(len(bad_service[6:-4]), 42)
        self.assertEqual(
            int.from_bytes(bad_service[-4:], "little"),
            protocol.crc32(bad_service[:-4]),
        )
        self.assertNotEqual(bad_service[-4:], good_service[-4:])
        with self.assertRaisesRegex(ValueError, "request CRC mismatch"):
            request_from_wire(good_service[:1] + b"\x02" + good_service[2:])
        decoded_bad_frame = request_from_wire(bad_service)
        self.assertEqual(decoded_bad_frame.version, 0x02)
        self.assertEqual(decoded_bad_frame.opcode, good_frame.opcode)
        self.assertEqual(decoded_bad_frame.flags, good_frame.flags)
        self.assertEqual(decoded_bad_frame.payload, good_frame.payload)

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (
                    endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                    endpoint.committed_pc, endpoint.committed_fp,
                    endpoint.retire_seq, endpoint.pins().done_pulse,
                )
            elif index == 1:
                rejected = protocol.decode_response(model_responses[-1])
                self.assertIs(rejected.status, protocol.Status.BAD_VERSION)
                self.assertEqual(rejected.payload, bytes(5))
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot,
                )
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            protocol.ResponseFrame(protocol.Status.BAD_VERSION, bytes(5)).encode(),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_VERSION,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "bad-version-service-response.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"bad-version-service-response-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS", "+V3_BAD_VERSION_SERVICE"], cwd=ROOT,
            check=True, capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "81", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_BAD_VERSION_SERVICE "))
        self.assertEqual(
            pending,
            "RTL_V3_BAD_VERSION_SERVICE service_pending=1 service_seq=00000001 "
            "txn_id=10203040 service_id=00000001 state_valid=0 pc=00000000 "
            "fp=00000000 retire_seq=00000000 done=0",
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

    def test_service_response_unknown_opcode_preserves_pending_then_retry_retires(self) -> None:
        """Reject CRC-valid opcode 0xff, then accept the untouched valid retry."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        bad_service = bytearray(good_service)
        bad_service[2] = 0xff
        # An unknown opcode is still presented to the compute validator.  Keep
        # its would-be compute profile and flags slots valid so that a mutant
        # which wrongly lets pending-state handling outrank BAD_OPCODE reaches
        # BAD_STATE rather than being intercepted first by the response digest's
        # 0xa5/0xdd bytes as BAD_PROFILE/BAD_FLAGS.
        bad_service[6 + 12] = int(protocol.Profile.INTERPRETER_COMPAT)
        bad_service[6 + 13] = 0
        bad_service[-4:] = protocol.crc32(bad_service[:-4]).to_bytes(4, "little")
        bad_service = bytes(bad_service)
        requests = [request, bad_service, good_service, retire]

        # Before CRC, only the opcode and the would-be compute profile/flags
        # slots differ from the valid response.  The latter are deliberately
        # sanitized from the opaque service digest so this is genuinely an
        # opcode-vs-pending test.
        self.assertEqual(len(bad_service), len(good_service))
        self.assertEqual(
            [index for index, (good, bad) in
             enumerate(zip(good_service[:-4], bad_service[:-4])) if good != bad],
            [2, 18, 19],
        )
        self.assertEqual((good_service[2], bad_service[2]), (0x11, 0xff))
        self.assertEqual(good_service[18], 0xa5)
        self.assertEqual(bad_service[18], int(protocol.Profile.INTERPRETER_COMPAT))
        self.assertEqual(good_service[19], 0xdd)
        self.assertEqual(bad_service[19], 0)
        self.assertEqual(good_service[0:2], bad_service[0:2])
        self.assertEqual(good_service[3:6], bad_service[3:6])
        self.assertEqual(good_service[0], protocol.SOF_REQUEST)
        self.assertEqual(good_service[1], protocol.PROTOCOL_VERSION)
        self.assertEqual(good_service[3], 0)
        self.assertEqual(int.from_bytes(bad_service[4:6], "little"), 42)
        self.assertEqual(len(bad_service[6:-4]), 42)
        self.assertEqual(int.from_bytes(bad_service[-4:], "little"),
                         protocol.crc32(bad_service[:-4]))
        self.assertNotEqual(bad_service[-4:], good_service[-4:])
        with self.assertRaisesRegex(ValueError, "request CRC mismatch"):
            request_from_wire(good_service[:2] + b"\xff" + good_service[3:])
        with self.assertRaises(ValueError):
            request_from_wire(bad_service)

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (
                    endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                    endpoint.committed_pc, endpoint.committed_fp,
                    endpoint.retire_seq, endpoint.pins().done_pulse,
                )
            elif index == 1:
                rejected = protocol.decode_response(model_responses[-1])
                self.assertIs(rejected.status, protocol.Status.BAD_OPCODE)
                self.assertIsNot(rejected.status, protocol.Status.BAD_STATE)
                self.assertEqual(rejected.payload, bytes(5))
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot,
                )
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            protocol.ResponseFrame(protocol.Status.BAD_OPCODE, bytes(5)).encode(),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_OPCODE,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "unknown-opcode-service-response.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"unknown-opcode-service-response-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS", "+V3_UNKNOWN_OPCODE_SERVICE"], cwd=ROOT,
            check=True, capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "82", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_UNKNOWN_OPCODE_SERVICE "))
        self.assertEqual(
            pending,
            "RTL_V3_UNKNOWN_OPCODE_SERVICE service_pending=1 service_seq=00000001 "
            "txn_id=10203040 service_id=00000001 state_valid=0 pc=00000000 "
            "fp=00000000 retire_seq=00000000 done=0",
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

    def test_short_service_response_preserves_pending_then_retry_retires(self) -> None:
        """Replay one bounded CRC-valid BAD_LENGTH/retry trace."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        good_frame = request_from_wire(good_service)
        short_service = protocol.RequestFrame(
            protocol.Opcode.SERVICE_RESPONSE, good_frame.payload[:-1]).encode()
        requests = [request, short_service, good_service, retire]

        # This is a structurally valid LSC-1 request with a fresh matching CRC,
        # differing from the nominal service response only by its final payload
        # byte and consequent length/CRC fields.
        short_frame = request_from_wire(short_service)
        self.assertEqual(len(good_frame.payload), 42)
        self.assertEqual(len(short_frame.payload), 41)
        self.assertEqual(short_frame.payload, good_frame.payload[:-1])
        self.assertEqual(short_service[0:4], good_service[0:4])
        self.assertEqual(short_service[4:6], (41).to_bytes(2, "little"))
        self.assertNotEqual(short_service[-4:], good_service[-4:])

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (
                    endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                    endpoint.committed_pc, endpoint.committed_fp,
                    endpoint.retire_seq, endpoint.pins().done_pulse,
                )
            elif index == 1:
                rejected = protocol.decode_response(model_responses[-1])
                self.assertIs(rejected.status, protocol.Status.BAD_LENGTH)
                self.assertEqual(
                    rejected.payload,
                    int(0x10203040).to_bytes(4, "little") + b"\x02",
                )
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot,
                )
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            bytes.fromhex("5a0183050040302010025f5212e1"),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_LENGTH,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "short-service-response.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"short-service-response-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS"], cwd=ROOT, check=True,
            capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "83", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_SHORT_SERVICE "))
        self.assertEqual(
            pending,
            "RTL_V3_SHORT_SERVICE service_pending=1 service_seq=00000001 "
            "txn_id=10203040 service_id=00000001 state_valid=0 pc=00000000 "
            "fp=00000000 retire_seq=00000000 done=0",
        )
        self.assertFalse(any(line.startswith("RTL_V3_LENGTH_SERVICE ")
                             for line in run.stdout.splitlines()), run.stdout)
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

    def test_oversized_service_response_preserves_pending_then_retry_retires(self) -> None:
        """Replay one bounded CRC-valid one-byte-oversized retry trace."""
        wire = self.nominal["wire"]
        request = bytes.fromhex(wire["blake3_request_hex"])
        good_service = bytes.fromhex(wire["service_response_frame_hex"])
        retire = bytes.fromhex(wire["retire_request_hex"])
        good_frame = request_from_wire(good_service)
        oversized_service = protocol.RequestFrame(
            protocol.Opcode.SERVICE_RESPONSE, good_frame.payload + b"\xa5").encode()
        requests = [request, oversized_service, good_service, retire]

        # Pin the mutation itself: the complete nominal 42-byte payload is an
        # unchanged prefix, exactly 0xa5 is appended, the declared length is
        # 43, and the envelope carries a newly computed valid CRC.
        oversized_frame = request_from_wire(oversized_service)
        self.assertEqual(len(good_frame.payload), 42)
        self.assertEqual(len(oversized_frame.payload), 43)
        self.assertEqual(oversized_frame.payload[:-1], good_frame.payload)
        self.assertEqual(oversized_frame.payload[-1:], b"\xa5")
        self.assertEqual(oversized_service[0:4], good_service[0:4])
        self.assertEqual(oversized_service[4:6], (43).to_bytes(2, "little"))
        self.assertEqual(
            int.from_bytes(oversized_service[-4:], "little"),
            protocol.crc32(oversized_service[:-4]),
        )
        self.assertNotEqual(oversized_service[-4:], good_service[-4:])

        endpoint = protocol.Lsc1Endpoint()
        model_responses = []
        pending_snapshot = None
        pending_identity = None
        for index, raw in enumerate(requests):
            model_responses.append(protocol.drive(endpoint, raw)[0])
            if index == 0:
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)
                self.assertIsNotNone(endpoint.staged)
                pending_identity = endpoint.staged
                pending_snapshot = (
                    endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                    endpoint.committed_pc, endpoint.committed_fp,
                    endpoint.retire_seq, endpoint.pins().done_pulse,
                )
            elif index == 1:
                rejected = protocol.decode_response(model_responses[-1])
                self.assertIs(rejected.status, protocol.Status.BAD_LENGTH)
                self.assertEqual(
                    rejected.payload,
                    int(0x10203040).to_bytes(4, "little") + b"\x02",
                )
                self.assertEqual(
                    (endpoint.staged, endpoint.service_seq, endpoint.state_valid,
                     endpoint.committed_pc, endpoint.committed_fp,
                     endpoint.retire_seq, endpoint.pins().done_pulse),
                    pending_snapshot,
                )
                self.assertIs(endpoint.staged, pending_identity)
                self.assertEqual(endpoint.state, protocol.TxnState.SERVICE_PENDING)

        expected = [
            bytes.fromhex(wire["service_required_frame_hex"]),
            bytes.fromhex("5a0183050040302010025f5212e1"),
            bytes.fromhex(wire["result_frame_hex"]),
            bytes.fromhex(wire["retire_response_hex"]),
        ]
        self.assertEqual(model_responses, expected)
        self.assertEqual(
            [protocol.decode_response(raw).status for raw in model_responses],
            [protocol.Status.SERVICE_REQUIRED, protocol.Status.BAD_LENGTH,
             protocol.Status.OK, protocol.Status.RETIRED],
        )
        self.assertEqual(endpoint.service_seq, 1)
        self.assertEqual(endpoint.retire_seq, 1)
        self.assertEqual(endpoint.state, protocol.TxnState.IDLE)

        manifest = Path(self.temporary.name) / "oversized-service-response.manifest"
        manifest_lines = []
        for index, raw in enumerate(requests):
            path = Path(self.temporary.name) / f"oversized-service-response-{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in raw) + "\n")
            manifest_lines.append(f"{path} {len(raw)}")
        manifest.write_text("\n".join(manifest_lines) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+MANIFEST={manifest}",
             "+V3_FINITE_STALLS"], cwd=ROOT, check=True,
            capture_output=True, text=True)
        rtl_responses = [
            bytes.fromhex(line.removeprefix("RESPONSE "))
            for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]
        self.assertEqual(rtl_responses, expected)
        self.assertEqual(rtl_responses, model_responses)
        for raw in rtl_responses:
            protocol.decode_response(raw)

        transactions = [line for line in run.stdout.splitlines()
                        if line.startswith("RTL_TRANSACTION ")]
        self.assertEqual(len(transactions), 4)
        self.assertEqual([line.split("status=")[1][:2] for line in transactions],
                         ["01", "83", "00", "02"])
        pending = next(line for line in run.stdout.splitlines()
                       if line.startswith("RTL_V3_LENGTH_SERVICE "))
        self.assertEqual(
            pending,
            "RTL_V3_LENGTH_SERVICE payload_length=43 service_pending=1 "
            "service_seq=00000001 txn_id=10203040 service_id=00000001 "
            "state_valid=0 pc=00000000 fp=00000000 retire_seq=00000000 done=0",
        )
        self.assertFalse(any(line.startswith("RTL_V3_SHORT_SERVICE ")
                             for line in run.stdout.splitlines()), run.stdout)
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
