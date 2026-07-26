"""Seeded byte-exact differential checks: packet model versus integrated RTL."""

from __future__ import annotations

import random
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
    "asic_core/rtl/lsc1_packet_frontend.sv",
    "test/packet_frontend/tb_lsc1_packet_vector.sv",
]


def model_exchange(frame: protocol.RequestFrame) -> bytes:
    endpoint = protocol.Lsc1Endpoint()
    response, _ = protocol.drive(endpoint, frame.encode())
    return response


class PacketFrontendRtlDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.simulator = Path(cls.temporary.name) / "packet-vector.vvp"
        subprocess.run(
            ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o", str(cls.simulator)]
            + [str(ROOT / path) for path in RTL],
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


if __name__ == "__main__":
    unittest.main()
