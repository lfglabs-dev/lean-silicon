# M2 scalar controller

M2 adds a synthesizable scalar controller for frozen XOR, MUL, SET, JUMP, and
halt behavior.  Its deliberately narrow wide-port test/service boundary is not
the byte-RPC protocol and does not alter the existing Tiny Tapeout wrapper.
Memory is represented by a bounded write-once array to make the controller
executable in RTL; an integration adapter must provide equivalent external
memory semantics.  MUL back-solving exposes a one-outstanding `inverse_req`
service because field inversion is explicitly an external scalar-profile
service.  The controller does not claim DEREF Cell reconciliation, BLAKE3,
trace counting, byte-RPC compatibility, or upstream-complete execution.

Addresses are bounded by the instantiated test memory and JUMP reverse lookup
is bounded likewise.  These are test-adapter limits, not a replacement for the
frozen u32/reverse-map host contract.

Instruction operands are offsets relative to `fp`; offset addition and
`pc + 1` fault on u32 overflow.  HALT is terminal until reset.  The test loader
uses the same idempotent write-once rule as instruction writes.
