# RTL formal check

The required M0 finite check, run from this directory, is:

```sh
sby -f gf8_mul.sby
```

The harness quantifies over every pair of 8-bit operands. It drives the exact
generic RTL used by the 128-bit specialization and exhaustively checks the
bounded transaction that the result after eight accepted multiplier bits equals an independent schoolbook carry-less
product reduced modulo `x^8 + x^4 + x^3 + x + 1`.

The Lean proof in `lean/LeanVMBMinCore/GF8.lean` checks the same simplified
algorithm through a separate formalization. This creates two independent proof
paths: Lean bit-blasting and RTL model checking.

The finite SAT script checks frames 0 through 22. The harness toggles its
generated clock on each global step; its assertion first evaluates at frame 21,
after the reset, A-load, and eight multiplier-bit positive edges. The script
does not alter the RTL or assertion. It removes only the non-constraining cover
cell because the Yosys SAT backend cannot import cover cells. `SUCCESS` means
there is no counterexample through this finite bound; it is a bounded check,
never an unbounded proof of an unconstrained stream protocol.

The required SBY check uses ABC's `bmc3` engine, preserves the assertion, and
passes at depth 32. The separate `yosys -s gf8_mul_bounded.ys` script is a
finite SAT cross-check through frame 22; it removes only the non-constraining
cover cell because the Yosys SAT backend cannot import cover cells.

The historical cvc5 baseline reached frame 21 but did not finish within its
recorded cap. `gf8_mul_depth22_z3.sby` and
`gf8_mul_bounded_boolector.sby` are diagnostic reproductions of, respectively,
the same frame-21 timeout and Boolector's incompatibility with SBY's universal
`anyconst` encoding. Use the versioned driver under `results/` to reproduce all
of these outcomes and their time limits.
