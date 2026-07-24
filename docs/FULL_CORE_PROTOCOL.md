# Draft full-core service protocol

This is the next-stage protocol layered on the same physical 8-bit buses. It is
not implemented by the current MinCore RTL. It fixes message shapes early so
the host bridge, FPGA model, and future ASIC controller can evolve together.

## Transport rules

- ASIC is the request master while a program is running.
- At most one request is outstanding; no transaction tag is required.
- First byte selects a fixed request or response shape.
- All `u32` values and `F128` words are little-endian.
- Host responses are returned on `ui_in`; ASIC requests use `uo_out`.
- `FAULT` is asserted on an unexpected response type or nonzero status.

## ASIC-to-host requests

| Code | Name | Payload |
|---:|---|---|
| `0x10` | `FETCH` | `pc_index:u32` |
| `0x11` | `READ_CELL` | `address:u32` |
| `0x12` | `READ_POINTER` | `address:u32` |
| `0x13` | `WRITE_ONCE` | `address:u32, value:F128` |
| `0x14` | `DEFER_EQUALITY` | `left:u32, right:u32` |
| `0x15` | `ENCODE_ADDRESS` | `index:u32` |
| `0x16` | `INVERT_FIELD` | `value:F128` |
| `0x17` | `BLAKE3_COMPRESS` | six input `F128`, metadata `F128` |
| `0x18` | `BUMP_ACCESS_COUNT` | `address:u32` |
| `0x19` | `TRACE_EVENT` | fixed event header followed by opcode data |
| `0x1f` | `HALT` | final `pc:u32, fp:u32, status:u8` |

`INVERT_FIELD` exists because the current interpreter can back-solve a MUL when
one operand is missing. Keeping inversion outside v1 avoids a large field
inverter in the ASIC.

## Host-to-ASIC responses

| Code | Name | Payload |
|---:|---|---|
| `0x90` | `FETCH_RESULT` | instruction encoding below |
| `0x91` | `CELL_RESULT` | `status:u8, written:u8, value:F128` |
| `0x92` | `POINTER_RESULT` | `status:u8, written:u8, value:F128, index_valid:u8, index:u32` |
| `0x93` | `WRITE_ACK` | `status:u8` |
| `0x94` | `DEFER_ACK` | `status:u8` |
| `0x95` | `ENCODE_RESULT` | `status:u8, value:F128` |
| `0x96` | `INVERT_RESULT` | `status:u8, value:F128` |
| `0x97` | `BLAKE3_RESULT` | `status:u8, out0:F128, out1:F128` |
| `0x98` | `COUNT_RESULT` | `status:u8, old_count:F128` |
| `0x99` | `TRACE_ACK` | `status:u8` |

Suggested status values:

```text
00 OK
01 out of range
02 write-once conflict
03 unresolved/non-g-power pointer
04 division by zero / inverse unavailable
05 malformed program
06 deferred-equality resource exhausted
```

## Instruction encoding in `FETCH_RESULT`

| Opcode | Payload |
|---:|---|
| `0x00 XOR` | `a:u32, b:u32, c:u32` |
| `0x01 MUL` | `a:u32, b:u32, c:u32` |
| `0x02 SET` | `o:u32, k:F128` |
| `0x03 DEREF_CELL` | `alpha:u32, beta:u32, gamma:u32` |
| `0x04 DEREF_PC` | `alpha:u32, beta:u32, gamma:u32` |
| `0x05 DEREF_FP` | `alpha:u32, beta:u32, gamma:u32` |
| `0x06 JUMP` | `oc:u32, od:u32, of:u32` |
| `0x07 BLAKE3` | `ins[4]:u32, cv:u32, out:u32, metadata:F128` |
| `0xff SENTINEL` | no payload |

These preserve the current Rust `u32` offsets without a 24-bit packing format.

## Memory consistency responsibility

The host service owns:

- value array;
- written bitmap;
- `g^i -> i` reverse map;
- access counts;
- deferred DEREF equality list;
- instruction storage;
- BLAKE3 implementation;
- trace persistence.

The ASIC owns instruction sequencing, arithmetic, branch decision, address-index
addition, and verification that every response matches the outstanding request.

This partition is intentionally explicit: every external assumption can later
be replaced by FPGA/ASIC logic and added to the refinement theorem one service
at a time.
