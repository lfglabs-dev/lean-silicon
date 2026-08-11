#!/usr/bin/env python3
"""Require real assertion failures for critical end-to-end bridge mutants."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from formal.subprocess_tree import run_bounded
except ModuleNotFoundError:
    from subprocess_tree import run_bounded

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "formal"
RTL = ROOT / "asic_core" / "rtl"
SOURCES = [
    "lsc1_packet_rx.sv", "lsc1_packet_tx.sv", "gf2n_mul_bitstream.sv",
    "gf128_mul_bitstream.sv", "leanvm_b_stream_alu.sv", "lsc1_stream_adapter.sv",
    "lsc1_field_encoder.sv", "lsc1_packet_frontend.sv",
]
SOLVER_TIMEOUT_SECONDS = 900
MAX_PARALLEL_MUTATIONS = 2
MUTATIONS = [
    ("corrupted_result_envelope_crc", "lsc1_packet_tx.sv",
     "saved_crc <= ~crc_byte(envelope_crc_work, tx_data);",
     "saved_crc <= ~crc_byte(envelope_crc_work, tx_data) ^ 32'h00000001;"),
    ("extra_result_envelope_beat", "lsc1_packet_tx.sv",
     "if (index == saved_length + 8) begin",
     "if (index == saved_length + 9) begin"),
    ("corrupted_result_crc_binding", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc ^ 32'h00000001;"),
    ("early_committed_pc", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc;\n"
     "                committed_pc <= staged_next_pc;"),
    ("early_committed_fp", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc;\n"
     "                committed_fp <= staged_next_fp;"),
    ("duplicate_retirement", "lsc1_packet_frontend.sv",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b0;",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b1;"),
    ("duplicate_completion_pulse", "lsc1_packet_frontend.sv",
     "            encoder_start <= 1'b0;\n            done_pulse <= 1'b0;\n"
     "            if (tx_done && capture_result_crc) begin",
     "            encoder_start <= 1'b0;\n            done_pulse <= done_pulse;\n"
     "            if (tx_done && capture_result_crc) begin"),
]


def run_formal(
    name: str, mutation: tuple[str, str, str] | None = None
) -> subprocess.CompletedProcess[str]:
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
        if mutation is not None:
            filename, old, new = mutation
            target = rtl_work / filename
            source_text = target.read_text()
            if source_text.count(old) != 1:
                raise ValueError(f"{name}: mutation anchor count {source_text.count(old)}")
            target.write_text(source_text.replace(old, new))
        return run_bounded(
            ["sby", "-f", "full_lsc1_deref_bridge.sby", "witness_safety"],
            cwd=work, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
            timeout=SOLVER_TIMEOUT_SECONDS,
        )


def check_mutation(mutation: tuple[str, str, str, str]) -> tuple[str, bool, str]:
    name, filename, old, new = mutation
    try:
        result = run_formal(name, (filename, old, new))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return name, False, str(error)
    output = result.stdout.lower()
    # SymbiYosys reports a falsified assertion as a completed FAIL independently
    # of the selected engine. Require that terminal result so synthesis/tool
    # errors cannot count as mutation kills merely because they returned nonzero.
    assertion_failure = (
        result.returncode != 0 and "done (fail, rc=2)" in output
    )
    return name, assertion_failure, result.stdout[-4000:]


def check_mutations(
    mutations: list[tuple[str, str, str, str]],
) -> list[tuple[str, bool, str]]:
    """Run every mutant while bounding simultaneous depth-2788 model builds."""
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_MUTATIONS) as executor:
        futures = [executor.submit(check_mutation, item) for item in mutations]
        return [future.result() for future in futures]


def main() -> int:
    failures: list[str] = []
    # Fail closed before starting any long mutant.  In particular, a pristine
    # failure must not enter an executor whose shutdown waits for mutant jobs.
    try:
        baseline = run_formal("baseline")
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"baseline_pass=false\nERROR: baseline could not complete: {error}")
        return 1
    baseline_pass = baseline.returncode == 0
    print(f"baseline_pass={str(baseline_pass).lower()}")
    if not baseline_pass:
        print(baseline.stdout[-4000:])
        print("ERROR: refusing to start mutations until the unmodified baseline passes")
        return 1

    # After the baseline gate passes, the disjoint temporary trees are safe to
    # check concurrently within the Actions wall-clock budget.
    results = check_mutations(MUTATIONS)
    for name, assertion_failure, detail in results:
        print(f"{name}: real_property_failure={str(assertion_failure).lower()}")
        if not assertion_failure:
            print(detail)
            failures.append(f"{name}: no assertion failure")
    if failures:
        print("\n".join(f"ERROR: {failure}" for failure in failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
