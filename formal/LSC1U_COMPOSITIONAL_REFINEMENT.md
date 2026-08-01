# LSC-1u compositional cycle refinement

This milestone closes the authored LSC-1u controller's MUL control and
arithmetic path without putting two copies of the 256-bit datapath into one
induction problem.

## Partition

`lsc1u_compositional_refinement.sby` checks the shipped `lsc1u_core` against
an independent cycle transition model.  It covers opcode decode/fault, XOR,
SET, `MUL_A`, `MUL_B`, `MUL_BITS`, `MUL_TX`, each pending output beat, and
final retirement.  At the multiplier module boundary it elaborates
`gf128_mul_controller_boundary_formal.sv`, a conservative arbitrary-result
contract.  Because control never branches on multiplier data, this retains
the output-mux obligation while removing 384 irrelevant arithmetic state bits.

`gf128_mul_stream_refinement.sby` then checks the production
`src/gf128_mul_bitstream.sv` and `src/gf2n_mul_bitstream.sv` against the same
mathematical recurrence.  Sixteen little-endian A bytes are accepted, 128
symbolic B bits update `product := product XOR power` when set and
`power := x * power mod (x^128 + x^7 + x^2 + x + 1)`, and sixteen result bytes
are emitted least-significant first.

The shipped modules expose retained state and multiplier control only when
the `FORMAL` preprocessor symbol is defined.  These observation ports are
absent from ordinary synthesis and simulation builds and have no behavioral
fan-in; they let PDR state the inductive composition relation directly.

Both safety tasks are unbounded PDR proofs.  The multiplier cover reaches a
complete accepted stream; the pre-existing LSC-1u reachability task reaches
MUL retirement at depth 178. Partitioning is a solver-performance choice,
not an environment assumption: every concrete result is included by the
controller boundary, while the second proof establishes the production
multiplier's stronger arithmetic behavior.

## Environment and backpressure

The controller proof leaves `rx_valid`, `tx_ready`, `ena`, `rst_n`, and all
input bytes free on every cycle after the required initial reset.  Therefore
TX_READY may arrive immediately or after any finite delay.  A pending output
remains stable and no subsequent input is accepted until the beat fires.
`ena` may pause any receive, bit-processing, or transmit state.  Reset may
occur in any state and cancels both controller and multiplier state.

The multiplier proof permits arbitrary pauses between accepted A bytes, B
bits, and result shifts, and arbitrary reset/abort timing.  Its phase ordering
is the public multiplier protocol, not an additional controller assumption.
No fairness assumption is made, so the claims are safety and conditional
completion, not eventual completion when a peer stalls forever.

## Mutation sensitivity

`check_mutations.py` requires terminal counterexamples for a shortened
`MUL_A` transition, misrouted `mul_bit_valid`, inverted result-shift control,
the wrong MUL output mux input, and OR in place of XOR in the production
accumulator.  These complement the existing retirement, stall, enable, XOR,
SET, serialization, and generic arithmetic mutations.

## Remaining release boundary

This is full cycle equivalence for the authored `lsc1u_core` module, composed
with its production GF(2^128) multiplier.  It does not yet connect the Lean
functional model to RTL, prove the Tiny Tapeout wrapper or packet LSC-1
controller, prove liveness under unfair ready/valid behavior, or establish
sequential equivalence from RTL to the synthesized release netlist.
