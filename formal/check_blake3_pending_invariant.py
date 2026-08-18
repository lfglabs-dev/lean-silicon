#!/usr/bin/env python3
"""Prove and mutation-check the production full-LSC1 pending binding."""

from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "asic_core" / "rtl"
FORMAL = ROOT / "formal"
SOURCES = [
    "lsc1_packet_rx.sv", "lsc1_packet_tx.sv", "lsc1_response_payload_mux.sv",
    "lsc1_blake3_alias_check.sv", "lsc1_request_validator.sv",
    "lsc1_cell_alias_check.sv", "gf2n_mul_bitstream.sv",
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return "unavailable"
    return result.stdout.strip()


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


def contract_receipt(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"valid": False, "reason": "validator_receipt_unparseable",
                "raw_output": result.stdout[-2000:]}


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
        baseline_contract_receipt = contract_receipt(baseline_contract)
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
            contract_meta = contract_receipt(contract)
            proof = run(mutant_work, "bmc")
            cover = run(mutant_work, "cover")
            assertion_results[name] = {
                "input_frontend_sha256": text_digest(source_text),
                "input_invariant_sha256": text_digest(mutant_invariant),
                "isolated": isolated,
                "union_intact": (mutant_work / "lsc1_packet_frontend.sv").read_text() == source_text
                    and source_text.count(UNION_BINDING) == 1,
                "proof_pass": proof.returncode == 0,
                "cover_reached": cover.returncode == 0,
                "contract_rejected": contract.returncode == 1,
                "contract_output": contract.stdout,
                "contract_receipt": contract_meta,
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
        control_contract_receipt = contract_receipt(control_contract)

    baseline_pass = baseline.returncode == 0 and baseline_contract.returncode == 0
    cover_reached = coverage.returncode == 0
    binding_mutation_killed = (
        binding_mutation.returncode != 0
        and "done (fail" in binding_mutation.stdout.lower()
    )
    assertion_mutations_killed = all(result["killed"] for result in assertion_results.values())
    receipt = {
        "receipt_version": 2,
        "provenance": {
            "git_head": tool_version(["git", "rev-parse", "HEAD"]),
            "production_frontend_sha256": digest(RTL / "lsc1_packet_frontend.sv"),
            "production_invariant_sha256": digest(FORMAL / INVARIANT),
            "validator_sha256": digest(VALIDATOR),
            "yosys_version": tool_version(["yosys", "-V"]),
            "sby_version": tool_version(["sby", "--version"]),
            "formal_command": "sby -f binding-{bmc,cover}.sby",
            "validator_command": f"{sys.executable} {VALIDATOR} INVARIANT",
            "validator_contract_version": baseline_contract_receipt.get("contract_version"),
            "validator_runtime_yosys_version": baseline_contract_receipt.get(
                "runtime_yosys_version"),
            "validator_json_creator": baseline_contract_receipt.get("json_creator"),
            "validator_consumption_route": baseline_contract_receipt.get(
                "consumption_route"),
            "validator_archive_fd": baseline_contract_receipt.get("archive_fd"),
            "validator_source_fd": baseline_contract_receipt.get("source_fd"),
            "validator_archive_sha256": baseline_contract_receipt.get("archive_sha256"),
            "validator_toolchain_manifest_sha256": baseline_contract_receipt.get(
                "toolchain_manifest_sha256"),
            "validator_archive_observed_before": baseline_contract_receipt.get(
                "archive_observed_before"),
            "validator_archive_observed_after_elaboration": baseline_contract_receipt.get(
                "archive_observed_after_elaboration"),
            "validator_snapshot_route": baseline_contract_receipt.get("snapshot_route"),
            "validator_trusted_workspace": baseline_contract_receipt.get(
                "trusted_workspace"),
            "validator_snapshot_identity_before": baseline_contract_receipt.get(
                "snapshot_identity_before"),
            "validator_snapshot_identity_after": baseline_contract_receipt.get(
                "snapshot_identity_after"),
            "validator_runtime_descriptor_objects": baseline_contract_receipt.get(
                "runtime_descriptor_objects"),
            "validator_runtime_descriptor_objects_after": baseline_contract_receipt.get(
                "runtime_descriptor_objects_after"),
            "validator_output_consumption_route": baseline_contract_receipt.get(
                "output_consumption_route"),
            "validator_threat_boundary": baseline_contract_receipt.get(
                "threat_boundary"),
            "validator_sanitized_environment": baseline_contract_receipt.get(
                "sanitized_environment"),
            "validator_observed_runtime_files": baseline_contract_receipt.get(
                "observed_runtime_files"),
            "validator_runtime_dependency_audit": baseline_contract_receipt.get(
                "runtime_dependency_audit"),
            "validator_source_observed_before": baseline_contract_receipt.get(
                "source_observed_before"),
            "validator_source_observed_after": baseline_contract_receipt.get(
                "source_observed_after"),
            "validator_json_sha256": baseline_contract_receipt.get("json_sha256"),
            "validator_elaboration_command": baseline_contract_receipt.get("command"),
            "validator_representation_classification": baseline_contract_receipt.get(
                "representation_classification"),
            "validator_trigger_classification": baseline_contract_receipt.get(
                "trigger_classification"),
            "validator_supported_yosys_range": baseline_contract_receipt.get(
                "supported_yosys_range"),
            "validator_supported_representation": baseline_contract_receipt.get(
                "supported_representation"),
        },
        "baseline_proof": baseline_pass,
        "blake_pending_cover": cover_reached,
        "mutations": {
            "omit_frontend_union": {
                "input_frontend_sha256": text_digest(binding_text),
                "input_invariant_sha256": text_digest(invariant_text),
                "anchor_count": source_text.count(UNION_BINDING),
                "isolated": binding_isolated,
                "contract_pass": binding_contract.returncode == 0,
                "contract_receipt": contract_receipt(binding_contract),
                "killed": binding_mutation_killed and binding_isolated
                    and binding_contract.returncode == 0,
                "reason": "production_pending_assertion_failed",
            },
            **{
                name: {
                    "input_frontend_sha256": result["input_frontend_sha256"],
                    "input_invariant_sha256": result["input_invariant_sha256"],
                    "anchor_count": invariant_text.count(PENDING_ASSERTION),
                    "isolated": result["isolated"],
                    "union_intact": result["union_intact"],
                    "proof_pass": result["proof_pass"],
                    "cover_reached": result["cover_reached"],
                    "contract_rejected": result["contract_rejected"],
                    "contract_receipt": result["contract_receipt"],
                    "killed": result["killed"],
                    "reason": "independent_production_pending_contract_rejected",
                } for name, result in assertion_results.items()
            },
            "control_cover_change": {
                "input_frontend_sha256": text_digest(source_text),
                "input_invariant_sha256": text_digest(control_invariant),
                "anchor_count": invariant_text.count(CONTROL_COVER),
                "isolated": control_isolated,
                "contract_pass": control_contract.returncode == 0,
                "contract_receipt": control_contract_receipt,
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
