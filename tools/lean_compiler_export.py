#!/usr/bin/env python3
"""Export a program artifact from the frozen upstream ``lean_compiler``.

A tiny Cargo example is written into a disposable detached worktree of the
verified checkout, so the supplied tree is never modified and Cargo consumes
the frozen lockfile with ``--locked``.  The probe calls only the public pinned
interface: ``lean_compiler::{parse, compile, disassemble}`` and
``lean_vm::cpu::Program::execute``.

``Program::hints``, ``Program::main_frame``, ``Program::witness`` and
``Execution::trace`` are ``pub(crate)`` at the frozen commit, so an out-of-crate
probe cannot read them.  Every artifact records that limit instead of guessing
around it.
"""
import argparse
import datetime
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE_SOURCE = ROOT / "tools" / "frozen_upstream_differential.py"

_gate = types.ModuleType("_tracked_frozen_upstream_differential")
_gate.__file__ = str(GATE_SOURCE)
sys.modules[_gate.__name__] = _gate
try:
    exec(compile(GATE_SOURCE.read_bytes(), str(GATE_SOURCE), "exec"), _gate.__dict__)
finally:
    del sys.modules[_gate.__name__]

COMMIT, REPOSITORY = _gate.COMMIT, _gate.REPOSITORY
require_checkout, candidate_head, sha256 = _gate.require_checkout, _gate.candidate_head, _gate.sha256

SCHEMA = "leansilicon.host.program/1"

#: Public-only fields.  Anything `pub(crate)` upstream is reported as absent.
UNEXPOSED = {
    "Program::hints": "pub(crate): prover frame/buffer allocation hints",
    "Program::main_frame": "pub(crate): size of main's frame",
    "Program::witness": "pub(crate): named prover witness streams",
    "Execution::trace": "pub(crate): per-step trace rows and access counts",
}

PROBE = r'''use lean_compiler::{compile, disassemble, parse};
use lean_vm::cpu::{DerefMode, Op};
use primitives::field::F128;
use std::io::{self, Read};

fn hex(v: F128) -> String { format!("0x{:016x}{:016x}", v.hi, v.lo) }

fn op_json(i: usize, op: &Op) -> String {
    match op {
        Op::Xor { a, b, c } => format!(r#"{{"index":{i},"op":"Xor","a":{a},"b":{b},"c":{c}}}"#),
        Op::Mul { a, b, c } => format!(r#"{{"index":{i},"op":"Mul","a":{a},"b":{b},"c":{c}}}"#),
        Op::Set { o, k } => format!(r#"{{"index":{i},"op":"Set","o":{o},"k":"{}"}}"#, hex(*k)),
        Op::Deref { alpha, beta, gamma, mode } => {
            let m = match mode { DerefMode::Cell => "Cell", DerefMode::Pc => "Pc", DerefMode::Fp => "Fp" };
            format!(r#"{{"index":{i},"op":"Deref","alpha":{alpha},"beta":{beta},"gamma":{gamma},"mode":"{m}"}}"#)
        }
        Op::Jump { oc, od, of } => format!(r#"{{"index":{i},"op":"Jump","oc":{oc},"od":{od},"of":{of}}}"#),
        Op::Blake3 { ins, cv, out, metadata } => format!(
            r#"{{"index":{i},"op":"Blake3","ins":[{},{},{},{}],"cv":{cv},"out":{out},"metadata":"{}"}}"#,
            ins[0], ins[1], ins[2], ins[3], hex(*metadata)),
    }
}

fn main() {
    let mut source = String::new();
    io::stdin().read_to_string(&mut source).unwrap();
    let ast = parse(&source).expect("zkDSL source failed to parse");
    let program = compile(&ast);
    let ops: Vec<String> = program.prog.iter().enumerate().map(|(i, op)| op_json(i, op)).collect();
    let ranges: Vec<String> = program.fn_ranges.iter()
        .map(|(n, e, l)| format!(r#"["{n}",{e},{l}]"#)).collect();
    let run = program.execute([F128::ONE, F128::ZERO]);
    // `mem` is padded to a power of two; only the first `mem_used` cells were
    // touched, and everything past them is zero. Emit the touched prefix and
    // the full length rather than megabytes of padding.
    let mem: Vec<String> = run.mem.iter().take(run.mem_used)
        .map(|v| format!("\"{}\"", hex(*v))).collect();
    println!(
        r#"{{"pc0":{},"fp0":{},"bytecode":[{}],"fn_ranges":[{}],"disassembly":{},"execution":{{"cycles":{},"mem_used":{},"mem_len":{},"mem":[{}]}}}}"#,
        program.pc0, program.fp0, ops.join(","), ranges.join(","),
        serde_json_string(&disassemble(&program.prog)),
        run.cycles, run.mem_used, run.mem.len(), mem.join(","));
}

/// Minimal JSON string escaping; the disassembly is ASCII plus newlines.
fn serde_json_string(text: &str) -> String {
    let mut out = String::from("\"");
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
'''


