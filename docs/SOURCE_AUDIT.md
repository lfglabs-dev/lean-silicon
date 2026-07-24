# leanVM-b source audit for hardware implementation

## Freeze

The current design analysis targets:

```text
repository: leanEthereum/leanVM-b
commit:     c308034ab78619b39a59d26f3dc60e7df5b52649
```

Relevant files:

- `crates/lean_vm/src/cpu/isa.rs`
- `crates/lean_vm/src/cpu/execute.rs`
- `crates/lean_vm/src/cpu/mod.rs`
- `crates/primitives/src/field/gf2_128.rs`
- `misc/doc.tex`

## Confirmed hardware-relevant facts

- Operand offsets, initial PC, and initial FP are `u32` in the Rust model.
- Memory exponents are constrained to 16 through 32.
- `F128` bit `i` is polynomial coefficient `x^i`.
- Canonical bytes are little-endian.
- Generator `g` is `x`; fixed multiplication by `g` is shift plus `0x87` fold.
- The execution interpreter uses ordinary integer indices and separately keeps
  `g^i` encodings and a reverse map.

## Semantics that need explicit hardware treatment

### XOR/MUL deduction

If output C is already written and exactly one input is unwritten, execution
back-solves the missing input before recomputing C. MUL deduction requires field
inversion and rejects a zero known operand.

This behavior is materially larger than a forward-only ALU and is a strong
reason to expose an external quotient service in the first full system.

### DEREF is a reconciliation relation

`DEREF Cell` is not merely a load or store. It equates two write-once cells,
fills the missing side, checks equality when both exist, and defers the case
where neither exists.

### Pointer resolution

DEREF and taken JUMP convert raw `g^i` field values back into integer indices.
The Rust runner uses a reverse map, not a general discrete-log computation.
Hardware should request resolution from the host.

### Access accounting

JUMP reads and access-counts condition, destination PC, and destination FP even
when the branch is not taken. A hardware trace generator must preserve this if
it intends to reproduce current proof tables.

## Potential specification inconsistency

The `DerefMode` source comment describes the PC source as a return address
`pc + gamma`, while the current interpreter writes `g^(pc + 2)` in Pc mode.
The prose document also describes the fixed `pc + 2` call convention.

The first hardware model should follow the executable interpreter and record
this issue upstream before a compatibility claim is made.

## Consequence

A complete ISA should be versioned by exact commit, and its normative semantics
should be generated from or tested against both:

1. the prose/formal instruction specification;
2. the executable Rust transition behavior.
