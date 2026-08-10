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
`asic_core/rtl/lsc1_packet_frontend.sv`. Its safety proof is unbounded induction:
arbitrary RX/TX stalls, stalled-output stability, reset/ABORT dominance, staged
metadata stability, matching RETIRE, and exactly-once retirement are not assigned
a trace depth. Simulation and differential reachability are finite and therefore
explicitly **bounded**. They include result/RETIRE CRC behavior and kill focused
pointer-bypass, address-source, PC increment, profile, CRC, canonical-cell,
same-edge ABORT, result-byte and duplicate-retirement mutations.

This is a full-profile non-release assurance lane. It does not claim a physical
netlist proof or BLAKE3 service refinement.
