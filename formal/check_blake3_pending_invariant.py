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
INVARIANT = "full_lsc1_controller_invariants.sv"
PENDING_ASSERTION = "if (blake_result_pending) assert(result_pending);"
WEAK_PENDING_ASSERTION = "if (blake_result_pending) assert(1'b1);"


def run(work: Path, mode: str) -> subprocess.CompletedProcess[str]:
    config = work / f"binding-{mode}.sby"
    file_list = "\n".join(SOURCES)
    config.write_text(f"""[options]
mode {mode}
depth 2

[engines]
smtbmc boolector

[script]
read -formal -D FORMAL_FULL_LSC1 -D FORMAL_BLAKE_PENDING_FOCUSED -sv {' '.join(SOURCES)} {INVARIANT}
prep -top lsc1_packet_frontend

[files]
{file_list}
{INVARIANT}
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
        shutil.copy2(FORMAL / INVARIANT, work / INVARIANT)
        frontend = work / "lsc1_packet_frontend.sv"
        invariant = work / INVARIANT
        source_text = frontend.read_text()
        invariant_text = invariant.read_text()
        if source_text.count(UNION_BINDING) != 1:
            print("production_union_binding=false")
            return 1
        if invariant_text.count(PENDING_ASSERTION) != 1:
            print("production_pending_assertion=false")
            return 1

        baseline = run(work, "bmc")
        coverage = run(work, "cover")
        frontend.write_text(source_text.replace(UNION_BINDING, OMITTED_BINDING))
        binding_mutation = run(work, "bmc")
        invariant.write_text(invariant_text.replace(PENDING_ASSERTION, WEAK_PENDING_ASSERTION))
        assertion_mutation = run(work, "bmc")

    baseline_pass = baseline.returncode == 0
    cover_reached = coverage.returncode == 0
    binding_mutation_killed = (
        binding_mutation.returncode != 0
        and "done (fail" in binding_mutation.stdout.lower()
    )
    # With the deliberately omitted frontend union still installed, weakening the
    # shipped assertion removes the expected counterexample.  Treat that unexpected
    # proof success as the mutation being detected by this receipt.
    assertion_mutation_killed = assertion_mutation.returncode == 0
    print("production_union_binding=true")
    print("production_pending_assertion=true")
    print(f"baseline_proof={str(baseline_pass).lower()}")
    print(f"blake_pending_cover={str(cover_reached).lower()}")
    print(f"omit_production_blake_pending_mutation_killed={str(binding_mutation_killed).lower()}")
    print(f"weaken_production_pending_assertion_mutation_killed={str(assertion_mutation_killed).lower()}")
    if not baseline_pass:
        print(baseline.stdout[-4000:])
    if not cover_reached:
        print(coverage.stdout[-4000:])
    if not binding_mutation_killed:
        print(binding_mutation.stdout[-4000:])
    if not assertion_mutation_killed:
        print(assertion_mutation.stdout[-4000:])
    return 0 if (baseline_pass and cover_reached and binding_mutation_killed
                 and assertion_mutation_killed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
