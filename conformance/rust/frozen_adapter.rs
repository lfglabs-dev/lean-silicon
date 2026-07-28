//! Official leanVM-b adapter for the immutable LSC-1 conformance corpus.
//!
//! The Python runner copies this file into a disposable worktree of the exact
//! frozen upstream checkout and compiles it there as a `lean_vm` example.
//! Keeping the adapter here makes the compared Rust source reviewable without
//! modifying the frozen checkout.

use std::io::{self, BufRead};

use lean_vm::cpu::{DerefMode, Op, Program};
use primitives::field::{F128, g_pow};

fn f(value: u128) -> F128 {
    F128::new(value as u64, (value >> 64) as u64)
}

fn execute(case_id: &str) -> lean_vm::cpu::Execution {
    let (program, input) = match case_id {
        "scalar.set.forward" => (
            Program::from_bytecode(
                vec![Op::Set { o: 2, k: f(0x1234) }, Op::Set { o: 0, k: f(0) }],
                3,
            ),
            [f(5), f(6)],
        ),
        "scalar.xor.forward" => (
            Program::from_bytecode(
                vec![Op::Xor { a: 0, b: 1, c: 2 }, Op::Set { o: 0, k: f(0) }],
                3,
            ),
            [f(0xdead), f(0xbeef)],
        ),
        "scalar.mul.forward" => (
            Program::from_bytecode(
                vec![Op::Mul { a: 0, b: 1, c: 2 }, Op::Set { o: 0, k: f(0) }],
                3,
            ),
            [f(0x53), f(0xca)],
        ),
        "scalar.xor.backsolve_a" => (
            Program::from_bytecode(
                vec![Op::Xor { a: 2, b: 0, c: 1 }, Op::Set { o: 0, k: f(0) }],
                3,
            ),
            [f(0x1111), f(0x3333)],
        ),
        "scalar.xor.backsolve_b" => (
            Program::from_bytecode(
                vec![Op::Xor { a: 0, b: 2, c: 1 }, Op::Set { o: 0, k: f(0) }],
                3,
            ),
            [f(0x1111), f(0x3333)],
        ),
        "scalar.deref.cell" => (
            Program::from_bytecode(
                vec![
                    Op::Deref { alpha: 0, beta: 0, gamma: 1, mode: DerefMode::Cell },
                    Op::Set { o: 0, k: f(0) },
                ],
                9,
            ),
            [g_pow(8), f(0x77)],
        ),
        "scalar.deref.pc" => (
            Program::from_bytecode(
                vec![
                    Op::Deref { alpha: 0, beta: 0, gamma: 1, mode: DerefMode::Pc },
                    Op::Set { o: 0, k: f(0) },
                ],
                9,
            ),
            [g_pow(8), f(0)],
        ),
        "scalar.deref.fp" => (
            Program::assemble(
                vec![
                    Op::Set { o: 0, k: g_pow(8) },
                    Op::Set { o: 1, k: F128::ONE },
                    Op::Set { o: 2, k: g_pow(7) },
                    Op::Set { o: 3, k: F128::ONE },
                    Op::Deref { alpha: 0, beta: 0, gamma: 1, mode: DerefMode::Fp },
                    Op::Jump { oc: 1, od: 2, of: 3 },
                    Op::Set { o: 0, k: f(0) },
                    Op::Set { o: 0, k: f(0) },
                ],
                0,
                4,
                Default::default(),
                12,
            ),
            [f(0), f(0)],
        ),
        "scalar.jump.not_taken" => (
            Program::from_bytecode(
                vec![Op::Jump { oc: 1, od: 0, of: 0 }, Op::Set { o: 0, k: f(0) }],
                2,
            ),
            [f(1), f(0)],
        ),
        "scalar.jump.taken_nontrivial_inverse" => (
            Program::from_bytecode(
                vec![
                    Op::Set { o: 2, k: F128::ONE },
                    Op::Jump { oc: 0, od: 1, of: 2 },
                    Op::Set { o: 3, k: f(0x99) },
                    Op::Set { o: 0, k: f(0) },
                ],
                4,
            ),
            [f(0x53), g_pow(3)],
        ),
        _ => panic!("unknown corpus case_id: {case_id}"),
    };
    program.execute(input)
}

fn main() {
    for line in io::stdin().lock().lines() {
        let case_id = line.expect("stdin");
        if case_id.is_empty() {
            continue;
        }
        let execution = execute(&case_id);
        print!(
            "{{\"case_id\":\"{}\",\"cycles\":{},\"mem_used\":{},\"memory\":[",
            case_id, execution.cycles, execution.mem_used
        );
        for (index, value) in execution.mem.iter().take(execution.mem_used).enumerate() {
            if index != 0 {
                print!(",");
            }
            print!("\"{:016x}{:016x}\"", value.hi, value.lo);
        }
        println!("]}}");
    }
}
