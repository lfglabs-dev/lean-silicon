# leanSilicon roadmap — LSC-1

## Direction

leanSilicon is **“A formally verified physical scalar coprocessor for leanVM-b.”**
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
