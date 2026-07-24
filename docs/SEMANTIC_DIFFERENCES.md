# Semantic differences and profile decisions

Comparison baseline: `leanEthereum/leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649`.

| Topic | Frozen upstream evidence | Scalar-core profile |
|---|---|---|
| Address arithmetic | Interpreter uses `u32` additions such as `fp + a`; overflow is not a stable release-mode fault. | Checked `u32` arithmetic; fault before wrap. |
| Unwritten reads | Runner helper returns zero. | Return `(written,value)` from memory; only runner-compatibility maps unwritten to zero. |
| XOR/MUL deduction | Runner fills one missing input when C is set; MUL asserts nonzero divisor. | Compatibility-only witness selection. Strict execution must request/commit an explicit value; zero divisor faults if deduction requested. |
| Field inverse zero | `F128::inv()` returns zero through exponentiation. | `inverse(0)=0` is an algebra-library convention, not a division permission. |
| DEREF Cell both unwritten | Upstream records a row then patches it after execution, ultimately to a later value or zero. | Preserve a deferred equality obligation; only materialize zero at finalization. |
| DEREF Pc | `execute.rs` writes `gpow[pc + 2]`; table constraint is `g²*pc`. | Normative `encode(pc+2)`. |
| JUMP | Reads/counts c,d,f before deciding; taken d/f are raw field values reverse-looked-up afterwards. | Same, with explicit reverse-lookup failures and no integer reinterpretation of raw field bits. |
| Write-once | Equal repeat write accepted; differing repeat panics. | Same outcome, structured `write_conflict` fault. |
| Trace patching | Deferred DEREF row values and all nonzero JUMP inverses are patched after the walk. | Trace sink accepts patches/finalization; retirement events are not immutable final proofs. |
| Halt | Runner loops until last bytecode slot and asserts `(pc,fp)==(B-1,0)`; layout fixes same boundary. | Same exact sentinel and final state. |
| BLAKE3 | Runner computes it and flock proves it. | Explicit external service boundary; no claim that M0 implements it. |
| u32 arithmetic ISA | Deferred TeX text is disabled; no current opcode. | No added u32 opcode. Checked arithmetic applies only to host indexes. |

The existing `docs/FULL_CORE.md` is an implementation sketch, not a substitute
for this frozen contract. In particular, its use of ordinary indices is valid
only with `encode`/reverse-lookup boundaries and the checked-index profile
above.
