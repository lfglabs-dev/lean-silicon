# Path from MinCore to a complete leanVM-b scalar execution system

## Architectural state

The full core should use ordinary integer indices internally:

```text
pc_index : u32
fp_index : u32
```

The architectural relation is:

```text
field_address(i) = g^i
```

Frame-relative addressing becomes integer addition:

```text
physical_index = fp_index + offset
```

The Lean theorem in `Address.lean` states the representation fact needed for
refinement:

```text
encode(fp + offset) = encode(fp) * encode(offset)
```

Keeping the external ABI at 32 bits matches the current Rust ISA fields and
avoids an artificial 24-bit compatibility boundary.

## External services

The ASIC should remain a single-outstanding-request master. An RP2040, FPGA, or
host supplies:

| Service | Request | Response / effect |
|---|---|---|
| `FETCH` | `pc_index` | decoded instruction |
| `READ_CELL` | `u32 index` | written flag + 128-bit value |
| `WRITE_ONCE` | index + value | success / conflict |
| `RESOLVE_POINTER` | 128-bit `g^i` | valid flag + `u32 i` |
| `ENCODE_INDEX` | `u32 i` | 128-bit `g^i` |
| `DEFER_EQUALITY` | two indices | records unresolved DEREF pair |
| `MUL_DIVIDE` | numerator + nonzero divisor | field quotient |
| `BLAKE3` | operand indices + metadata | two 128-bit result words |
| `TRACE` | retirement event | append to host trace |

All messages can be serialized over the existing 8-bit ready/valid buses. The
current MinCore commands should remain available as debug primitives.

## Why memory remains external

Each VM word is 128 bits. Even the specified minimum `2^16` cells require 1 MiB
of value storage before written bits, access counts, or traces. Tiny Tapeout
standard-cell storage is unsuitable for this capacity.

The host memory representation should contain:

```text
value[index]         : 128 bits
written[index]       : 1 bit
access_count[index]  : field element, if generating the prover trace
pointer reverse map  : field value -> u32 index
```

A later board can put values in PSRAM while retaining metadata in an FPGA or
host process. The ASIC does not need to change as long as the service protocol
is preserved.

## Scalar instruction sequencing

### XOR and MUL

The current interpreter has more than simple forward evaluation:

1. Read cells A, B, and C with written flags.
2. If C is written and exactly one input is unwritten:
   - XOR: recover missing input as `C xor known`;
   - MUL: recover missing input as `C / known`, requiring the known value to be
     nonzero.
3. Compute the forward result.
4. Apply write-once updates.
5. Record three access-count events and one opcode trace row.

The MinCore handles forward XOR/MUL. The first full system should delegate
`MUL_DIVIDE` to the host rather than place a 127-squaring/field-inversion engine
on the ASIC.

### SET

1. Address is `fp_index + o`.
2. Send `WRITE_ONCE(address, immediate)`.
3. Record access and retirement.

### JUMP

1. Read condition, destination PC value, and destination FP value. The current
   interpreter counts all three accesses even when the branch is not taken.
2. NONZERO computes the branch predicate.
3. If false, set `pc_index += 1`.
4. If true, use resolver metadata for destination PC and FP. Raw field values
   remain in the trace.

### DEREF Cell

1. Read pointer at `fp + alpha` and resolve it to integer `base`.
2. Compute `a2 = base + beta`, `a3 = fp + gamma`.
3. Read written flags and values for both cells.
4. Reconcile:
   - both written: require equality;
   - only a2 written: write a3;
   - only a3 written: write a2;
   - neither written: emit `DEFER_EQUALITY(a2, a3)`.
5. Record all three accesses and the trace row.

### DEREF Pc / Fp

The current interpreter writes:

```text
Pc mode: encode(pc_index + 2)
Fp mode: encode(fp_index)
```

This can use `ENCODE_INDEX` initially. A later core may cache field-form PC/FP
and update them with the inexpensive fixed-generator `xtime` network.

### BLAKE3

The first implementation sends a BLAKE3 request to the host and stalls. The
same interface can later target an FPGA or a second ASIC without changing the
scalar core.

## Trace boundary

The ASIC should emit one retirement record containing at least:

```text
opcode, pc_index, fp_index,
physical operand addresses,
raw operand values,
result or branch outcome,
memory read/write events,
error status
```

The host adds access-count field values and any deferred-DEREF patches required
by the current prover tables.

## Staged implementation

1. **M0 — delivered here:** value-level stream ALU and verified simplified field
   model.
2. **M1:** abstract wide-port scalar controller in simulation.
3. **M2:** byte-RPC bridge and host-managed memory; full XOR/MUL/SET/JUMP.
4. **M3:** DEREF reconciliation and trace compatibility.
5. **M4:** host-offloaded BLAKE3; full board-level ISA execution.
6. **M5:** optional direct PSRAM and hardware BLAKE3.
