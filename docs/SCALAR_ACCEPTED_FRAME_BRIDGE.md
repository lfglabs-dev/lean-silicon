# SET/XOR/MUL accepted-frame lifecycle

This lane closes the authored-RTL request-to-retirement seam for one canonical
forward SET, XOR, and MUL transaction each.  Every witness starts from reset,
accepts the complete CRC-protected v1 request, checks every byte of the RESULT
envelope against an independently constructed value, accumulates the RESULT
payload CRC from emitted bytes, supplies that CRC in RETIRE, and checks exactly
one atomic `pc`/`fp`/`retire_seq` commit and completion pulse.

The formal work is deliberately decomposed into independently checkable
accepted-RESULT, matching-RETIRE, and post-RETIRE reachability/safety pairs for
each opcode.  Each subprocess has a 540-second fail-closed timeout.  A missing
cover, timeout, or tool error is not a proof or a mutation kill.

The host-only executable receipt from `make -C test/packet_frontend sim` is:

| Opcode | accepted cycle | last RESULT cycle | RETIRE accepted | completion | RESULT envelope |
|---|---:|---:|---:|---:|---:|
| SET | 61 | 130 | 150 | 151 | 48 bytes |
| XOR | 87 | 180 | 200 | 201 | 56 bytes |
| MUL | 104 | 325 | 345 | 346 | 56 bytes |

Each row is measured from its own synchronous reset prefix.  The emitted
payload CRCs are respectively `0xad67e5e5`, `0x77ce087f`, and `0x1779c059`.
The Lean host receipt is `lake build` plus
`check_accepted_scalar_binding_mutations.py`; theorem axiom reports contain
only Lean's existing `propext`, `Quot.sound`, and where required
`Classical.choice` dependencies.

Focused mutations cover the SET write byte, XOR and MUL result write bytes,
RESULT-to-RETIRE CRC binding, and duplicate retirement.  Existing DEREF and
JUMP harnesses and claims are unchanged; this lane only selects additional
witness configurations in their shared lifecycle checker.

These are finite authored-RTL checks at the stated bounds, not unbounded
liveness, fairness under permanent backpressure, SystemVerilog-to-Lean
translation, RTL/netlist sequential equivalence, physical-netlist assurance,
or silicon evidence.  The Lean theorem proves the canonical byte decoder feeds
the established SET/XOR/MUL semantics and the existing exactly-once transaction
model; it does not import RTL into Lean.  No GPU, accelerator, or offload is
used by any receipt.
