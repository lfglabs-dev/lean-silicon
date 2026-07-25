# Validation record

## Executed in this workspace

Command:

```sh
python -m unittest discover -s sim -v
```

Result: ten tests passed.

Coverage:

- exhaustive `GF(2^8)` serial-vs-polynomial multiplication: 65,536 pairs;
- 100,000 deterministic random `GF(2^128)` pairs;
- multiplication identities and reduction boundary behavior;
- command-level XOR, MUL, SET, NONZERO, STATUS, CLEAR, and error behavior;
- exact no-stall cycle counts: XOR 33, MUL 161, SET 17, NONZERO 17,
  STATUS 5, CLEAR 1;
- 1,000 randomized cycle-model transactions with independent receive stalls and
  transmit backpressure;
- unknown-command error behavior.

The structural SystemVerilog smoke checker also reports balanced delimiters and
block constructs for all RTL, testbench, and formal-harness files.

## Not executable in this workspace

The environment lacked:

- Lean / Lake;
- Icarus Verilog or Verilator;
- Yosys / OpenLane;
- SymbiYosys / Boolector.

Package download and apt access were unavailable. Therefore the following must
run in CI or a normal development machine:

```sh
cd lean && lake build
cd test && make sim
cd formal && sby -f gf8_mul.sby
```

The project deliberately includes no proof placeholders or global axiom declarations. CI also checks for any
future `sorry`, `admit`, or `axiom` occurrence.

## Independence of arithmetic checks

The checks below provide finite or model-scoped evidence only.  They do not
connect the full LSC-1 SV controller to the frozen ISA and do not establish
RTL-to-netlist equivalence; see `docs/PROOF_BOUNDARIES.md`.

Three distinct descriptions are present:

1. bit-streamed RTL transition;
2. Python carry-less schoolbook product with polynomial long reduction;
3. Lean `GF(2^8)` bit-vector model checked by `bv_decide`.

The SymbiYosys harness contains a fourth, local schoolbook/reduction function
for the eight-bit RTL specialization.
