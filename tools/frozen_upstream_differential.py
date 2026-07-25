#!/usr/bin/env python3
"""Seeded differential check: independent oracle versus frozen upstream runner.

The upstream checkout is explicit and verified before use.  A small Rust probe
is written only inside that checkout; it uses the public Program::execute API
and emits final-memory facts for straight-line programs.  The oracle being
checked lives in sim/scalar_step_oracle.py and has no upstream dependency.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
ORACLE_SOURCE = ROOT / "sim/scalar_step_oracle.py"


def load_oracle_source() -> tuple:
    """Execute the tracked oracle source without consulting Python bytecode caches."""
    module_name = "_tracked_scalar_step_oracle"
    module = types.ModuleType(module_name)
    module.__file__ = str(ORACLE_SOURCE)
    sys.modules[module_name] = module
    try:
        code = compile(ORACLE_SOURCE.read_bytes(), str(ORACLE_SOURCE), "exec")
        exec(code, module.__dict__)
    finally:
        del sys.modules[module_name]
    return module.encode, module.run


encode, run = load_oracle_source()

COMMIT = "c308034ab78619b39a59d26f3dc60e7df5b52649"
REPOSITORY = "https://github.com/leanEthereum/leanVM-b.git"
PROBE = r'''use std::io::{self, Read};
use lean_vm::cpu::{DerefMode, Op, Program};
use primitives::field::F128;
fn f(s: &str) -> F128 { let v = u128::from_str_radix(s, 16).unwrap(); F128::new(v as u64, (v >> 64) as u64) }
fn main() { let mut input = String::new(); io::stdin().read_to_string(&mut input).unwrap();
 for line in input.lines().filter(|s| !s.is_empty()) { let mut p=line.split(','); let a=f(p.next().unwrap()); let b=f(p.next().unwrap());
  let prog=vec![Op::Set{o:2,k:a},Op::Set{o:3,k:b},Op::Xor{a:2,b:3,c:4},Op::Mul{a:2,b:3,c:5},Op::Deref{alpha:0,beta:6,gamma:7,mode:DerefMode::Pc},Op::Deref{alpha:0,beta:7,gamma:7,mode:DerefMode::Fp},Op::Jump{oc:1,od:0,of:0},Op::Set{o:0,k:F128::ZERO}];
  let e=Program::from_bytecode(prog, 8).execute([F128::ONE,F128::ZERO]);
  print!("{}", e.cycles); for v in e.mem.iter().take(8) { print!(",{:016x}{:016x}",v.hi,v.lo); } println!();
 }}'''


def generate_cases(seed: int, count: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    fixed = [(0x12, 0x34), (0x55, 0x66), (0x0A, 0x05)]
    return (fixed + [(rng.getrandbits(128), rng.getrandbits(128))
                     for _ in range(max(0, count - len(fixed)))])[:count]


def command_output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def require_checkout(path: pathlib.Path) -> dict[str, str]:
    """Reject anything other than a clean detached checkout of the frozen source."""
    try:
        actual = command_output(["git", "-C", str(path), "rev-parse", "HEAD"])
        origin = command_output(["git", "-C", str(path), "remote", "get-url", "origin"])
        status = command_output(["git", "-C", str(path), "status", "--porcelain=v1", "--untracked-files=all"])
        detached = subprocess.run(
            ["git", "-C", str(path), "symbolic-ref", "-q", "HEAD"],
            text=True, capture_output=True,
        ).returncode != 0
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"invalid upstream checkout {path}: {error.output}") from error
    expected_origin = REPOSITORY.removesuffix(".git")
    actual_origin = origin.rstrip("/").removesuffix(".git")
    if actual != COMMIT or actual_origin != expected_origin or not detached or status:
        raise SystemExit(
            "upstream checkout rejected: require clean detached "
            f"{REPOSITORY}@{COMMIT}; got origin={origin!r} head={actual!r} "
            f"detached={detached} dirty={bool(status)}"
        )
    return {"origin": origin, "head": actual, "detached": str(detached).lower(), "status": status}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_head() -> str:
    head = command_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    status = command_output(
        ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"]
    )
    if status:
        raise SystemExit(
            f"candidate checkout rejected: require clean tree at {head}; dirty=true"
        )
    return head


def program(a: int, b: int) -> list[tuple]:
    return [("set", 2, a), ("set", 3, b), ("xor", 2, 3, 4), ("mul", 2, 3, 5),
            ("deref_pc", 0, 6, 7), ("deref_fp", 0, 7, 7), ("jump", 1, 0, 0),
            ("set", 0, 0)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=pathlib.Path, help="clean checkout at the frozen commit")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0xC308034A)
    parser.add_argument("--cases", type=int, default=64)
    parser.add_argument("--record", type=pathlib.Path, help="write a one-line PASS result")
    parser.add_argument("--evidence", type=pathlib.Path, help="write reproducibility metadata as JSON")
    parser.add_argument("--rust-toolchain", default="1.88.0", help="Rust toolchain used for the locked probe")
    args = parser.parse_args()
    if args.cases <= 0:
        raise SystemExit("--cases must be positive")
    tested_head = candidate_head()
    preflight = require_checkout(args.upstream)
    if shutil.which("cargo") is None:
        raise SystemExit("cargo is required to compile the pinned upstream probe")
    # Keep the first cases aligned with the M2 RTL regression, then fill the
    # requested total with seeded full-width cases.
    cases = generate_cases(args.seed, args.cases)
    payload = "".join(f"{a:032x},{b:032x}\n" for a, b in cases)
    # The supplied checkout is never modified.  A disposable detached worktree
    # gets the tiny probe, so Cargo runs from the frozen workspace and consumes
    # its committed lockfile with --locked.  The supplied checkout is verified
    # again after the worktree is removed.
    with tempfile.TemporaryDirectory(prefix="leanvm-b-frozen-probe-") as directory:
        probe_root = pathlib.Path(directory) / "upstream-worktree"
        subprocess.run(["git", "-C", str(args.upstream), "worktree", "add", "--detach", str(probe_root), COMMIT], check=True, capture_output=True)
        try:
            example = probe_root / "crates/lean_vm/examples/scalar_probe.rs"
            example.parent.mkdir(exist_ok=True)
            example.write_text(PROBE)
            command = ["cargo", f"+{args.rust_toolchain}", "run", "--quiet", "--locked", "-p", "lean_vm", "--example", "scalar_probe"]
            completed = subprocess.run(command, cwd=probe_root, input=payload, text=True, capture_output=True)
        finally:
            subprocess.run(["git", "-C", str(args.upstream), "worktree", "remove", "--force", str(probe_root)], check=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(f"upstream Cargo probe failed ({completed.returncode}):\n{completed.stderr}")
    rows = [row.split(",") for row in completed.stdout.splitlines()]
    if len(rows) != len(cases): raise SystemExit(f"probe returned {len(rows)} rows for {len(cases)} cases")
    for index, ((a, b), row) in enumerate(zip(cases, rows)):
        machine = run(program(a, b), (1, 0))
        expected = [str(machine.cycles)] + [f"{machine.read(address):032x}" for address in range(8)]
        if row != expected: raise SystemExit(f"mismatch case={index} seed={args.seed:#x}: upstream={row} oracle={expected}")
    postflight = require_checkout(args.upstream)
    if candidate_head() != tested_head:
        raise SystemExit("candidate checkout rejected: HEAD changed during differential")
    message = f"PASS upstream={COMMIT} seed={args.seed:#x} cases={args.cases} profile=7-step-set-xor-mul-deref-pc-deref-fp-nontaken-jump\n"
    if args.record: args.record.write_text(message)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps({
            "schema": 1,
            "result": "PASS",
            "exit_status": 0,
            "tested_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tested_repo_head": tested_head,
            "upstream": {"repository": REPOSITORY, "sha": COMMIT,
                         "preflight": preflight, "postflight": postflight,
                         "cargo_lock_sha256": sha256(args.upstream / "Cargo.lock")},
            "profile": "seven-step straight-line SET, SET, XOR, MUL, DEREF(Pc), DEREF(Fp), non-taken JUMP",
            "limits": "Does not cover BLAKE3, Cell DEREF/deferred reconciliation, taken jumps, allocation hints, or overflow behavior.",
            "seed": f"{args.seed:#x}", "case_count": args.cases,
            "command": command, "cargo_exit_status": completed.returncode,
            "rust_toolchain": args.rust_toolchain,
            "provenance": {"checker_sha256": sha256(pathlib.Path(__file__)),
                           "oracle_sha256": sha256(ORACLE_SOURCE)},
        }, indent=2, sort_keys=True) + "\n")
    print(message, end="")


if __name__ == "__main__": main()
