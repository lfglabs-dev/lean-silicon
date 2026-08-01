# RTL formal check

Three independent harnesses live here.  Each has a different boundary; none of
them proves the full LSC-1 controller or ISA correspondence.  See
`docs/PROOF_BOUNDARIES.md`.

| Config | Boundary proved | Mode |
|---|---|---|
| `gf8_mul.sby` | GF(2^8) product of the generic multiplier at WIDTH=8 | bounded BMC |
| `gf128_serialize.sby` | WIDTH=128 16-beat little-endian byte load and result shift-out ordering | BMC + k-induction + cover |
| `stream_alu_mul_pulse.sby` | `mul_a_valid`/`mul_bit_valid`/`mul_result_shift` are mutually exclusive in the shipped `leanvm_b_stream_alu` FSM | k-induction + cover |
| `lsc1u_protocol.sby` | LSC-1u clamp/reset/stall/completion/framing plus retained XOR/SET bytes | unbounded PDR |
| `lsc1u_reachability.sby` | Independent completion witnesses for XOR, MUL, SET, and fault response | bounded cover per opcode |
| `lsc1u_xor_refinement.sby` | Cycle-accurate retained-state refinement from accepted XOR command through all arithmetic result beats and retirement | unbounded PDR + bounded covers |
| `gf128_mul_stream_refinement.sby` | Production GF(2^128) datapath refines the accepted-event polynomial specification, including arbitrary pauses and reset/abort | unbounded PDR + bounded covers |
| `lsc1u_compositional_refinement.sby` | Cycle-accurate all-op transition refinement, including MUL_A/B/BITS/TX, output stalls, enable pauses, reset, and retirement | unbounded PDR |

The XOR refinement's architectural state, invariants, assumptions, mutation
falsifiers, and residual gaps are enumerated in `LSC1U_XOR_REFINEMENT.md`.

The compositional milestone partitions the 128-bit arithmetic from controller
control.  The controller proof uses a conservative arbitrary-result boundary
and checks every visible cycle, including multiplier control and output
selection.  The multiplier proof independently establishes the production
module's accepted-event polynomial recurrence.  Neither proof assumes progress:
`rx_valid`, `tx_ready`, `ena`, reset, and datapath event pauses may be delayed
arbitrarily.  Consequently this is a safety/refinement claim, not liveness
under an unfair environment.

## LSC-1u retained boundary

`lsc1u_protocol.sby` deliberately does not elaborate the concrete 256-bit
multiplier state.  It links `lsc1u_core` against
`gf128_mul_boundary_formal.sv`, whose result is unconstrained.  This is a
conservative over-approximation for these properties: the core never branches
on the result, MUL data arithmetic is not asserted here, and every concrete
multiplier output is among the values considered by the boundary model.
Concrete arithmetic and serialization remain checked by `gf8_mul.sby` and
`gf128_serialize.sby`.

The safety run uses ABC PDR and proves all ten assertions for unbounded
reachable execution.  Reachability is a separate four-task config so a deep
MUL witness (completion at depth 178) cannot force every safety property
through the same incremental SMT-BMC.  The reachability harness drives a legal,
always-ready retained-boundary transaction; its constant multiplier result is
only a witness choice because control is result-independent.

Run:

```sh
sby -f lsc1u_protocol.sby
sby -f lsc1u_reachability.sby
python3 check_mutations.py
```

`check_mutations.py` works only in temporary copies.  It requires terminal
counterexamples for broken stall stability, enable clamping, XOR data, SET
data, generic multiplier arithmetic, and WIDTH=128 result serialization.

## GF(2^8) product check

The required M0 finite check, run from this directory, is:

```sh
sby -f gf8_mul.sby
```

The harness quantifies over every pair of 8-bit operands. It drives the exact
generic RTL used by the 128-bit specialization and exhaustively checks the
bounded transaction that the result after eight accepted multiplier bits equals an independent schoolbook carry-less
product reduced modulo `x^8 + x^4 + x^3 + x + 1`.

The Lean proof in `lean/LeanVMBMinCore/GF8.lean` checks the same simplified
algorithm through a separate formalization. This creates two independent proof
paths: Lean bit-blasting and RTL model checking.

This is a GF(2^8) proof boundary only.  In particular, Lean's GF8
`native_decide` result and this bounded SBY run are not a proof of the
production GF(2^128) multiplier, the full LSC-1 controller, or frozen-ISA
semantics.  See `docs/PROOF_BOUNDARIES.md` for the required bridges.

The finite SAT script checks frames 0 through 22. The harness toggles its
generated clock on each global step; its assertion first evaluates at frame 21,
after the reset, A-load, and eight multiplier-bit positive edges. The script
does not alter the RTL or assertion. It removes only the non-constraining cover
cell because the Yosys SAT backend cannot import cover cells. `SUCCESS` means
there is no counterexample through this finite bound; it is a bounded check,
never an unbounded proof of an unconstrained stream protocol.

The required SBY check uses ABC's `bmc3` engine, preserves the assertion, and
passes at depth 32. The separate `yosys -s gf8_mul_bounded.ys` script is a
finite SAT cross-check through frame 22; it removes only the non-constraining
cover cell because the Yosys SAT backend cannot import cover cells.

