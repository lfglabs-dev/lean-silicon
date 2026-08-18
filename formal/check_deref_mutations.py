#!/usr/bin/env python3
"""Kill focused mutations at the canonical DEREF frame/cycle bridge."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTL = [
    "lsc1_packet_rx.sv", "lsc1_packet_tx.sv", "lsc1_response_payload_mux.sv",
    "lsc1_blake3_alias_check.sv", "gf2n_mul_bitstream.sv",
    "gf128_mul_bitstream.sv", "leanvm_b_stream_alu.sv", "lsc1_stream_adapter.sv",
    "lsc1_field_encoder.sv", "lsc1_blake3_lifecycle.sv", "lsc1_packet_frontend.sv",
]

MUTATIONS = [
    ("pointer_bypass", "lsc1_packet_frontend.sv", "encoder_result != val_a", "1'b0"),
    ("base_plus_beta", "lsc1_packet_frontend.sv", "addr_b = base_index + off_b;", "addr_b = fp + off_b;"),
    ("pc_plus_two", "lsc1_packet_frontend.sv", "pc[15:0] + 16'd2", "pc[15:0] + 16'd1"),
    ("profile_guard", "lsc1_packet_frontend.sv", "if (profile != active_profile) begin", "if (1'b0) begin"),
    ("crc_bypass", "lsc1_packet_rx.sv", "if ({rx_data, received_crc[23:0]} != ~crc)", "if (1'b0)"),
    ("hidden_absent_value", "lsc1_packet_frontend.sv", "cell_is_malformed = present > 1 || (!present && value != 0);", "cell_is_malformed = present > 1;"),
    ("same_edge_abort", "lsc1_packet_frontend.sv", "end else if (abort) begin", "end else if (1'b0 && abort) begin"),
    ("result_byte", "lsc1_packet_frontend.sv", "write_value = val_b;", "write_value = val_b ^ 1'b1;"),
    ("duplicate_retirement", "lsc1_packet_frontend.sv", "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b0;", "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b1;"),
]

def main() -> int:
    failures = []
    for name, filename, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix=f"deref-{name}-") as raw:
            work = Path(raw)
            for source in RTL:
                shutil.copy2(ROOT / "asic_core/rtl" / source, work / source)
            target = work / filename
            text = target.read_text()
            if text.count(old) != 1:
                failures.append(f"{name}: anchor count {text.count(old)}")
                continue
            target.write_text(text.replace(old, new))
            env = os.environ | {"LSC1_RTL_DIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run([sys.executable, "-m", "unittest",
                                     "sim.test_packet_frontend_rtl_differential"], cwd=ROOT,
                                    env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            binary = work / "tb.vvp"
            compile_result = subprocess.run(
                ["iverilog", "-g2012", "-s", "tb_lsc1_packet_frontend", "-o", str(binary),
                 *(str(work / source) for source in RTL),
                 str(ROOT / "test/packet_frontend/tb_lsc1_packet_frontend.sv")],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            sim_result = (subprocess.run(["vvp", str(binary)], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                          if compile_result.returncode == 0 else compile_result)
            killed = result.returncode != 0 or sim_result.returncode != 0
            print(f"{name}: mutation_rejected={str(killed).lower()}")
            if not killed:
                failures.append(f"{name}: survived")
    if failures:
        print("\n".join(f"ERROR: {failure}" for failure in failures))
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
