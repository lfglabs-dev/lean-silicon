# host/

Mac-side runtime for LSC-1. See [docs/HOST_RUNTIME.md](../docs/HOST_RUNTIME.md)
for the architecture, the pinned `lean_compiler` interface and the limits of
the upstream comparison.

| Module | Role |
|---|---|
| `protocol.py` | binds the normative `sim/lsc1_transaction.py` model |
| `errors.py` | host error taxonomy, including `UnsupportedCapability` |
| `memory.py` | write-once memory, pointer map, deferred state, inverse witnesses |
| `lean_compiler_adapter.py` | loads and validates an exported program artifact |
| `runtime.py` | prepares, drives, retires and applies one transaction per instruction |
| `fixtures/` | a zkDSL source and the artifact compiled from it by the frozen upstream |

This package consumes the transaction protocol. It does not define wire
formats, opcodes, status codes or profiles, and must not change them.

`SET_CONSTANT`, `XOR` and `MUL_NATIVE` are integrated. `DEREF`, `JUMP` and
`BLAKE3` raise `UnsupportedCapability` naming the missing host capability.
