#!/usr/bin/env python3
"""Prove and mutation-check the production full-LSC1 pending binding."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "asic_core" / "rtl"
FORMAL = ROOT / "formal"
SOURCES = [
    "lsc1_packet_rx.sv", "lsc1_packet_tx.sv", "gf2n_mul_bitstream.sv",
    "gf128_mul_bitstream.sv", "leanvm_b_stream_alu.sv", "lsc1_stream_adapter.sv",
    "lsc1_field_encoder.sv", "lsc1_blake3_lifecycle.sv", "lsc1_packet_frontend.sv",
]
UNION_BINDING = ".result_pending(result_pending || blake_result_pending)"
OMITTED_BINDING = ".result_pending(result_pending)"


def run(work: Path, mode: str) -> subprocess.CompletedProcess[str]:
    config = work / f"binding-{mode}.sby"
    file_list = "\n".join(SOURCES)
    config.write_text(f"""[options]
mode {mode}
depth 2

[engines]
smtbmc boolector

[script]
read -formal -D FORMAL_FULL_LSC1 -D FORMAL_BLAKE_PENDING_BINDING -sv {' '.join(SOURCES)} full_lsc1_controller_invariants.sv
prep -top lsc1_packet_frontend

[files]
{file_list}
full_lsc1_controller_invariants.sv
""")
    return subprocess.run(
        ["sby", "-f", config.name], cwd=work, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="blake3-pending-invariant-") as raw:
        work = Path(raw)
        for source in SOURCES:
            shutil.copy2(RTL / source, work / source)
        shutil.copy2(
            FORMAL / "full_lsc1_controller_invariants.sv",
            work / "full_lsc1_controller_invariants.sv",
        )
        frontend = work / "lsc1_packet_frontend.sv"
        source_text = frontend.read_text()
        if source_text.count(UNION_BINDING) != 1:
            print("production_union_binding=false")
            return 1

        baseline = run(work, "bmc")
        coverage = run(work, "cover")
        frontend.write_text(source_text.replace(UNION_BINDING, OMITTED_BINDING))
        mutation = run(work, "bmc")

    baseline_pass = baseline.returncode == 0
    cover_reached = coverage.returncode == 0
    mutation_killed = mutation.returncode != 0 and "done (fail" in mutation.stdout.lower()
    print("production_union_binding=true")
    print(f"baseline_proof={str(baseline_pass).lower()}")
    print(f"blake_pending_cover={str(cover_reached).lower()}")
    print(f"omit_production_blake_pending_mutation_killed={str(mutation_killed).lower()}")
    if not baseline_pass:
        print(baseline.stdout[-4000:])
    if not cover_reached:
        print(coverage.stdout[-4000:])
    if not mutation_killed:
        print(mutation.stdout[-4000:])
    return 0 if baseline_pass and cover_reached and mutation_killed else 1


if __name__ == "__main__":
    raise SystemExit(main())
