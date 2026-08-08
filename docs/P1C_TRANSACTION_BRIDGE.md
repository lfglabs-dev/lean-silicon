# P1-C retained RTL/transaction bridge

This lane adds the smallest missing common relation between the existing
byte-accurate LSC-1u trace model and the existing functional transaction
lifecycle. The source base is current `main` at
`c5003f34e70599eb3409b520b19fb8ced6e11968`.

## Pinned unchanged inputs

| Input | SHA-256 |
| --- | --- |
| `src/lsc1u_core.sv` | `f1c653ffe7d84b594bd43950d639f523b38b086e89772f4dab7f1c33bfcd1fb0` |
| `src/gf128_mul_bitstream.sv` | `1f50cc6a666864a2e8daa107a0d28a780394a82dff2444d9674e9f02ebc5a5a2` |
| `formal/lsc1u_compositional_refinement.sby` | `06461ceed820f60c504c5e749c06d88e161d3cb866314091a8d6ddc332c62337` |
| `formal/lsc1u_compositional_refinement_formal.sv` | `55435fff86913d25386c8aee0695f2c9d0dbf16350955983125eeca70871a2b3` |
| `formal/gf128_mul_stream_refinement.sby` | `29baf77c22316e7a56b0ccd4ccfabd9651b9305c19d5fc36982aa7a489958740` |
| `formal/gf128_mul_stream_refinement_formal.sv` | `bb5df51df50233314d72eaa705fa5cdc809c472585522577b1cdd916f03c0c84` |
| `lean/LeanVMBMinCore/RTLTraceRefinement.lean` | `f9854c438b805f33db14c00ee87d054ec48bd0102aaf2a29f10fe1d8d2f83218` |
| `lean/LeanVMBMinCore/Transaction.lean` | `a81918a95c1152b8aa57d132dd9fdc5b0d63843ca22dfdbd5c7ffb2c0e6e858b` |

Lean is pinned by `lean/lean-toolchain` to
`leanprover/lean4:v4.32.1`. Formal jobs use the repository SBY engines and CI's
pinned `YosysHQ/setup-oss-cad-suite` action.

## Claim

`RTLTransactionRefinement.coupled_finite_trace_refines` is the central
prefix-sensitive theorem. It quantifies over arbitrary finite retained
interaction traces and maintains a product of retained RTL state and the
functional `Transaction.Model` after every event. Accepted commands atomically
STAGE, the final ordered response beat performs matching RETIRE, reset invokes
functional reset, and `ena = 0` invokes functional abort. Its invariant also
retains the exact ordered arithmetic-result history. The companion theorem
`finite_sequence_refines` projects completed transactions into an arbitrary
finite command sequence.

`ValidTrace` binds every receive to the correct operand byte. The relation
requires the command sequence to equal the RTL trace's ordered retirement
history. `ValidSequence` checks each functional STAGE at the state where it
occurs. The conclusion gives ordered exact SET/XOR/GHASH-MUL results and a
functional IDLE state after every matching RETIRE.

Supporting theorems pin the raw `0x01`/`0x02`/`0x03` decoder and `0xe0` fault
precedence, one-command acceptance/staging/retirement, TX backpressure
stutter, and reset/disable cleanup. General Lean witnesses reach synchronized
acceptance and enable-disable abort; a concrete example reaches SET retirement
and another theorem rejects a `retired = false` lifecycle mutation. The
existing formal
mutation gate terminal-fails result mutations (`xor_result`, `set_result`,
`gf128_mul_accumulate`, `lsc1u_mul_output_mux`) and lifecycle mutations
(`xor_retirement_lane`, `lsc1u_enable_multiplier_abort`, `stall_stability`).

## Assumptions and residual boundary

The host supplies the transaction identifier and complete operand ghost value
at the retained boundary; `ValidTrace` checks the subsequently received bytes
against it. Functional commands must remain within the transaction model's
16-bit current-index limit. No fairness is assumed, so infinite backpressure
has no liveness claim. MUL bit cycles remain composed through the separately
checked unbounded controller and multiplier SBY proofs.

Lean does not parse SystemVerilog and the SBY proofs do not emit a Lean proof
certificate. This remains a two-checker composition at the pinned retained
module boundary. It does not cover the packet frontend, full LSC-1 ISA,
wrapper/netlist equivalence, timing/physical behavior, or silicon.

No `sorry`, `admit`, new axiom, unsafe declaration, or `native_decide` is used
by this lane.
