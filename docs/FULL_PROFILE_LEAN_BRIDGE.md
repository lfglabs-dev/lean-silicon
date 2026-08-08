# Canonical full-profile Lean bridge

`LeanVMBMinCore.FullProfile` is the first functional bridge from every LSC-1
scalar instruction class to canonical Lean primitives and the existing
atomic transaction lifecycle. It models host-owned memory/fetch/witness inputs
as explicit request data. SET/XOR/MUL decide writes with `Memory.writeOnce` and
`GHASH128.mul`; DEREF and JUMP call `ControlPrimitives`; BLAKE3 can only create
an external service request and accepts a response bound to the same transaction
and service identifiers.

The proved bridge is deliberately transport-independent. A decided result is
translated to `Transaction.Transition`, staged atomically, committed only by a
matching RETIRE, and discarded without commit by ABORT. Existing `Packet`
theorems establish envelope round trips and validation precedence. This PR does
not claim that SystemVerilog implements this Lean function.

This foundation does not yet encode the complete packet-profile guard surface.
In particular XOR/MUL currently express the forward decision over supplied
cells, not interpreter-compatible missing-operand back-solving; effective
addresses and DEREF pointer resolution arrive already prepared; and result CRC
is an opaque lifecycle binding. Those are required edges below, not assumptions
silently promoted to a full-profile equivalence claim.

## Remaining theorem graph

1. Extend binary requests with presence/profile and inverse proposals, prove
   XOR/MUL back-solving and all write/alias fault quadrants against the canonical
   memory model, and relate prepared DEREF/JUMP inputs to checked packet fields.
2. Define a byte-exact Lean codec for every fixed full-profile payload and prove
   decode/encode and malformed-field precedence into `FullProfile.Instruction`.
3. Define an independent cycle transition system for
   `asic_core/rtl/lsc1_packet_frontend.sv`, including receive/transmit buffers,
   backpressure, reset and ABORT dominance.
4. Prove accepted-frame refinement from that cycle system to `FullProfile.decide`
   for SET/XOR/MUL/DEREF/JUMP and to `serviceRequired` for BLAKE3.
5. Prove response serialization and staged-result CRC correspondence, then lift
   `staged_result_matching_retire_commits` to the cycle system's DONE edge.
6. Bind the independent cycle system to authored SV with unbounded formal
   correspondence (or explicitly bounded results where induction cannot close).

Until all six edges exist, the correct claim is a canonical functional and
transaction-lifecycle foundation, not full Lean-to-RTL equivalence.