The historical cvc5 baseline reached frame 21 but did not finish within its
recorded cap. `gf8_mul_depth22_z3.sby` and
`gf8_mul_bounded_boolector.sby` are diagnostic reproductions of, respectively,
the same frame-21 timeout and Boolector's incompatibility with SBY's universal
`anyconst` encoding. Use the versioned driver under `results/` to reproduce all
of these outcomes and their time limits.

## WIDTH=128 byte-serialization order check

```sh
sby -f gf128_serialize.sby            # runs bmc, induction, cover
```

`gf128_serialize_formal.sv` instantiates the production `gf128_mul_bitstream`
(and through it the production `gf2n_mul_bitstream`) at its shipped WIDTH=128
parameterization.  A single `(* anyconst *) operand_a` symbolically covers all
2^128 operand values.  The harness sequences the module through the real
protocol: 16 `a_valid` load beats, a terminating `a_last`, one `bit_valid` beat
with `bit_value = 1` and `bit_last = 1`, then 16 `result_shift` beats.

Because the multiplier bit stream is the field identity, the accumulator after
the multiply phase is exactly the loaded A register.  The assertion therefore
compares each emitted `result_byte` against the corresponding little-endian
byte lane of `operand_a`, which makes any load-order or shift-order defect
observable.  Concretely this proves, for every 128-bit operand:

- load beat `i` supplies `operand_a[8*i +: 8]` and lands in lane `i`, and
- shift beat `j` emits `operand_a[8*j +: 8]`.

This is the property that `gf8_mul_formal.sv` cannot reach: that harness ties
`a_last = 1` and `result_shift = 0`, so it exercises neither the 16-beat
operand load nor the 16-beat destructive result serialization.  The 8-bit
exhaustive product check remains additional evidence for the arithmetic, not a
substitute for this ordering property.

`induction` is an unbounded k-induction proof (`mode prove`), not a bounded
run.  `cover` shows the final shift beat is reachable, so the assertion is not
vacuously true on an unreachable path.

**Assumptions.** The harness drives a deterministic schedule and a fixed
`bit_value`/`bit_last`; it constrains `abort = 0` and holds reset for the first
cycle.  It therefore says nothing about aborts, back-to-back transactions,
partial loads, or interleaved phases, and it is not a GF(2^128) product proof.

## Mutual-exclusion check on the shipped stream ALU

```sh
sby -f stream_alu_mul_pulse.sby       # runs induction, cover
```

`gf2n_mul_bitstream.sv` documents that the parent "must issue mutually
exclusive `a_valid`, `bit_valid`, and `result_shift` pulses", but until now
nothing checked it.  `stream_alu_mul_pulse_formal.sv` attaches a checker to the
shipped `leanvm_b_stream_alu` with a SystemVerilog `bind`, so no functional RTL
is modified.  The property is `$onehot0({mul_a_valid, mul_bit_valid,
mul_result_shift})`, written in expanded pairwise form because `yosys-slang`
does not implement the `$onehot0` system function; for three signals
`!((x&y) | (x&z) | (y&z))` is exactly `$onehot0({x,y,z})`.

**This config requires the `yosys-slang` plugin.**  The built-in Yosys Verilog
frontend parses `bind` without error but silently discards the bound instance
(it reports `Removing unused module`), which would make the run vacuously pass.
The script uses `plugin -i slang` and `read_slang --keep-hierarchy`.

That vacuity mode is not self-announcing: with the bound instance dropped the
design contains no checker cells at all, and both tasks still exit 0 -- `mode
prove` then has no assertion to disprove and `mode cover` has no cover
statement to miss.  The `[script]` section therefore ends with

```
select -assert-min 4 leanvm_b_mul_pulse_check*/t:$check
```

which aborts the run unless the four bound checks (one assert, three covers)
are present in the elaborated design.  Because this runs inside the proving
task itself, a frontend regression fails the proof instead of silently passing
it; the same assertion also runs as a standalone CI pre-flight step.  The
checker cells appear under `stream_alu_mul_pulse_formal.dut.u_mul_pulse_check`.

The `induction` task is an unbounded `mode prove` result: the pulses are
mutually exclusive in every reachable state, driven by free `rx_data`,
`rx_valid`, `tx_ready`, and `abort` inputs.  The `cover` task reaches
`a_valid` at step 3, `bit_valid` at step 19, and `result_shift` at step 147,
so all three arms of the property are individually reachable.

**Assumptions.** Reset is asserted low for the first cycle and released
thereafter, and the assertion is gated on `rst_n`; behavior during reset is not
constrained.  Only the multiplier handshake is checked — this is not a proof of
the ALU's opcode decode, its result values, or the full controller.

## Non-vacuity

The earlier properties were mutation-tested as follows; each mutation was
reverted after the run and none is present in the tree:

| Mutation | Expected | Observed |
|---|---|---|
| Reverse the expected shift-out byte order in the 128-bit harness | fail | `Assert failed` at step 37 |
| Reverse the load byte order in the 128-bit harness | fail | `Assert failed` |
| Drive `mul_bit_valid = tx_ready` in `S_MUL_TX` of the stream ALU | fail | induction-step assertion failure |
