# Serial multiplier byte-ordering evidence

Base commit: `2630c9be3fec014f5230e780f19e82af07372d5a` (also in
`base-source-sha.txt`).  Tool versions are in `toolchain.txt`.  All logs here
were produced from that base plus the changes in this PR; nothing else in the
tree was modified.

## What this evidence covers

Two independent proof paths were added over the existing serial multiplier, and
both were mutation-tested.  Neither is a GF(2^128) arithmetic proof and neither
is an ISA-to-RTL refinement.  See `docs/PROOF_BOUNDARIES.md`.

### 1. Mutual exclusion on shipped controller RTL

`gf2n_mul_bitstream.sv` documents that `a_valid`, `bit_valid`, and
`result_shift` must be mutually exclusive, but nothing checked it.
`formal/stream_alu_mul_pulse_formal.sv` `bind`s a checker into the shipped
`leanvm_b_stream_alu` and proves `$onehot0({mul_a_valid, mul_bit_valid,
mul_result_shift})` by unbounded k-induction with free stream inputs.  No
functional RTL was changed.

| Log | Result |
|---|---|
| `sby-stream-alu-mul-pulse-induction.log` | PASS, successful proof by k-induction (basecase + induction) |
| `sby-stream-alu-mul-pulse-cover.log` | PASS; `a_valid` reachable at step 3, `bit_valid` at step 19, `result_shift` at step 147 |
| `bind-elaboration-check.log` | `select -assert-min 4 leanvm_b_mul_pulse_check*/t:$check` passes; all 4 `$check` cells (1 assert + 3 covers) are elaborated inside `leanvm_b_mul_pulse_check$stream_alu_mul_pulse_formal.dut.u_mul_pulse_check` |

The elaboration check matters: the built-in Yosys Verilog frontend parses
`bind` and then silently discards the bound instance, which would produce a
vacuous PASS.  This config uses the `yosys-slang` plugin (`read_slang`)
specifically to avoid that, and the cell count is recorded as proof the
assertions are really in the design.

### 2. WIDTH=128 byte-serialization ordering

`formal/gf128_serialize_formal.sv` drives the shipped `gf128_mul_bitstream` at
its production WIDTH=128 through the real protocol — 16 `a_valid` load beats, a
terminating `a_last`, one identity multiplier bit, then 16 `result_shift`
beats — with an `(* anyconst *)` operand covering all 2^128 values.  It asserts
that load beat `i` carries `operand_a[8*i +: 8]` and that shift beat `j` emits
`operand_a[8*j +: 8]`.

| Log | Result |
|---|---|
| `sby-gf128-serialize-bmc.log` | PASS at depth 80 |
| `sby-gf128-serialize-induction.log` | PASS, unbounded proof by k-induction |
| `sby-gf128-serialize-cover.log` | PASS; final shift beat reached at step 67 |

This is what the pre-existing `formal/gf8_mul_formal.sv` harness cannot reach:
it ties `a_last = 1` and `result_shift = 0`, so it exercises neither the 16-beat
operand load nor the 16-beat destructive result serialization.  `sby-gf8-mul.log`
records that the pre-existing GF(2^8) gate still passes unchanged.

### 3. Lean byte-serialization model

`lean/LeanVMBMinCore/ByteSerialization.lean` models the same little-endian
shift-in/shift-out over `BitVec 128` and proves the ordering and round-trip
properties for all values.

| Log | Result |
|---|---|
| `lean-build.log` / `.status` | `lake build` completed successfully, rc=0 |
| `lean-print-axioms.log` | all 14 public theorems depend only on `[propext, Quot.sound]` |
| `placeholders.log` / `.status` | repository gate rejecting `sorry`/`admit`/`axiom`, rc=0 |

`lean-print-axioms.input.lean` is the exact input used.  No `native_decide` and
no `bv_decide` SAT path is used anywhere in the new module, so no generated
`_native.bv_decide.ax_*` axiom appears.  The proofs are structural bit-lane
arguments plus list induction.

### 4. Repository gates

| Log | Result |
|---|---|
| `make-check.log` / `.status` | rc=0 (python, design-space, exact-xor, interface-check, consistency, checksum-check, gate-count, smoke, placeholders) |
| `make-sim.log` / `.status` | rc=0 |
| `make-smoke.log` / `.status` | rc=0 |

## Non-vacuity by mutation

Each property was re-run against a deliberately broken tree and observed to
fail.  Every mutation was reverted; none is present in the committed sources.

| Mutation | Observed |
|---|---|
| Reverse expected shift-out byte order in `gf128_serialize_formal.sv` | `Assert failed` at step 37 |
| Reverse load byte order in `gf128_serialize_formal.sv` | `Assert failed` |
| Add `mul_bit_valid = tx_ready;` to `S_MUL_TX` in `leanvm_b_stream_alu.sv` | induction-step assertion failure (`rc=4`) |

## Scope limits

- Ordering only.  The GF(2^128) product itself is still unproved at 128 bits.
- The 128-bit harness uses a fixed schedule with `abort = 0`, a single identity
  multiplier bit, and no back-to-back or partial transactions.
- The mutual-exclusion property covers one documented handshake precondition of
  one module; the rest of `asic_core/rtl/` still carries no assertions.
- The Lean model and the SBY property are two independent arguments about the
  same intended ordering.  No mechanized refinement connects them.
- Nothing here is a full-controller, ISA-equivalence, FPGA, PPA, or synthesis
  claim.
