# LSC-1 Transaction Protocol, version 1

Normative specification of the host-prepared scalar instruction transaction
protocol carried over the LSC-1 8-bit ready/valid lane.

- **Protocol version:** `1` (the `version` byte of every envelope).
- **Status:** normative for the protocol and for the executable model
  `sim/lsc1_transaction.py`. The RTL packet frontend implements negotiation,
  status, retirement, SET/XOR/MUL, DEREF Cell/Pc/Fp and JUMP. BLAKE3 service
  exchange remains model-only; see `docs/STATUS.md` for the exact capability
  boundary.
- **Executable companion:** `sim/lsc1_transaction.py`. Every packet length,
  status code and budget in this document is generated from that module and is
  checked against it by `sim/test_lsc1_protocol_doc.py`. Do not hand-edit the
  tables; regenerate them from the model instead.

This document specifies **no** formal-verification result, **no** FPGA
validation, and **no** Tiny Tapeout readiness. The cycle figures in
[§13](#13-byte-and-cycle-budgets) are arithmetic over stated assumptions, not
simulation or synthesis measurements.

## Contents

1. [Scope and design premise](#1-scope-and-design-premise)
2. [Normative references](#2-normative-references)
3. [Physical ABI](#3-physical-abi)
4. [Byte lane](#4-byte-lane)
5. [Frame grammar](#5-frame-grammar)
6. [Primitive payload types](#6-primitive-payload-types)
7. [Request payload schemas](#7-request-payload-schemas)
8. [Response payload schemas](#8-response-payload-schemas)
9. [Status and fault codes](#9-status-and-fault-codes)
10. [Transaction state machine](#10-transaction-state-machine)
11. [Service request and response contract](#11-service-request-and-response-contract)
12. [Profiles and negotiation](#12-profiles-and-negotiation)
13. [Byte and cycle budgets](#13-byte-and-cycle-budgets)
14. [Trust boundary](#14-trust-boundary)
15. [Abort, reset and framing recovery](#15-abort-reset-and-framing-recovery)
16. [Frozen-source differences](#16-frozen-source-differences)
17. [Deliberately unresolved](#17-deliberately-unresolved)

---

## 1. Scope and design premise

LSC-1 processes **exactly one host-prepared scalar instruction transaction at a
time**. The host owns the program, the VM memory image, the written bitmap, the
pointer maps, BLAKE3, trace persistence, access counts, deferred equalities and
inversion proposals. For each instruction the host assembles a self-contained
request carrying every cell the transition reads or writes, plus whatever
witnesses the endpoint needs to check the host's own claims.

The endpoint retains the parts that must not be delegated:

- it **decides** the scalar transition (which cells are written, with what
  values, and what the next `pc`/`fp` are);
- it **verifies** host proposals it can check more cheaply than it can compute
  them — a g-power index by re-encoding, a multiplicative inverse by
  multiplying, a branch outcome by recomputing it;
- it **commits** nothing until the host acknowledges the exact result it read.

The endpoint holds no memory image. It sees only the cells named by the request
in flight, which is what makes a fixed per-opcode packet size possible.

### Out of scope

Program layout, memory sizing, the proof system, the trace encoding, the
multi-instruction schedule, and host-side persistence. This document specifies
the wire contract and the transition decision for one instruction.

## 2. Normative references

Semantic authority is the **frozen** upstream commit. Moving `main` is not
authoritative and MUST NOT be used to resolve questions about this protocol.

| Reference | Pinned location |
| --- | --- |
| leanVM-b, frozen commit | `leanEthereum/leanVM-b@c308034ab78619b39a59d26f3dc60e7df5b52649` |
| ISA and `DEREF` modes | [`crates/lean_vm/src/cpu/isa.rs`](https://github.com/leanEthereum/leanVM-b/blob/c308034ab78619b39a59d26f3dc60e7df5b52649/crates/lean_vm/src/cpu/isa.rs) |
| Executable step semantics | [`crates/lean_vm/src/cpu/execute.rs`](https://github.com/leanEthereum/leanVM-b/blob/c308034ab78619b39a59d26f3dc60e7df5b52649/crates/lean_vm/src/cpu/execute.rs) |
| Field, memory bounds, digest | [`crates/lean_vm/src/cpu/mod.rs`](https://github.com/leanEthereum/leanVM-b/blob/c308034ab78619b39a59d26f3dc60e7df5b52649/crates/lean_vm/src/cpu/mod.rs) |
| Trace layout | [`crates/lean_vm/src/cpu/layout.rs`](https://github.com/leanEthereum/leanVM-b/blob/c308034ab78619b39a59d26f3dc60e7df5b52649/crates/lean_vm/src/cpu/layout.rs) |
| Constraint document | [`misc/doc.tex`](https://github.com/leanEthereum/leanVM-b/blob/c308034ab78619b39a59d26f3dc60e7df5b52649/misc/doc.tex) |

Local references: `docs/LSC1_PROTOCOL.md` (physical ABI and seed-0 framing),
`docs/SEMANTIC_DIFFERENCES.md`, `docs/DECISIONS.md`, `docs/PROTOCOL_BYTE_CYCLE_AUDIT.md`.

### 2.1 Field

The field is `GF(2^128) = F2[x] / (x^128 + x^7 + x^2 + x + 1)`, the GHASH field
of `cpu/mod.rs`. The generator is `g = x`. A field element is transmitted as 16
bytes **little-endian**: byte 0 carries coefficients of `x^0..x^7`, byte 15
carries `x^120..x^127`. `encode(n)` denotes `g**n`.

All multi-byte integers on the wire are **little-endian**. Indices (`pc`, `fp`,
frame offsets, memory addresses) are `u32`.

## 3. Physical ABI

Unchanged from `docs/LSC1_PROTOCOL.md`; repeated here because the transaction
protocol is defined on top of it.

| Signal | Pins | Direction | Meaning |
| --- | --- | --- | --- |
| `ui_in[7:0]` | dedicated input | host to device | request byte |
| `uo_out[7:0]` | dedicated output | device to host | response byte |
| `uio[0]` | input | host to device | `RX_VALID` |
| `uio[1]` | output | device to host | `RX_READY` |
| `uio[2]` | output | device to host | `TX_VALID` |
| `uio[3]` | input | host to device | `TX_READY` |
| `uio[4]` | output | device to host | `BUSY` |
| `uio[5]` | output | device to host | `FAULT` |
| `uio[6]` | input | host to device | `ABORT` |
| `uio[7]` | output | device to host | `DONE`/IRQ |

`uio_oe = 8'b10110110`.

Status pin semantics:

- `BUSY` is high while any frame is partially received, any response byte is
  pending, or a transaction is not `IDLE`.
- `FAULT` is high while the last emitted status was a fault (`>= 0x80`). It is
  cleared by the next non-fault response and by reset. It is **not** cleared by
  `ABORT` — abort itself sets `ABORTED`.
- `DONE` is a **one-cycle pulse** asserted in the cycle following acceptance of
  a `RETIRE` whose checks passed. It is the only edge on which committed state
  moves. It is not asserted for any other response, and it is suppressed by
  abort and reset.

## 4. Byte lane

One byte per committed beat, one clock per beat at full rate.

- A **transfer commits** on a rising clock edge where `RX_VALID & RX_READY`
  (host to device) or `TX_VALID & TX_READY` (device to host). Both are sampled
  from their pre-edge combinational values.
- The device MUST hold `TX_VALID` and `uo_out` stable until the beat commits.
  Backpressure never changes, reorders or drops a byte; it only costs cycles.
- The host MAY deassert `RX_VALID` for arbitrarily many cycles at any byte
  boundary. Stalls never change the response bytes.
- **`RX_READY` is deasserted whenever any response byte is pending.** This is
  the mechanism that enforces one outstanding request: the host physically
  cannot begin a new frame until it has drained the previous response. There is
  no separate credit or resynchronization state.
- `ABORT` and `reset_n` are evaluated **before** any candidate transfer on the
  same edge and cancel it (see [§15](#15-abort-reset-and-framing-recovery)).

## 5. Frame grammar

Both envelopes are **version-invariant**: the position and width of `sof`,
`version` and `length` are fixed for all protocol versions, so a device can
consume and fault a frame of an unknown version without losing byte-stream
synchronization.

The envelope is distinct from the payload. The envelope is small and fixed; the
payload is per-opcode and carries the field elements, which dominate the frame.

### 5.1 Request

```
request  := sof version opcode flags length payload crc
sof      := 0xA1
version  := u8                 ; 1
opcode   := u8                 ; §7
flags    := u8                 ; reserved, MUST be 0x00
length   := u16le              ; payload byte count
payload  := byte{length}       ; §7, fixed per opcode
crc      := u32le              ; §5.3, over sof..payload
```

Request header: **6 bytes**. Envelope overhead: **10 bytes** (6 header + 4 CRC).

### 5.2 Response

```
response := sof version status length payload crc
sof      := 0x5A
version  := u8                 ; 1
status   := u8                 ; §9
length   := u16le              ; payload byte count
payload  := byte{length}       ; §8
crc      := u32le              ; §5.3, over sof..payload
```

Response header: **5 bytes**. Envelope overhead: **9 bytes**.

The response envelope has **no `flags` byte**; the asymmetry with the request
envelope is inherited from `docs/LSC1_PROTOCOL.md` and is deliberate. `status`
occupies the byte position that `opcode` occupies in a request.

### 5.3 Integrity

CRC-32, IEEE 802.3, reflected: polynomial `0xEDB88320`, initial register
`0xFFFFFFFF`, final XOR `0xFFFFFFFF`, processed least-significant bit first.
It covers `sof` through the last payload byte inclusive and is transmitted
little-endian.

The CRC is an integrity check against a noisy or desynchronized lane. **It is
not an authentication mechanism** and provides no protection against a hostile
host, which is assumed throughout ([§14](#14-trust-boundary)).

### 5.4 Length bound

`MAX_PAYLOAD_BYTES = 256`. A declared `length` above this is rejected at the
header, before the endpoint waits for payload bytes it would have to buffer.

### 5.5 Frame sizes

| Opcode | Code | Payload bytes | Frame bytes |
| --- | --- | --- | --- |
| `XOR` | `0x01` | 77 | 87 |
| `MUL_NATIVE` | `0x02` | 94 | 104 |
| `SET_CONSTANT` | `0x03` | 51 | 61 |
| `DEREF_CELL` | `0x04` | 81 | 91 |
| `DEREF_PC` | `0x05` | 81 | 91 |
| `DEREF_FP` | `0x06` | 81 | 91 |
| `JUMP` | `0x07` | 103 | 113 |
| `BLAKE3_REQUEST` | `0x08` | 190 | 200 |
| `NEGOTIATE` | `0x10` | 7 | 17 |
| `SERVICE_RESPONSE` | `0x11` | 42 | 52 |
| `RETIRE` | `0x12` | 8 | 18 |
| `STATUS_QUERY` | `0x13` | 0 | 10 |

Payload length is **fixed per opcode**. A frame whose `length` does not equal
the value above for its opcode is rejected with `BAD_LENGTH`, even if its CRC is
valid. Opcodes `0x01`–`0x08` are *instruction* opcodes; `0x10`–`0x13` are
*control* opcodes.

## 6. Primitive payload types

| Type | Bytes | Encoding |
| --- | --- | --- |
| `u8` | 1 | unsigned |
| `u16le` | 2 | unsigned little-endian |
| `u32le` | 4 | unsigned little-endian |
| `f128le` | 16 | field element, little-endian ([§2.1](#21-field)) |
| `cell` | 17 | `u8` presence (`0x00` or `0x01`) then `f128le` value |

A `cell` is the host's claim about one write-once memory location: whether it is
already written, and if so with what value. An **absent** cell MUST carry a
value of zero; a nonzero value behind a zero presence byte is rejected with
`BAD_CELL`, because it would smuggle data past the write-once bookkeeping the
host is responsible for. A presence byte other than `0x00`/`0x01` is likewise
`BAD_CELL`.

### 6.1 Transaction preamble

Every instruction request begins with the same 14-byte preamble.

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` |
| 4 | `u32le` | `pc` |
| 8 | `u32le` | `fp` |
| 12 | `u8` | `profile` ([§12](#12-profiles-and-negotiation)) |
| 13 | `u8` | reserved, MUST be `0x00` |

`pc` and `fp` are the scalar state the host believes is current. Once the
endpoint has retired at least one transaction, a preamble that does not match
the endpoint's committed `(pc, fp)` is rejected with `STATE_MISMATCH`: a host
that rewinds or forks the scalar state is refused, not followed.

`pc` and `fp` MUST be below `2**16` (`INDEX_BITS = 16`), the bound at which the
endpoint can re-derive `g**n` — see [§14.2](#142-index-bound). Violations are
`INDEX_RANGE`.

All frame offsets are added to `fp` with **checked** `u32` arithmetic; overflow
is `U32_OVERFLOW`, never a wrap ([§16.4](#164-u32-overflow)).

## 7. Request payload schemas

Offsets below are relative to the start of the payload. "cells" are supplied in
the order the corresponding addresses are listed.

### 7.1 `XOR` (`0x01`) — 77 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | preamble | [§6.1](#61-transaction-preamble) |
| 14 | `u32le` | `off_a` |
| 18 | `u32le` | `off_b` |
| 22 | `u32le` | `off_c` |
| 26 | `cell` | cell at `fp + off_a` |
| 43 | `cell` | cell at `fp + off_b` |
| 60 | `cell` | cell at `fp + off_c` |

Decision: `m[fp+off_c] = m[fp+off_a] + m[fp+off_b]` (field addition is XOR),
written once. `pc` advances by 1, `fp` is unchanged. Access order is
`a, b, c`. Back-solving of an absent operand is profile-dependent
([§12.2](#122-xormul_native)).

### 7.2 `MUL_NATIVE` (`0x02`) — 94 bytes

Identical to `XOR` through offset 76, then:

| Offset | Type | Field |
| --- | --- | --- |
| 77 | `cell` | proposed inverse of the known operand |

Decision: `m[fp+off_c] = m[fp+off_a] * m[fp+off_b]`. The proposed inverse is
used **only** on the back-solving path and only after the endpoint verifies
`known * proposed == 1` ([§14.1](#141-verified-proposals)). It is ignored
otherwise; hosts SHOULD send an absent cell when not back-solving.

### 7.3 `SET_CONSTANT` (`0x03`) — 51 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | preamble | |
| 14 | `u32le` | `off_o` |
| 18 | `f128le` | `k` |
| 34 | `cell` | cell at `fp + off_o` |

Decision: `m[fp+off_o] = k`, written once. `pc` advances by 1.

### 7.4 `DEREF_CELL` / `DEREF_PC` / `DEREF_FP` (`0x04`/`0x05`/`0x06`) — 81 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | preamble | |
| 14 | `u32le` | `alpha` |
| 18 | `u32le` | `beta` |
| 22 | `u32le` | `gamma` |
| 26 | `cell` | pointer cell at `fp + alpha` |
| 43 | `u32le` | `base` — the host's claim that `pointer == encode(base)` |
| 47 | `cell` | target cell at `base + beta` |
| 64 | `cell` | local cell at `fp + gamma` |

The endpoint recomputes `encode(base)` and rejects a mismatch with
`BAD_POINTER`. This replaces the frozen runner's `gmap` lookup, which the
endpoint cannot hold. `base` above `2**16` is `INDEX_RANGE`.

Target address is `base + beta`, checked. Access order is
`fp+alpha, base+beta, fp+gamma`. `pc` advances by 1.

- **`DEREF_PC`** stores `encode(pc + 2)` into the target cell.
- **`DEREF_FP`** stores `encode(fp)` into the target cell.
- **`DEREF_CELL`** reconciles target and local; the four presence quadrants are
  profile-dependent ([§12.3](#123-deref_cell)).

Note `beta` here is the **exponent**, matching `execute.rs`; `doc.tex` writes
the same address as multiplication by the field element `g**beta`. These are the
same address under the exponent isomorphism.

### 7.5 `JUMP` (`0x07`) — 103 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | preamble | |
| 14 | `u32le` | `off_c` — condition |
| 18 | `u32le` | `off_d` — destination `pc` operand |
| 22 | `u32le` | `off_f` — destination `fp` operand |
| 26 | `cell` | cell at `fp + off_c` |
| 43 | `cell` | cell at `fp + off_d` |
| 60 | `cell` | cell at `fp + off_f` |
| 77 | `u8` | `taken` (`0x00` or `0x01`) |
| 78 | `u32le` | `dest_pc` |
| 82 | `u32le` | `dest_fp` |
| 86 | `cell` | proposed inverse of the condition |

All three operand cells are read on **both** outcomes, matching `execute.rs`;
the access record is the same shape whether or not the branch is taken.

The endpoint recomputes the outcome from the condition and rejects a
disagreeing `taken` with `BAD_BRANCH_PROPOSAL`.

- **Taken** (`condition != 0`): the proposed inverse MUST satisfy
  `condition * proposed == 1` (`BAD_INVERSE` otherwise), and `dest_pc`,
  `dest_fp` MUST re-encode to the `off_d` and `off_f` operands
  (`BAD_POINTER` otherwise). Then `pc = dest_pc`, `fp = dest_fp`.
- **Not taken** (`condition == 0`): `doc.tex` constrains the witness only
  through `b = c*w`, which leaves `w` free when `c = 0`. v1 **pins it to zero**,
  the value the frozen runner's batch inversion produces, so the transaction is
  canonical. A nonzero witness is `BAD_INVERSE`. `dest_pc` and `dest_fp` MUST
  both be zero (`BAD_BRANCH_PROPOSAL` otherwise). Then `pc` advances by 1 and
  `fp` is unchanged.

`JUMP` writes no cells.

### 7.6 `BLAKE3_REQUEST` (`0x08`) — 190 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | preamble | |
| 14 | `u32le`×4 | `ins[0..3]` — message word offsets |
| 30 | `u32le` | `cv` — chaining-value base offset |
| 34 | `u32le` | `out` — digest base offset |
| 38 | `f128le` | `metadata` (`counter:u64 \| block_len:u32 \| flags:u32`, LE) |
| 54 | `cell`×4 | cells at `fp + ins[i]` |
| 122 | `cell`×2 | cells at `fp + cv`, `fp + cv + 1` |
| 156 | `cell`×2 | cells at `fp + out`, `fp + out + 1` |

Each message word is addressed independently — there is no forced contiguity,
per `isa.rs`. The chaining value and the output each occupy two consecutive
words. Access order is `ins[0..3], cv, cv+1, out, out+1`.

This opcode does **not** complete in one exchange; it suspends the transaction
and raises a service request ([§11](#11-service-request-and-response-contract)).

### 7.7 `NEGOTIATE` (`0x10`) — 7 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u8` | `version_min` |
| 1 | `u8` | `version_max` |
| 2 | `u8` | requested `profile` |
| 3 | `u32le` | `host_features` (advisory; v1 ignores it) |

Permitted only in `IDLE` (`BAD_STATE` otherwise). If `version_min <= 1 <=
version_max` does not hold, the reply is `BAD_VERSION` and the active profile is
unchanged. An unrecognized profile is `BAD_PROFILE`.

### 7.8 `SERVICE_RESPONSE` (`0x11`) — 42 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` |
| 4 | `u32le` | `service_id` |
| 8 | `u8` | `service_kind` |
| 9 | `u8` | reserved, MUST be `0x00` |
| 10 | `f128le` | digest word 0 |
| 26 | `f128le` | digest word 1 |

### 7.9 `RETIRE` (`0x12`) — 8 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` |
| 4 | `u32le` | `result_crc` — CRC-32 of the result **payload** |

`result_crc` is computed over the result payload alone ([§8.1](#81-result-ok)),
not over the enclosing response frame. It is the host's proof that it read the
result the endpoint actually produced.

### 7.10 `STATUS_QUERY` (`0x13`) — 0 bytes

Legal in every state and never changes any state.

## 8. Response payload schemas

### 8.1 Result (`OK`)

Emitted when an instruction transaction has been decided and is awaiting
retirement.

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` |
| 4 | `u32le` | `next_pc` |
| 8 | `u32le` | `next_fp` |
| 12 | `u8` | `n_writes` |
| 13 | `write`×`n_writes` | each: `u32le` address, `f128le` value (20 bytes) |
| … | `u8` | `n_deferred` |
| … | `deferred`×`n_deferred` | each: `u32le` target, `u32le` local (8 bytes) |
| … | `u8` | `n_accesses` |
| … | `u32le`×`n_accesses` | accessed addresses, in the frozen access order |

Size: `15 + 20*n_writes + 8*n_deferred + 4*n_accesses` bytes.

The **access list** is the ordered record of the addresses the transition
touched. The host owns access counting; the endpoint reports the order so the
host can bump its own counters consistently with the frozen runner.

The **deferred list** carries `DEREF_CELL` equalities the endpoint could not
resolve because neither side was written ([§12.3](#123-deref_cell)). The
endpoint never resolves them; the frozen runner patches them after the walk,
which is a whole-trace operation and therefore host work.

### 8.2 `SERVICE_REQUIRED` — 122 bytes

See [§11](#11-service-request-and-response-contract).

### 8.3 `RETIRED` — 16 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` |
| 4 | `u32le` | `retire_seq` — count of retirements since reset |
| 8 | `u32le` | committed `pc` |
| 12 | `u32le` | committed `fp` |

### 8.4 `OK` to `NEGOTIATE` — 14 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u8` | protocol version (`1`) |
| 1 | `u8` | active profile |
| 2 | `u16le` | `MAX_PAYLOAD_BYTES` (`256`) |
| 4 | `u8` | `INDEX_BITS` (`16`) |
| 5 | `u8` | reserved (`0x00`) |
| 6 | `u32le` | device features |
| 10 | `u32le` | device id (`0x4C534331`, "LSC1") |

Device feature bits: `0` forward-only profile, `1` interpreter-compatible
profile, `2` BLAKE3 service offload.

### 8.5 `INFO` (status query) — 20 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u8` | transaction state (`0x00` idle, `0x01` result pending, `0x02` service pending) |
| 1 | `u32le` | `txn_id` of the staged transaction, else `0` |
| 5 | `u8` | last status |
| 6 | `u32le` | `retire_seq` |
| 10 | `u8` | last fault |
| 11 | `u32le` | committed `pc` |
| 15 | `u32le` | committed `fp` |
| 19 | `u8` | committed state valid |

`committed pc`/`fp` are meaningless until `state valid` is `1`, which happens on
the first retirement after reset.

### 8.6 Fault — 5 bytes

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` if the frame decoded far enough to carry one, else `0` |
| 4 | `u8` | detail, a non-normative disambiguator |

The `detail` byte MUST NOT be interpreted as load-bearing; it exists for
diagnosis. Only `status` is normative.

Every fault response is 14 bytes on the wire.

## 9. Status and fault codes

Codes at or above `0x80` are faults and drive the `FAULT` pin.

| Status | Code | Meaning |
| --- | --- | --- |
| `OK` | `0x00` | request accepted; result or negotiation payload follows |
| `SERVICE_REQUIRED` | `0x01` | transaction suspended pending a host service |
| `RETIRED` | `0x02` | transaction committed |
| `INFO` | `0x03` | status query reply |
| `BAD_SOF` | `0x80` | first byte of a frame was not `0xA1` |
| `BAD_VERSION` | `0x81` | unsupported envelope version, or negotiation window excludes v1 |
| `BAD_OPCODE` | `0x82` | unrecognized opcode |
| `BAD_LENGTH` | `0x83` | declared length above the cap, wrong for the opcode, or payload truncated/overrun |
| `BAD_CRC` | `0x84` | frame CRC mismatch |
| `BAD_FLAGS` | `0x85` | reserved flag or reserved payload byte not zero |
| `BAD_PROFILE` | `0x86` | unrecognized profile, or request profile is not the active one |
| `BAD_STATE` | `0x87` | opcode not legal in the current transaction state |
| `BAD_CELL` | `0x88` | non-canonical cell encoding |
| `U32_OVERFLOW` | `0x89` | address arithmetic exceeded `u32` |
| `BAD_POINTER` | `0x8A` | proposed index does not re-encode to the operand |
| `BAD_INVERSE` | `0x8B` | proposed inverse failed verification, or a non-zero witness on an untaken branch |
| `WRITE_CONFLICT` | `0x8C` | transition would rewrite a written cell with a different value |
| `DEREF_MISMATCH` | `0x8D` | both `DEREF_CELL` sides written and unequal |
| `MUL_BACKSOLVE_ZERO` | `0x8E` | back-solve requested through a zero operand |
| `BAD_BRANCH_PROPOSAL` | `0x8F` | declared branch outcome or targets contradict the condition |
| `UNSUPPORTED_IN_PROFILE` | `0x90` | shape is legal in the other profile only |
| `BAD_SERVICE` | `0x91` | service response does not match the outstanding request |
| `RETIRE_MISMATCH` | `0x92` | retire `txn_id` or `result_crc` does not match |
| `ABORTED` | `0x93` | terminated by `ABORT` |
| `STATE_MISMATCH` | `0x94` | request `(pc, fp)` is not the committed state |
| `INDEX_RANGE` | `0x95` | index at or above `2**INDEX_BITS` |
| `ALIAS_INCONSISTENT` | `0x96` | two operands name one address with disagreeing cells |

### 9.1 What a fault does to an outstanding transaction

This distinction is normative.

- A fault raised **before the endpoint touches the staged transaction** —
  framing faults (`BAD_SOF` … `BAD_FLAGS`), the guard faults `BAD_STATE`,
  `BAD_PROFILE`, `STATE_MISMATCH`, `INDEX_RANGE` on a preamble, and
  `BAD_SERVICE` — is a rejection of *that frame only*. Any transaction already
  staged survives untouched. A duplicate, stale or corrupt frame therefore
  cannot destroy decided work. `BAD_SERVICE` is checked before the digest is
  folded in, so a suspended transaction stays in `SERVICE_PENDING` and the host
  may retry it with a correctly addressed `SERVICE_RESPONSE`; only a digest that
  reaches the write-once rule and fails it discards the transaction.
- A fault raised **while deciding a transition** leaves nothing staged; the
  transition never existed.
- A fault raised **after the endpoint began folding host input into a staged
  transition** discards that transaction. This covers `WRITE_CONFLICT` from a
  service digest, and `RETIRE_MISMATCH`. In the retire case the host and the
  endpoint disagree about what was decided, and re-requesting is safer than
  retiring a result the host may never have read correctly.

In no case does a fault move committed `pc`, `fp` or `retire_seq`.

## 10. Transaction state machine

Three states. Exactly one transaction may be outstanding.

```
                    instruction opcode, decided
        ┌──────────────────────────────────────────────────┐
        │                                                  ▼
   ┌─────────┐                                    ┌────────────────┐
   │  IDLE   │                                    │ RESULT_PENDING │
   └─────────┘                                    └────────────────┘
        ▲   │                                          │        ▲
        │   │ BLAKE3_REQUEST                           │        │
        │   ▼                                RETIRE ok │        │ SERVICE_RESPONSE ok
        │ ┌─────────────────┐                          │        │
        │ │ SERVICE_PENDING │──────────────────────────┼────────┘
        │ └─────────────────┘                          │
        └──────────────────────────────────────────────┘
```

| State | Legal opcodes | Effect |
| --- | --- | --- |
| `IDLE` | instruction opcodes, `NEGOTIATE`, `STATUS_QUERY` | instruction stages a transition; `BLAKE3_REQUEST` goes to `SERVICE_PENDING`, everything else to `RESULT_PENDING` |
| `RESULT_PENDING` | `RETIRE`, `STATUS_QUERY` | successful `RETIRE` commits and returns to `IDLE` |
| `SERVICE_PENDING` | `SERVICE_RESPONSE`, `STATUS_QUERY` | matching response resumes the transition, moving to `RESULT_PENDING` |

`ABORT` and reset return to `IDLE` from any state
([§15](#15-abort-reset-and-framing-recovery)).

### 10.1 Retirement

Retirement is the **only** operation that changes committed state, and a given
transaction retires **at most once**.

1. The endpoint decides the transition and emits the result payload. Committed
   `pc`, `fp`, `state_valid` and `retire_seq` are unchanged. Nothing about the
   transition is observable to any later transaction.
2. The host reads the result, computes the CRC-32 of the result payload, and
   sends `RETIRE` carrying `txn_id` and that CRC.
3. The endpoint checks both. On success it sets committed `pc`/`fp` to
   `next_pc`/`next_fp`, sets `state_valid`, increments `retire_seq`, pulses
   `DONE`, and returns to `IDLE`. On failure it discards
   ([§9.1](#91-what-a-fault-does-to-an-outstanding-transaction)).

A second `RETIRE` for the same transaction finds `IDLE` and is `BAD_STATE`. The
endpoint holds no per-`txn_id` history, so `txn_id` reuse is a host concern; the
`retire_seq` counter is the endpoint-side monotone witness.

## 11. Service request and response contract

BLAKE3 compression is a host service. It is never an LSC-1 datapath
(`docs/DECISIONS.md` D-004). Only `BLAKE3_COMPRESS` (`kind = 0x01`) is defined
in v1.

`BLAKE3_REQUEST` suspends the transaction and emits `SERVICE_REQUIRED` with a
122-byte payload:

| Offset | Type | Field |
| --- | --- | --- |
| 0 | `u32le` | `txn_id` |
| 4 | `u32le` | `service_id` — monotone per endpoint, from `1`, reset by reset |
| 8 | `u8` | `service_kind` (`0x01`) |
| 9 | `u8` | reserved (`0x00`) |
| 10 | `f128le`×4 | the four message words, in `ins` order |
| 74 | `f128le`×2 | the two chaining-value words |
| 106 | `f128le` | `metadata` |

The host compresses and replies with `SERVICE_RESPONSE` ([§7.8](#78-service_response-0x11--42-bytes)).
The endpoint checks `txn_id`, `service_id` and `service_kind` (`BAD_SERVICE`
otherwise), then writes the two digest words to `fp+out` and `fp+out+1` under
the write-once rule and moves to `RESULT_PENDING`.

**The endpoint does not verify the digest.** BLAKE3 is not recomputable on
LSC-1 at any acceptable cost, and unlike an inverse or a g-power it has no cheap
verifier. A dishonest host can substitute any digest. This is an explicit,
accepted trust delegation ([§14.3](#143-unverified-delegation)); soundness for
the digest rests on the proof system, not on LSC-1.

A `WRITE_CONFLICT` between the digest and an already-written output cell
discards the transaction. The host does not get to propose a second digest for
the same transaction.

## 12. Profiles and negotiation

The frozen sources do not agree with themselves about `XOR`, `MUL_NATIVE` and
`DEREF_CELL`. Rather than silently pick a reading, v1 carries **both** as
profiles, and the request preamble names the one it assumes.

| Profile | Code | Reading |
| --- | --- | --- |
| `FORWARD_ONLY` | `0x00` | `misc/doc.tex`: forward constraints only |
| `INTERPRETER_COMPAT` | `0x01` | `crates/lean_vm/src/cpu/execute.rs`: relational back-solving and four-quadrant reconciliation |

The default active profile after reset is `INTERPRETER_COMPAT`, because the
executable runner is what actually produces upstream traces.

`NEGOTIATE` sets the active profile. Every instruction request repeats the
profile in its preamble; a mismatch with the active profile is `BAD_PROFILE`.
The redundancy is deliberate — a host cannot get a differently-interpreted
transition by losing track of a negotiation.

Shapes that are legal only in the other profile are `UNSUPPORTED_IN_PROFILE`,
which is distinct from `BAD_PROFILE` (an unrecognized or non-active profile).

### 12.1 What the profiles do not change

Framing, sizes, status codes, the state machine, retirement, verification of
proposals, `SET_CONSTANT`, `DEREF_PC`, `DEREF_FP`, `JUMP`, `BLAKE3` and the
access-order records are identical in both profiles. Only the three cases below
differ.

### 12.2 `XOR`/`MUL_NATIVE`

`execute.rs` computes the forward result *and*, when the destination cell is
already written and exactly one operand is absent, back-solves the missing
operand first — `vc + vk` for `XOR`, `vc * vk.inv()` for `MUL_NATIVE`, which
`assert!`s that `vk` is non-zero.

| Situation | `INTERPRETER_COMPAT` | `FORWARD_ONLY` |
| --- | --- | --- |
| both operands present | forward-compute, write once | same |
| destination written, exactly one operand absent | back-solve the absent operand, then forward-compute | `UNSUPPORTED_IN_PROFILE` |
| any operand absent otherwise | absent reads as zero, forward-compute | `UNSUPPORTED_IN_PROFILE` |

In `INTERPRETER_COMPAT` the back-solved operand is visible to the forward step,
so the forward write is consistent by construction. `MUL_NATIVE` back-solving
requires the verified host inverse ([§14.1](#141-verified-proposals)); a zero
known operand is `MUL_BACKSOLVE_ZERO`, matching the upstream assertion.

Note the corner where the destination is written and *both* operands are absent:
`INTERPRETER_COMPAT` does not back-solve (the condition is exactly one absent),
forward-computes zero, and therefore reports `WRITE_CONFLICT` unless the
destination already holds zero. This reproduces the frozen runner.

### 12.3 `DEREF_CELL`

Let `T` be the target cell at `base + beta` and `L` the local cell at
`fp + gamma`.

| `T` written | `L` written | `INTERPRETER_COMPAT` | `FORWARD_ONLY` |
| --- | --- | --- | --- |
| yes | yes | assert `T == L`, no write | same |
| yes | no | write `L := T` | `UNSUPPORTED_IN_PROFILE` |
| no | yes | write `T := L` | write `T := L` |
| no | no | emit a deferred equality `(target, local)` | `UNSUPPORTED_IN_PROFILE` |

`doc.tex` states the forward store `v2 = v3`, so `FORWARD_ONLY` requires the
local side to exist. Unequal written sides are `DEREF_MISMATCH` in both
profiles.

## 13. Byte and cycle budgets

### 13.1 Stated assumptions

These are **assumptions, not measurements**. No simulation, synthesis or
silicon result is implied. They are declared in `BudgetAssumptions` in
`sim/lsc1_transaction.py` and are the sole basis of every figure below.

| Assumption | Cycles | Note |
| --- | --- | --- |
| `beat` | 1 | one committed byte per clock at full rate, no stalls |
| `field_mul` | 128 | bit-serial `GF(2^128)` multiply |
| `field_xor` | 1 | field addition |
| `xtime` | 1 | multiply by the generator |
| `compare` | 1 | 128-bit equality |
| `decode` | 2 | fixed per-frame decode overhead |

Derived: re-deriving `g**n` by square-and-multiply over `INDEX_BITS = 16` costs
`16 * (field_mul + xtime) = 2064` cycles. This dominates every opcode that
verifies a pointer or encodes an index, and it is the obvious first target if
these budgets ever need to shrink.

Stalls and backpressure add cycles one-for-one and change nothing else.

### 13.2 Worst-case per opcode, `INTERPRETER_COMPAT`

`round trip` is request in, decode, execute, result out, any service exchange,
`RETIRE` in (18 bytes), decode, and the `RETIRED` response out (25 bytes).

| Opcode | Request bytes | Result bytes | Service bytes | Execute cycles | Round trip cycles |
| --- | --- | --- | --- | --- | --- |
| `XOR` | 87 | 76 | 0 | 2 | 212 |
| `MUL_NATIVE` | 104 | 76 | 0 | 384 | 611 |
| `SET_CONSTANT` | 61 | 48 | 0 | 0 | 156 |
| `DEREF_CELL` | 91 | 56 | 0 | 2065 | 2259 |
| `DEREF_PC` | 91 | 56 | 0 | 4128 | 4322 |
| `DEREF_FP` | 91 | 56 | 0 | 4128 | 4322 |
| `JUMP` | 113 | 36 | 0 | 4257 | 4453 |
| `BLAKE3_REQUEST` | 200 | 96 | 183 | 0 | 526 |

### 13.3 Worst-case per opcode, `FORWARD_ONLY`

Only `XOR` and `MUL_NATIVE` differ; refusing back-solving removes the inverse
verification and the back-solve product.

| Opcode | Request bytes | Result bytes | Service bytes | Execute cycles | Round trip cycles |
| --- | --- | --- | --- | --- | --- |
| `XOR` | 87 | 76 | 0 | 1 | 211 |
| `MUL_NATIVE` | 104 | 76 | 0 | 128 | 355 |
| `SET_CONSTANT` | 61 | 48 | 0 | 0 | 156 |
| `DEREF_CELL` | 91 | 56 | 0 | 2065 | 2259 |
| `DEREF_PC` | 91 | 56 | 0 | 4128 | 4322 |
| `DEREF_FP` | 91 | 56 | 0 | 4128 | 4322 |
| `JUMP` | 113 | 36 | 0 | 4257 | 4453 |
| `BLAKE3_REQUEST` | 200 | 96 | 183 | 0 | 526 |

### 13.4 Control frames

| Exchange | Request bytes | Response bytes |
| --- | --- | --- |
| `NEGOTIATE` | 17 | 23 |
| `STATUS_QUERY` | 10 | 29 |
| `RETIRE` | 18 | 25 |
| `SERVICE_RESPONSE` | 52 | — |
| any fault | — | 14 |

`BLAKE3_REQUEST`'s 183 service bytes are the 131-byte `SERVICE_REQUIRED`
response plus the 52-byte `SERVICE_RESPONSE` request.

## 14. Trust boundary

The host is **not** trusted. The endpoint's guarantees are exactly those in the
"endpoint enforces" column; everything in the "host owns" column is the host's
own correctness problem and is out of LSC-1's scope.

| Concern | Host owns | Endpoint enforces |
| --- | --- | --- |
| program and memory image | yes | nothing — never sees them |
| written bitmap | yes | write-once consistency within one transition |
| pointer map (`g`-power to index) | yes | `encode(base) == pointer` |
| multiplicative inverse | proposes | `known * proposed == 1` |
| branch outcome | proposes | recomputed from the condition |
| branch targets | proposes | `encode(dest) == operand` |
| BLAKE3 digest | computes | **nothing** ([§14.3](#143-unverified-delegation)) |
| access counts | yes | reports the frozen access order |
| deferred equalities | resolves | reports them, never resolves |
| trace persistence | yes | nothing |
| scalar transition decision | no | decides it |
| `(pc, fp)` continuity | no | `STATE_MISMATCH` on any fork or rewind |
| retirement | acknowledges | at most once, bound to the result CRC |

### 14.1 Verified proposals

Where verification is cheaper than computation, the host proposes and the
endpoint checks:

- **inverses** — `x**(2**128 - 2)` costs 127 squarings and 126 multiplies; one
  verifying multiply costs `field_mul` (`docs/DECISIONS.md` D-003);
- **g-power indices** — the frozen runner uses a `gmap` hash table the endpoint
  cannot hold; re-encoding by square-and-multiply is `2064` cycles and needs no
  storage;
- **branch outcomes** — recomputed outright, since a 128-bit comparison against
  zero is cheaper than any witness scheme.

A failed verification is always a fault, never a fallback to computing the value
the endpoint could not check.

### 14.2 Index bound

`INDEX_BITS = 16` bounds every host-proposed index (`pc`, `fp`, `base`,
`dest_pc`, `dest_fp`) below `2**16`. It is the frozen `MIN_LOG_MEM` from
`cpu/mod.rs`, and it is what makes re-encoding a fixed 2064-cycle operation
rather than an unbounded one. Upstream permits memory exponents up to
`MAX_LOG_MEM = 32`; **LSC-1 v1 does not cover programs beyond `2**16`**. Raising
the bound is a v2 negotiation parameter, which is why `INDEX_BITS` is reported
in the `NEGOTIATE` response rather than assumed.

### 14.3 Unverified delegation

The BLAKE3 digest is the one input the endpoint accepts without checking. This
is stated here rather than buried because it is the single largest hole in the
endpoint's guarantees: a dishonest host controls the digest words written to
`fp+out` and `fp+out+1`. LSC-1 constrains everything *around* that write —
addresses, write-once behaviour, access order, retirement — but not its value.

## 15. Abort, reset and framing recovery

### 15.1 `ABORT`

`ABORT` is sampled before any candidate transfer on the same clock edge and
cancels it: neither an `RX` nor a `TX` beat commits on an aborting edge, even if
both `VALID` and `READY` were asserted. The endpoint then discards the partial
frame, any pending response bytes, and any staged transaction; sets the last
status to `ABORTED` (so `FAULT` is high); and returns to `IDLE`.

`ABORT` **never** moves committed `pc`, `fp` or `retire_seq`, and never
retroactively undoes a retirement that already succeeded. Aborting at any byte
boundary of any frame leaves the endpoint reusable for a fresh transaction.

Negotiated profile survives abort; it is state the host set deliberately, not
transaction state.

### 15.2 Reset

`reset_n` low takes priority over `ABORT` and over any transfer. It restores
every field to its power-on value: `IDLE`, default profile, committed `pc` and
`fp` zero, `state_valid` false, `retire_seq` zero, `service_seq` zero, buffers
empty, `FAULT` low.

### 15.3 Framing recovery

The `length` field is what tells the endpoint where a frame ends, so a
corruption inside it is the one case the CRC cannot catch in time:

- **length above the cap** — rejected immediately at the header with
  `BAD_LENGTH`; the receive buffer is cleared and the host may start a new
  frame at once.
- **length inside the cap but too large** — the endpoint waits for bytes the
  host never intended to send. There is no in-band resynchronization. Recovery
  is the host's timeout plus `ABORT`.
- **length too small** — the endpoint dispatches a prefix, which fails the CRC
  check; the trailing bytes are not a frame and are rejected as they arrive.
  The host should `ABORT` rather than rely on incidental resynchronization.

Every other single-bit corruption anywhere in a frame is caught by the CRC and
answered with a fault, leaving no staged transaction and no state movement.

## 16. Frozen-source differences

Differences between the frozen sources, and how v1 resolves each. See also
`docs/SEMANTIC_DIFFERENCES.md`.

### 16.1 `DEREF_PC` stores `encode(pc + 2)`

`isa.rs` documents the `DEREF` source as "the return address `pc+γ`". **This
comment is stale.** `execute.rs` writes `gpow[pc + 2]`, and `doc.tex` gives the
store constraint

```
v2 = (1 + f_pc + f_fp)·v3 + f_pc·(g²·pc) + f_fp·fp
```

where `g²·pc` is `encode(pc + 2)` under the exponent isomorphism. Two
independent authorities agree against one comment, so **v1 implements
`encode(pc + 2)`** and records the discrepancy here. The two readings are
distinguishable whenever `gamma != 2`, and `sim/test_lsc1_transaction.py`
asserts against the stale reading explicitly.

### 16.2 Relational versus forward semantics

`execute.rs` back-solves `XOR`/`MUL_NATIVE` operands and reconciles four
`DEREF_CELL` quadrants; `doc.tex` states forward constraints. Both are preserved
as profiles ([§12](#12-profiles-and-negotiation)). Neither is declared correct
by this document.

### 16.3 `beta` as exponent versus field element

`execute.rs` treats `beta` as a `u32` exponent and computes the address
`base + beta`; `doc.tex` writes the address as multiplication by `g**beta`.
These are the same address under the exponent isomorphism. v1 transmits the
exponent, matching `execute.rs`, because the endpoint works in indices.

### 16.4 `u32` overflow

Rust `u32` addition panics in debug builds and wraps in release builds, so the
frozen runner has no single defined overflow behaviour. The external ABI is
specified with **checked** `u32` semantics: an address computation exceeding
`u32` is `U32_OVERFLOW`, never a wrap. This matches the debug runner and
`sim/scalar_step_oracle.py`. A host that requires release-build wrapping is not
supported by v1; that would be a distinct compatibility profile and is not
defined here.

### 16.5 Untaken-branch witness

`doc.tex` constrains the inversion witness only through `b = c·w`, leaving `w`
unconstrained when `c = 0`. The frozen runner's batch inversion fills zero. v1
pins it to zero so that a transaction has one canonical encoding
([§7.5](#75-jump-0x07--103-bytes)).

## 17. Deliberately unresolved

Recorded rather than silently decided:

1. **Which profile the pivot targets.** Both are specified and implemented;
   `INTERPRETER_COMPAT` is merely the default. Choosing one is a project
   decision, not a protocol one.
2. **Indices above `2**16`.** Upstream allows `MAX_LOG_MEM = 32`. v1 caps at
   `INDEX_BITS = 16` to keep pointer verification a fixed cost, and reports the
   cap during negotiation so a v2 can raise it.
3. **Release-build wrapping `u32` semantics** ([§16.4](#164-u32-overflow)).
4. **`txn_id` reuse.** The endpoint keeps no per-`txn_id` history; `retire_seq`
   is the only endpoint-side monotone witness.
5. **Multi-instruction batching.** One transaction at a time is a deliberate
   v1 constraint, not a transport limitation.
6. **Digest verification** ([§14.3](#143-unverified-delegation)).
