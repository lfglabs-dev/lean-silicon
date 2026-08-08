#!/usr/bin/env python3
"""Reproduce issue #51's bounded, non-release workload-validation receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

# Never allow repository-local replacement refs to rewrite pinned Git objects.
os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "workloads/plan.json"
SUPPORTED_RUNTIME = {
    "public_input": [
        "0x00000000000000000000000000000001",
        "0x00000000000000000000000000000000",
    ],
    "profile": "INTERPRETER_COMPAT",
}
SUPPORTED_UPSTREAM_REPOSITORY = "https://github.com/leanEthereum/leanVM-b.git"
SAFE_WORKLOAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
REQUIRED_WORKLOAD_INPUTS = {
    "field_division": (
        "workloads/field_division.zkdsl",
        "workloads/field_division.program.json",
        "crates/lean_compiler/tests/field_div.rs",
    ),
    "heap_recurrence": (
        "workloads/heap_recurrence.zkdsl",
        "workloads/heap_recurrence.program.json",
        "crates/rec_aggregation/src/fibonacci.rs",
    ),
    "blake3_stack": (
        "workloads/blake3_stack.zkdsl",
        "workloads/blake3_stack.program.json",
        "crates/lean_compiler/tests/stack_buf.rs",
    ),
}
REQUIRED_WORKLOAD_IDS = frozenset(REQUIRED_WORKLOAD_INPUTS)
REQUIRED_WORKLOAD_CLAIM_DIGESTS = {
    "field_division": "0dc1ce05f79073b6bfe6f3137bbc2c561c8db16429dcea09aca1380ec45a90b7",
    "heap_recurrence": "c551f7b25229a9c97cf01603428f540cdfe6586a6ebba8227384fcd79bde8af3",
    "blake3_stack": "c38c09b27718ab365feaaedfa17eeb61e766b5b6c8289362b7805955f3a1d9a8",
}
WORKLOAD_CLAIM_KEYS = (
    "source_sha256", "artifact_sha256", "origin_sha256", "expected",
)
IMPORTABLE_FILE_SUFFIXES = frozenset({
    ".py", ".pyw", ".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib",
})


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(argv: list[str], cwd: Path = ROOT) -> str:
    return subprocess.check_output(argv, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def require_clean_tracked_worktree(root: Path = ROOT) -> None:
    """Compare filesystem bytes and modes directly to canonical HEAD objects."""
    entries = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "--full-tree", "HEAD"], cwd=root
    ).split(b"\0")
    for entry in entries:
        if not entry:
            continue
        metadata, encoded_name = entry.split(b"\t", 1)
        mode, object_type, oid = metadata.decode().split()
        relative = encoded_name.decode(errors="surrogateescape")
        path = root / relative
        try:
            if object_type == "blob" and mode == "120000":
                actual = os.readlink(path).encode(errors="surrogateescape")
            elif object_type == "blob":
                actual = path.read_bytes()
                expected_executable = mode == "100755"
                actual_executable = bool(path.stat().st_mode & 0o111)
                if actual_executable != expected_executable:
                    raise SystemExit("tracked workload checkout must match HEAD")
            elif object_type == "commit":
                actual = capture(["git", "rev-parse", "HEAD"], cwd=path).encode()
            else:
                raise SystemExit("tracked workload checkout contains unsupported Git objects")
        except OSError as error:
            raise SystemExit("tracked workload checkout must match HEAD") from error
        expected = subprocess.check_output(
            ["git", "cat-file", object_type, oid], cwd=root
        )
        if object_type == "commit":
            expected = oid.encode()
        if actual != expected:
            raise SystemExit("tracked workload checkout must match HEAD")


def require_clean_worktree(root: Path = ROOT) -> None:
    """Reject changed tracked bytes and non-ignored untracked import shadows."""
    if capture(["git", "for-each-ref", "--format=%(refname)", "refs/replace"], cwd=root):
        raise SystemExit("workload checkout must not contain Git replacement refs")
    require_clean_tracked_worktree(root)
    if capture(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=root
    ):
        raise SystemExit("workload checkout must not contain untracked files")
    ignored = subprocess.check_output(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        cwd=root,
    ).split(b"\0")
    for name in ignored:
        if not name:
            continue
        relative = Path(name.decode())
        if (
            relative.suffix.lower() in IMPORTABLE_FILE_SUFFIXES
            or (root / relative).is_symlink()
        ):
            raise SystemExit(
                "workload checkout must not contain ignored importable paths"
            )


def clean_head() -> tuple[str, str]:
    require_clean_worktree()
    return capture(["git", "rev-parse", "HEAD"]), capture(["git", "rev-parse", "HEAD^{tree}"])


@contextmanager
def pinned_worktree(repository: Path, commit: str):
    """Yield a private detached worktree at the canonical captured commit."""
    with tempfile.TemporaryDirectory(prefix="workload-validation-snapshot-") as temp:
        checkout = Path(temp) / "checkout"
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "worktree", "add",
             "--detach", str(checkout), commit],
            cwd=repository,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        try:
            require_clean_worktree(checkout)
            yield checkout
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout)],
                cwd=repository,
                check=True,
                stdout=subprocess.DEVNULL,
            )


def run_comparison(command: list[str], out: Path, workload_id: str,
                   cwd: Path = ROOT) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run one comparison and return only a receipt created by this invocation."""
    if command[:2] != [sys.executable, "-I"]:
        raise SystemExit("comparison must use isolated Python")
    out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="workload-validation-pycache-") as pycache:
        isolated_command = command[:2] + ["-X", f"pycache_prefix={pycache}"] + command[2:]
        run = subprocess.run(
            isolated_command,
            cwd=cwd,
            env=os.environ,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    if not out.exists():
        sys.stderr.write(run.stdout)
        raise SystemExit(f"comparison produced no receipt: {workload_id}")
    return run, json.loads(out.read_text())


def prepare_receipt_path(cache: Path) -> Path:
    """Invalidate any aggregate receipt left by an earlier invocation."""
    receipt_path = cache / "receipt.json"
    receipt_path.unlink(missing_ok=True)
    return receipt_path


def publish_receipt(receipt_path: Path, receipt: dict,
                    expected_checkout: tuple[str, str]) -> None:
    """Publish only if the validated checkout is still the captured revision."""
    if clean_head() != expected_checkout:
        raise SystemExit("workload checkout changed during validation")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def validate_runtime(runtime: dict) -> None:
    """Refuse plan runtime claims the fixed comparator does not execute."""
    if runtime != SUPPORTED_RUNTIME:
        raise SystemExit("plan runtime differs from the comparator's supported runtime")


def selected_workload_count(plan: dict) -> int:
    """Report the number of workloads this invocation will actually validate."""
    return len(plan["workloads"])


def validate_unique_workload_ids(plan: dict) -> None:
    """Require the documented workload set and distinct safe cache filenames."""
    ids = [workload["id"] for workload in plan["workloads"]]
    if len(ids) != len(set(ids)):
        raise SystemExit("workload ids must be unique")
    if any(SAFE_WORKLOAD_ID.fullmatch(workload_id) is None for workload_id in ids):
        raise SystemExit("workload ids must be safe filename components")
    if set(ids) != REQUIRED_WORKLOAD_IDS:
        raise SystemExit("plan must contain exactly the required workload ids")


def validate_workload_identities(plan: dict) -> None:
    """Bind each coverage label to its documented candidate/upstream inputs."""
    for workload in plan["workloads"]:
        actual = (workload["source"], workload["artifact"], workload["origin"])
        if actual != REQUIRED_WORKLOAD_INPUTS[workload["id"]]:
            raise SystemExit(
                f"workload inputs differ from documented identity: {workload['id']}"
            )
        claim = {key: workload[key] for key in WORKLOAD_CLAIM_KEYS}
        digest = hashlib.sha256(
            json.dumps(claim, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != REQUIRED_WORKLOAD_CLAIM_DIGESTS[workload["id"]]:
            raise SystemExit(
                f"workload claims differ from canonical contents: {workload['id']}"
            )


def validate_upstream_repository(upstream: dict) -> None:
    """Bind the plan attribution to the repository supported by the comparator."""
    if upstream["repository"] != SUPPORTED_UPSTREAM_REPOSITORY:
        raise SystemExit("plan upstream repository is unsupported")


def validate_upstream_checkout(upstream: Path, plan: dict) -> None:
    """Revalidate the pinned upstream state and every consumed origin file."""
    if capture(["git", "rev-parse", "HEAD"], cwd=upstream) != plan["upstream"]["commit"]:
        raise SystemExit("upstream checkout is not at the pinned commit")
    require_clean_worktree(upstream)
    if sha(upstream / "Cargo.lock") != plan["upstream"]["cargo_lock_sha256"]:
        raise SystemExit("upstream Cargo.lock hash mismatch")
    for workload in plan["workloads"]:
        origin = resolve_tracked_path(upstream, workload["origin"])
        if sha(origin) != workload["origin_sha256"]:
            raise SystemExit(f"hash mismatch: {origin}")


def resolve_tracked_path(root: Path, relative: str) -> Path:
    """Resolve a plan input inside its checkout and require Git tracking."""
    root = root.resolve()
    candidate = Path(relative)
    if candidate.is_absolute():
        raise SystemExit(f"plan path must be checkout-relative: {relative}")
    path = (root / candidate).resolve()
    try:
        canonical_relative = path.relative_to(root)
    except ValueError as error:
        raise SystemExit(f"plan path escapes its checkout: {relative}") from error
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(canonical_relative)],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not tracked:
        raise SystemExit(f"plan path is not tracked: {relative}")
    return path


def comparison_outcome(comparison: dict) -> dict:
    """Return every boundary value that the workload plan pins."""
    return {
        "comparison": comparison["comparison"]["result"],
        "terminal": comparison["lean_silicon"]["terminal"],
        "cycles": comparison["upstream"]["cycles"],
        "model_steps": len(comparison["lean_silicon"]["steps"]),
        "reason": comparison["lean_silicon"]["reason"],
        "mismatches": comparison["comparison"]["mismatches"],
        "model_written": comparison["lean_silicon"]["final_state"]["written"],
    }


def validate_comparison_runtime(comparison: dict, runtime: dict) -> None:
    """Bind the receipt's runtime claim to the comparator's executed profile."""
    if comparison["lean_silicon"]["profile"] != runtime["profile"]:
        raise SystemExit("comparison profile differs from the planned runtime")


def validate_source_binding(source: Path, artifact_doc: dict,
                            expected_path: str) -> None:
    """Bind the checked source file to the compiler input embedded in its artifact."""
    embedded = artifact_doc["source"]
    expected = {
        "path": expected_path,
        "sha256": sha(source),
        "text": source.read_text(),
    }
    if any(embedded.get(key) != value for key, value in expected.items()):
        raise SystemExit(f"artifact source binding mismatch: {source}")


def validate_artifact_runtime(artifact_doc: dict, runtime: dict) -> None:
    """Bind recorded execution attribution to the runtime actually exercised."""
    if artifact_doc["upstream_execution"]["public_input"] != runtime["public_input"]:
        raise SystemExit("artifact public input differs from the planned runtime")


def collect_evidence(plan: dict, cache: Path, receipt: dict, upstream: Path,
                     head: str) -> None:
    """Run every comparison from immutable candidate and upstream snapshots."""
    with (
        pinned_worktree(ROOT, head) as candidate_snapshot,
        pinned_worktree(upstream, plan["upstream"]["commit"]) as upstream_snapshot,
    ):
        for workload in plan["workloads"]:
            source = resolve_tracked_path(ROOT, workload["source"])
            artifact = resolve_tracked_path(ROOT, workload["artifact"])
            origin = resolve_tracked_path(upstream, workload["origin"])
            for path, expected in ((source, workload["source_sha256"]),
                                   (artifact, workload["artifact_sha256"]),
                                   (origin, workload["origin_sha256"])):
                if sha(path) != expected:
                    raise SystemExit(f"hash mismatch: {path}")
            artifact_doc = json.loads(artifact.read_text())
            validate_source_binding(source, artifact_doc, workload["source"])
            validate_artifact_runtime(artifact_doc, plan["runtime"])
            if len(artifact_doc["program"]["bytecode"]) != workload["expected"]["bytecode_slots"]:
                raise SystemExit(f"bytecode count mismatch: {workload['id']}")
            out = cache / f"{workload['id']}.comparison.json"
            command = [sys.executable, "-I", "tools/host_upstream_comparison.py", "--artifact",
                       workload["artifact"], "--upstream", str(upstream_snapshot), "--rust-toolchain",
                       plan["upstream"]["rust_toolchain"], "--out", str(out)]
            run, comparison = run_comparison(
                command, out, workload["id"], cwd=candidate_snapshot
            )
            validate_comparison_runtime(comparison, plan["runtime"])
            actual = comparison_outcome(comparison)
            if actual != {k: workload["expected"][k] for k in actual}:
                raise SystemExit(f"unexpected outcome {workload['id']}: {actual}")
            is_match = actual["comparison"] == "MATCH"
            receipt["coverage"]["matched" if is_match else "expected_failures"] += 1
            receipt["evidence"]["functional_model"].append({
                "id": workload["id"], "source_sha256": workload["source_sha256"],
                "artifact_sha256": workload["artifact_sha256"],
                "origin_sha256": workload["origin_sha256"],
                "bytecode_slots": len(artifact_doc["program"]["bytecode"]),
                "upstream_cycles": comparison["upstream"]["cycles"],
                "upstream_mem_used": comparison["upstream"]["mem_used"],
                "model_steps": len(comparison["lean_silicon"]["steps"]),
                "result": actual["comparison"], "terminal": actual["terminal"],
                "reason": comparison["lean_silicon"]["reason"],
                "comparison_receipt": out.name, "comparison_sha256": sha(out),
                "command_exit_code": run.returncode,
            })


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
    receipt_path = prepare_receipt_path(cache)

    plan = json.loads(PLAN_PATH.read_text())
    validate_runtime(plan["runtime"])
    validate_unique_workload_ids(plan)
    validate_workload_identities(plan)
    validate_upstream_repository(plan["upstream"])
    head, tree = clean_head()
    base = plan["source_commit"]
    if capture(["git", "rev-parse", f"{base}^{{tree}}"] ) != plan["source_tree"]:
        raise SystemExit("pinned main commit/tree mismatch")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT, check=True)
    validate_upstream_checkout(upstream, plan)

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
        "coverage": {"selected": selected_workload_count(plan),
                     "matched": 0, "expected_failures": 0},
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
    collect_evidence(plan, cache, receipt, upstream, head)
    validate_upstream_checkout(upstream, plan)
    publish_receipt(receipt_path, receipt, (head, tree))
    print(json.dumps({"status": "pass", "receipt": str(receipt_path),
                      "checkout_head": head, "coverage": receipt["coverage"]}, sort_keys=True))


if __name__ == "__main__":
    main()
