#!/usr/bin/env python3
"""Validate the immutable corpus and compare semantic cases to frozen leanVM-b."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance/corpus-v1.json"
SCHEMA = ROOT / "conformance/schema-v1.json"
ADAPTER = ROOT / "conformance/rust/frozen_adapter.rs"
UPSTREAM_REPOSITORY = "https://github.com/leanEthereum/leanVM-b.git"
UPSTREAM_COMMIT = "c308034ab78619b39a59d26f3dc60e7df5b52649"


class InfrastructureFailure(RuntimeError):
    pass


class SemanticFailure(RuntimeError):
    pass


def command(*args: str, cwd: pathlib.Path | None = None) -> str:
    try:
        return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        output = getattr(error, "output", "")
        raise InfrastructureFailure(f"command failed: {' '.join(args)}\n{output}") from error


def require_upstream(path: pathlib.Path) -> dict[str, str]:
    head = command("git", "-C", str(path), "rev-parse", "HEAD")
    origin = command("git", "-C", str(path), "remote", "get-url", "origin")
    dirty = command("git", "-C", str(path), "status", "--porcelain=v1", "--untracked-files=all")
    detached = subprocess.run(
        ["git", "-C", str(path), "symbolic-ref", "-q", "HEAD"], capture_output=True
    ).returncode != 0
    if (
        head != UPSTREAM_COMMIT
        or origin.rstrip("/").removesuffix(".git")
        != UPSTREAM_REPOSITORY.removesuffix(".git")
        or dirty
        or not detached
    ):
        raise InfrastructureFailure(
            "frozen upstream rejected: require clean detached "
            f"{UPSTREAM_REPOSITORY}@{UPSTREAM_COMMIT}; "
            f"got origin={origin!r} head={head!r} detached={detached} dirty={bool(dirty)}"
        )
    return {"repository": origin, "commit": head}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def validate_corpus() -> dict:
    try:
        import jsonschema

        corpus = json.loads(CORPUS.read_text())
        schema = json.loads(SCHEMA.read_text())
    except (ImportError, OSError, json.JSONDecodeError) as error:
        raise InfrastructureFailure(f"cannot load corpus/schema: {error}") from error
    if corpus.get("schema") != schema.get("$id"):
        raise SemanticFailure("corpus schema identifier does not match schema-v1.json")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(corpus),
            key=lambda error: list(error.absolute_path),
        )
    except jsonschema.SchemaError as error:
        raise SemanticFailure(f"invalid schema-v1.json: {error.message}") from error
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise SemanticFailure(f"schema violation at {location}: {error.message}")
    if corpus.get("frozen_upstream") != {
        "repository": UPSTREAM_REPOSITORY,
        "commit": UPSTREAM_COMMIT,
    }:
        raise SemanticFailure("corpus frozen_upstream identity mismatch")
    seen: set[str] = set()
    for case in corpus.get("cases", []):
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen:
            raise SemanticFailure(f"missing or duplicate case_id: {case_id!r}")
        seen.add(case_id)
        fingerprint = case.get("fingerprint")
        body = {key: value for key, value in case.items() if key != "fingerprint"}
        expected = "sha256:" + hashlib.sha256(canonical(body)).hexdigest()
        if fingerprint != expected:
            raise SemanticFailure(f"{case_id}: fingerprint mismatch")
        for key in ("raw", "initial_state", "final_state", "retire", "coverage", "upstream"):
            if key not in case:
                raise SemanticFailure(f"{case_id}: missing {key}")
        if case["upstream"].get("mode") == "program_execute":
            transition = case["upstream"].get("transition")
            staged = case.get("staged_transition")
            if not isinstance(staged, dict) or transition != {
                "next_pc": staged.get("next_pc"),
                "next_fp": staged.get("next_fp"),
                "writes": staged.get("writes"),
            }:
                raise SemanticFailure(
                    f"{case_id}: frozen upstream expectation disagrees with corpus transition"
                )
        if case["retire"].get("attempted") and case["retire"].get("done_pulse") is not True:
            raise SemanticFailure(f"{case_id}: successful RETIRE must observe DONE")
    return corpus


def run_adapter(upstream: pathlib.Path, case_ids: list[str], toolchain: str) -> list[dict]:
    if shutil.which("cargo") is None:
        raise InfrastructureFailure("cargo is required")
    temporary_parent = ROOT.parent / "temp"
    temporary_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="lean-silicon-corpus-", dir=temporary_parent
    ) as directory:
        worktree = pathlib.Path(directory) / "leanvm-b"
        try:
            command(
                "git", "-C", str(upstream), "worktree", "add", "--detach",
                str(worktree), UPSTREAM_COMMIT,
            )
            example = worktree / "crates/lean_vm/examples/frozen_lsc1_conformance.rs"
            example.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ADAPTER, example)
            completed = subprocess.run(
                [
                    "cargo", f"+{toolchain}", "run", "--quiet", "--locked",
                    "-p", "lean_vm", "--example", "frozen_lsc1_conformance",
                ],
                cwd=worktree,
                input="\n".join(case_ids) + "\n",
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "CARGO_TARGET_DIR": str(temporary_parent / "conformance-cargo-target"),
                },
            )
            if completed.returncode:
                raise InfrastructureFailure(
                    f"frozen Rust adapter failed ({completed.returncode}):\n{completed.stderr}"
                )
            try:
                return [json.loads(line) for line in completed.stdout.splitlines() if line]
            except json.JSONDecodeError as error:
                raise InfrastructureFailure(f"adapter emitted malformed JSON: {error}") from error
        finally:
            subprocess.run(
                ["git", "-C", str(upstream), "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=pathlib.Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--rust-toolchain", default="1.88.0")
    args = parser.parse_args()
    try:
        corpus = validate_corpus()
        semantic = [case for case in corpus["cases"] if case["upstream"]["mode"] == "program_execute"]
        if args.validate_only:
            print(f"PASS corpus cases={len(corpus['cases'])} fingerprints=verified schema=v1")
            return 0
        if args.upstream is None:
            raise InfrastructureFailure("--upstream is required unless --validate-only is used")
        preflight = require_upstream(args.upstream)
        actual = run_adapter(args.upstream, [case["case_id"] for case in semantic], args.rust_toolchain)
        actual_by_id = {row["case_id"]: row for row in actual}
        mismatches = []
        for case in semantic:
            expected = case["upstream"]["expected"]
            observed = actual_by_id.get(case["case_id"])
            if observed != {"case_id": case["case_id"], **expected}:
                mismatches.append({"case_id": case["case_id"], "expected": expected, "actual": observed})
        require_upstream(args.upstream)
        if mismatches:
            raise SemanticFailure(json.dumps(mismatches, indent=2, sort_keys=True))
        print(
            f"PASS corpus={len(corpus['cases'])} differential={len(semantic)} "
            f"upstream={preflight['commit']} rust={args.rust_toolchain}"
        )
        return 0
    except InfrastructureFailure as error:
        print(f"INFRASTRUCTURE FAILURE: {error}", file=sys.stderr)
        return 2
    except SemanticFailure as error:
        print(f"SEMANTIC FAILURE: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
