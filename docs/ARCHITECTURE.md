# MinCore architecture

## Objective

Minimize first-silicon area while preserving the real leanVM-b 128-bit field
operation and a clean path to a complete scalar execution system.

The circuit is intentionally not pipelined. External byte traffic dominates the
simple opcodes, while a multi-cycle FSM is easier to verify and less likely to
fail physical design.

## Block diagram

```text
ui_in + RX handshake
          │
          ▼
┌────────────────────────────┐
│ command / stream FSM       │
│                            │
│ 8-bit shared scratch       │── XOR / NONZERO / MUL tail
│ 4-bit byte counter         │
│ 4-bit state                │
│ 1-bit sticky fault         │
└────────────┬───────────────┘
             │ A bytes / B bits
             ▼
┌────────────────────────────┐
│ GF(2^128) radix-1 unit     │
│                            │
│ shifted A       128 bits   │
│ accumulator     128 bits   │
│ no B register              │
│ no internal counter        │
└────────────┬───────────────┘
             │ low result byte; destructive shift
             ▼
uo_out + TX handshake
```

## Exact source-level register budget

### Stream engine: 17 bits

| Register | Bits |
|---|---:|
| FSM state, 11 reachable states | 4 |
| byte index | 4 |
| liveness-shared scratch byte | 8 |
| sticky fault | 1 |
| **Total** | **17** |

### Multiplier: 256 bits

| Register | Bits |
|---|---:|
| shifted multiplicand | 128 |
| accumulator | 128 |
| **Total** | **256** |

### Combined

```text
17 + 256 = 273 explicit sequential bits
```

A synthesis tool may alter this count through state encoding, register sharing,
or constant propagation. The number is an exact property of the written RTL,
not a post-layout cell count.

## Multiplier invariant

After processing multiplier bits `b[0] ... b[k-1]`:

```text
accumulator = Σ_{i < k, b[i] = 1} A * x^i
shifted_A   = A * x^k
```

All operations are in `GF(2^128)`. The next transition conditionally XORs
`shifted_A` into the accumulator and applies `xtime` unless this is the final
bit.

The parent FSM supplies `bit_last`, so the multiplier needs no busy flag or
internal bit counter.

## GHASH `xtime`

For polynomial-basis value `z`:

```text
carry = z[127]
next  = (z << 1) xor (carry ? 0x87 : 0)
```

Under a two-input XOR, free-wire, free-fanout model, the fixed reduction network
uses exactly three XOR gates. Output bit 0 is exactly `carry` and is therefore a
wire; output bits 1, 2, and 7 XOR `carry` into the shifted word. Every other
output is a shifted wire.

## Area-oriented data movement

### Sequential A loading

The host sends A least-significant byte first. Instead of an indexed write into
one of 16 byte lanes, each accepted byte executes:

```text
shifted_A = {new_byte, shifted_A[127:8]}
```

After 16 transfers the register has the required little-endian word. This
removes the indexed-write decoder and its wide input mux.

### Destructive result serialization

The result output is always `accumulator[7:0]`. After each accepted output byte:

```text
accumulator >>= 8
```

This replaces a variable 16-way byte selector with wires and a fixed shift at
the register input.

### XOR

A conventional implementation would retain one or both 128-bit operands. The
protocol interleaves corresponding bytes. The engine stores A[i], then emits
`A[i] xor B[i]` combinationally while accepting B[i]. It needs eight XOR gates
and one saved byte, with no result register.

### SET

Input and output handshakes occur atomically. The circuit is an 8-bit wire path
plus control.

### NONZERO

One bit accumulates whether any prior byte was nonzero. On byte 15, the circuit
ORs that bit with the current byte test and emits the answer on the same edge.

### MUL B tail

Bit zero is consumed when each B byte arrives. The register is then loaded as:

```text
{sentinel, B[7:1]}
```

It shifts right after every remaining bit. When bits `[7:1] == 1`, bit zero is
B[7], the final data bit in that byte. The sentinel therefore replaces a
three-bit within-byte counter.

## State lower-bound perspective

For the implemented feature set, the stream-engine state is close to the
obvious representation lower bounds:

- 11 control phases require at least 4 state bits;
- 16-byte words require at least a 4-bit byte position;
- interleaved XOR requires one saved arbitrary byte, hence 8 bits;
- sticky fault reporting requires one bit.

That totals 17 bits, exactly the engine implementation. This does not prove
that no radically different protocol can use less state; it proves there is no
slack in these four explicit requirements.

## Initial physical target

A one-tile design is still unlikely: 273 sequential bits leave little room for
the 259-gate radix-1 transition, stream control, clocking, and routing. Sensible
placement attempts are:

- `1x2` / two tiles as the aggressive experiment;
- `2x2` / four tiles as the default first-tapeout target;
- `3x2` / six tiles only if timing or routing reports require it.

This is a pre-synthesis recommendation. Run the official Tiny Tapeout/OpenLane
flow before purchasing area.

## Radix alternatives

The generated design-space report is in `tools/design_space.md`.

| Radix | Direct digit-step gates | Ideal MUL transaction | Role |
|---:|---:|---:|---|
| 1 | 259 | 161 cycles | minimum direct logic, implemented |
| 2 | 518 | 97 cycles | low-cost speedup candidate |
| 4 | 1036 | 65 cycles | balanced candidate |
| 8 | 2072 | 49 cycles | protocol-minimum latency candidate |

The shared scratch/sentinel strategy means all four modeled choices retain the
same 273 explicit state bits. These gate counts use an explicit AND2/XOR2
architecture model. Standard-cell mapping may use multiplexers, compound gates,
or different sharing.
