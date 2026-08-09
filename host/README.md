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
| `blake3_service.py` | transport-neutral schema, epoch guard and compression adapter |
| `fixtures/` | a zkDSL source and the artifact compiled from it by the frozen upstream |

This package consumes the transaction protocol. It does not define wire
formats, opcodes, status codes or profiles, and must not change them.

`SET_CONSTANT`, `XOR`, `MUL_NATIVE`, `DEREF`, `JUMP`, and the host-owned
`BLAKE3` service lifecycle are integrated in the CPU/executable-model runtime.
The transport-independent service codecs, software compression implementation,
epoch binding, and model tests live in `host/blake3_service.py`; they
intentionally do not claim a production transport or RTL service path.
