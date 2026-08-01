# LSC-1u XOR retained-boundary refinement

## Milestone and proven boundary

`lsc1u_xor_refinement.sby` proves a cycle-accurate lockstep relation between
the handwritten `lsc1u_core` RTL and a reduced retained-state model for one or
more complete XOR micro-ops.  Every accepted idle command is assumed to be
XOR; this is an opcode-specific refinement lane, not an opcode-decoder proof.
All 32 payload bytes per command are otherwise arbitrary.

The environment may independently vary `rx_valid`, `tx_ready`, `ena`, and
`rst_n` on every cycle.  Consequently the proof includes arbitrary finite or
infinite input/output backpressure, enable pauses, reset during any partial or
stalled operation, and back-to-back XOR transactions.  It is a safety proof:
an environment that never supplies a beat or never accepts a result is not
assumed to make progress.  Separate covers demonstrate concrete acceptance,
stalled-result retention, mid-operation reset, and final retirement traces.

## Architectural state and relation

The reduced model retains exactly:

| Field | Meaning | RTL correspondence |
|---|---|---|
| `ref_phase` | idle, waiting for lane A, or waiting for lane B | `state` = `IDLE`, `XOR_A`, or `XOR_B` |
| `ref_lane` | result lane to retire, 0 through 15 | `byte_index` |
| `ref_a` | accepted first operand of the current lane | `saved_byte` |
| `ref_result` | retained result byte | `out_byte` |
| `ref_result_valid` | result is pending acceptance | `out_valid` |
| `ref_fault` | retained fault state (always clear on this lane) | `fault_reg` |
| `ref_retired` | one-cycle completion/retirement pulse | `done_reg` |

These conceptual RTL correspondences explain the abstraction; the mechanically
checked refinement relation is observational and equates `rx_ready`,
`tx_valid`, `tx_data`, `busy`, `fault`, and `done_pulse` to functions of the
reduced state on every post-initial clock boundary.  Because those equalities
hold after every arbitrary input step, each retained field that can affect a
later XOR observation is exercised through the transition relation rather than
read through non-portable hierarchical references.  The
multiplier is replaced by an unconstrained output because the XOR states never
read it; this is a conservative cone cut, not a result assumption.

## Inductive invariants

- The lane index is always in `[0, 15]`.
- Waiting for B never overlaps a pending output.
- A pending output exists only in the A-wait phase, which prevents payload
  acceptance until that exact retained byte is accepted.
- The retained result after accepting a pair is exactly `A XOR B`.
- Output data and validity remain unchanged through arbitrary `tx_ready = 0`
  cycles and through `ena = 0` pauses.
- Retirement occurs only after acceptance of lane 15, returns to idle, clears
  the pending result, and is a single enabled cycle.
- Reset restores all related retained state and cancels partial or stalled work.

## Assumptions and residual gaps

The only functional assumption is `rx_data == 8'h01` when a command handshake
occurs in idle.  There is no fairness, ready/valid scheduling, payload-value,
or reset-exclusion assumption.  LSC-1u exposes reset and enable but has no
abort port, so abort refinement is outside this RTL interface rather than
silently excluded.

This tranche does not prove opcode decode/fault responses, SET, MUL arithmetic,
the Tiny Tapeout wrapper, packet LSC-1, Lean-to-RTL correspondence, liveness
under unfair backpressure, or RTL-to-netlist equivalence.  It supplies one
compositional accepted-micro-op-to-arithmetic-result/retirement lane toward the
full controller relation.

Run:

```sh
cd formal
sby -f lsc1u_xor_refinement.sby
cd ..
python3 formal/check_mutations.py
```
