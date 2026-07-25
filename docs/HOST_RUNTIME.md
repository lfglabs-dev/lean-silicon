# Mac host runtime for LSC-1

This document describes the host half of the split in
[ARCHITECTURE](ARCHITECTURE.md): what the Mac owns, how it turns a compiled
program into LSC-1 transactions, and exactly how far the current scaffold in
`host/` goes.

The transaction protocol itself is unchanged. `docs/LSC1_TRANSACTION_PROTOCOL.md`
and `sim/lsc1_transaction.py` remain the normative pair; `host/` is a consumer
of that contract and adds no wire format, opcode, status code or profile.

## 1. Division of state

The host owns, and never delegates:

| State | Host module |
|---|---|
| Compiled program and bytecode | `host/lean_compiler_adapter.py` |
| VM memory image and write-once bitmap | `host/memory.py` (`HostMemory`) |
| Pointer map: `g**i` forward, index reverse lookup | `host/memory.py` (`PointerMap`) |
| Deferred-equality state | `host/memory.py` (`HostMemory.deferred`) |
| Inversion witnesses | `host/memory.py` (`field_inverse`) |
| Per-cell access counts | `host/memory.py` (`HostMemory.access_counts`) |
| Transaction preparation and retirement | `host/runtime.py` (`HostRuntime`) |

LSC-1 receives one self-contained transaction and answers with transition
effects. It performs no fetch, holds no memory array, and never searches the
pointer map: the host sends the index as a witness and the endpoint re-encodes
it (`encode(base) == pointer`). Inversion is the same shape, a host witness
checked by multiplication (D-003). BLAKE3 stays a host service (D-004).

## 2. The step loop

For each instruction the host:

1. reads its own memory for every address the transition can touch, and packs
   each one as a present cell or an absent cell;
2. proposes a witness where the endpoint will need one (currently only the MUL
   back-solve inverse);
3. builds the request with the existing `sim/lsc1_transaction.py` builders and
   drives it over the byte lane;
4. decodes the `OK` result payload, and only then retires it by echoing
   `txn_id` and the CRC-32 of the result payload (two-phase retirement, D-008);
5. applies the returned writes to its own memory, counts the returned accesses,
   and records any returned deferred equality.

Nothing is applied before the endpoint has decided it, and nothing is retired
before the host has read it back.

## 3. What is integrated, and what is not

Integrated end to end: `SET_CONSTANT`, `XOR`, `MUL_NATIVE`, including the
INTERPRETER_COMPAT back-solve path and its inverse witness.

Not integrated. Each raises `UnsupportedCapability` naming the missing piece;
none of them silently degrade or skip an instruction:

| Compiler opcode | Missing host capability |
|---|---|
| `Deref` | pointer-map driven request preparation and the deferred-equality reconciliation loop |
| `Jump` | branch proposal and destination re-encoding |
| `Blake3` | a BLAKE3 compression implementation to answer `SERVICE_REQUIRED` |

Index range is limited to `2**16` by the protocol (`INDEX_BITS`), and
`PointerMap` refuses anything above it rather than extending the window.

## 4. The pinned lean_compiler interface

`host/` consumes a JSON program artifact produced by
`tools/lean_compiler_export.py` from `leanEthereum/leanVM-b` at
`c308034ab78619b39a59d26f3dc60e7df5b52649`. The probe uses only the public
interface at that commit:

- `lean_compiler::parse(&str) -> Result<Ast, String>`
- `lean_compiler::compile(&Ast) -> lean_vm::cpu::Program`
- `lean_compiler::disassemble(&[Op]) -> String`
- `lean_vm::cpu::Program::execute([F128; 2]) -> Execution`
- `Program::prog`, `Program::pc0`, `Program::fp0`, `Program::fn_ranges`
- `Execution::mem`, `Execution::cycles`, `Execution::mem_used`

Four fields a complete host runtime will eventually need are `pub(crate)` at
that commit and cannot be read from outside the crate:

| Field | Consequence |
|---|---|
| `Program::hints` | prover frame/buffer allocation hints are unavailable, so programs that need nondeterministic frame allocation cannot be driven from an artifact |
| `Program::main_frame` | the frame size must be inferred or supplied separately |
| `Program::witness` | named `hint_witness` streams are unavailable |
| `Execution::trace` | upstream exposes no per-step record, which bounds what a differential can compare (section 5) |

This is a recorded limit of the frozen source, not a workaround target. Every
artifact carries the same list under `upstream.not_exposed_by_public_interface`.

The adapter reads only the exported artifact. It never shells out and never
imports Rust, so the tests run with no toolchain installed.

## 5. Comparison against the official runner

`tools/host_upstream_comparison.py` emits a
`leansilicon.host.comparison/1` document. The leanSilicon side is recorded in
full for every transition: `pc`, `fp`, `opcode`, effective `addresses`, input
cell presence and values, `writes`, `branch`, `deferred`, `fault`, `status`,
plus the final state.

The upstream side is not comparable field for field. Because
`Execution::trace` is `pub(crate)`, `Program::execute` yields only the final
memory image, `cycles` and `mem_used`. The tool therefore:

- compares the final memory value at every address the host actually wrote,
  which is sound because memory is write-once on both sides, so no later
  upstream instruction can give one of those cells a different value;
- compares `cycles` only when the host run reached the sentinel, and otherwise
  records why it did not;
- emits every remaining schema field with an explicit reason for being
  unverified, under `comparison.not_compared`.

Equivalence is claimed only for the entries under `comparison.compared`.

## 6. Reproducing

```sh
git clone https://github.com/leanEthereum/leanVM-b.git /tmp/leanvm-b
git -C /tmp/leanvm-b checkout c308034ab78619b39a59d26f3dc60e7df5b52649
make host-export LEANVM_B_UPSTREAM=/tmp/leanvm-b
make host-comparison LEANVM_B_UPSTREAM=/tmp/leanvm-b
```

Both targets require `cargo` and reject an upstream checkout that is not a
clean detached checkout of the frozen commit. `make host-comparison` without
`LEANVM_B_UPSTREAM` compares against the upstream execution recorded in the
artifact instead of re-running it, and says which one it used.
