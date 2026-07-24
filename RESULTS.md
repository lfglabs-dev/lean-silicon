# Design result

## Selected implementation

The first Tiny Tapeout target is the **radix-1 streaming MinCore**.

```text
external lane             8 bits in + 8 bits out
field                     GF(2^128), GHASH polynomial
explicit sequential state 273 bits
radix-1 transition        128 AND2 + 131 XOR2 = 259 simple gates
ideal XOR transaction     33 cycles
ideal MUL transaction     161 cycles
ideal SET transaction     17 cycles
ideal NONZERO transaction 17 cycles
suggested TT area          2x2 tiles initially
```

The 259-gate figure covers the direct multiplier transition only, not registers,
FSM control, handshake logic, clocking, or physical-design overhead.

## Why this point was selected

All modeled radix points have the same sequential state and form a Pareto
frontier:

| Radix | State | Direct gates | MUL transaction |
|---:|---:|---:|---:|
| **1** | **273** | **259** | **161** |
| 2 | 273 | 518 | 97 |
| 4 | 273 | 1036 | 65 |
| 8 | 273 | 2072 | 49 |

Radix 1 minimizes direct logic and therefore best matches the first-tapeout goal.
Radix 8 is the minimum-latency point permitted by the declared non-overlapped
8-bit protocol. No point dominates another.

## Exact scoped results

The Lean model proves, under explicit assumptions:

- at least 16 accepted 8-bit beats are required for one arbitrary 128-bit word;
- at least 32 are required for two arbitrary words;
- XOR cannot beat 33 transaction cycles in the atomic interleaved model;
- SET and NONZERO cannot beat 17;
- radix-1 MUL cannot beat 161;
- radix-8 MUL cannot beat 49;
- the stream engine needs at least 17 state bits under its declared phase,
  position, scratch, and sticky-fault requirements;
- adding the two required 128-bit multiplier registers gives 273 bits;
- lane-local XOR requires eight single-output gates;
- exact linear-circuit enumeration (`tools/exact_linear_xor.py`) proves direct GHASH `xtime` needs exactly three reduction XOR gates;
- the direct radix-1 transition needs at least 259 gates in the declared model.

## Implemented optimizations

1. No full-word storage for XOR, SET, or NONZERO.
2. Atomic input/output handshakes remove the result holding register.
3. One scratch byte is shared by three mutually exclusive operations.
4. A is shifted directly into the sole multiplicand register.
5. B is streamed; no B word is stored.
6. An in-band sentinel replaces the multiplier sub-bit counter.
7. The parent phase replaces the multiplier busy flag and cycle counter.
8. The accumulator shifts destructively during output, removing a 16-way mux.
9. The external ABI remains byte-oriented and Tiny Tapeout-compatible.

## Evidence produced

- ten executable Python tests pass;
- all 65,536 simplified field products were exhaustively checked;
- 100,000 random GF(2^128) products matched an independent implementation;
- 1,000 randomly stalled/backpressured transactions matched the reference;
- a separate SymbiYosys harness is configured to prove the 8-bit RTL specialization;
- Lean source contains no proof placeholders or global axiom declarations;
- CI definitions are included for kernel-compiling Lean and simulating RTL.

## What is not yet established

- post-synthesis Sky130 cell count;
- routed Tiny Tapeout tile count;
- timing at 25 MHz;
- power or energy per opcode;
- correctness of the full external-memory ISA controller;
- complete leanVM-b semantics, including backward MUL deduction, deferred DEREF,
  access counters, and BLAKE3.

The next defensible optimization step is not more hand editing: it is to run
Yosys/OpenLane on the 1x2 and 2x2 floorplans and compare mapped cells, timing,
and routing congestion.
