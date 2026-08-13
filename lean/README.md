# Lean 4 proof model

Pinned toolchain: `leanprover/lean4:v4.32.1`.

Build:

```sh
lake build
lake build LeanVMBMinCore
```

Modules:

- `Packet.lean` — executable parsed request/response envelopes, ordered request
  validation, protocol-size-bounded checksum-parametric round trips, and
  concrete codec examples. Byte-stream reception and per-opcode payload schemas
  remain outside this model. The stable checksum seam is intended for a later
  proof that instantiates the protocol's CRC-32 implementation without changing
  packet consumers.
- `FullProfilePayload.lean` — byte-exact decoding of canonical 81-byte DEREF
  and 103-byte JUMP payloads into raw packet preparation, with explicit
  malformed-field and mutation-sensitive witnesses. The absent request-side
  result checksum is initialized to zero rather than supplied by a caller.
- `AcceptedDeref.lean` — canonical v1 envelope acceptance using the reflected
  IEEE CRC-32, exact DEREF 0x04--0x06 dispatch, refinement to
  `preparedDerefDecision`, and result/RETIRE checksum derivation from the actual
  effect payload. Its executable witnesses cover every mode and both profiles'
  four Cell presence quadrants.
- `AcceptedJump.lean` — canonical JUMP envelope acceptance, exact 103-byte
  decoding into `preparedJumpDecision`, effect-derived RESULT checksum,
  exactly-once matching retirement, non-vacuity, and mutation witnesses.
- `AcceptedSequence.lean` — arbitrary finite state-dependent legal sequences
  mixing DEREF, JUMP, SET, XOR, and MUL. Every item carries its complete
  accepted-frame/decision premise and v1-representable current/next control;
  the sequence theorem preserves acceptance
  order, emits one byte-exact CRC-protected RESULT receipt per item, accepts
  the matching RETIRE exactly once, rejects its replay, and finishes idle.
- `Transaction.lean` — pure staging/retirement state model with atomic staging,
  v1 current-state index bounds, abort preservation, matching commit, mismatch
  rejection, reset, and exactly-once retirement theorems. Arithmetic and
  control instruction models provide already-validated proposed transitions
  through this interface.
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
- `Memory.lean` — 128-bit write-once memory success, conflict, idempotence, and
  different-address commutation lemmas.
- `Deref.lean` — faithful simplified `DEREF Cell` reconciliation: equality,
  conflict, either-direction fill, and deferred both-unwritten behavior.
- `ControlPrimitives.lean` — strict-host pure semantics for checked signed
  DEREF address preparation and Cell/Pc/Fp effects, fetch-free JUMP control
  updates, and host-proposed GF(2^128) inverse-witness acceptance.
- `ISA.lean` — simplified XOR/MUL/SET/JUMP transition refinement; hardware MUL
  uses the serial implementation while the specification uses the independent
  polynomial implementation.
- `Optimality.lean` — channel-capacity cycle lower bounds, restricted gate
  lower bounds, and the 273-bit state lower bound under stated requirements.
- `RTLRefinement.lean`, `RTLTraceRefinement.lean`, and
  `RTLTransactionRefinement.lean` — the retained LSC-1u
  SET/XOR/MUL boundary, first for one transaction and then as an inductive
  payload-valid arbitrary-finite-trace invariant covering acceptance, ordered
  operand bytes with SET/XOR output interleaving, collapsed MUL execution, all
  sixteen response-byte handshakes with MUL refill bubbles, retirement,
  backpressure, faults,
  reset, and disable. The transaction bridge relates the ordered retirement
  list to repeated functional STAGE/RETIRE steps and returns the lifecycle to
  IDLE. Exact source hashes and the non-SV-import boundary are in
  `docs/P1B_ASSURANCE_SCOPE.md` and `docs/P1C_TRANSACTION_BRIDGE.md`.

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
