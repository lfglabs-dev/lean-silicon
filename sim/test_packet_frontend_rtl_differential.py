"""Seeded byte-exact differential checks: packet model versus integrated RTL."""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sim import lsc1_transaction as protocol

ROOT = Path(__file__).resolve().parents[1]
RTL = [
    "asic_core/rtl/lsc1_packet_rx.sv",
    "asic_core/rtl/lsc1_packet_tx.sv",
    "asic_core/rtl/lsc1_response_payload_mux.sv",
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
    """Allow the mutation target to substitute only flattened RTL inputs."""
    override = os.environ.get("LSC1_RTL_DIR")
    if override and path.startswith("asic_core/rtl/"):
        return Path(override) / Path(path).name
    return ROOT / path


def model_exchange(frame: protocol.RequestFrame) -> bytes:
    endpoint = protocol.Lsc1Endpoint()
    response, _ = protocol.drive(endpoint, frame.encode())
    return response


class PacketFrontendRtlDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("iverilog") is None or shutil.which("vvp") is None:
            raise unittest.SkipTest("Icarus Verilog is exercised by the systemverilog CI job")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.simulator = Path(cls.temporary.name) / "packet-vector.vvp"
        netlist = os.environ.get("LSC1_SYNTH_NETLIST")
        sources = ([netlist, str(ROOT / "test/packet_frontend/tb_lsc1_packet_vector_netlist.sv")]
                   if netlist else [str(rtl_path(path)) for path in RTL])
        subprocess.run(
            ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o", str(cls.simulator)]
            + sources,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def rtl_exchange(self, frame: protocol.RequestFrame) -> bytes:
        encoded = frame.encode()
        request = Path(self.temporary.name) / "request.hex"
        request.write_text("\n".join(f"{byte:02x}" for byte in encoded) + "\n")
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+REQUEST={request}", f"+LENGTH={len(encoded)}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        line = next(item for item in run.stdout.splitlines() if item.startswith("RESPONSE "))
        return bytes.fromhex(line.removeprefix("RESPONSE "))

    def rtl_sequence(self, first: protocol.RequestFrame,
                     second: protocol.RequestFrame) -> list[bytes]:
        paths = []
        encoded_frames = (first.encode(), second.encode())
        for index, encoded in enumerate(encoded_frames, 1):
            path = Path(self.temporary.name) / f"request{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in encoded) + "\n")
            paths.append(path)
        run = subprocess.run(
            ["vvp", str(self.simulator), f"+REQUEST={paths[0]}",
             f"+LENGTH={len(encoded_frames[0])}", f"+REQUEST2={paths[1]}",
             f"+LENGTH2={len(encoded_frames[1])}"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        )
        return [bytes.fromhex(line.removeprefix("RESPONSE "))
                for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]

    def rtl_workload(self, frames: list[protocol.RequestFrame],
                     control_after_first: str | None = None,
                     service_seq: int | None = None) -> list[bytes]:
        paths = []
        arguments = []
        for index, frame in enumerate(frames, 1):
            encoded = frame.encode()
            path = Path(self.temporary.name) / f"workload{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in encoded) + "\n")
            paths.append(path)
            suffix = "" if index == 1 else str(index)
            arguments.extend((f"+REQUEST{suffix}={path}", f"+LENGTH{suffix}={len(encoded)}"))
        if control_after_first is not None:
            arguments.append(f"+{control_after_first}")
        if service_seq is not None:
            arguments.append(f"+SERVICE_SEQ={service_seq:08x}")
        run = subprocess.run(
            ["vvp", str(self.simulator), *arguments], cwd=ROOT, check=True,
            capture_output=True, text=True,
        )
        return [bytes.fromhex(line.removeprefix("RESPONSE "))
                for line in run.stdout.splitlines() if line.startswith("RESPONSE ")]

    def test_realistic_three_transaction_workload_matches_model_byte_exactly(self) -> None:
        endpoint = protocol.Lsc1Endpoint()
        frames = []
        expected = []
        operations = [
            protocol.build_set_constant(
                txn_id=1, pc=0, fp=0, profile=protocol.Profile.INTERPRETER_COMPAT,
                offset=2, constant=0x123456789ABCDEF, cell=protocol.ABSENT),
            protocol.build_set_constant(
                txn_id=2, pc=1, fp=0, profile=protocol.Profile.INTERPRETER_COMPAT,
                offset=3, constant=0xFEDCBA987654321, cell=protocol.ABSENT),
            protocol.build_binary_op(
                protocol.Opcode.XOR, txn_id=3, pc=2, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT, offsets=(2, 3, 4),
                cells=(protocol.Cell(True, 0x123456789ABCDEF),
                       protocol.Cell(True, 0xFEDCBA987654321), protocol.ABSENT)),
        ]
        for operation in operations:
            raw, _ = protocol.drive(endpoint, operation.encode())
            result = protocol.decode_response(raw)
            retire = protocol.build_retire(
                txn_id=int.from_bytes(result.payload[:4], "little"),
                result_crc=protocol.crc32(result.payload),
            )
            retired, _ = protocol.drive(endpoint, retire.encode())
            frames.extend((operation, retire))
            expected.extend((raw, retired))
        actual = self.rtl_workload(frames)
        self.assertEqual(actual, expected)
        self.assertEqual(protocol.decode_response(actual[-1]).payload.hex(),
                         "03000000030000000300000000000000")

    def test_blake3_service_result_and_retirement_match_model_byte_exactly(self) -> None:
        request = protocol.build_blake3(
            txn_id=0x10203040, pc=2, fp=64,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 3, 1, 7), cv_offset=8, out_offset=10,
            metadata=0x0000007F000000401122334455667788,
            message_cells=tuple(protocol.Cell(True, value) for value in (11, 22, 33, 44)),
            cv_cells=(protocol.Cell(True, 55), protocol.Cell(True, 66)),
            out_cells=(protocol.ABSENT, protocol.ABSENT),
        )
        self.assertEqual(len(request.payload), 190)
        endpoint = protocol.Lsc1Endpoint()
        service_raw, _ = protocol.drive(endpoint, request.encode())
        service = protocol.decode_response(service_raw)
        self.assertIs(service.status, protocol.Status.SERVICE_REQUIRED)
        response = protocol.build_service_response(
            txn_id=0x10203040,
            service_id=int.from_bytes(service.payload[4:8], "little"),
            digest=(0x00112233445566778899AABBCCDDEEFF,
                    0xFFEEDDCCBBAA99887766554433221100),
        )
        result_raw, _ = protocol.drive(endpoint, response.encode())
        result = protocol.decode_response(result_raw)
        retire = protocol.build_retire(
            txn_id=0x10203040, result_crc=protocol.crc32(result.payload))
        retired_raw, _ = protocol.drive(endpoint, retire.encode())
        self.assertEqual(self.rtl_workload([request, response, retire]),
                         [service_raw, result_raw, retired_raw])

    def test_oversized_accepted_frames_consume_crc_checked_discarded_tails(self) -> None:
        for length, mutation_index in ((191, 190), (255, 190), (256, 255)):
            baseline_payload = bytes((index ^ 0xA5) & 0xFF for index in range(length))
            mutated_payload = bytearray(baseline_payload)
            mutated_payload[mutation_index] ^= 1
            baseline = protocol.RequestFrame(protocol.Opcode.BLAKE3_REQUEST,
                                             baseline_payload)
            mutated = protocol.RequestFrame(protocol.Opcode.BLAKE3_REQUEST,
                                            bytes(mutated_payload))
            with self.subTest(length=length, mutation_index=mutation_index):
                self.assertNotEqual(baseline.encode()[-4:], mutated.encode()[-4:])
                baseline_response = self.rtl_exchange(baseline)
                mutated_response = self.rtl_exchange(mutated)
                self.assertEqual(mutated_response, baseline_response)
                self.assertIs(protocol.decode_response(baseline_response).status,
                              protocol.Status.BAD_LENGTH)

    def test_blake3_bad_service_retry_and_abort_reset_recovery(self) -> None:
        request = protocol.build_blake3(
            txn_id=7, pc=0, fp=32, profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=4, out_offset=6, metadata=0x40,
            message_cells=tuple(protocol.Cell(True, value) for value in (1, 2, 3, 4)),
            cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
            out_cells=(protocol.ABSENT, protocol.ABSENT))
        endpoint = protocol.Lsc1Endpoint()
        required, _ = protocol.drive(endpoint, request.encode())
        wrong = protocol.build_service_response(txn_id=7, service_id=99, digest=(8, 9))
        refused, _ = protocol.drive(endpoint, wrong.encode())
        correct = protocol.build_service_response(txn_id=7, service_id=1, digest=(8, 9))
        result, _ = protocol.drive(endpoint, correct.encode())
        self.assertEqual(self.rtl_workload([request, wrong, correct]),
                         [required, refused, result])

        for control in ("ABORT_AFTER_FIRST", "RESET_AFTER_FIRST"):
            with self.subTest(control=control):
                recovered = protocol.Lsc1Endpoint()
                first, _ = protocol.drive(recovered, request.encode())
                if control.startswith("ABORT"):
                    recovered.step(abort=True)
                else:
                    recovered.step(reset_n=False)
                status_frame = protocol.build_status_query()
                status, _ = protocol.drive(recovered, status_frame.encode())
                self.assertEqual(self.rtl_workload(
                    [request, status_frame], control_after_first=control),
                    [first, status])

    def test_blake3_write_once_shapes_and_conflict_match_model(self) -> None:
        digest = (0xAA, 0xBB)
        for outputs in (
            (protocol.ABSENT, protocol.ABSENT),
            (protocol.Cell(True, digest[0]), protocol.ABSENT),
            (protocol.Cell(True, digest[0]), protocol.Cell(True, digest[1])),
            (protocol.Cell(True, 0xDEAD), protocol.ABSENT),
        ):
            with self.subTest(outputs=outputs):
                request = protocol.build_blake3(
                    txn_id=1, pc=0, fp=0,
                    profile=protocol.Profile.INTERPRETER_COMPAT,
                    message_offsets=(0, 1, 2, 3), cv_offset=4, out_offset=6,
                    metadata=0,
                    message_cells=tuple(protocol.Cell(True, value)
                                        for value in (1, 2, 3, 4)),
                    cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
                    out_cells=outputs)
                endpoint = protocol.Lsc1Endpoint()
                required, _ = protocol.drive(endpoint, request.encode())
                response = protocol.build_service_response(
                    txn_id=1, service_id=1, digest=digest)
                finished, _ = protocol.drive(endpoint, response.encode())
                self.assertEqual(self.rtl_workload([request, response]),
                                 [required, finished])

    def test_blake3_terminal_pc_is_rejected_without_suspending(self) -> None:
        for pc in (0xFFFE, 0xFFFF):
            with self.subTest(pc=pc):
                request = protocol.build_blake3(
                    txn_id=1, pc=pc, fp=0,
                    profile=protocol.Profile.INTERPRETER_COMPAT,
                    message_offsets=(0, 1, 2, 3), cv_offset=4, out_offset=6,
                    metadata=0,
                    message_cells=tuple(protocol.Cell(True, value)
                                        for value in (1, 2, 3, 4)),
                    cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
                    out_cells=(protocol.ABSENT, protocol.ABSENT))
                expected = model_exchange(request)
                self.assertEqual(self.rtl_exchange(request), expected)
                self.assertIs(protocol.decode_response(expected).status,
                              protocol.Status.SERVICE_REQUIRED if pc == 0xFFFE
                              else protocol.Status.INDEX_RANGE)

    def test_blake3_invalid_metadata_is_rejected_before_service_admission(self) -> None:
        invalid_metadata = (
            65 << 64,
            0xFFFFFFFF << 64,
            0x80 << 96,
            0xFFFFFFFF << 96,
        )
        for metadata in invalid_metadata:
            with self.subTest(metadata=f"{metadata:#034x}"):
                request = protocol.build_blake3(
                    txn_id=1, pc=0, fp=0,
                    profile=protocol.Profile.INTERPRETER_COMPAT,
                    message_offsets=(0, 1, 2, 3), cv_offset=4, out_offset=6,
                    metadata=metadata,
                    message_cells=tuple(protocol.Cell(True, value)
                                        for value in (1, 2, 3, 4)),
                    cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
                    out_cells=(protocol.ABSENT, protocol.ABSENT))
                expected = model_exchange(request)
                self.assertEqual(self.rtl_exchange(request), expected)
                self.assertIs(protocol.decode_response(expected).status,
                              protocol.Status.BAD_SERVICE)

    def test_blake3_invalid_metadata_precedes_other_execution_faults(self) -> None:
        cases = (
            {"pc": 0xFFFF, "fp": 0, "message_offsets": (0, 1, 2, 3)},
            {"pc": 0, "fp": 0xFFFF, "message_offsets": (0xFFFFFFFF, 1, 2, 3)},
        )
        for metadata in (65 << 64, 0x80 << 96):
            for case in cases:
                with self.subTest(metadata=f"{metadata:#034x}", case=case):
                    request = protocol.build_blake3(
                        txn_id=1, profile=protocol.Profile.INTERPRETER_COMPAT,
                        cv_offset=4, out_offset=6, metadata=metadata,
                        message_cells=tuple(protocol.Cell(True, value)
                                            for value in (1, 2, 3, 4)),
                        cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
                        out_cells=(protocol.ABSENT, protocol.ABSENT), **case)
                    expected = model_exchange(request)
                    self.assertEqual(self.rtl_exchange(request), expected)
                    self.assertIs(protocol.decode_response(expected).status,
                                  protocol.Status.BAD_SERVICE)

    def test_blake3_reserved_service_id_exhaustion_is_rejected_without_wrap(self) -> None:
        if os.environ.get("LSC1_SYNTH_NETLIST"):
            self.skipTest("generic netlist has no public service-sequence test hook")
        request = protocol.build_blake3(
            txn_id=1, pc=0, fp=0, profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=4, out_offset=6,
            metadata=0,
            message_cells=tuple(protocol.Cell(True, value) for value in (1, 2, 3, 4)),
            cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
            out_cells=(protocol.ABSENT, protocol.ABSENT))
        for service_seq in (0xFFFFFFFE, 0xFFFFFFFF):
            with self.subTest(service_seq=f"{service_seq:#010x}"):
                endpoint = protocol.Lsc1Endpoint()
                endpoint.service_seq = service_seq
                expected, _ = protocol.drive(endpoint, request.encode())
                self.assertEqual(self.rtl_workload([request], service_seq=service_seq),
                                 [expected])
                self.assertIs(protocol.decode_response(expected).status,
                              protocol.Status.BAD_SERVICE)
                self.assertEqual(endpoint.service_seq, service_seq)

    def test_blake3_service_id_exhaustion_precedes_execution_faults(self) -> None:
        if os.environ.get("LSC1_SYNTH_NETLIST"):
            self.skipTest("generic netlist has no public service-sequence test hook")
        cases = (
            {"pc": 0xFFFF, "fp": 0, "message_offsets": (0, 1, 2, 3)},
            {"pc": 0, "fp": 0xFFFF, "message_offsets": (0xFFFFFFFF, 1, 2, 3)},
        )
        for service_seq in (0xFFFFFFFE, 0xFFFFFFFF):
            for case in cases:
                with self.subTest(service_seq=f"{service_seq:#010x}", case=case):
                    request = protocol.build_blake3(
                        txn_id=1, profile=protocol.Profile.INTERPRETER_COMPAT,
                        cv_offset=4, out_offset=6, metadata=0,
                        message_cells=tuple(protocol.Cell(True, value)
                                            for value in (1, 2, 3, 4)),
                        cv_cells=(protocol.Cell(True, 5), protocol.Cell(True, 6)),
                        out_cells=(protocol.ABSENT, protocol.ABSENT), **case)
                    endpoint = protocol.Lsc1Endpoint()
                    endpoint.service_seq = service_seq
                    expected, _ = protocol.drive(endpoint, request.encode())
                    self.assertEqual(self.rtl_workload([request], service_seq=service_seq),
                                     [expected])
                    self.assertIs(protocol.decode_response(expected).status,
                                  protocol.Status.BAD_SERVICE)
                    self.assertEqual(endpoint.service_seq, service_seq)

    def test_blake3_overflow_precedes_terminal_pc_rejection(self) -> None:
        request = protocol.build_blake3(
            txn_id=1, pc=0xFFFF, fp=1,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0xFFFFFFFF, 0, 1, 2), cv_offset=4, out_offset=6,
            metadata=0,
            message_cells=tuple(protocol.Cell(True, v) for v in (10, 20, 30, 40)),
            cv_cells=(protocol.Cell(True, 50), protocol.Cell(True, 60)),
            out_cells=(protocol.ABSENT, protocol.ABSENT))
        expected = model_exchange(request)
        self.assertEqual(self.rtl_exchange(request), expected)
        self.assertIs(protocol.decode_response(expected).status,
                      protocol.Status.U32_OVERFLOW)

    def test_blake3_alias_inconsistent_precedes_terminal_pc_rejection(self) -> None:
        request = protocol.build_blake3(
            txn_id=1, pc=0xFFFF, fp=0,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 0, 1, 2), cv_offset=4, out_offset=6,
            metadata=0,
            message_cells=(protocol.Cell(True, 111),
                           protocol.Cell(True, 222),
                           protocol.Cell(True, 333),
                           protocol.Cell(True, 444)),
            cv_cells=(protocol.Cell(True, 555), protocol.Cell(True, 666)),
            out_cells=(protocol.ABSENT, protocol.ABSENT))
        expected = model_exchange(request)
        self.assertEqual(self.rtl_exchange(request), expected)
        self.assertIs(protocol.decode_response(expected).status,
                      protocol.Status.ALIAS_INCONSISTENT)

    def test_valid_negotiate_and_staged_retire_match_model(self) -> None:
        negotiate = protocol.build_negotiate(
            profile=protocol.Profile.INTERPRETER_COMPAT, host_features=0x13579BDF)
        # The authored RTL implements interpreter-compatible semantics and
        # BLAKE3 service offload, but not the forward-only profile.
        expected_negotiate = protocol.ResponseFrame(
            protocol.Status.OK,
            b"\x01\x01\x00\x01\x10\x00\x06\x00\x00\x00\x31\x43\x53\x4c",
        ).encode()
        self.assertEqual(self.rtl_exchange(negotiate), expected_negotiate)

        staged = protocol.build_set_constant(
            txn_id=0x42, pc=7, fp=11,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            offset=3, constant=0x123456789ABCDEF, cell=protocol.ABSENT,
        )
        endpoint = protocol.Lsc1Endpoint()
        staged_response, _ = protocol.drive(endpoint, staged.encode())
        result = protocol.decode_response(staged_response)
        retire = protocol.build_retire(
            txn_id=0x42, result_crc=protocol.crc32(result.payload))
        retire_response, _ = protocol.drive(endpoint, retire.encode())
        self.assertEqual(self.rtl_sequence(staged, retire),
                         [staged_response, retire_response])

    def test_seeded_set_xor_mul_and_frame_faults(self) -> None:
        randomizer = random.Random(0x4C534331)
        frames: list[protocol.RequestFrame] = [protocol.build_status_query()]
        for txn_id in range(1, 7):
            left = randomizer.getrandbits(128)
            right = randomizer.getrandbits(128)
            frames.append(protocol.build_set_constant(
                txn_id=txn_id, pc=0, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offset=txn_id, constant=left, cell=protocol.ABSENT,
            ))
            for opcode in (protocol.Opcode.XOR, protocol.Opcode.MUL_NATIVE):
                frames.append(protocol.build_binary_op(
                    opcode, txn_id=txn_id, pc=0, fp=0,
                    profile=protocol.Profile.INTERPRETER_COMPAT,
                    offsets=(1, 2, 3),
                    cells=(protocol.Cell(True, left), protocol.Cell(True, right), protocol.ABSENT),
                ))
        frames.append(protocol.RequestFrame(0x7F, b""))
        for frame in frames:
            with self.subTest(opcode=int(frame.opcode), length=len(frame.payload)):
                self.assertEqual(self.rtl_exchange(frame), model_exchange(frame))

    def test_partial_transaction_prefix_length_faults_match_rtl(self) -> None:
        prefixes = (b"", b"\x28", b"\x28\x22", b"\x28\x22\x33", b"\x28\x22\x33\x44")
        frames = [protocol.RequestFrame(opcode, payload)
                  for opcode in (protocol.Opcode.SET_CONSTANT, protocol.Opcode.RETIRE)
                  for payload in prefixes]
        for frame in frames:
            with self.subTest(opcode=int(frame.opcode), payload=frame.payload.hex()):
                self.assertEqual(self.rtl_exchange(frame), model_exchange(frame))

        # Independent literal wire vectors prevent a matching model/RTL bug from
        # hiding RETIRE's zero-extended little-endian transaction-ID contract.
        retire_responses = {
            b"": "5a01830500000000000206a6453b",
            b"\x28": "5a018305002800000002c3c2f4ca",
            b"\x28\x22": "5a01830500282200000276a5cfc0",
            b"\x28\x22\x33": "5a018305002822330002bffee2e6",
            b"\x28\x22\x33\x44": "5a018305002822334402be74f772",
        }
        for payload, expected_hex in retire_responses.items():
            with self.subTest(retire_wire_vector=payload.hex()):
                frame = protocol.RequestFrame(protocol.Opcode.RETIRE, payload)
                self.assertEqual(self.rtl_exchange(frame).hex(), expected_hex)

    def test_deref_and_jump_match_the_executable_model(self) -> None:
        base = 40
        pointer = protocol.Cell(True, protocol.field_encode(base))
        frames = [
            protocol.build_binary_op(
                protocol.Opcode.MUL_NATIVE, txn_id=0, pc=0, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(1, 2, 3),
                cells=(
                    protocol.ABSENT,
                    protocol.Cell(True, 7),
                    protocol.Cell(True, 9),
                ),
                proposed_inverse=protocol.Cell(True, 1),
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=1, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.ABSENT, local=protocol.Cell(True, 0x99),
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=2, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.ABSENT, local=protocol.ABSENT,
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=0x21, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.Cell(True, 0x99), local=protocol.ABSENT,
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=0x22, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.Cell(True, 0x99), local=protocol.Cell(True, 0x99),
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_PC, txn_id=3, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.ABSENT, local=protocol.ABSENT,
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_FP, txn_id=4, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.ABSENT, local=protocol.ABSENT,
            ),
            protocol.build_jump(
                txn_id=5, pc=12, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(10, 11, 10),
                cells=(
                    protocol.Cell(True, 1),
                    protocol.Cell(True, protocol.field_encode(15)),
                    protocol.Cell(True, 1),
                ),
                taken=True, dest_pc=15, dest_fp=0,
                proposed_inverse=protocol.Cell(True, 1),
            ),
            protocol.build_jump(
                txn_id=6, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(0, 1, 2),
                cells=(
                    protocol.Cell(True, 0), protocol.ABSENT, protocol.ABSENT,
                ),
                taken=False, dest_pc=0, dest_fp=0,
                proposed_inverse=protocol.Cell(True, 0),
            ),
        ]
        for frame in frames:
            with self.subTest(opcode=int(frame.opcode)):
                self.assertEqual(self.rtl_exchange(frame), model_exchange(frame))

    def test_adversarial_jump_inverse_and_xor_backsolve_match_model(self) -> None:
        condition = 0xD3A5_9C71_E246_B8F0_1357_9BDF_2468_ACE1
        inverse = 1
        base = condition
        exponent = (1 << 128) - 2
        while exponent:
            if exponent & 1:
                inverse = protocol.field_mul(inverse, base)
            base = protocol.field_mul(base, base)
            exponent >>= 1
        self.assertGreater(inverse.bit_length(), 120)

        known = 0x81_0000_0000_0000_0000_0000_0000_0000_5A
        result = 0xFE_DCBA_9876_5432_10FE_DCBA_9876_5432_10
        frames = [
            protocol.build_jump(
                txn_id=0x51, pc=12, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(10, 11, 12),
                cells=(protocol.Cell(True, condition), protocol.ABSENT, protocol.ABSENT),
                taken=True, dest_pc=15, dest_fp=0,
                proposed_inverse=protocol.Cell(True, inverse),
            ),
            protocol.build_binary_op(
                protocol.Opcode.XOR, txn_id=0x52, pc=0, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(1, 2, 3),
                cells=(protocol.ABSENT, protocol.Cell(True, known), protocol.Cell(True, result)),
            ),
            protocol.build_binary_op(
                protocol.Opcode.XOR, txn_id=0x53, pc=0, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(4, 5, 6),
                cells=(protocol.Cell(True, known), protocol.ABSENT, protocol.Cell(True, result)),
            ),
        ]
        for frame in frames:
            with self.subTest(opcode=int(frame.opcode), txn=frame.payload[:4].hex()):
                self.assertEqual(self.rtl_exchange(frame), model_exchange(frame))

    def test_deref_and_jump_faults_match_the_executable_model(self) -> None:
        base = 40
        pointer = protocol.Cell(True, protocol.field_encode(base))
        frames = [
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=0x40, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.Cell(False, 1), local=protocol.Cell(True, 1),
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=0, pc=5, fp=64,
                profile=protocol.Profile.FORWARD_ONLY,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.ABSENT, local=protocol.Cell(True, 1),
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=1, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3,
                pointer=protocol.Cell(True, 0), base=base,
                target=protocol.ABSENT, local=protocol.Cell(True, 1),
            ),
            protocol.build_deref(
                protocol.Opcode.DEREF_CELL, txn_id=2, pc=5, fp=64,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer, base=base,
                target=protocol.Cell(True, 1), local=protocol.Cell(True, 2),
            ),
            protocol.build_jump(
                txn_id=3, pc=12, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(10, 11, 10),
                cells=(
                    protocol.Cell(True, 1),
                    protocol.Cell(True, protocol.field_encode(15)),
                    protocol.Cell(True, 1),
                ),
                taken=False, dest_pc=0, dest_fp=0,
                proposed_inverse=protocol.Cell(True, 0),
            ),
            protocol.build_jump(
                txn_id=4, pc=12, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(10, 11, 10),
                cells=(
                    protocol.Cell(True, 1),
                    protocol.Cell(True, protocol.field_encode(15)),
                    protocol.Cell(True, 1),
                ),
                taken=True, dest_pc=15, dest_fp=0,
                proposed_inverse=protocol.Cell(True, 0),
            ),
            protocol.build_jump(
                txn_id=5, pc=12, fp=0,
                profile=protocol.Profile.INTERPRETER_COMPAT,
                offsets=(10, 11, 10),
                cells=(
                    protocol.Cell(True, 1), protocol.Cell(True, 0xBAD),
                    protocol.Cell(True, 1),
                ),
                taken=True, dest_pc=15, dest_fp=0,
                proposed_inverse=protocol.Cell(True, 1),
            ),
        ]
        valid_jump = protocol.build_jump(
            txn_id=6, pc=12, fp=0,
            profile=protocol.Profile.INTERPRETER_COMPAT,
            offsets=(10, 11, 10),
            cells=(
                protocol.Cell(True, 1),
                protocol.Cell(True, protocol.field_encode(15)),
                protocol.Cell(True, 1),
            ),
            taken=True, dest_pc=15, dest_fp=0,
            proposed_inverse=protocol.Cell(True, 1),
        )
        malformed_payload = bytearray(valid_jump.payload)
        malformed_payload[77] = 2
        for frame in frames:
            with self.subTest(opcode=int(frame.opcode), txn=frame.payload[:4].hex()):
                self.assertEqual(self.rtl_exchange(frame), model_exchange(frame))
        malformed = protocol.RequestFrame(valid_jump.opcode, bytes(malformed_payload))
        rtl_fault = self.rtl_exchange(malformed)
        model_fault = model_exchange(malformed)
        self.assertEqual(rtl_fault[2], int(protocol.Status.BAD_BRANCH_PROPOSAL))
        self.assertEqual(rtl_fault[2], model_fault[2])
        self.assertEqual(rtl_fault[9], 3)
        self.assertEqual(rtl_fault[9], model_fault[9])


if __name__ == "__main__":
    unittest.main()
