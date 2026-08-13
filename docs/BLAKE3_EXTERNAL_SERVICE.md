# External BLAKE3 service prerequisites

This document freezes the canonical host-service contract and software/model
implementation boundary. Authored SystemVerilog now implements the bounded TX
transport contract below, but no authored RTL controller, ASIC/FPGA integration,
UART, JTAG, or hardware path implements the service lifecycle.

## Transport-independent schema

All integers are little-endian. Exactly one service may be outstanding.

`SERVICE_REQUIRED` is 131 bytes:

| Offset | Bytes | Field |
| ---: | ---: | --- |
| 0 | 1 | schema version (`1`) |
| 1 | 8 | host-created nonzero `session_epoch` |
| 9 | 4 | `txn_id` |
| 13 | 4 | `service_id` |
| 17 | 1 | kind (`1`, BLAKE3 compression) |
| 18 | 1 | reserved zero |
| 19 | 64 | message block |
| 83 | 32 | chaining value |
| 115 | 8 | counter |
| 123 | 4 | block length (`0..64`) |
| 127 | 4 | flags (known mask `0x7f`) |

`SERVICE_RESPONSE` is 53 bytes:

| Offset | Bytes | Field |
| ---: | ---: | --- |
| 0 | 1 | schema version (`1`) |
| 1 | 8 | `session_epoch` |
| 9 | 4 | `txn_id` |
| 13 | 4 | `service_id` |
| 17 | 1 | kind |
| 18 | 1 | status (`OK`, transient failure, permanent failure) |
| 19 | 2 | digest length (must be `32`) |
| 21 | 32 | digest |

The binding key is `(session_epoch, txn_id, service_id, kind)`. The host creates
a fresh unpredictable epoch after endpoint reset or reconnect and does not
reuse transaction IDs within it. ABORT invalidates the outstanding key. Reset
invalidates the epoch. A retry reuses the identical key and operands. The
current v1 wire payload remains the inner model ABI; until an eventual wire
revision, the adapter is the trusted epoch boundary.

Malformed lengths, version/status values, digest lengths, metadata, and
bindings are semantic failures and never mutate staged state. Tool startup,
process exit, and transport availability are infrastructure failures and are
reported separately. Only infrastructure failures receive bounded automatic
retry. A successful response moves the model to `RESULT_PENDING`; neither
endpoint state nor host memory commits until a validated `RETIRE`/`RETIRED`
exchange.

There is no endpoint service-latency bound. Ready/valid data must remain stable
under arbitrary stalls, and timeout policy belongs to the host. Timeout
recovery must explicitly ABORT or reset; reconnect alone is not a commit or an
abort.

## Authored RTL transport boundary

`lsc1_packet_tx.sv` supports one logical 122-byte v1 `SERVICE_REQUIRED`
payload through its bounded external byte-source mode. The controller selects
that mode at `start`, asserts `payload_external_valid` only for payload beats,
and then presents the byte named by `payload_index`. The source byte must remain
immutable while that valid signal is asserted. This is the transport-side
scatter/gather contract: it avoids duplicating another 122-byte register bank
and avoids transport-level fragmentation. The existing 68-byte locally staged
path remains the path used by the integrated scalar controller. Focused RTL
regression covers:

- byte-exact mapping and CRC under a stall at every output byte;
- source index/data stability under a stall at every transmitted beat;
- ABORT/reset invalidate same-edge transfers and all source references;
- existing short responses remain byte-identical.

The BLAKE3 service controller/FSM is deliberately not implemented here. The
executable model and host service lifecycle therefore remain ahead of authored
RTL semantics; no netlist, P&R, FPGA, or hardware claim follows from this
serializer regression.

## Executable evidence

`host/blake3_service.py` supplies the codecs, epoch/replay adapter, bounded retry
policy, the `Blake3HostService` implementation protocol, and the default
`SoftwareBlake3HostService` CPU implementation. `host/runtime.py` drives the
complete request/service/result/retire lifecycle and records SHA-256 receipts
for the exact 131-byte canonical request and 53-byte canonical response.
`sim/test_blake3_service.py`
compares it against the official `blake3_guts` low-level compression API using
the exact dependency and registry checksum pinned by
`tools/blake3_reference/Cargo.lock`. Oracle build/execution failures raise
`ServiceInfrastructureError`; byte mismatches remain ordinary test failures.

The runtime evidence is not an RTL BLAKE3 claim. The integrated packet RTL
continues to advertise only its implemented scalar feature bit. CPU/model
workloads may include BLAKE3; RTL workload replay still stops at the supported
SET/XOR/MUL/DEREF/JUMP controller boundary.
