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

`RTLTraceRefinement.lean` models acceptance, a collapsed execution phase,
stable RETIRE backpressure, exactly-once successful retirement to IDLE,
invalid-opcode fault response, reset, disable, and ignored inputs while busy.
Its invariant proves that retired commands form the accepted history in order
and that every output is the Lean mathematical result for the corresponding
SET, XOR, or production-polynomial MUL.  Induction proves this for every finite
interaction list, so it is not limited to a single transaction.

Focused executable examples witness two successful transactions with a stalled
RETIRE, MUL acceptance, and the invalid-opcode fault/acknowledgement path.  The
general `backpressure_stable`, `reset_clears`, and `disable_clears` theorems
guard the most important stutter/abort regressions.

## Preserved boundary

This is a sound composition at the existing retained boundary, not a new
SystemVerilog importer.  Lean does not inspect the SV AST.  Byte counters and
the 128 MUL bit cycles are collapsed into one `execute` transition; the exact
unchanged modules are checked separately by the pinned unbounded SBY lanes.
Therefore this result does **not** prove the packet frontend, full LSC-1 ISA,
fair-progress liveness, RTL-to-netlist equivalence, or that the two proof
checkers form one kernel theorem.  Reset/disable intentionally erase proof
history because the shipped LSC-1u block has no architectural committed store.

No `sorry`, `admit`, new `axiom`, `native_decide`, or unsafe declaration is
introduced by this lane.
