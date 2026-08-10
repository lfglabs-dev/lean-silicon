# Canonical full-profile Lean bridge

`LeanVMBMinCore.FullProfile` is the first functional bridge from every LSC-1
scalar instruction class to canonical Lean primitives and the existing
atomic transaction lifecycle. It models host-owned memory/fetch/witness inputs
as explicit request data. SET/XOR/MUL decide writes with `Memory.writeOnce` and
`GHASH128.mul`; DEREF and JUMP call `ControlPrimitives`; BLAKE3 crosses an
explicit raw-to-validated preparation boundary before it can create an external
service request, and accepts a response bound to the same transaction
and endpoint-assigned monotone service identifier. Its request type fixes the
compression shape at four message words, two chaining-value words, and sixteen
metadata bytes, so malformed arities are not representable.
Responses must also carry the BLAKE3 compression service kind. The staging
bridge enforces the negotiated 16-bit control-index limit rather than merely
the transport's wider `u32` representation.

Raw BLAKE3 preparation validates `block_len <= 64` and the known `0x7f` flags,
then computes addresses in frozen access order: four message addresses,
`fp+cv`, `fp+cv+1`, `fp+out`, and `fp+out+1`. Repeated supplied addresses must
carry consistent cells. The service request retains this validated memory view
across suspension.
Both returned digest words pass through `Memory.writeOnce`; either collision is
proved to fault, so external service ownership does not bypass canonical memory
policy or imply that the endpoint computed BLAKE3.

The controller validates and retains the next control state before publishing a
service request. Its service lifecycle is linear: exactly one response can be
consumed only from a live pending state, and consumption, ABORT, or reset returns
to idle. IDs begin at 1 after reset, advance monotonically, and reject
`0xffffffff` exhaustion rather than wrapping. A wrongly bound response faults while retaining the pending request so
the correctly bound response can still arrive. Replayed responses and responses
arriving after ABORT/reset are proved to fault without reconstructing a
discarded effect.

The proved bridge is deliberately transport-independent. A successful matching
service response is composed with `Transaction.step`, so its effect enters
`RESULT_PENDING` rather than merely returning while the service idles. A decided result is
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
committed state, and a matching result can retire exactly once. A write-once
collision takes precedence over checked PC-increment overflow, matching the
executable decision path; an otherwise valid write with overflowing PC faults
as an address error.

The binary decision now models both negotiated profiles. `FORWARD_ONLY` rejects
either absent operand. `INTERPRETER_COMPAT` reproduces single-absent-operand
back-solving when the destination is present, including verified host-proposed
MUL inverses and the zero-known-operand fault, before applying the canonical
forward XOR or GHASH multiplication through write-once memory. Effective
addresses, the packet's inconsistent-alias rejection, and DEREF pointer resolution
still arrive below this boundary. BLAKE3 completion is the exception: it retains
the fixed service kind and access order, composes the digest through write-once
memory, serializes the completed result payload, and derives the staged RETIRE
checksum with reflected IEEE CRC-32. `DEREF_CELL` does carry the
profile at the functional boundary and proves that `FORWARD_ONLY` rejects a
missing local operand instead of applying interpreter reconciliation. The
pointer's written/encoding proof is checked first, preserving unresolved-pointer
precedence over that profile guard. The
remaining preparation obligations remain explicit edges,
not assumptions promoted to a full-profile equivalence claim.

`FullProfile.PacketPreparation` now covers SET, binary, DEREF, and JUMP
packet-to-functional boundaries. SET checks its effective output address, retains the supplied
write-once cell, and refines through canonical SET execution into staging. The
binary path computes all three `fp + offset` addresses with checked `u32`
arithmetic before inspecting supplied cells, so address overflow has precedence
over alias faults. Contradictory cells naming any repeated address are rejected;
successful preparation materializes the finite host memory view and refines
through canonical XOR/MUL execution into atomic transaction staging.
Raw DEREF and JUMP preparation rejects noncanonical cells, performs checked
address arithmetic, rejects contradictory cells at aliased addresses, and
checks host pointer/index and branch proposals in the executable endpoint's
fault order. Successful packets refine directly to the existing canonical
control primitives. Concrete successful DEREF/JUMP decisions and competing-fault
witnesses keep both the success paths and precedence claims non-vacuous; the
mutation runner changes each validation edge and requires Lean to reject it.

`FullProfile.Payload` closes the next bounded host boundary for DEREF and JUMP:
it decodes the canonical 81/103-byte payloads at the byte offsets fixed by the
v1 transaction protocol, rejects malformed profile/reserved/cell/branch bytes,
and feeds only successfully decoded packets to the preparation functions above.
The ordinary-result checksum remains an explicit endpoint-derived argument
because request payloads do not carry it. A concrete 103-byte not-taken JUMP
witness reaches a canonical result, and byte-offset/width/cell/branch mutations
must fail elaboration. This is a payload-to-functional theorem, not a parser for
ready/valid cycles or a Lean-to-RTL correspondence result.

## Remaining theorem graph

1. Extend the proved byte-exact DEREF/JUMP payload decoder across SET/XOR/MUL
   and the BLAKE3/control payloads, then compose it with the checksum-parametric
   envelope decoder and the endpoint-derived ordinary-result CRC.
2. Define an independent cycle transition system for
   `asic_core/rtl/lsc1_packet_frontend.sv`, including receive/transmit buffers,
   backpressure, reset and ABORT dominance.
3. Prove accepted-frame refinement from that cycle system to `FullProfile.decide`
   for SET/XOR/MUL/DEREF/JUMP and to the proved raw BLAKE3 service path.
4. Lift the proved BLAKE3 staged-result CRC correspondence and
   `successful_service_response_matching_retire_exactly_once` to the cycle system's
   DONE edge.
5. Bind the independent cycle system to authored SV with unbounded formal
   correspondence (or explicitly bounded results where induction cannot close).

Until all five edges exist, the correct claim is a canonical functional and
transaction-lifecycle foundation, not full Lean-to-RTL equivalence.
