# Protocol byte/cycle model and trust-boundary audit

**Scope.** This document specifies the implemented MinCore byte lane in
`src/leanvm_b_stream_alu.sv`, its wrapper, and the executable model in
`sim/protocol_contract.py`.  It does not specify or implement the draft
full-core controller in `FULL_CORE_PROTOCOL.md`.

## Normative edge model

All signals below are sampled at the rising clock edge.  A potential input
beat is `RX_VALID && RX_READY`; a potential output beat is
`TX_VALID && TX_READY`.  A beat is **committed** only when its potential beat
is true and neither synchronous reset nor `ABORT` is asserted for that edge.
This qualification is necessary because reset and abort have sequential
priority over the FSM; they discard same-edge candidate transfers.

`rst_n` is synchronous and active low.  Pins for an edge are combinationally
observable from the pre-edge state; therefore reset or abort can coincide with
an apparent `TX_VALID` byte and/or `DONE_PULSE`.  Neither observation commits
a transfer on that edge.  After a reset edge the engine is IDLE, deasserts
`BUSY` and `FAULT`, and has no outstanding output.  `ABORT` is synchronous:
after its edge the engine is IDLE, in-flight arithmetic is cleared, and sticky
`FAULT` is set.  It is not an acknowledged cancellation message.  The host
must stop counting a transaction on either reset or abort and resynchronize
from IDLE; it must not interpret a simultaneously visible `TX_VALID` byte or
`DONE_PULSE` as delivered or complete.

For an ordinary ready/valid stall, the sender holds `VALID` and data stable
until a committed beat.  The core holds registered responses (MUL, STATUS,
error) stable while `TX_READY=0`.  XOR, SET, and final NONZERO are deliberate
combinational stream paths: their response is valid only while the host holds
the matching input byte valid.  The host may not wait for `RX_READY` before
asserting `RX_VALID` in those states, because `RX_READY` depends on
`TX_READY`.  A bridge that cannot obey this must buffer one byte externally.

## Fixed byte grammar and cycle accounting

`F128` and `u32` values are little-endian.  There is no packet delimiter,
length, checksum, sequence number, transaction ID, timeout, or retry in this
MinCore grammar.

| Command | Request after command | Response | Ideal committed-edge count |
|---|---|---|---:|
| `01 XOR128` | `A0,B0 ... A15,B15` | 16 XOR bytes | 33 |
| `02 MUL128` | `A0..A15,B0..B15` | 16 product bytes | 161 |
| `03 SET128` | `V0..V15` | 16 echoed bytes | 17 |
| `04 NONZERO` | `V0..V15` | `00` or `01` | 17 |
| `7d CLEAR` | none | none | 1 |
| `7e STATUS` | none | `01 01 0f 08` | 5 |
| other | none | `e0` and sticky `FAULT` | 2 |

The listed ideal counts assume `rst_n=1`, `ABORT=0`, an always-valid source,
and an always-ready sink.  Every source gap or sink stall adds one or more
wall-clock cycles; no maximum completion time exists.  With neither reset nor
abort asserted, `DONE_PULSE` marks the final committed response beat, or a
committed `CLEAR`.  It is a combinational pulse and can also be visibly high
on a reset/abort edge whose candidate transfer is discarded; it is not durable
completion state.  A host must qualify completion with the committed-beat rule
and synchronize/capture it if it can miss the pulse.

## Framing and malformed/partial behavior

The engine decodes only the first command byte in IDLE.  Once selected, it
consumes exactly the command's fixed number of payload beats; bytes cannot be
marked malformed and a partial transaction waits indefinitely.  A reset or
abort terminates it but does not identify how many bytes were lost.  A byte
sent while `RX_READY=0` is not accepted; the source must retain it.  A byte
sent when `RX_READY=1` during a payload phase is payload, never a new command.
Unknown IDLE commands return one `e0`; `CLEAR` is the only in-band way to clear
the resulting sticky fault.

Therefore a UART/USB/network bridge MUST add its own message envelope,
length check, integrity check, timeout, cancellation/retry policy, and
resynchronization policy.  It must never silently replay a command with side
effects once a future full-core service is used.

## Service and trust boundary

The implemented ASIC trusts electrical timing, synchronous reset/abort,
stable ready/valid data, and a single cooperative host.  It provides neither
authentication nor isolation.  The draft full-core protocol makes the host
service responsible for memory, write-once enforcement, pointer/index maps,
deferred equality, program storage, BLAKE3, and trace persistence.  That host
is therefore part of the trusted computing base: the current MinCore cannot
validate service results, protect their confidentiality/integrity, or recover
from a host crash beyond abort/reset.

No command is safely idempotent by protocol declaration.  `XOR`, `MUL`, and
`NONZERO` are pure at this boundary, but `SET` is explicitly a future memory
attachment and full-core requests include writes, counters, and trace events.
Hosts must treat an interrupted transaction as outcome-unknown unless their
own envelope supplies an operation ID and durable acknowledgement.

## Findings and disposition

| Severity | Finding | Disposition |
|---|---|---|
| High | Raw lane has no framing, integrity, timeout, replay protection, or resynchronization after loss/corruption. | Residual; bridge requirement documented. |
| High | Full-core services place memory and semantic enforcement in an untrusted-by-hardware host boundary. | Residual; needs authenticated/verified service design before hostile deployment. |
| Medium | `ABORT` can coincide with apparent valid/ready transfers, which RTL discards. | Resolved in the byte/cycle contract and executable vector; bridge must apply committed-beat rule. |
| Medium | Combinational stream commands create a ready/valid dependency and require a non-waiting source or external byte buffer. | Residual architectural constraint, explicitly documented and tested under backpressure. |
| Medium | Partial fixed-length transactions can stall forever and have no in-band error code. | Residual; bridge timeout/abort/resync required. |
| Low | `DONE_PULSE` is one cycle and can be visibly high for a reset/abort-discarded candidate transfer. | Residual; qualify it with reset/abort and committed beats, then synchronize/capture externally. |
| Low | Reset clears `FAULT`, so it is not persistent diagnostic evidence. | Residual; bridge logging required. |

The test vectors cover pin-level stall stability, registered response
backpressure, abort priority, reset cancellation with pre-reset STATUS pins,
reset/abort qualification of a same-edge STATUS `DONE_PULSE`, and
unknown-command error serialization.  They do not establish metastability
safety, physical timing, cryptographic transport integrity, full-core
correctness, or exhaustive RTL verification.
