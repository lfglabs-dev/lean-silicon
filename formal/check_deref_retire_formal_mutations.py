#!/usr/bin/env python3
"""Require real failures in independently bounded DEREF lifecycle sub-goals."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
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
SOLVER_TIMEOUT_SECONDS = 540
SBY_NAME = "full_lsc1_deref_bridge.sby"
TEMP_PREFIX = "deref"
MUTATIONS = [
    ("corrupted_result_envelope_crc", "accepted_result_safety", "lsc1_packet_tx.sv",
     "saved_crc <= ~crc_byte(envelope_crc_work, tx_data);",
     "saved_crc <= ~crc_byte(envelope_crc_work, tx_data) ^ 32'h00000001;"),
    ("extra_result_envelope_beat", "accepted_result_safety", "lsc1_packet_tx.sv",
     "if (index == saved_length + 8) begin",
     "if (index == saved_length + 9) begin"),
    ("corrupted_result_crc_binding", "accepted_result_safety", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc ^ 32'h00000001;"),
    ("early_committed_pc", "accepted_result_safety", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc;\n"
     "                committed_pc <= staged_next_pc;"),
    ("early_committed_fp", "accepted_result_safety", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc;\n"
     "                committed_fp <= staged_next_fp;"),
    ("corrupted_staged_fp_retention", "matching_retire_safety", "lsc1_packet_frontend.sv",
     "            done_pulse <= 1'b0;\n"
     "            if (tx_done && capture_result_crc) begin",
     "            done_pulse <= 1'b0;\n"
     "            if (result_pending && !capture_result_crc)\n"
     "                staged_next_fp <= staged_next_fp ^ 32'h00000001;\n"
     "            if (tx_done && capture_result_crc) begin"),
    ("duplicate_retirement", "matching_retire_safety", "lsc1_packet_frontend.sv",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b0;",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b1;"),
    ("duplicate_completion_pulse", "post_retire_safety", "lsc1_packet_frontend.sv",
     "            encoder_start <= 1'b0;\n            done_pulse <= 1'b0;\n"
     "            if (tx_done && capture_result_crc) begin",
     "            encoder_start <= 1'b0;\n            done_pulse <= done_pulse;\n"
     "            if (tx_done && capture_result_crc) begin"),
]


def run_formal(
    name: str, task: str, mutation: tuple[str, str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix=f"{TEMP_PREFIX}-formal-{name}-") as raw:
        root = Path(raw)
        work = root / "formal"
        rtl_work = root / "asic_core" / "rtl"
        work.mkdir(parents=True)
        rtl_work.mkdir(parents=True)
        shutil.copy2(FORMAL / SBY_NAME, work)
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
            ["sby", "-f", SBY_NAME, task],
            cwd=work, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
            timeout=SOLVER_TIMEOUT_SECONDS,
        )


def check_mutation(mutation: tuple[str, str, str, str, str]) -> tuple[str, bool, str]:
    name, task, filename, old, new = mutation
    try:
        result = run_formal(name, task, (filename, old, new))
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


def main() -> int:
    failures: list[str] = []
    grouped: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)
    for mutation in MUTATIONS:
        grouped[mutation[1]].append(mutation)
    for task, mutations in grouped.items():
        try:
            baseline = run_formal(f"baseline-{task}", task)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            print(f"{task}: baseline_pass=false\nERROR: {error}")
            return 1
        baseline_pass = baseline.returncode == 0
        print(f"{task}: baseline_pass={str(baseline_pass).lower()}")
        if not baseline_pass:
            print(baseline.stdout[-4000:])
            return 1
        for mutation in mutations:
            name, assertion_failure, detail = check_mutation(mutation)
            print(f"{name}: task={task} real_property_failure={str(assertion_failure).lower()}")
            if not assertion_failure:
                print(detail)
                failures.append(f"{name}: no assertion failure")
    if failures:
        print("\n".join(f"ERROR: {failure}" for failure in failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
