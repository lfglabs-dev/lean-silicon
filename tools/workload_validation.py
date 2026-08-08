#!/usr/bin/env python3
"""Reproduce issue #51's bounded, non-release workload-validation receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "workloads/plan.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(argv: list[str], cwd: Path = ROOT) -> str:
    return subprocess.check_output(argv, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def clean_head() -> tuple[str, str]:
    if capture(["git", "status", "--porcelain"]):
        raise SystemExit("tracked workload checkout must be clean")
    return capture(["git", "rev-parse", "HEAD"]), capture(["git", "rev-parse", "HEAD^{tree}"])


def run_comparison(command: list[str], out: Path, workload_id: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run one comparison and return only a receipt created by this invocation."""
    out.unlink(missing_ok=True)
    run = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    if not out.exists():
        sys.stderr.write(run.stdout)
        raise SystemExit(f"comparison produced no receipt: {workload_id}")
    return run, json.loads(out.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    upstream = args.upstream.resolve()
    if cache == ROOT or ROOT in cache.parents:
        raise SystemExit("cache must be outside the checkout")
    cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(cache.stat().st_mode) & 0o077:
        raise SystemExit("cache must deny group and other access")

    plan = json.loads(PLAN_PATH.read_text())
    head, tree = clean_head()
    base = plan["source_commit"]
    if capture(["git", "rev-parse", f"{base}^{{tree}}"] ) != plan["source_tree"]:
        raise SystemExit("pinned main commit/tree mismatch")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT, check=True)
    if capture(["git", "-C", str(upstream), "rev-parse", "HEAD"]) != plan["upstream"]["commit"]:
        raise SystemExit("upstream checkout is not at the pinned commit")
    if capture(["git", "-C", str(upstream), "status", "--porcelain"]):
        raise SystemExit("upstream checkout must be clean")
    if sha(upstream / "Cargo.lock") != plan["upstream"]["cargo_lock_sha256"]:
        raise SystemExit("upstream Cargo.lock hash mismatch")

    receipt = {
        "schema": "lean-silicon/workload-validation-receipt/v1",
        "status": "pass", "issue": 51, "release_critical_path": False,
        "plan_sha256": sha(PLAN_PATH), "checkout_head": head, "checkout_tree": tree,
        "source_commit": base, "source_tree": plan["source_tree"],
        "upstream": plan["upstream"], "runtime": plan["runtime"],
        "toolchains": {
            "python": sys.version.replace("\n", " "),
            "cargo": capture(["cargo", f"+{plan['upstream']['rust_toolchain']}", "--version"]),
            "rustc": capture(["rustc", f"+{plan['upstream']['rust_toolchain']}", "--version"]),
        },
        "evidence": {"functional_model": [], "rtl_fpga": [], "asic": []},
        "coverage": {"selected": 3, "matched": 0, "expected_failures": 0},
        "limitations": [
            "finite three-program sample is not representative of all zkDSL or leanVM-b programs",
            "host/model comparison is not Lean-to-RTL equivalence or a proof",
            "heap pointer preparation fails before representative DEREF coverage",
            "BLAKE3 service integration is absent and the workload stops at the unsupported opcode",
            "no RTL simulation, synthesis, FPGA execution, place-and-route, or fabricated ASIC measurement is run",
            "upstream public trace fields are private, limiting the oracle to cycles and final memory",
            "timing of the Python/Rust validation command is deliberately not a benchmark",
        ],
    }
    for workload in plan["workloads"]:
        source, artifact = ROOT / workload["source"], ROOT / workload["artifact"]
        origin = upstream / workload["origin"]
        for path, expected in ((source, workload["source_sha256"]),
                               (artifact, workload["artifact_sha256"]),
                               (origin, workload["origin_sha256"])):
            if sha(path) != expected:
                raise SystemExit(f"hash mismatch: {path}")
        artifact_doc = json.loads(artifact.read_text())
        if len(artifact_doc["program"]["bytecode"]) != workload["expected"]["bytecode_slots"]:
            raise SystemExit(f"bytecode count mismatch: {workload['id']}")
        out = cache / f"{workload['id']}.comparison.json"
        command = [sys.executable, "tools/host_upstream_comparison.py", "--artifact",
                   workload["artifact"], "--upstream", str(upstream), "--rust-toolchain",
                   plan["upstream"]["rust_toolchain"], "--out", str(out)]
        run, comparison = run_comparison(command, out, workload["id"])
        actual = {"comparison": comparison["comparison"]["result"],
                  "terminal": comparison["lean_silicon"]["terminal"],
                  "cycles": comparison["upstream"]["cycles"]}
        if actual != {k: workload["expected"][k] for k in actual}:
            raise SystemExit(f"unexpected outcome {workload['id']}: {actual}")
        is_match = actual["comparison"] == "MATCH"
        receipt["coverage"]["matched" if is_match else "expected_failures"] += 1
        receipt["evidence"]["functional_model"].append({
            "id": workload["id"], "source_sha256": sha(source),
            "artifact_sha256": sha(artifact), "origin_sha256": sha(origin),
            "bytecode_slots": len(artifact_doc["program"]["bytecode"]),
            "upstream_cycles": comparison["upstream"]["cycles"],
            "upstream_mem_used": comparison["upstream"]["mem_used"],
            "model_steps": len(comparison["lean_silicon"]["steps"]),
            "result": actual["comparison"], "terminal": actual["terminal"],
            "reason": comparison["lean_silicon"]["reason"],
            "comparison_receipt": out.name, "comparison_sha256": sha(out),
            "command_exit_code": run.returncode,
        })
    receipt_path = cache / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "pass", "receipt": str(receipt_path),
                      "checkout_head": head, "coverage": receipt["coverage"]}, sort_keys=True))


if __name__ == "__main__":
    main()
