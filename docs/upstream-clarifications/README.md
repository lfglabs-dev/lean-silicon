# Draft upstream clarifications (not filed)

These are drafts only. No upstream issue has been created by this change.

1. **Specify host-index overflow.** `Program::execute` adds `u32` indexes
directly. State whether programs must make every sum representable, whether
debug/release behavior is intentionally different, or whether checked errors
are required.
2. **Separate proof relation from runner deduction.** Document that XOR/MUL
back-solving and both-unwritten DEREF finalization are witness-generation
choices, not source-ISA read/write ordering.
3. **Name the DEREF Pc rule consistently.** The normative rule is `g²*pc`
(`encode(pc+2)`). Remove/update any prose that describes it as an ordinary
one-step successor.
4. **Expose structured runner errors.** Wild pointers, taken JUMP targets,
write conflicts, and zero-divisor back-solving currently surface mostly as
panics. Typed errors would make external implementations interoperable.
