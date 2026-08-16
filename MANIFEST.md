# Artifact manifest

## Frozen upstream target

```text
leanEthereum/leanVM-b
commit c308034ab78619b39a59d26f3dc60e7df5b52649
```

## LSC-1 boundary

```text
name                       leanSilicon LSC-1
boundary                   host-prepared, one-instruction scalar transaction
field                      GF(2^128), modulus x^128+x^7+x^2+x+1
physical transport         8-bit input, 8-bit output, 8-bit ready/valid/status
current implemented seed   XOR128, MUL128, SET128, NONZERO, STATUS, CLEAR
multiplier                 radix-1 LSB-first bitstream
explicit sequential state  273 bits
radix-1 direct step        128 AND2 + 131 XOR2 = 259 simple gates
Tiny Tapeout top           lean_silicon_lsc1
```

The current seed is not the LSC-1 packet executor.  The Mac owns compilation,
program and VM memory, hints/witnesses, pointer/deferred-equality state,
inversion assistance, BLAKE3, traces, and proofs.  The ASIC has no autonomous
fetch, general memory controller, inverter, BLAKE3 datapath, SDRAM, or USB
controller.  `docs/ROADMAP.md` is authoritative for completion criteria.

## Proofs and checks

These entries are layer-specific evidence, not a project-level formal
verification claim.  `docs/PROOF_BOUNDARIES.md` identifies the missing
frozen-ISA/controller and RTL/netlist correspondence bridges.

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
- Cross-file interface, declared-source, packet-marker, and Tiny Tapeout
  metadata consistency checks.
- Immutable LSC-1 conformance corpus with stable case fingerprints, complete
  retirement records, byte-lane lifecycle cases, and a Rust differential
  adapter compiled against the exact frozen upstream source.

## Local limitation

Historical result directories record the environment available when they were
produced; they are not LSC-1 validation claims. Current CI runs Lean
compilation, HDL simulation, formal checking, and LSC-1 synthesis.

## LSC1-08 scalar RESULT serialization receipt

`results/lsc1-08-scalar-result-stream/yosys-structure.json` records paired
generic Yosys process-lowering statistics from exact base
`008c2f57a2843e0213004c611a9e4edd1dc88e85` and the bounded scalar RESULT
streaming slice.  It is registered-state/structure evidence only and makes no
PPA, physical-design, FPGA, release, or hardware claim.
