# Canonical full-profile Lean bridge

`LeanVMBMinCore.FullProfile` is the first functional bridge from every LSC-1
scalar instruction class to canonical Lean primitives and the existing
atomic transaction lifecycle. It models host-owned memory/fetch/witness inputs
as explicit request data. SET/XOR/MUL decide writes with `Memory.writeOnce` and
`GHASH128.mul`; DEREF and JUMP call `ControlPrimitives`; BLAKE3 can only create
an external service request and accepts a response bound to the same transaction
and endpoint-assigned monotone service identifier. Its request type fixes the
compression shape at four message words, two chaining-value words, and sixteen
metadata bytes, so malformed arities are not representable.

The service request retains the host-supplied memory view across suspension.
Both returned digest words pass through `Memory.writeOnce`; either collision is
proved to fault, so external service ownership does not bypass canonical memory
policy or imply that the endpoint computed BLAKE3.

The controller validates and retains the next control state before publishing a
service request. Its service lifecycle is linear: exactly one response can be
consumed only from a live pending state, and consumption, ABORT, or reset returns
to idle. A wrongly bound response faults while retaining the pending request so
the correctly bound response can still arrive. Replayed responses and responses
arriving after ABORT/reset are proved to fault without reconstructing a
discarded effect.

The proved bridge is deliberately transport-independent. A decided result is
translated to `Transaction.Transition`, staged atomically, committed only by a
matching RETIRE, and discarded without commit by ABORT. Existing `Packet`
theorems establish envelope round trips and validation precedence. This PR does
not claim that SystemVerilog implements this Lean function.

The relation requires all canonical control indices to be losslessly
representable at the `UInt32` transaction boundary and requires the stage
outcome to contain the exact pending transition. A rejected stage therefore
cannot satisfy the relation. The reachability witness constructs a concrete SET
that reaches this pending state from `Transaction.initial`.

DEREF rejects a prepared host resolution whose captured control differs from
the transaction's current control. JUMP is control-only and returns the exact
supplied memory view unchanged; it cannot erase host-owned state.

The bridge also lifts reset, abort, and matching retirement into the semantic
relation. Reset restores the initial committed state, abort preserves the
committed state, and a matching result can retire exactly once. Checked PC
increment failure is an address fault and precedes any attempted write.

The binary decision now models both negotiated profiles. `FORWARD_ONLY` rejects
either absent operand. `INTERPRETER_COMPAT` reproduces single-absent-operand
back-solving when the destination is present, including verified host-proposed
MUL inverses and the zero-known-operand fault, before applying the canonical
forward XOR or GHASH multiplication through write-once memory. Effective
addresses, the packet's inconsistent-alias rejection, DEREF pointer resolution,
and result CRC still arrive below this boundary. `DEREF_CELL` does carry the
profile at the functional boundary and proves that `FORWARD_ONLY` rejects a
missing local operand instead of applying interpreter reconciliation. The
pointer's written/encoding proof is checked first, preserving unresolved-pointer
precedence over that profile guard. The
remaining preparation obligations remain explicit edges,
not assumptions promoted to a full-profile equivalence claim.

`FullProfile.PacketPreparation` now covers SET and binary packet-to-functional
boundaries. SET checks its effective output address, retains the supplied
write-once cell, and refines through canonical SET execution into staging. The
binary path computes all three `fp + offset` addresses with checked `u32`
arithmetic before inspecting supplied cells, so address overflow has precedence
over alias faults. Contradictory cells naming any repeated address are rejected;
successful preparation materializes the finite host memory view and refines
through canonical XOR/MUL execution into atomic transaction staging.

## Remaining theorem graph

1. Extend packet preparation to raw DEREF/JUMP fields, including pointer/index
   proposals, supplied-cell aliases, and their exact fault precedence.
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
