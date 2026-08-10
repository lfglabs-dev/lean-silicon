# DEREF accepted-frame bridge

This lane closes the request/result checksum seam for DEREF opcodes `0x04`--`0x06`.
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

A separate cover task establishes a byte-exact valid DEREF_CELL frame witness.
It drives reset followed by all 91 accepted envelope bytes (81-byte payload,
profile byte 1, reflected IEEE CRC-32 `0x58e32428`) and reaches controller
acceptance at step 94 with depth 97. Reducing that bound to 20 makes the
cover task fail with the witness unreached. There is deliberately no formal
RETIRE cover claim: the sequential pointer encoders, result serialization, and
following RETIRE frame require a much larger bound that is not certified here.
Executable RTL simulation supplies the finite end-to-end DEREF/RETIRE witness.

No unbounded RTL or netlist equivalence is claimed. Simulation and differential
reachability are likewise finite. They include result/RETIRE CRC behavior and kill focused
pointer-bypass, address-source, PC increment, profile, CRC, canonical-cell,
same-edge ABORT, result-byte and duplicate-retirement mutations.

This is a full-profile non-release assurance lane. The residual gap is an
unbounded proof of the exact frontend transition system (or an independently
checked sequential-equivalence certificate). It does not claim a physical
netlist proof or BLAKE3 service refinement.
