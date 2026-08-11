#!/usr/bin/env python3
"""Require real assertion failures for critical end-to-end bridge mutants."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
    ("corrupted_result_envelope_crc", "lsc1_packet_tx.sv",
     "saved_crc <= ~crc_byte(envelope_crc_work, tx_data);",
     "saved_crc <= ~crc_byte(envelope_crc_work, tx_data) ^ 32'h00000001;"),
    ("corrupted_result_crc_binding", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc ^ 32'h00000001;"),
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
        return subprocess.run(
            ["sby", "-f", "full_lsc1_deref_bridge.sby", "witness_safety"],
            cwd=work, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=12600,
        )


def check_mutation(mutation: tuple[str, str, str, str]) -> tuple[str, bool, str]:
    name, filename, old, new = mutation
    try:
        result = run_formal(name, (filename, old, new))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return name, False, str(error)
    assertion_failure = result.returncode != 0 and (
        "assert failed" in result.stdout.lower() or
        "assertion failed" in result.stdout.lower()
    )
    return name, assertion_failure, result.stdout[-4000:]


def main() -> int:
    failures: list[str] = []
    # These proofs use disjoint temporary trees and have no ordering dependency.
    # Run the pristine design alongside the mutants to preserve the Actions
    # wall-clock budget, but do not inspect or count any mutant result until the
    # baseline has independently passed.
    with ThreadPoolExecutor(max_workers=len(MUTATIONS) + 1) as executor:
        baseline_future = executor.submit(run_formal, "baseline")
        mutation_futures = [executor.submit(check_mutation, item) for item in MUTATIONS]
        try:
            baseline = baseline_future.result()
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            print(f"baseline_pass=false\nERROR: baseline could not complete: {error}")
            return 1
        baseline_pass = baseline.returncode == 0
        print(f"baseline_pass={str(baseline_pass).lower()}")
        if not baseline_pass:
            print(baseline.stdout[-4000:])
            print("ERROR: refusing to count mutation failures until the unmodified baseline passes")
            return 1
        results = [future.result() for future in mutation_futures]
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
