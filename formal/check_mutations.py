#!/usr/bin/env python3
"""Require retained LSC-1u formal checks to reject representative RTL faults."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MUTATIONS = [
    (
        "stall_stability",
        "src/lsc1u_core.sv",
        "assign tx_data = out_byte;",
        "assign tx_data = out_byte ^ {8{!tx_ready}};",
        ["lsc1u_protocol.sby"],
    ),
    (
        "enable_clamp",
        "src/lsc1u_core.sv",
        "assign tx_valid = ena && out_valid;",
        "assign tx_valid = out_valid;",
        ["lsc1u_protocol.sby"],
    ),
    (
        "xor_result",
        "src/lsc1u_core.sv",
        "out_byte <= saved_byte ^ rx_data;",
        "out_byte <= saved_byte + rx_data;",
        ["lsc1u_protocol.sby"],
    ),
    (
        "set_result",
        "src/lsc1u_core.sv",
        "out_byte <= rx_data;\n                    out_valid <= 1'b1;",
        "out_byte <= rx_data ^ 8'h01;\n                    out_valid <= 1'b1;",
        ["lsc1u_protocol.sby"],
    ),
    (
        "mul_arithmetic",
        "asic_core/rtl/gf2n_mul_bitstream.sv",
        "wire [WIDTH-1:0] accumulator_next = accumulator ^ selected;",
        "wire [WIDTH-1:0] accumulator_next = accumulator | selected;",
        ["gf8_mul.sby"],
    ),
    (
        "mul_serialization",
        "asic_core/rtl/gf2n_mul_bitstream.sv",
        "assign result_byte = accumulator[BYTE_BITS-1:0];",
        "assign result_byte = accumulator[WIDTH-1 -: BYTE_BITS];",
        ["gf128_serialize.sby"],
    ),
]


def main() -> int:
    sby = shutil.which("sby")
    if not sby:
        raise SystemExit("sby is required")

    failures: list[str] = []
    for name, relative, old, new, configs in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix=f"lsc1u-{name}-") as raw:
            work = Path(raw)
            shutil.copytree(ROOT / "formal", work / "formal")
            shutil.copytree(ROOT / "src", work / "src")
            shutil.copytree(ROOT / "asic_core", work / "asic_core")
            target = work / relative
            text = target.read_text()
            if text.count(old) != 1:
                failures.append(f"{name}: mutation anchor count was {text.count(old)}")
                continue
            target.write_text(text.replace(old, new))

            for config in configs:
                result = subprocess.run(
                    [sby, "-f", config],
                    cwd=work / "formal",
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                )
                output = result.stdout
                rejected = result.returncode != 0 and "DONE (FAIL" in output
                print(
                    f"{name}: config={config} exit={result.returncode} "
                    f"mutation_rejected={str(rejected).lower()}"
                )
                if not rejected:
                    print(output[-4000:])
                    failures.append(f"{name}: {config} did not terminal-FAIL")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