def run_probe(upstream: pathlib.Path, source: str, toolchain: str) -> tuple[dict, list[str]]:
    with tempfile.TemporaryDirectory(prefix="leanvm-b-compiler-probe-") as directory:
        worktree = pathlib.Path(directory) / "upstream-worktree"
        subprocess.run(
            ["git", "-C", str(upstream), "worktree", "add", "--detach", str(worktree), COMMIT],
            check=True, capture_output=True,
        )
        try:
            example = worktree / "crates/lean_compiler/examples/leansilicon_export.rs"
            example.parent.mkdir(parents=True, exist_ok=True)
            example.write_text(PROBE)
            command = [
                "cargo", f"+{toolchain}", "run", "--quiet", "--locked",
                "-p", "lean_compiler", "--example", "leansilicon_export",
            ]
            completed = subprocess.run(
                command, cwd=worktree, input=source, text=True, capture_output=True
            )
        finally:
            subprocess.run(
                ["git", "-C", str(upstream), "worktree", "remove", "--force", str(worktree)],
                check=True, capture_output=True,
            )
    if completed.returncode:
        raise SystemExit(f"lean_compiler probe failed ({completed.returncode}):\n{completed.stderr}")
    return json.loads(completed.stdout), command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=pathlib.Path,
                        help="clean detached checkout at the frozen commit")
    parser.add_argument("--source", required=True, type=pathlib.Path, help="zkDSL source file")
    parser.add_argument("--out", required=True, type=pathlib.Path, help="artifact JSON to write")
    parser.add_argument("--rust-toolchain", default="1.88.0")
    args = parser.parse_args()

    tested_head = candidate_head()
    preflight = require_checkout(args.upstream)
    if shutil.which("cargo") is None:
        raise SystemExit("cargo is required to compile the pinned lean_compiler probe")

    source = args.source.read_text()
    probe, command = run_probe(args.upstream, source, args.rust_toolchain)
    postflight = require_checkout(args.upstream)
    if candidate_head() != tested_head:
        raise SystemExit("candidate checkout rejected: HEAD changed during export")

    artifact = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generated_from_repo_head": tested_head,
        "upstream": {
            "repository": REPOSITORY,
            "sha": COMMIT,
            "preflight": preflight,
            "postflight": postflight,
            "cargo_lock_sha256": sha256(args.upstream / "Cargo.lock"),
            "rust_toolchain": args.rust_toolchain,
            "command": command,
            "interface": [
                "lean_compiler::parse(&str) -> Result<Ast, String>",
                "lean_compiler::compile(&Ast) -> lean_vm::cpu::Program",
                "lean_compiler::disassemble(&[Op]) -> String",
                "lean_vm::cpu::Program::execute([F128; 2]) -> Execution",
            ],
            "not_exposed_by_public_interface": UNEXPOSED,
        },
        "source": {
            "language": "zkDSL",
            "path": str(args.source.relative_to(ROOT)) if args.source.is_relative_to(ROOT)
                    else args.source.name,
            "sha256": sha256(args.source),
            "text": source,
        },
        "program": {
            "pc0": probe["pc0"],
            "fp0": probe["fp0"],
            "bytecode": probe["bytecode"],
            "fn_ranges": probe["fn_ranges"],
            "disassembly": probe["disassembly"],
        },
        "upstream_execution": {
            "public_input": ["0x00000000000000000000000000000001",
                             "0x00000000000000000000000000000000"],
            "cycles": probe["execution"]["cycles"],
            "mem_used": probe["execution"]["mem_used"],
            "mem_len": probe["execution"]["mem_len"],
            # Only the `mem_used` prefix is recorded; upstream pads `mem` to
            # `mem_len` (a power of two) and every padded cell is zero.
            "mem": probe["execution"]["mem"],
        },
        "provenance": {"exporter_sha256": sha256(pathlib.Path(__file__))},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(
        f"exported {len(probe['bytecode'])} bytecode slots from "
        f"{REPOSITORY}@{COMMIT} to {args.out}"
    )


if __name__ == "__main__":
    main()
