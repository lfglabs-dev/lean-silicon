# P1-B inductive assurance scope

This lane proves an arbitrary-finite-trace invariant for the implemented
LSC-1u SET/XOR/MUL profile at the retained command/result boundary.  The source
base is `f10be11b05a4e798a962e13c61de2eff8cd5ddec` (`origin/main` when the lane
was created).  The exact unchanged implementation/proof inputs are:

| File | SHA-256 at the pinned base |
| --- | --- |
| `src/lsc1u_core.sv` | `f1c653ffe7d84b594bd43950d639f523b38b086e89772f4dab7f1c33bfcd1fb0` |
| `src/gf128_mul_bitstream.sv` | `1f50cc6a666864a2e8daa107a0d28a780394a82dff2444d9674e9f02ebc5a5a2` |
| `formal/lsc1u_compositional_refinement.sby` | `06461ceed820f60c504c5e749c06d88e161d3cb866314091a8d6ddc332c62337` |
| `formal/lsc1u_compositional_refinement_formal.sv` | `55435fff86913d25386c8aee0695f2c9d0dbf16350955983125eeca70871a2b3` |
| `formal/gf128_mul_stream_refinement.sby` | `29baf77c22316e7a56b0ccd4ccfabd9651b9305c19d5fc36982aa7a489958740` |
| `formal/gf128_mul_stream_refinement_formal.sv` | `bb5df51df50233314d72eaa705fa5cdc809c472585522577b1cdd916f03c0c84` |
| `lean/LeanVMBMinCore/RTLRefinement.lean` | `19c92b03aae729a778d27875943fea234fe6e0fb9c75b201d9065404c13bf16e` |

`RTLTraceRefinement.lean` models acceptance, every operand byte in its RTL
order, the required SET/XOR receive/result-transfer interleaving, a collapsed
MUL execution phase, all sixteen least-significant-byte-first response transfers, stable per-byte
backpressure, the mandatory MUL not-valid refill cycle between output bytes,
exactly-once successful retirement to IDLE after transfer 16,
invalid-opcode fault response, reset, disable, and ignored inputs while busy.
Its invariant proves that retired commands form the accepted history in order
and that every output is the Lean mathematical result for the corresponding
SET, XOR, or production-polynomial MUL. `ValidTrace` binds every receive event
to the corresponding byte of the accepted transaction; induction proves the
invariant for every finite payload-valid interaction list, so it is not limited
to a single transaction.

Focused examples witness transaction acceptance, the payload-byte validity
binding, and an exactly-once final response retirement. The general
`backpressure_stable`, `reset_aborts`, and `disable_aborts` theorems guard the
most important stutter/abort regressions. Aborts drop only an outstanding
transaction; already retired ghost history remains visible across epochs.

## Preserved boundary

This is a sound composition at the existing retained boundary, not a new
SystemVerilog importer. Lean does not inspect the SV AST. Payload and response
transfers are retained byte-for-byte; only MUL's internal bit cycles are
collapsed into one `execute` transition. The exact
unchanged modules are checked separately by the pinned unbounded SBY lanes.
Therefore this result does **not** prove the packet frontend, full LSC-1 ISA,
fair-progress liveness, RTL-to-netlist equivalence, or that the two proof
checkers form one kernel theorem. Ghost history is observational proof state,
not architectural storage in the shipped block.

No `sorry`, `admit`, new `axiom`, `native_decide`, or unsafe declaration is
introduced by this lane.
