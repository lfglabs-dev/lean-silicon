# leanSilicon roadmap — LSC-1

## Active SKY26c release track

SKY26c is the active shuttle target. The immediate next deliverable is the
LSC-1u v0.1 release bundle built from an immutable `main` head. Phase C1
multiply equivalence is complete (PR #35); Phase C2 full-release equivalence
is in flight and remains a release claim blocker.

The pre-submission verification ladder is:

1. Freeze source head/tree, tool/action refs, PDK identity, CI run, job IDs,
   artifact hashes, pinout, and claim boundaries in bundle v0.1.
2. Repeat Cocotb RTL and exact hardened-netlist gate-level tests as one-shot
   release evidence and verify deterministic bundle regeneration.
3. Complete and independently review Phase C2 full-release equivalence.
4. Re-run GDS, precheck, gate-level, FPGA ASIC-simulator, and viewer lanes on
   the final reviewed head; reconcile every artifact hash.
5. Perform the remaining SKY26c submission checks and independent go/no-go
   review. Shuttle submission is a separate, explicitly authorized action.

Silicon validation necessarily remains after fabrication and is not a
pre-submission claim.

## Direction

leanSilicon's long-term objective is a formally verified physical scalar
coprocessor for leanVM-b.  That objective is **not** a present-tense product
claim: leanSilicon is **not currently marketed as formally verified** because
the present evidence is
bounded and layer-specific.  The exact correspondence boundaries, missing
theorems, and release gates are in [PROOF_BOUNDARIES](PROOF_BOUNDARIES.md).
LSC-1 executes one host-prepared instruction transaction at a time.  The host
(initially a Mac) owns compilation, program storage, VM memory, hints and
witnesses, pointer resolution, deferred-equality state, inversion assistance,
BLAKE3, trace construction, and proofs.  The ASIC validates a self-contained
packet, performs non-BLAKE3 scalar semantics, and returns next `pc`/`fp`,
writes, deferred events, service requests, and retirement or fault.

## ASIC responsibilities

XOR, MUL_NATIVE, SET_CONSTANT, DEREF Cell/Pc/Fp, JUMP, u32 pc/fp arithmetic,
decode, effective addresses, zero tests, write-once validation, scalar
transition, BLAKE3 *request*, retirement/fault, and stable 8-bit ready/valid.
For back-solving the host proposes an inverse/witness; the ASIC verifies it by
multiplication.  It never contains an inverter.

## Explicit non-goals

LSC-1 has no autonomous fetch, program or VM-memory ownership, general
external-memory controller, field inverter, BLAKE3 datapath, SDRAM/USB ASIC
controller, dense trace store, pointer resolver, or global-optimality claim.
The FPGA is only a pin-accurate ULX3S prototype/debug harness and cannot use an
internal wide service bypass.

## Deliverables and validation order

1. Versioned packet spec and host reference transaction runtime.
2. RTL packet validator and scalar transition, seeded by MinCore arithmetic.
3. Differential packet tests, then Lean refinement for the same contract.
4. Pin-accurate ULX3S harness, then Tiny Tapeout PPA/precheck.
5. Official zkDSL validation against frozen leanVM-b
   `c308034ab78619b39a59d26f3dc60e7df5b52649`.

## Required proof bridges and gates

Completion requires more than individual proofs or successful simulations.
The planned graph must close these bridges in dependency order:

1. Frozen source to documentation/oracle traceability, then official zkDSL
   validation against the pinned source.
2. Oracle to a complete Lean v1 packet functional model, with all operation and
   fault cases covered.
3. That model to the exact completed `lean_silicon_lsc1` SystemVerilog
   controller, through an explicit state/packet relation and refinement proof.
4. Exact-SV controller properties with documented assumptions and proof bounds
   or induction; GF8 bounded properties are not a substitute for this gate.
5. Oracle/Lean/RTL differential vectors with deterministic fault, stall, and
   response coverage.
6. Sequential RTL-to-netlist equivalence for the release synthesis inputs,
   before using netlist/PPA results as implementation evidence.

The machine-readable counterparts are
`frozen_oracle_traceability`, `docs_reference_oracle`, `lean_refinement`,
`sv_controller_correspondence`, `sv_controller_formal`,
`differential_tests`, and `rtl_netlist_equivalence` in
[`planning/milestones.yaml`](../planning/milestones.yaml).  Their shared
release gate is `formal_verification_release_claim`.

Until those gates are recorded as passing, no repository artifact may claim
that the full LSC-1 controller or the project is formally verified.  The
current proof boundaries are deliberately separated in
[PROOF_BOUNDARIES](PROOF_BOUNDARIES.md).

## Completion criteria

LSC-1 is complete only when the packet executor covers every listed non-BLAKE3
operation; host witnesses/inverses are checked; packet, RTL, and Lean
refinements agree in differential tests; the harness uses the physical
interface; and Tiny Tapeout PPA plus official zkDSL validation are recorded.
This PR does **not** meet those criteria: it establishes the boundary, protocol
contract, planning graph, and exercised arithmetic seed.

## Supersession

The prior autonomous-VM/external-FPGA-service roadmap is superseded.  Files
under `results/` and the retained M2 controller describe historical experiments
under their original names and boundaries; they are evidence, not LSC-1 claims.
