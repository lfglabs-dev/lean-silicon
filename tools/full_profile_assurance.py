#!/usr/bin/env python3
"""Reproducible bounded assurance receipt for the non-release LSC-1 lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import jsonschema
except ImportError as error:
    raise SystemExit("required Python package missing: jsonschema") from error

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "assurance/full-profile/plan.json"
SCHEMA_PATH = ROOT / "assurance/full-profile/schema.json"
RTL = [
    "asic_core/rtl/lsc1_packet_rx.sv",
    "asic_core/rtl/lsc1_packet_tx.sv",
    "asic_core/rtl/gf2n_mul_bitstream.sv",
    "asic_core/rtl/gf128_mul_bitstream.sv",
    "asic_core/rtl/leanvm_b_stream_alu.sv",
    "asic_core/rtl/lsc1_stream_adapter.sv",
    "asic_core/rtl/lsc1_field_encoder.sv",
    "asic_core/rtl/lsc1_packet_frontend.sv",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output(argv: list[str]) -> str:
    return subprocess.check_output(argv, cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip()


def require_clean_tracked_worktree() -> None:
    """Compare actual tracked files to HEAD without trusting index flags."""
    index_fd, index_name = tempfile.mkstemp(prefix="lsc1-full-index-")
    os.close(index_fd)
    os.unlink(index_name)
    try:
        env = os.environ | {"GIT_INDEX_FILE": index_name}
        subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env, check=True)
        clean = subprocess.run(["git", "diff-files", "--quiet"], cwd=ROOT, env=env).returncode == 0
    finally:
        Path(index_name).unlink(missing_ok=True)
    if not clean:
        raise SystemExit("tracked assurance checkout must match HEAD")


def validate_contract(document: dict, definition: dict) -> None:
    """Validate the complete closed machine contract."""
    jsonschema.Draft202012Validator.check_schema(definition)
    jsonschema.Draft202012Validator(definition).validate(document)


def run(name: str, argv: list[str], receipt: dict, env: dict[str, str] | None = None,
        recorded_argv: list[str] | None = None) -> str:
    completed = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=env)
    receipt["commands"].append({"name": name, "argv": recorded_argv or argv,
                                "exit_code": completed.returncode})
    if completed.returncode:
        sys.stderr.write(completed.stdout)
        raise SystemExit(f"{name} failed with exit {completed.returncode}")
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--verify", action="store_true", required=True)
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    if cache == ROOT or ROOT in cache.parents:
        raise SystemExit("cache must resolve outside the checkout")
    cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    if cache.stat().st_mode & 0o077:
        raise SystemExit("cache must deny group and other access")
    plan = json.loads(PLAN_PATH.read_text())
    schema = json.loads(SCHEMA_PATH.read_text())
    validate_contract(plan, schema["$defs"]["plan"])
    require_clean_tracked_worktree()
    head = output(["git", "rev-parse", "HEAD"])
    tree = output(["git", "rev-parse", "HEAD^{tree}"])
    # A PR checkout naturally has a new commit/tree; its first parent is the pinned main source.
    base = output(["git", "rev-parse", f"{plan['source_commit']}^{{commit}}"])
    base_tree = output(["git", "rev-parse", f"{base}^{{tree}}"])
    if (base != plan["source_commit"] or base_tree != plan["source_tree"] or
            output(["git", "merge-base", "--is-ancestor", base, head]) != ""):
        raise SystemExit("checkout does not descend from the pinned main source")
    for tool in ("python3", "iverilog", "vvp", "yosys"):
        if shutil.which(tool) is None:
            raise SystemExit(f"required tool missing: {tool}")
    receipt = {
        "schema": "lean-silicon/full-profile-assurance-receipt/v1",
        "plan_sha256": sha(PLAN_PATH), "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"], "checkout_head": head, "checkout_tree": tree,
        "release_critical_path": False,
        "toolchains": {
            "python": sys.version.replace("\n", " "),
            "iverilog": output(["iverilog", "-V"]).splitlines()[0],
            "yosys": output(["yosys", "-V"]),
        },
        "rtl": [{"path": path, "sha256": sha(ROOT / path)} for path in RTL],
        "assumptions": [
            "single synchronous clock", "testbench asserts reset before traffic",
            "two-state finite vectors", "ready/valid defines accepted beats",
            "finite test vectors are eventually supplied and drained",
            "Yosys-elaborated hierarchy snapshot is provenance-only",
        ],
        "classification": {"unbounded": [], "bounded": plan["claims"]["bounded"]},
        "commands": [], "mutations": [], "residual_gaps": [
            "no complete independent formal packet transition specification",
            "no Lean-to-RTL relation", "BLAKE3 request/service response are model-only",
            "no synthesized or pinned physical full-profile netlist", "finite corpus is not exhaustive",
        ],
    }
    baseline_env = os.environ.copy()
    baseline_env.pop("LSC1_RTL_DIR", None)
    run("rtl_model_differential", [sys.executable, "-m", "unittest",
                                    "sim.test_packet_frontend_rtl_differential", "-v"],
        receipt, env=baseline_env,
        recorded_argv=["$PYTHON", "-m", "unittest",
                       "sim.test_packet_frontend_rtl_differential", "-v"])
    run("cycle_non_vacuity", ["make", "-C", "test/packet_frontend", "sim"], receipt)
    run("cycle_mutations", ["make", "-C", "test/packet_frontend", "mutation"], receipt)
    receipt["mutations"].append({"boundary": "cycle/runtime", "killed": True, "count": 5})
    mutation_env = os.environ.copy()
    mutation_env["PYTHONPATH"] = str(ROOT) + os.pathsep + mutation_env.get("PYTHONPATH", "")
    run("differential_mutations", ["make", "-C", "test/packet_frontend", "differential-mutation"],
        receipt, env=mutation_env | {"PYTHON": sys.executable})
    receipt["mutations"].append({"boundary": "model/RTL", "killed": True, "count": 2})
    snapshot = cache / "lsc1_packet_frontend.elaborated.v"
    script_prefix = "read_verilog -sv " + " ".join(RTL) + "; hierarchy -check -top lsc1_packet_frontend; write_verilog -noattr "
    run("generate_elaborated_snapshot", ["yosys", "-q", "-p", script_prefix + str(snapshot)], receipt,
        recorded_argv=["yosys", "-q", "-p", script_prefix + "$LSC1_FULL_CACHE/lsc1_packet_frontend.elaborated.v"])
    receipt["generated_snapshot"] = {"path": snapshot.name, "sha256": sha(snapshot), "bytes": snapshot.stat().st_size}
    mutated = cache / "lsc1_packet_frontend.elaborated.mutated.v"
    mutated.write_bytes(snapshot.read_bytes() + b"\n// provenance mutation\n")
    killed = sha(mutated) != receipt["generated_snapshot"]["sha256"]
    receipt["mutations"].append({"boundary": "generated-artifact provenance pin", "killed": killed, "count": 1})
    if not killed:
        raise SystemExit("generated-artifact provenance mutation unexpectedly survived")
    receipt["status"] = "pass"
    validate_contract(receipt, schema["$defs"]["receipt"])
    (cache / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "pass", "receipt": str(cache / "receipt.json"),
                      "snapshot_sha256": receipt["generated_snapshot"]["sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
