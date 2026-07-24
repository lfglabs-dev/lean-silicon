# Frozen scalar reference

Run `python3 oracle.py` in this directory. The executable JSON vectors cover
each current upstream opcode at the scalar boundary and its relevant fault
paths. BLAKE3 is intentionally an adapter/service vector: this repository does
not claim to implement upstream flock compression in M0.

`oracle.py` is suitable as a frozen differential target for a Rust single-step
adapter: feed it the decoded operation and compare result/fault, access count,
and checked-index result. It does not try to mimic upstream private types or
turn witness-generation conveniences into hardware requirements.

The deferred-Cell cases intentionally preserve the frozen runner's asymmetric
finalization: a later write to the indirect (`a2`) side is propagated, while a
later nonzero write only to the local (`a3`) side ends in a write-once conflict.
This is runner behavior, not a symmetric equality solver.
