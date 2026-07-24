# MinCore byte-stream protocol

## Physical Tiny Tapeout mapping

The top module is `tt_um_leanvm_b_mincore`.

### Dedicated buses

| Pins | Direction | Meaning |
|---|---|---|
| `ui_in[7:0]` | host → ASIC | receive byte |
| `uo_out[7:0]` | ASIC → host | transmit byte |

### Bidirectional pins

The directions are fixed by `uio_oe = 8'b10110110`.

| Pin | Direction | Meaning |
|---|---|---|
| `uio[0]` | input | `RX_VALID` |
| `uio[1]` | output | `RX_READY` |
| `uio[2]` | output | `TX_VALID` |
| `uio[3]` | input | `TX_READY` |
| `uio[4]` | output | `BUSY` |
| `uio[5]` | output | sticky `FAULT` |
| `uio[6]` | input | synchronous `ABORT` |
| `uio[7]` | output | one-cycle `DONE_PULSE` |

`rst_n` is the Tiny Tapeout active-low reset. `ena` is ignored.

## Handshake

An input byte is accepted on a rising edge when:

```text
RX_VALID && RX_READY
```

The host must keep `ui_in` and `RX_VALID` stable until acceptance.

An output byte is accepted on a rising edge when:

```text
TX_VALID && TX_READY
```

For the combinational stream commands, `TX_VALID` depends on `RX_VALID` and
`RX_READY` depends on `TX_READY`. The host must follow ordinary ready/valid
rules: it may not wait for `RX_READY` before asserting `RX_VALID`.

The dedicated input and output buses allow simultaneous input and output
handshakes.

## Byte order

A 128-bit value `v` is transferred as:

```text
v[7:0], v[15:8], ..., v[127:120]
```

This matches leanVM-b's canonical little-endian `F128` byte representation.

## Commands

### `0x01 XOR128`

Input payload:

```text
A[0], B[0], A[1], B[1], ..., A[15], B[15]
```

On every B-byte handshake, the same edge also transfers:

```text
A[i] xor B[i]
```

Only one saved A byte is stored. Under no stalls, the transaction takes the
minimum 33 cycles: one command and 32 input beats. There is no drain cycle.

### `0x02 MUL128`

Input payload:

```text
A[0] ... A[15], B[0] ... B[15]
```

Output is `A * B` in the leanVM-b GHASH field.

A is loaded sequentially into the sole shifted-multiplicand register. Each B
byte is consumed least-significant bit first. Bit zero is processed on the
receive edge; bits one through seven occupy the shared scratch register with an
in-band sentinel, eliminating a sub-bit counter. B is never stored as a word.

The accumulator is destructively shifted by one byte after each output
handshake, eliminating a 16-way output-byte mux.

No-stall latency is 161 cycles:

```text
1 command + 16 A-load + 128 multiplier-bit + 16 output
```

### `0x03 SET128`

Each of the 16 input bytes is passed directly to the output on the same
handshake. This models the streaming data path used by `SET_CONSTANT`; the full
core will attach the destination memory transaction. No-stall latency is the
minimum 17 cycles.

### `0x04 NONZERO`

Consumes 16 bytes and returns:

```text
0x00  when every input byte is zero
0x01  otherwise
```

The response transfers atomically with the final input byte. This is the
control predicate needed by `JUMP`. No-stall latency is the minimum 17 cycles.

### `0x7d CLEAR`

Clears sticky `FAULT`. It has no response; `DONE_PULSE` is asserted on command
acceptance.

### `0x7e STATUS`

Returns four bytes:

```text
01 01 0f 08
```

They mean protocol version 1.1, command mask `0x0f`, and an 8-bit external lane.

## Errors and abort

An unknown command sets `FAULT` and returns `0xe0`. An impossible internal FSM
state also sets `FAULT` and enters the same error response state.

`ABORT` synchronously returns the engine to IDLE, resets multiplier state, and
sets sticky `FAULT`.

## Why no packet length or checksum?

Every command has a fixed payload and response length, and the intended first
connection is a synchronous on-board RP2040 PIO or FPGA bridge. Removing generic
framing saves state and decoder logic. A USB/UART bridge should add framing and
integrity checks outside the ASIC.

## Extension path

The full VM core can retain the same physical signals and place a byte-coded RPC
layer above them. Candidate request/response messages are specified in
[`FULL_CORE.md`](FULL_CORE.md). More tiles do not add user pins, so preserving a
narrow, reusable service bus is important.
