# Artifact manifest

## Frozen upstream target

```text
leanEthereum/leanVM-b
commit c308034ab78619b39a59d26f3dc60e7df5b52649
```

## Selected circuit

```text
name                       leanVM-b MinCore
boundary                   streamed value-level scalar opcode engine
field                      GF(2^128), modulus x^128+x^7+x^2+x+1
external data lanes        8-bit input, 8-bit output
implemented commands       XOR128, MUL128, SET128, NONZERO, STATUS, CLEAR
multiplier                 radix-1 LSB-first bitstream
explicit sequential state  273 bits
radix-1 direct step        128 AND2 + 131 XOR2 = 259 simple gates
Tiny Tapeout trial area    2x2, with 1x2 exploratory build recommended
```

## Proofs and checks

- Lean 4 source for GF8 multiplier equivalence, actual-width GHASH `xtime`,
  streaming transforms, address representation, write-once memory, simplified
  scalar refinement, DEREF reconciliation, and scoped optimality lower bounds.
- SymbiYosys harness for the parameterized eight-bit RTL multiplier.
- Exhaustive 65,536-pair GF8 executable comparison.
- 100,000 deterministic random GF128 comparisons against independent
  carry-less schoolbook multiplication and long reduction.
- 1,000 randomized cycle-model transactions with independent stalls and
  backpressure.
- Exact linear XOR-circuit enumeration proving the three-gate GHASH reduction
  tap minimum in the declared model.
- Cross-file interface and Tiny Tapeout metadata consistency checks.

## Local limitation

The workspace did not contain Lean/Lake, Icarus/Verilator, Yosys/OpenLane, or
SymbiYosys/Boolector, and outbound package installation was unavailable. The
included GitHub Actions workflow runs Lean compilation and HDL simulation on a
normal runner. `VALIDATION.txt` records every check executed locally.
