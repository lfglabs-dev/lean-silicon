#!/usr/bin/env python3
"""Seeded differential check: independent oracle versus frozen upstream runner.

The upstream checkout is explicit and verified before use.  A small Rust probe
is written only inside that checkout; it uses the public Program::execute API
and emits final-memory facts for straight-line programs.  The oracle being
checked lives in sim/scalar_step_oracle.py and has no upstream dependency.
"""
import argparse
import pathlib
import random
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
from scalar_step_oracle import encode, run  # noqa: E402

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


def require_checkout(path: pathlib.Path) -> None:
    actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    origin = subprocess.check_output(["git", "-C", str(path), "remote", "get-url", "origin"], text=True).strip()
    if actual != COMMIT or origin.rstrip("/").removesuffix(".git") != REPOSITORY.removesuffix(".git"):
        raise SystemExit(f"upstream mismatch: expected {REPOSITORY}@{COMMIT}, got {origin}@{actual}")


def program(a: int, b: int) -> list[tuple]:
    return [("set", 2, a), ("set", 3, b), ("xor", 2, 3, 4), ("mul", 2, 3, 5),
            ("deref_pc", 0, 6, 7), ("deref_fp", 0, 7, 7), ("jump", 1, 0, 0),
            ("set", 0, 0)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=pathlib.Path, help="clean checkout at the frozen commit")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0xC308034A)
    parser.add_argument("--cases", type=int, default=64)
    parser.add_argument("--record", type=pathlib.Path)
    args = parser.parse_args()
    if args.cases <= 0:
        raise SystemExit("--cases must be positive")
    require_checkout(args.upstream)
    if shutil.which("cargo") is None:
        raise SystemExit("cargo is required to compile the pinned upstream probe")
    example = args.upstream / "crates/lean_vm/examples/scalar_probe.rs"
    example.parent.mkdir(exist_ok=True)
    example.write_text(PROBE)
    rng = random.Random(args.seed)
    cases = [(rng.getrandbits(128), rng.getrandbits(128)) for _ in range(args.cases)]
    payload = "".join(f"{a:032x},{b:032x}\n" for a, b in cases)
    command = ["cargo", "run", "--quiet", "-p", "lean_vm", "--example", "scalar_probe"]
    completed = subprocess.run(command, cwd=args.upstream, input=payload, text=True, capture_output=True, check=True)
    rows = [row.split(",") for row in completed.stdout.splitlines()]
    if len(rows) != len(cases): raise SystemExit(f"probe returned {len(rows)} rows for {len(cases)} cases")
    for index, ((a, b), row) in enumerate(zip(cases, rows)):
        machine = run(program(a, b), (1, 0))
        expected = [str(machine.cycles)] + [f"{machine.read(address):032x}" for address in range(8)]
        if row != expected: raise SystemExit(f"mismatch case={index} seed={args.seed:#x}: upstream={row} oracle={expected}")
    message = f"PASS upstream={COMMIT} seed={args.seed:#x} cases={args.cases} program=7-step-set-xor-mul-deref-jump\n"
    if args.record: args.record.write_text(message)
    print(message, end="")


if __name__ == "__main__": main()
