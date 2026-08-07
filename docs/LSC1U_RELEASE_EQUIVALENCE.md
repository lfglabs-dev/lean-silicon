# LSC-1u v0.1.1 RTL-to-netlist sequential-equivalence lane

## Result and boundary

This lane establishes **bounded**, not unbounded, sequential equivalence between
the LSC-1u RTL used by final-main physical run `31203929606` and that run's
selected gate netlist. For every `ui_in`, `uio_in`, and `ena` sequence, it checks
all bits of `uo_out`, `uio_out`, and `uio_oe` for 74 rising edges. The sole
environment constraint is `rst_n == 0` on the first modeled rising edge; reset
and every other input are unconstrained afterward. `VPWR` is tied high and
`VGND` low. Filler, antenna, physical-only, and tap cells are removed; the
checked-in SKY130 cell models express digital Boolean/DFF behavior only.

This proves neither four-state/X behavior, delays, SDF/SPEF timing, power,
analog or physical behavior, clock-quality assumptions, metastability,
manufacturability, nor equivalence of GDS/OAS geometry. It is not a full LSC-1
or Lean-to-RTL proof. A 74-edge BMC is exhaustive within that prefix but says
nothing about edge 75 or later and does not span a complete 128-bit multiply.

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
changes the first output comparison to demand a one-bit mismatch;
the 74-edge task must produce SBY status `FAIL`, meaning a property
counterexample. `ERROR`, timeout, missing status, and every other infrastructure
outcome fail the lane. The assertion cardinality guard runs after elaboration
and prevents an unsupported frontend or optimization change from silently
dropping checks.

## Why this does not claim unbounded equivalence

ABC PDR was attempted on the same miter and constraint. It did not converge:
after about 203 seconds it had reached frame 86, with 319 flops in the active
cone and a maximum obligation queue of 1,387. Terminating a growing proof search
is not a counterexample and does not show inequivalence, but it supplies no
inductive invariant. Direct Yosys `equiv_induct -seq 20` likewise left 13 of 24
observable `$equiv` cells unproved because arbitrary internal initial states do
not encode the harness's reset-reachable-state restriction. Consequently the
300-edge BMC cost grew sharply after frame 55 and had not completed after frame
74 (about 229 seconds), so it is not used as a passing receipt. The strongest
reproducible sound result reported here is the 74-edge BMC; the PR deliberately
makes no unbounded or full-multiply claim.

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
the SAT witness and 74-edge proof, and requires the mutation to produce an
actual property counterexample.
