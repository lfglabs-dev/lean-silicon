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

    def rtl_workload(self, frames: list[protocol.RequestFrame]) -> list[bytes]:
        paths = []
        arguments = []
        for index, frame in enumerate(frames, 1):
            encoded = frame.encode()
            path = Path(self.temporary.name) / f"workload{index}.hex"
            path.write_text("\n".join(f"{byte:02x}" for byte in encoded) + "\n")
            paths.append(path)
            suffix = "" if index == 1 else str(index)
            arguments.extend((f"+REQUEST{suffix}={path}", f"+LENGTH{suffix}={len(encoded)}"))
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

    def test_valid_negotiate_and_staged_retire_match_model(self) -> None:
        negotiate = protocol.build_negotiate(
            profile=protocol.Profile.INTERPRETER_COMPAT, host_features=0x13579BDF)
        # The canonical RTL advertises only its implemented feature bit.  The
        # executable model also advertises services explicitly excluded here.
        expected_negotiate = protocol.ResponseFrame(
            protocol.Status.OK,
            b"\x01\x01\x00\x01\x10\x00\x02\x00\x00\x00\x31\x43\x53\x4c",
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
