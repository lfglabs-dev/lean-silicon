# LSC-1 architecture

LSC-1 is a scalar coprocessor, not an autonomous VM. The host supplies a
self-contained transaction; LSC-1 decodes it, computes effective addresses and
u32 pc/fp transitions, checks write-once constraints/witnesses, executes XOR,
MUL_NATIVE, SET_CONSTANT, DEREF Cell/Pc/Fp, and JUMP, then emits transition
effects. BLAKE3 becomes a service request. Inversion is a host witness checked
with multiplication.

No program fetch, VM-memory array/controller, pointer reverse map, trace store,
inverter, or BLAKE3 datapath crosses this boundary. The physical transport is
defined in [LSC1_PROTOCOL](LSC1_PROTOCOL.md).

The current implementation only wraps the historical MinCore GF(2^128)
stream-ALU as a datapath seed. It preserves its arithmetic and proof history
without claiming the architectural features above are already in RTL.
