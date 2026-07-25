# Frozen scalar semantics

This document freezes the scalar-core contract against
`leanEthereum/leanVM-b` commit `c308034ab78619b39a59d26f3dc60e7df5b52649`.
It is deliberately narrower than a hardware implementation: the current RTL
and M0 stream protocol are not an implementation of this machine.

## Normative layers

**Architectural behavior** is the relation proved by the upstream instruction
tables.  Field values are GF(2^128) polynomial-basis values modulo
`x^128 + x^7 + x^2 + x + 1`; addition is XOR and multiplication is carry-less
multiplication reduced by that polynomial.  `lo` holds coefficients 0..63,
`hi` 64..127.  A 16-byte wire value is little-endian (`lo` first), so `x` is
`02 00 ... 00`, and `x^128` reduces to `87 00 ... 00`.

Indexes are host integers.  `encode(i) = g^i`, with `g = x`; native addresses
are field values but all index arithmetic below is checked `u32` addition.
An implementation MUST fault before an overflowing `fp + offset`, `base +
beta`, `pc + 1`, or `pc + 2` is converted to an index.  This checked-index
rule is a scalar-core profile decision: frozen Rust uses unchecked `u32` `+`
in release builds and therefore does not itself specify overflow behavior.

**Executable-runner behavior** is the frozen `Program::execute` algorithm.
It reads unwritten cells as zero, seeds cells 0 and 1 as written public input,
and accepts an equal repeat write but rejects a different repeat write.
These are not permission to expose an unwritten/zero distinction to a proof
consumer: final memory is padded with zeroes.

**Witness-generation convenience** is not an architectural instruction effect:
XOR/MUL back-solving, lazy reverse `g` lookup, deferred DEREF patching, and
batched JUMP inversion merely select a witness that satisfies the table.

**Compatibility profiles** are opt-in. `upstream-runner` reproduces the above
runner conveniences (including its unchecked index arithmetic). `strict-host`
is the default scalar profile and requires checked arithmetic, explicit memory
status, reverse-pointer lookup, and an external BLAKE3 service.

## State, halt, memory, and counts

The initial state is `(pc, fp) = (0, 0)` as indexes, i.e. `(g^0,g^0)` in
field form. Bytecode length `B` MUST be a power of two. Slot `B-1` is the
never-executed halt sentinel. A successful execution stops exactly when
`pc == B-1` and MUST also have `fp == 0`; otherwise it faults `bad_halt_state`.
Every non-JUMP instruction advances to `pc + 1` without changing `fp`.

Every operand memory access is counted, including a destination that is also
written and every three JUMP operands on both branch outcomes. Counts begin at
`g^0` and are multiplied by `g` per access; bytecode counts do the same for
each fetched instruction. Trace rows retain the *old* count. This is trace
data, not a replacement for a physical read protocol.

`write_once(a,v)` succeeds for an unwritten cell, succeeds idempotently for a
written cell with exactly `v`, and faults `write_conflict` for a different
value. It never silently overwrites. Unwritten reads produce zero in the
upstream runner; strict hosts return both `written` and `value`.

## Opcodes

All offsets are `u32`; `L(o)=fp+o` after checked addition.

| Opcode | Frozen scalar effect |
|---|---|
| XOR(a,b,c) | If the result is prewritten and exactly one input is unwritten, upstream may fill the missing input with `C XOR known`. Then it requires/writes `C=A XOR B`; accesses A, B, C; `pc+1`. |
| MUL(a,b,c) | Same shape, with `C=A*B`. Back-solving uses `C*known^-1` only if `known != 0`; otherwise `mul_backsolve_zero_divisor`. `inv(0)` is conventionally zero in the field implementation, but it MUST NOT authorize this deduction. |
| SET(o,k) | `write_once(L(o),k)`, one access, `pc+1`. |
| DEREF(alpha,beta,gamma,Cell) | `alpha` and `gamma` are frame-relative offsets: read pointer `P=L(alpha)`, require raw reverse lookup `P=encode(base)`, then touch target `a2=base+beta` and local counterpart `a3=L(gamma)`. `beta` is a pointer-relative target offset; it is not the PC increment. If both cells are written they must agree; if one is written fill the other; if neither is written, defer equality. It has three accesses and `pc+1`. |
| DEREF(...,Pc) | At pointer-derived target `a2=base+beta` (not `L(gamma)`), write `encode(pc+2)`; `gamma` still names the separately accessed local counterpart. This is not the misleading `pc+gamma` source comment. Three accesses and `pc+1`. |
| DEREF(...,Fp) | At pointer-derived target `a2=base+beta` (not `L(gamma)`), write `encode(fp)`; three accesses and `pc+1`. |
| JUMP(oc,od,of) | `oc`, `od`, and `of` are all frame-relative offsets: read `c=L(oc), d=L(od), f=L(of)` and make all three access events. If `c=0`, next `(pc,fp)=(pc+1,fp)`; otherwise the *values* `d` and `f` (not the offsets `od` and `of`) MUST each reverse-resolve to valid raw `g` powers and their indexes become next `(pc,fp)`. The witness fields are `b=[c!=0]`, `w=c^-1` for nonzero `c`, otherwise `b=w=0`. |
| BLAKE3(ins[4],cv,out,metadata) | Read four independently addressed input words, two consecutive CV words, and write two consecutive output words. Bytes and metadata are little-endian. Compression is an external/optional service in this scalar profile; the upstream witness uses flock. It makes eight memory accesses and `pc+1`. |

Deferred Cell equalities are resolved after execution to a fixpoint. A later
write to `a2` supplies `a3`; a later write only to `a3` does not reconcile and
conflicts with zero finalization. A component with no later write is materialized
as zero on both sides. Rows are patched with the reconciled values
but retain their original access counts. This is specifically upstream witness
construction; a strict live executor may hold the equality obligation instead
of prematurely writing zero.

## Explicit non-semantics

The currently compiled ISA has no active u32 arithmetic opcode. The u32 ADD,
MUL, and nonzero material in `misc/doc.tex` is inside `\iffalse`; neither
modular overflow nor checked overflow is frozen upstream. This project’s
checked-index policy must not be represented as an upstream ISA opcode.

The reference adapter and vectors live in
`docs/semantics/reference/`. They use hexadecimal little-endian integers for
field elements and classify expected faults instead of relying on panics.
