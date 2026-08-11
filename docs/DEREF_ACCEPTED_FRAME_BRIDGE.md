# DEREF accepted-frame bridge

This lane closes the request/result checksum seam for DEREF opcodes `0x04`--`0x06`.

The dedicated `reachability` task now drives a byte-exact valid `DEREF_CELL`
envelope into the production `lsc1_packet_frontend`, checks and drains every
byte of its 35-byte RESULT payload and envelope, independently accumulates the
payload CRC-32 from those emitted bytes, and uses that value in a matching
RETIRE envelope.  The assertion lane also proves that `tx_valid` is low in the
first state after envelope beat 43, excluding a 45th RESULT transfer.  Its
cover requires the expected staged effect and exactly
one `pc`/`fp`/`retire_seq` commit with one `done_pulse`, then reaches a
quiescent cycle where both ghost counters equal one and `done_pulse` is low.
Before the matching RETIRE completion, assertions keep committed `pc` and `fp`
at their reset values so the staged effect cannot become architecturally
visible early.
Cycle-accurate RTL simulation, with reset released away from a sampling edge,
derives request acceptance at cycle 92 and the first completion at cycle 2784.
The formal harness requires the
same single sampled reset edge; its prior `reset_seen <= past_valid` startup
inserted an unintended second reset sample, placing the cover at step 2788
while the configured depth checked only steps 0--2787.  With the startup
contract aligned, the quiescent cover is sampled at formal step 2787, so the
formal task uses depth 2788 (SymbiYosys checks steps `0..depth-1`), and a
depth-2787 mutant must report an unreached cover.  This is a finite witness
through step 2787, not an unbounded liveness claim.

The separate depth-20 `safety` task retains arbitrary traffic and backpressure.
The depth-2788 `reachability` task remains the end-to-end claim and must still
reach the final quiescent cover.  Its former monolithic `witness_safety` task is
split at observable lifecycle boundaries, without adding assumptions or
changing the byte-exact environment: `accepted_result_{reachability,safety}`
checks the complete RESULT and stable staged CRC at depth 2767,
`matching_retire_{reachability,safety}` checks the matching RETIRE commit at
depth 2786, and `post_retire_safety` checks the following exactly-once and
quiescent state at depth 2788.  Each reachability task is a non-vacuity mate for
its safety task; the same end-to-end harness prefix reaches every checkpoint.
The tasks intentionally use different engines: BTOR/`btormc` checks the one
long concrete cover and the same-depth witness assertions and their mutants as
bit-vector transition systems, while SMTBMC/Boolector is kept
only for the shallow arbitrary-traffic safety task.  This avoids 2,788
incremental SMT queries for a witness whose cycle is already fixed by the
byte-exact environment; it does not change the depth, assumptions, assertions,
or cover condition.
Critical mutants run only in the first sub-goal that can observe them.  RESULT
envelope/CRC and early-publication mutants use `accepted_result_safety`, stage
retention uses `matching_retire_safety`, and a retained completion pulse uses
`post_retire_safety`.  A pristine baseline for each sub-goal must pass before
its mutants run.  The mutations remain individual (not combined), and only a
completed assertion failure counts as a kill; missing covers, timeouts, tool
errors, or surviving mutants fail closed.  Every solver subprocess has a
540-second timeout, strictly inside the 600-second outer bound.

The executable trace now records the intermediate boundaries as well as the
unchanged endpoints: RESULT beat 43 transfers at cycle 2763, matching RETIRE is
accepted at cycle 2783, and the first completion remains cycle 2784.  Accounting
for registered capture and formal sampling places the stable RESULT checkpoint
at the last step of depth 2767, the matching commit at the last step of depth
2786, and final quiescence at the last step of depth 2788.  The focused
below-bound mutation checks all three reachability tasks one step lower.
`LeanVMBMinCore.AcceptedDeref.accept` validates the complete asymmetric LSC-1 v1
request envelope with the production reflected IEEE CRC-32, then decodes exactly
81 payload bytes. No result checksum is accepted from the host or theorem caller.
For a successful decision, `transition` derives the RETIRE checksum from
`crc32 (effectResultPayload effect)`.

The Lean acceptance theorem is functional and canonical: accepted Cell, Pc, and
Fp frames feed the existing `preparedDerefDecision` without a second semantic
path. Existing preparation/effect theorems cover pointer verification,
`base + beta`, `pc + 2`, FP encoding, Cell reconciliation and deferred equality;
the new accepted witnesses establish reachability of every opcode and all four
Cell presence quadrants in both profile encodings.

The `FORMAL_DEREF_BRIDGE` checker is instantiated inside the exact authored
`asic_core/rtl/lsc1_packet_frontend.sv`. Its safety check is explicitly bounded
to 20 cycles over arbitrary RX/TX choices: stalled-output stability,
reset/ABORT dominance, staged metadata stability, matching RETIRE, and
exactly-once retirement. Those RETIRE assertions are bounded safety checks, not
reachability claims. The checker also carries a ghost retirement-history
invariant: reset establishes sequence zero and only an accepted matching RETIRE
advances it. This is an asserted reachable-state relation, not an environment
assumption.

A separate cover task establishes the complete byte-exact witness. It drives
all 91 accepted request-envelope bytes (81-byte payload, profile byte 1,
distinct addresses 0/1/2, pointer witness 1, nonzero transaction id and frame
pointer, reflected IEEE request CRC-32 `0x92b67fa9`), drains the 44-byte RESULT
envelope, and supplies the 18-byte
RETIRE envelope. The RETIRE payload uses the independently accumulated RESULT
payload CRC-32 `0x70840564`; the checker never assumes that value or obtains it
from `staged_result_crc`.

No unbounded RTL or netlist equivalence is claimed. Simulation and differential
reachability are likewise finite. They include result/RETIRE CRC behavior and kill focused
pointer-bypass, address-source, PC increment, profile, CRC, canonical-cell,
same-edge ABORT, result-byte and duplicate-retirement mutations.

This is a full-profile non-release assurance lane. The residual gap is an
unbounded proof of the exact frontend transition system (or an independently
checked sequential-equivalence certificate). It does not claim a physical
netlist proof or BLAKE3 service refinement.
