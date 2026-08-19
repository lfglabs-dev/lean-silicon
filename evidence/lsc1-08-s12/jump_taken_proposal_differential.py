#!/usr/bin/env python3
"""Direct differential proof: JUMP taken_proposal field enumeration.

This script enumerates JUMP frames varying the taken byte (byte 77)
and verifies model vs RTL behavior is identical after inlining
taken_proposal = frame_payload[77*8 +: 8].
"""
from __future__ import annotations
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT / "sim"))
from sim import lsc1_transaction as protocol

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
    override = os.environ.get("LSC1_RTL_DIR")
    if override and path.startswith("asic_core/rtl/"):
        return Path(override) / Path(path).name
    return ROOT / path


def model_exchange(frame: protocol.RequestFrame) -> bytes:
    endpoint = protocol.Lsc1Endpoint()
    response, _ = protocol.drive(endpoint, frame.encode())
    return response


class DifferentialProof:
    def __init__(self):
        if shutil.which("iverilog") is None or shutil.which("vvp") is None:
            raise RuntimeError("Icarus Verilog not available")
        self.temporary = tempfile.TemporaryDirectory()
        self.simulator = Path(self.temporary.name) / "packet-vector.vvp"
        sources = [str(rtl_path(path)) for path in RTL]
        subprocess.run(
            ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o", str(self.simulator)]
            + sources,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

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

    def close(self):
        self.temporary.cleanup()


def build_jump_varying_taken(txn_id: int, taken_byte: int, val_a_zero: bool) -> protocol.RequestFrame:
    """Build a JUMP frame with a specific taken_byte value."""
    payload = protocol.transaction_preamble(txn_id, pc=0, fp=64, profile=protocol.Profile.INTERPRETER_COMPAT)
    payload += b"".join(protocol.u32le(offset) for offset in (1, 2, 3))
    payload += b"".join(cell.encode() for cell in (
        protocol.Cell(True, 7),
        protocol.Cell(True, 9),
        protocol.ABSENT,
    ))
    payload += protocol.u8(taken_byte)
    payload += protocol.u32le(0x1000)
    payload += protocol.u32le(0x40)
    payload += protocol.Cell(True, 1).encode()
    return protocol.RequestFrame(protocol.Opcode.JUMP, payload)


def main():
    random.seed(0xdeadbeef)
    proof = DifferentialProof()
    mismatches = []
    total = 0

    taken_values = list(range(256))

    for taken_byte in taken_values:
        for val_a_zero in (True, False):
            total += 1
            frame = build_jump_varying_taken(0, taken_byte, val_a_zero)
            model_resp = model_exchange(frame)
            rtl_resp = proof.rtl_exchange(frame)
            if model_resp != rtl_resp:
                mismatches.append((taken_byte, val_a_zero, model_resp.hex(), rtl_resp.hex()))

    proof.close()

    if mismatches:
        print(f"FAIL: {len(mismatches)}/{total} mismatches")
        for m in mismatches[:5]:
            print(f"  taken={m[0]} val_a_zero={m[1]} model={m[2]} rtl={m[3]}")
        return 1

    print(f"PASS: {total}/{total} JUMP taken_proposal enumerations match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
