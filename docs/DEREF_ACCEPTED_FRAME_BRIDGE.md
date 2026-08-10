# DEREF accepted-frame bridge

This lane closes the request/result checksum seam for DEREF opcodes `0x04`--`0x06`.

The dedicated `reachability` task now drives a byte-exact valid `DEREF_CELL`
envelope into the production `lsc1_packet_frontend`, checks and drains every
byte of its 35-byte RESULT payload and envelope, independently accumulates the
payload CRC-32 from those emitted bytes, and uses that value in a matching
RETIRE envelope.  Its cover requires the expected staged effect and exactly
one `pc`/`fp`/`retire_seq` commit with one `done_pulse`.  Cycle-accurate RTL
simulation derives the first completion at cycle 2784; the formal task uses
depth 2786, and a depth-2785 mutant must report an unreached cover.

The separate depth-20 `safety` task retains arbitrary traffic and backpressure.
Critical formal mutants corrupting the emitted-result CRC binding or retaining
the stage after retirement must terminate with assertion failures; missing
covers, timeouts, tool errors, or surviving mutants fail the gate.
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
distinct addresses 0/1/2, pointer witness 1, reflected IEEE request CRC-32
`0xf96e5fb0`), drains the 44-byte RESULT envelope, and supplies the 18-byte
RETIRE envelope. The RETIRE payload uses the independently accumulated RESULT
payload CRC-32 `0x80b86ca4`; the checker never assumes that value or obtains it
from `staged_result_crc`.

No unbounded RTL or netlist equivalence is claimed. Simulation and differential
reachability are likewise finite. They include result/RETIRE CRC behavior and kill focused
pointer-bypass, address-source, PC increment, profile, CRC, canonical-cell,
same-edge ABORT, result-byte and duplicate-retirement mutations.

This is a full-profile non-release assurance lane. The residual gap is an
unbounded proof of the exact frontend transition system (or an independently
checked sequential-equivalence certificate). It does not claim a physical
netlist proof or BLAKE3 service refinement.
