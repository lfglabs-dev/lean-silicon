# leanVM-b MinCore

An area-first Tiny Tapeout prototype for the scalar datapath of
[`leanEthereum/leanVM-b`](https://github.com/leanEthereum/leanVM-b), frozen for
analysis at commit `c308034ab78619b39a59d26f3dc60e7df5b52649`.

The repository contains:

- synthesizable SystemVerilog for a byte-streamed 128-bit opcode engine;
- the Tiny Tapeout 8-input / 8-output / 8-bidirectional wrapper;
- the real leanVM-b `GF(2^128)` multiplier using the GHASH polynomial;
- a cycle-accurate Python model and independent field-arithmetic reference;
- exhaustive `GF(2^8)` and randomized `GF(2^128)` tests;
- a simplified Lean 4 refinement model with no `sorry`, `admit`, or global `axiom` declarations;
- exact latency lower bounds for the declared streaming models;
- a SymbiYosys harness for the 8-bit multiplier specialization;
- a design-space analysis for radix 1, 2, 4, and 8 multipliers.

## Current hardware boundary

The first circuit implements value-level operations:

| Command | Operation | Payload | Response | Ideal cycles |
|---|---|---:|---:|---:|
| `0x01` | `XOR128` | 32 interleaved bytes | 16 bytes | 33 |
| `0x02` | `MUL128` | 16 A bytes, then 16 B bytes | 16 bytes | 161 |
| `0x03` | `SET128` | 16 bytes | 16 bytes | 17 |
| `0x04` | `NONZERO` | 16 bytes | 1 byte | 17 |
| `0x7d` | clear sticky fault | none | none | 1 |
| `0x7e` | status | none | 4 bytes | 5 |

All multibyte values are little-endian. A transfer occurs on a rising edge when
both `valid` and `ready` are high.

XOR and SET produce each output byte combinationally on the same handshake that
accepts the corresponding input byte. NONZERO produces its result on the final
input handshake. This reaches the 8-bit-lane capacity bound and removes an
output register.

This is not yet an autonomous VM. Program fetch, 32-bit `pc`/`fp`, write-once
memory, pointer resolution, `DEREF`, trace construction, and BLAKE3 belong to
the full-core integration described in [`docs/FULL_CORE.md`](docs/FULL_CORE.md).

## Why this boundary first?

It isolates the hardest scalar arithmetic while keeping the circuit small and
formally tractable. The implementation deliberately avoids:

- a 128-bit multiplier-operand B register;
- a duplicate multiplicand register;
- an internal 128-cycle counter;
- an indexed A-load decoder;
- a 16-way result-byte mux;
- full-word registers for XOR, SET, or NONZERO;
- an output holding register;
- packet FIFOs.

The explicit sequential state is **273 bits**:

- 256 bits in the multiplier: shifted multiplicand and accumulator;
- 17 bits in the stream engine: FSM, byte counter, one liveness-shared scratch
  byte, and sticky fault.

## Field representation

The RTL matches leanVM-b's current `F128` representation:

```text
GF(2^128) = GF(2)[x] / (x^128 + x^7 + x^2 + x + 1)
```

Bit `i` is the coefficient of `x^i`; byte 0 is least significant. Multiplication
by `x` is a left shift followed by XOR with `0x87` when bit 127 was set.

## Local validation performed

The Python test suite currently passes:

- all 65,536 operand pairs for the simplified `GF(2^8)` model;
- 100,000 random `GF(2^128)` products against an independent carry-less
  polynomial multiplication and long reduction implementation;
- protocol-level XOR, MUL, SET, NONZERO, STATUS, CLEAR, and error tests;
- exact no-stall latency tests for every command;
- 1,000 randomized transactions with input stalls and output backpressure.

Run the checks that do not require external EDA tools:

```sh
make check
```

With the pinned Lean toolchain installed (both commands must pass):

```sh
cd lean
lake build
lake build LeanVMBMinCore
```

With Icarus Verilog installed:

```sh
make sim
```

With SymbiYosys and Boolector installed:

```sh
make formal
```

## Optimality status

The project makes only scoped, reproducible claims:

- XOR reaches the 33-cycle command-plus-input lower bound of the stated
  atomic streaming protocol.
- SET and NONZERO reach their 17-cycle bounds.
- The implemented radix-1 multiplier has minimum direct transition logic
  within the declared digit-serial family.
- A radix-8 variant would reach the 49-cycle lower bound of the non-overlapped
  multiplication transaction protocol.
- The radix 1/2/4/8 points are all Pareto-optimal under the analytical metrics
  `(sequential bits, direct digit-step gates, ideal cycles)`.

It does **not** claim globally minimum Sky130 standard-cell area. That requires
synthesis, placement, routing, timing constraints, and a fixed cell library.
See [`docs/OPTIMALITY.md`](docs/OPTIMALITY.md).

## Important source-audit findings

Independent hardware modeling exposed execution semantics not captured by a
naive six-opcode summary:

- current XOR/MUL witness generation can back-solve one missing operand when
  the result is already written;
- back-solving MUL requires field inversion and should initially be an external
  service;
- `DEREF Cell` can fill either side and defers the both-unwritten case;
- field-valued jump targets need a `g^i -> i` resolver;
- the current interpreter stores `g^(pc+2)` for `DEREF Pc`, while one source
  comment describes `pc+gamma`.

These are recorded in [`docs/SOURCE_AUDIT.md`](docs/SOURCE_AUDIT.md) and must be
resolved before claiming a complete ISA-compatible core.

## Repository map

```text
src/       synthesizable RTL and Tiny Tapeout wrapper
sim/       executable Python references and cycle model
test/      SystemVerilog testbench
formal/    SymbiYosys simplified multiplier proof
lean/      Lean 4 functional/refinement proofs
tools/     design-space and structural-check scripts
docs/      interface, architecture, full-core, and optimality specifications
```

## Verification evidence

The recovery evidence under `results/` records commands, real exit statuses,
tool versions, and the tested Git parent/tree/head. It is generated only after
the tested content is fixed. If an evidence-only commit changes the head SHA,
the record calls that out explicitly rather than claiming the new commit was
tested. GitHub CI repeats the executable, RTL, Lean default-target, explicit
Lean-target, formal, and Yosys gates.
