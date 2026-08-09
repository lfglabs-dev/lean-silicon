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
2. proposes witnesses where the endpoint needs them (MUL back-solve and taken
   JUMP inversion) and resolves pointer-map indexes for DEREF/JUMP;
3. builds the request with the existing `sim/lsc1_transaction.py` builders and
   drives it over the byte lane;
4. decodes the `OK` result payload, and only then retires it by echoing
   `txn_id` and the CRC-32 of the result payload (two-phase retirement, D-008);
5. applies the returned writes to its own memory, counts the returned accesses,
   and records any returned deferred equality.

Nothing is applied before the endpoint has decided it, and nothing is retired
before the host has read it back.

## 3. What is integrated, and what is not

Integrated through the host and executable packet model: `SET_CONSTANT`,
`XOR`, `MUL_NATIVE`, `DEREF_CELL`, `DEREF_PC`, `DEREF_FP`, `JUMP`, and the
host-owned `BLAKE3` lifecycle through `SERVICE_REQUIRED`, software compression,
bound response, result, and retirement. This is CPU/model integration only;
there is no production BLAKE3 transport or RTL service path. FPGA RTL status is
tracked separately in `docs/STATUS.md`.

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

`Execution::mem` is padded to a power of two and only the first `mem_used`
cells are ever touched. The artifact records that prefix as
`upstream_execution.mem` plus the full buffer length as
`upstream_execution.mem_len`, rather than megabytes of untouched zeros.

The adapter reads only the exported artifact. It never shells out and never
imports Rust, so the tests run with no toolchain installed. It validates the
schema, the frozen commit, the bytecode length and slot labelling, and rejects
an unknown opcode or a malformed field operand instead of guessing.

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

For the checked-in fixture, the host executes all 13 upstream cycles including
the terminating `JUMP`. The comparison covers all 12 touched cells and the
cycle count and returns `MATCH`. Per-step upstream trace fields remain outside
the claim because `Execution::trace` is not public at the frozen revision.

## 6. Reproducing

Live compiler export/comparison requires x86_64 Linux, mount namespaces, and
non-interactive passwordless `sudo` for the fixed privileged broker commands,
plus a selected Rust toolchain provisioned as the root of its own read-only
filesystem mount. The live probe fails closed when a prerequisite is unavailable.

```sh
private=$(mktemp -d /tmp/lean-silicon-host.XXXXXX)
export CARGO_HOME="$private/cargo" RUSTUP_HOME="$private/rustup"
export PATH="$CARGO_HOME/bin:$PATH"
rustup toolchain install 1.88.0-x86_64-unknown-linux-gnu --profile minimal
installed_toolchain=$(dirname "$(dirname "$(rustup which --toolchain 1.88.0-x86_64-unknown-linux-gnu cargo)")")
toolchain_mb=$(du -sm "$installed_toolchain" | awk '{print $1}')
truncate -s "$((toolchain_mb + 256))M" "$private/rust-toolchain.ext4"
/usr/sbin/mkfs.ext4 -q "$private/rust-toolchain.ext4"
mkdir "$private/rust-toolchain-ro"
sudo mount -o loop "$private/rust-toolchain.ext4" "$private/rust-toolchain-ro"
sudo cp -a "$installed_toolchain/." "$private/rust-toolchain-ro/"
sudo umount "$private/rust-toolchain-ro"
rustup toolchain uninstall 1.88.0-x86_64-unknown-linux-gnu
sudo mount -o loop,ro "$private/rust-toolchain.ext4" "$private/rust-toolchain-ro"
rustup toolchain link leanvm-validation-1.88.0 "$private/rust-toolchain-ro"
git clone https://github.com/leanEthereum/leanVM-b.git "$private/leanvm-b"
git -C "$private/leanvm-b" checkout --detach c308034ab78619b39a59d26f3dc60e7df5b52649
make host-export LEANVM_B_UPSTREAM="$private/leanvm-b"
make host-comparison LEANVM_B_UPSTREAM="$private/leanvm-b"
rustup toolchain uninstall leanvm-validation-1.88.0
sudo umount "$private/rust-toolchain-ro"
```

`make host-export` requires `cargo`, and both targets reject an upstream
checkout that is not a clean detached checkout of the frozen commit.
`make host-comparison` without `LEANVM_B_UPSTREAM` compares against the
upstream execution recorded in the artifact instead of re-running it, and says
which one it used. With a checkout it re-compiles live and refuses to continue
unless the live compile reproduces the recorded bytecode.

`make python` runs `sim/test_host_runtime.py`, which needs no toolchain: it
exercises the memory, pointer, adapter, transaction and fault paths, and
re-checks the host run against the upstream execution recorded in the artifact.
