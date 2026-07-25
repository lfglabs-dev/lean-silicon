# Lean 4 proof model

Pinned toolchain: `leanprover/lean4:v4.32.1`.

Build:

```sh
lake build
lake build LeanVMBMinCore
```

Modules:

- `GHASH128.lean` proves the real 128-bit `xtime` tap equations, reduction boundary, and XOR linearity.
- `GF8.lean` — two independent executable definitions of multiplication in
  `GF(2^8)` and exhaustive `bv_decide` equivalence.
- `Stream.lean` — correctness of the interleaved XOR byte protocol and the
  optimized SET/NONZERO transforms.
- `Address.lean` — abstract representation relation between integer indices and
  multiplicative field-address encodings.
- `CheckedIndex.lean` — executable `u32`-bounded host-index addition plus
  success, overflow, local-address, and next-PC lemmas for the strict scalar
  profile. It intentionally does not refine the unmerged full-core RTL.
- `Memory.lean` — write-once memory success, conflict, idempotence, and
  different-address commutation lemmas.
- `Deref.lean` — faithful simplified `DEREF Cell` reconciliation: equality,
  conflict, either-direction fill, and deferred both-unwritten behavior.
- `ISA.lean` — simplified XOR/MUL/SET/JUMP transition refinement; hardware MUL
  uses the serial implementation while the specification uses the independent
  polynomial implementation.
- `Optimality.lean` — channel-capacity cycle lower bounds, restricted gate
  lower bounds, and the 273-bit state lower bound under stated requirements.

Both commands build the same root module. The project gate rejects source
occurrences of `sorry`, `admit`, and `axiom`; the evidence record names the
exact parent, tree, and tested head so a later evidence-only commit cannot be
misrepresented as testing itself.
The address theorem is intentionally parametric over an `AddressEncoding`
structure carrying the law `encode(i+j)=encode(i)*encode(j)`; instantiating that
structure with the actual GF(2^128) generator is a later proof milestone.

These are functional-model theorems, not a theorem about the full authored
SystemVerilog controller or its synthesized netlist.  `GF8.lean` uses
`native_decide` only for GF(2^8); it is not the production GF(2^128)
multiplier proof.  The optimality results are scoped arithmetic lower bounds
under their stated assumptions, never global implementation-optimality claims.
See `docs/PROOF_BOUNDARIES.md`.
