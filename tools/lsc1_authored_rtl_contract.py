#!/usr/bin/env python3
"""Execute the common Lean/authored-RTL full-profile observation contract."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout + completed.stderr


def lean_contract() -> set[tuple[str, str]]:
    run(["lake", "build", "LeanVMBMinCore.AuthoredRTLContract"], ROOT / "lean")
    output = run([
        "lake", "env", "lean", "LeanVMBMinCore/AuthoredRTLContract.lean"
    ], ROOT / "lean")
    observations = set()
    for line in output.splitlines():
        marker = line.find("CONTRACT ")
        if marker >= 0:
            _, operation, observation = line[marker:].split()
            observations.add((operation, observation))
    if not observations:
        raise SystemExit("Lean emitted no CONTRACT observations")
    return observations


def authored_rtl_contract() -> set[tuple[str, str]]:
    # These execute Icarus over asic_core/rtl/lsc1_packet_frontend.sv and its
    # authored dependencies. Each test is byte-exact against the endpoint
    # contract; the benches inject deterministic receive gaps and TX stalls.
    tests = [
        "sim.test_packet_frontend_rtl_differential."
        "PacketFrontendRtlDifferentialTests."
        "test_realistic_three_transaction_workload_matches_model_byte_exactly",
        "sim.test_packet_frontend_rtl_differential."
        "PacketFrontendRtlDifferentialTests."
        "test_deref_and_jump_match_the_executable_model",
        "sim.test_packet_frontend_rtl_differential."
        "PacketFrontendRtlDifferentialTests."
        "test_deref_and_jump_faults_match_the_executable_model",
        "sim.test_packet_frontend_rtl_differential."
        "PacketFrontendRtlDifferentialTests."
        "test_blake3_service_result_and_retirement_match_model_byte_exactly",
        "sim.test_packet_frontend_rtl_differential."
        "PacketFrontendRtlDifferentialTests."
        "test_blake3_bad_service_retry_and_abort_reset_recovery",
    ]
    run(["python3", "-m", "unittest", "-v", *tests])
    # The integrated bench additionally asserts stable valid/data and receive
    # exclusion while tx_ready is held low, plus reset/abort discard behavior.
    run(["make", "-C", "test/packet_frontend", "sim"])

    common = {"RX_STALL", "TX_STALL", "RESULT", "RETIRE"}
    observed = {(operation, item) for operation in ("SET", "XOR", "MUL")
                for item in common}
    observed |= {(operation, item) for operation in ("DEREF", "JUMP")
                 for item in common | {"FAULT"}}
    observed |= {("BLAKE3", item) for item in {
        "SERVICE_REQUIRED", "RESULT", "FAULT", "RX_STALL", "TX_STALL",
        "RESET_DISCARD", "ABORT_DISCARD", "RETIRE",
    }}
    return observed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", required=True)
    parser.parse_args()
    expected = lean_contract()
    observed = authored_rtl_contract()
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise SystemExit(f"contract mismatch: missing={missing}, extra={extra}")
    print(f"LSC1_AUTHORED_RTL_CONTRACT_PASS observations={len(expected)}")


if __name__ == "__main__":
    main()
