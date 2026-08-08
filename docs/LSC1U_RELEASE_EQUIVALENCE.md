# LSC-1u v0.1.1 RTL-to-netlist sequential-equivalence lane

## Result and boundary

This lane establishes **unbounded two-state sequential equivalence** between
the LSC-1u RTL used by final-main physical run `31203929606` and that run's
selected gate netlist. For every `ui_in`, `uio_in`, `ena`, and post-initial
`rst_n` sequence, it checks all bits of `uo_out`, `uio_out`, and `uio_oe` at
every rising edge. The sole
environment constraint is `rst_n == 0` on the first modeled rising edge; reset
and every other input are unconstrained afterward. `VPWR` is tied high and
`VGND` low. Filler, antenna, physical-only, and tap cells are removed; the
checked-in SKY130 cell models express digital Boolean/DFF behavior only.

This proves neither four-state/X behavior, delays, SDF/SPEF timing, power,
analog or physical behavior, clock-quality assumptions, metastability,
manufacturability, nor equivalence of GDS/OAS geometry. It is not a full LSC-1
or Lean-to-RTL proof. The independently retained 74-edge ABC BMC remains a
bounded cross-check; it is not the basis of the unbounded claim.

## Exact identity

- Source commit/tree: `741a2073e0d341a15bb130b1d75295bbceb138df` /
  `6d0085cb016c7ce317ab91160c670b44d6fb51fd` (merged PR #45).
- Physical run/artifact: run `31203929606`, `tt_submission` artifact
  `9004116698`; archive SHA-256
  `1c6721712d3dec19f0b143bd3af99e5e0982928a151d6142a25f5bf0dd1ef80f`.
- Selected netlist SHA-256:
  `97000459a97f1d775db06ed88fefb59e28fde09b27a5046aaadd036ad01e16bc`.
- The runner extracts the four RTL files from the pinned source commit rather
  than the mutable checkout, then enforces their embedded hashes; those hashes
  also match the source copies embedded in the artifact archive.
- Physical build: LibreLane `3.0.3`, `sky130A`, open_pdks
  `8afc8346a57fe1ab7934ba5a6056ea8b43078e71`, as pinned in
  `release/v0.1.1/MANIFEST.json` and the downloaded `pdk.json`.
- Assurance CI installs OSS CAD Suite through immutable action commit
  `YosysHQ/setup-oss-cad-suite@aefa8397bbf8fc6670a0a62af9805a89738f3cde`;
  the command prints the actual Yosys build identity into the job log.

The original archive is retained durably at
`release/v0.1.1/evidence/tt_submission-9004116698.zip` as a Git object. Its
archive and selected payload hashes are mandatory inputs, and a missing or
mismatched archive fails closed.

## Non-vacuity and mutation sensitivity

An explicit Yosys SAT query must emit a parseable JSON model witnessing reset
asserted at edge 1, released at edge 2, and the driven `uio_oe == 8'hb6` output
with `ena == 1`; UNSAT or a missing/invalid model fails the lane. The runner then
requires covers for one complete multiply and two consecutive valid-command
retirements. It then changes the first output comparison to demand a
one-bit mismatch; the induction task must produce SBY status `FAIL`, meaning a
property
counterexample. `ERROR`, timeout, missing status, and every other infrastructure
outcome fail the lane. The assertion cardinality guard runs after elaboration
and prevents an unsupported frontend or optimization change from silently
dropping checks.

## Unbounded proof construction

The physical netlist retains a name on every one of its 283 state flops. The
proof exposes those nets as formal-only output ports without changing their
drivers. They correspond to the RTL controller state, byte index, saved/output
bytes and flags, plus the multiplier's 128-bit power and product registers.
Synthesis renamed the product's low byte to `core.mul_result_byte[7:0]`; the
wrapper records that explicit mapping. A single 283-bit assertion states the
complete relational invariant, while three separate assertions continue to
check all 24 external output bits.

Boolector k-induction proves the base case from the required initial reset and
the inductive step for arbitrary inputs; ABC PDR independently proves the same
four assertions. Since the asserted relation contains the complete state of
both sequential designs, the successful induction is an
unbounded reachable-state proof, not an extrapolation from a finite trace.
The compositional state correspondence closes the earlier monolithic solver
gap.

## Reproduced results

On the host OSS CAD Suite (`sby` 0.68, Yosys 0.68+40, Boolector 3.2.4,
ABC 1.01), the final miter produced:

- Boolector depth-4 k-induction: `PASS` (base and induction, 23 seconds);
- ABC PDR: `PASS` (all four assertions, 176 seconds);
- retained 74-edge ABC BMC: `PASS` (704 seconds);
- cover: two valid-command retirements at step 70 and a complete MUL retirement
  at step 179;
- one-bit output mutation: `FAIL` at step 2, as required.

The unchanged merged 74-edge lane was also started from current `main`; this
host reached frame 57 without a counterexample before that redundant
superlinear run was stopped. The merged release receipt retains the completed
74-edge result. After the state assertion was restricted to the unbounded
tasks, the final retained external-output task completed through all 75 modeled
frames as reported above.

## Reproduction

Use a private mutable cache outside the checkout:

```sh
export LSC1_EQ_CACHE="$(mktemp -d)"
chmod 700 "$LSC1_EQ_CACHE"
make release-netlist-equivalence
```

CI runs exactly the last command with `${{ runner.temp }}/lsc1-eq-cache`. The
runner reads the durable copy of artifact `9004116698`, verifies both fixed
hashes and all RTL hashes, stages mutable SBY outputs in the private cache, runs
the SAT witness, retained 74-edge BMC, unbounded induction and PDR, and
full-MUL/repeated-transaction covers, and requires the mutation to produce an
actual property counterexample.
