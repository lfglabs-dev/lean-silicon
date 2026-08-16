#!/usr/bin/env python3
"""Prove and mutation-check the production full-LSC1 pending binding."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
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
REMOVED_PENDING_ASSERTION = "if (blake_result_pending) /* assertion removed by mutation */;"
CONTROL_COVER = "cover(blake_result_pending);"
CONTROL_COVER_MUTATION = "cover(blake_result_pending || 1'b0);"
VALIDATOR = FORMAL / "validate_blake3_pending_contract.py"


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


def install_baseline(root: Path, name: str) -> Path:
    """Create an independent exact-baseline workspace for one receipt task."""
    work = root / name
    work.mkdir()
    for source in SOURCES:
        shutil.copy2(RTL / source, work / source)
    shutil.copy2(FORMAL / INVARIANT, work / INVARIANT)
    return work


def anchor_once(text: str, anchor: str, label: str) -> None:
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label} anchor count is {count}, expected 1")


def mutation_isolated(work: Path, expected_frontend: str, expected_invariant: str) -> bool:
    """Ensure a mutant changed only its named file from the production baseline."""
    for source in SOURCES:
        expected = expected_frontend if source == "lsc1_packet_frontend.sv" else (RTL / source).read_text()
        if (work / source).read_text() != expected:
            return False
    return (work / INVARIANT).read_text() == expected_invariant


def validate_contract(work: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the independent production-invariant structural contract."""
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(work / INVARIANT)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="blake3-pending-invariant-") as raw:
        root = Path(raw)
        source_text = (RTL / "lsc1_packet_frontend.sv").read_text()
        invariant_text = (FORMAL / INVARIANT).read_text()
        try:
            anchor_once(source_text, UNION_BINDING, "production union binding")
            anchor_once(invariant_text, PENDING_ASSERTION, "production pending assertion")
        except RuntimeError as error:
            print(json.dumps({"receipt_version": 1, "error": str(error)}, sort_keys=True))
            return 1

        baseline_work = install_baseline(root, "baseline")
        baseline_contract = validate_contract(baseline_work)
        baseline = run(baseline_work, "bmc")
        coverage = run(baseline_work, "cover")

        binding_work = install_baseline(root, "omit_union")
        binding_frontend = binding_work / "lsc1_packet_frontend.sv"
        binding_text = source_text.replace(UNION_BINDING, OMITTED_BINDING)
        binding_frontend.write_text(binding_text)
        binding_isolated = mutation_isolated(binding_work, binding_text, invariant_text)
        binding_contract = validate_contract(binding_work)
        binding_mutation = run(binding_work, "bmc")

        assertion_results = {}
        for name, replacement in (("weaken_assertion", WEAK_PENDING_ASSERTION),
                                  ("remove_assertion", REMOVED_PENDING_ASSERTION)):
            mutant_work = install_baseline(root, name)
            mutant_invariant = invariant_text.replace(PENDING_ASSERTION, replacement)
            anchor_once(mutant_invariant, replacement, f"{name} replacement")
            (mutant_work / INVARIANT).write_text(mutant_invariant)
            isolated = mutation_isolated(mutant_work, source_text, mutant_invariant)
            contract = validate_contract(mutant_work)
            proof = run(mutant_work, "bmc")
            cover = run(mutant_work, "cover")
            assertion_results[name] = {
                "isolated": isolated,
                "union_intact": (mutant_work / "lsc1_packet_frontend.sv").read_text() == source_text
                    and source_text.count(UNION_BINDING) == 1,
                "proof_pass": proof.returncode == 0,
                "cover_reached": cover.returncode == 0,
                "contract_rejected": contract.returncode == 1,
                "contract_output": contract.stdout,
                "killed": isolated and contract.returncode == 1
                    and proof.returncode == 0 and cover.returncode == 0,
                "proof_output": proof.stdout,
                "cover_output": cover.stdout,
            }

        control_work = install_baseline(root, "control_cover")
        anchor_once(invariant_text, CONTROL_COVER, "control cover")
        control_invariant = invariant_text.replace(CONTROL_COVER, CONTROL_COVER_MUTATION)
        anchor_once(control_invariant, CONTROL_COVER_MUTATION, "control cover replacement")
        (control_work / INVARIANT).write_text(control_invariant)
        control_isolated = mutation_isolated(control_work, source_text, control_invariant)
        control_contract = validate_contract(control_work)

    baseline_pass = baseline.returncode == 0 and baseline_contract.returncode == 0
    cover_reached = coverage.returncode == 0
    binding_mutation_killed = (
        binding_mutation.returncode != 0
        and "done (fail" in binding_mutation.stdout.lower()
    )
    assertion_mutations_killed = all(result["killed"] for result in assertion_results.values())
    receipt = {
        "receipt_version": 1,
        "baseline_proof": baseline_pass,
        "blake_pending_cover": cover_reached,
        "mutations": {
            "omit_frontend_union": {
                "anchor_count": source_text.count(UNION_BINDING),
                "isolated": binding_isolated,
                "contract_pass": binding_contract.returncode == 0,
                "killed": binding_mutation_killed and binding_isolated
                    and binding_contract.returncode == 0,
                "reason": "production_pending_assertion_failed",
            },
            **{
                name: {
                    "anchor_count": invariant_text.count(PENDING_ASSERTION),
                    "isolated": result["isolated"],
                    "union_intact": result["union_intact"],
                    "proof_pass": result["proof_pass"],
                    "cover_reached": result["cover_reached"],
                    "contract_rejected": result["contract_rejected"],
                    "killed": result["killed"],
                    "reason": "independent_production_pending_contract_rejected",
                } for name, result in assertion_results.items()
            },
            "control_cover_change": {
                "anchor_count": invariant_text.count(CONTROL_COVER),
                "isolated": control_isolated,
                "contract_pass": control_contract.returncode == 0,
                "accepted": control_isolated and control_contract.returncode == 0,
                "reason": "unrelated_invariant_change_accepted",
            },
        },
    }
    print(json.dumps(receipt, sort_keys=True))
    print("production_union_binding=true")
    print("production_pending_assertion=true")
    print(f"baseline_proof={str(baseline_pass).lower()}")
    print(f"blake_pending_cover={str(cover_reached).lower()}")
    print(f"omit_production_blake_pending_mutation_killed={str(binding_mutation_killed).lower()}")
    print(f"weaken_production_pending_assertion_mutation_killed={str(assertion_results['weaken_assertion']['killed']).lower()}")
    print(f"remove_production_pending_assertion_mutation_killed={str(assertion_results['remove_assertion']['killed']).lower()}")
    if not baseline_pass:
        print(baseline.stdout[-4000:])
    if not cover_reached:
        print(coverage.stdout[-4000:])
    if not binding_mutation_killed:
        print(binding_mutation.stdout[-4000:])
    for result in assertion_results.values():
        if not result["killed"]:
            print(result["contract_output"][-2000:])
            print(result["proof_output"][-2000:])
            print(result["cover_output"][-2000:])
    control_accepted = control_isolated and control_contract.returncode == 0
    return 0 if (baseline_pass and cover_reached and binding_mutation_killed
                 and binding_isolated and binding_contract.returncode == 0
                 and assertion_mutations_killed and control_accepted) else 1


if __name__ == "__main__":
    raise SystemExit(main())
