# LSC-1µ (LSC-1 Micro) architecture contract

> **LSC-1µ is a deliberately reduced Tiny Tapeout profile/sub-core of LSC-1.**
> It is not “LSC-1/2”, not LSC-2, and not a second-generation architecture.
> Full LSC-1 remains unchanged for FPGA and future larger ASIC targets.
> ASCII contexts use `LSC-1u` and `lsc1u`.

## Retained semantic boundary

LSC-1µ accepts fixed-width byte-streamed micro-operations:

| Opcode | Operation | Accepted payload | Response |
| --- | --- | --- | --- |
| `0x01` | GF(2¹²⁸) XOR | `A0,B0,...,A15,B15` | `A XOR B`, 16 bytes |
| `0x02` | GF(2¹²⁸) MUL | `A0..A15,B0..B15` | `A × B`, 16 bytes |
| `0x03` | SET | `V0..V15` | `V`, 16 bytes |

All retained values use the exact LSC-1 convention: byte 0 and bit 0 are
least-significant; multiplication is in GF(2¹²⁸) modulo
`x^128 + x^7 + x^2 + x + 1` (low reduction constant `0x87`). SET is an exact
copy and XOR is bitwise. There is no weakened or alternative arithmetic.

An unsupported opcode produces one `0xe0` response byte and asserts `FAULT`
until that byte is accepted or a new supported command is accepted.

## Explicit exclusions and host responsibilities

LSC-1µ does **not** implement LSC-1 packet framing, packet CRC, transaction
orchestration, instruction fetch or memory, DEREF/JUMP resolution, the BLAKE3
service, witnesses, or commit tracking. It never claims that an arithmetic
response represents any of those omitted behaviors. The host must validate and
frame packets, check CRCs, resolve control/memory effects, call BLAKE3, manage
witnesses/commits, and decompose authorized scalar work into these micro-ops.
The canonical `asic_core/` full LSC-1 implementation is unchanged.

## Tiny Tapeout pin protocol

`ui_in[7:0]` is RX data and `uo_out[7:0]` is TX data. Bidirectional pins are:

| Pin | Direction | Meaning |
| --- | --- | --- |
| `uio[0]` | input | `RX_VALID` |
| `uio[1]` | output | `RX_READY` |
| `uio[2]` | output | `TX_VALID` |
| `uio[3]` | input | `TX_READY` |
| `uio[4]` | output | `BUSY` |
| `uio[5]` | output | `FAULT` |
| `uio[6]` | reserved input | ignored |
| `uio[7]` | output | one-cycle `DONE_PULSE` |

A byte is accepted only on a rising edge with both VALID and READY high.
Payload width is determined solely by the accepted opcode; there is no length
field, delimiter, CRC, or full-packet buffer. The producer must hold RX data
stable while stalled. TX data remains stable while `TX_VALID && !TX_READY`.
Exactly one `DONE_PULSE` is emitted when the final response byte is accepted.

`rst_n=0` synchronously cancels partial work, clears outputs/fault, and returns
to command acceptance. When `ena=0`, all outputs and output-enables are zero,
no transfer can be accepted, and internal state is frozen. Therefore
deselect/reselect resumes the same partial operation without duplicating it.

## Physical inclusion rule for MUL

The first reduced implementation includes the existing serial multiplier, then
measures it against a SET/XOR-only build. MUL remains only if real ttsky26c
placement and routing succeeds. If it prevents routability it will be removed,
with both area measurements recorded; SET/XOR semantics are never altered to
make room.
