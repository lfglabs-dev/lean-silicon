#!/usr/bin/env python3
"""Require real assertion failures for critical end-to-end bridge mutants."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "formal"
RTL = ROOT / "asic_core" / "rtl"
SOURCES = [
    "lsc1_packet_rx.sv", "lsc1_packet_tx.sv", "gf2n_mul_bitstream.sv",
    "gf128_mul_bitstream.sv", "leanvm_b_stream_alu.sv", "lsc1_stream_adapter.sv",
    "lsc1_field_encoder.sv", "lsc1_packet_frontend.sv",
]
MUTATIONS = [
    ("corrupted_result_crc_binding", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc ^ 32'h00000001;"),
    ("duplicate_retirement", "lsc1_packet_frontend.sv",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b0;",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b1;"),
]


def main() -> int:
    failures: list[str] = []
    for name, filename, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix=f"deref-formal-{name}-") as raw:
            root = Path(raw)
            work = root / "formal"
            rtl_work = root / "asic_core" / "rtl"
            work.mkdir(parents=True)
            rtl_work.mkdir(parents=True)
            shutil.copy2(FORMAL / "full_lsc1_deref_bridge.sby", work)
            shutil.copy2(FORMAL / "full_lsc1_deref_bridge_checker.sv", work)
            for source in SOURCES:
                shutil.copy2(RTL / source, rtl_work / source)
            target = rtl_work / filename
            text = target.read_text()
            if text.count(old) != 1:
                failures.append(f"{name}: anchor count {text.count(old)}")
                continue
            target.write_text(text.replace(old, new))
            result = subprocess.run(
                ["sby", "-f", "full_lsc1_deref_bridge.sby", "reachability"],
                cwd=work, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=900,
            )
            assertion_failure = result.returncode != 0 and (
                "assert failed" in result.stdout.lower() or
                "assertion failed" in result.stdout.lower()
            )
            print(f"{name}: real_property_failure={str(assertion_failure).lower()}")
            if not assertion_failure:
                print(result.stdout[-4000:])
                failures.append(f"{name}: no assertion failure")
    if failures:
        print("\n".join(f"ERROR: {failure}" for failure in failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
