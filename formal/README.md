# RTL formal check

Run from this directory:

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

The bound is 32 global formal steps. The harness toggles its generated clock on
each global step, so this covers more than the eleven positive edges needed to
reset, load A, consume all eight B bits, and exercise the result assertion. A
cover point is placed beside the assertion to make reachability visible in the
formal report. This is a bounded equivalence check, not an inductive proof of
an unconstrained stream protocol.
