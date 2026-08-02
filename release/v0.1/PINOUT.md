# LSC-1u pinout and micro-op protocol

This pinout is derived from `src/tt_um_lfglabs_lsc1u.sv` at source commit
`9f78b01c501b8cfd22760a35fe4cbd745865a31e`. LSC-1u is the reduced Tiny
Tapeout arithmetic sub-core; it is not the full LSC-1 packet executor.

## Dedicated pins

| Pins | Direction | Assignment |
|---|---|---|
| `ui_in[7:0]` | input | request byte, bit-for-bit |
| `uo_out[7:0]` | output | response byte, bit-for-bit |

## Bidirectional pins

| Bit | `uio_in` assignment | `uio_out` assignment | `uio_oe` while enabled |
|---:|---|---|---:|
| 0 | `RX_VALID` | constant 0 | 0 (input) |
| 1 | unused | `RX_READY` | 1 (output) |
| 2 | unused | `TX_VALID` | 1 (output) |
| 3 | `TX_READY` | constant 0 | 0 (input) |
| 4 | unused | `BUSY` | 1 (output) |
| 5 | unused | `FAULT` | 1 (output) |
| 6 | unused | constant 0 (reserved) | 0 (input) |
| 7 | unused | `DONE_PULSE` | 1 (output) |

Thus `uio_oe` is `8'b10110110` while `ena` is asserted and zero while the
design is deselected. All output values are forced to zero while deselected.

## Fixed-width micro-ops

Each transaction begins with one opcode byte accepted on `RX_VALID &&
RX_READY`. Operands and results are exactly 128 bits and are transferred least
significant byte first. There are no length fields.

| Opcode | Operation | Request bytes after opcode | Response bytes |
|---:|---|---|---|
| `0x01` | XOR | 32 bytes interleaved `A0,B0,...,A15,B15` | 16 bytes `A XOR B` |
| `0x02` | MUL | 16 bytes `A0..A15`, then 16 bytes `B0..B15` | 16-byte product |
| `0x03` | SET | 16 bytes `V0..V15` | the same 16 bytes |

MUL is carry-less multiplication in GF(2^128). Values and polynomial
coefficients are little-endian; reduction uses
`x^128 + x^7 + x^2 + x + 1`, represented by the low-byte constant `0x87`.
An unsupported opcode returns `0xE0` and asserts `FAULT` until that response is
accepted. `DONE_PULSE` marks acceptance of the final response byte.
