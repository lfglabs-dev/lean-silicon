# Decision ledger

- D-001: LSC-1 is host-prepared, one instruction transaction at a time.
- D-002: The Mac owns VM memory and all service state; FPGA is harness only.
- D-003: Inversion is host-proposed and ASIC-verified by multiplication.
- D-004: BLAKE3 is a host service request, never an LSC-1 datapath.
- D-005: MinCore is retained as a datapath seed; M2's bounded-memory controller
  remains historical and is excluded from the ASIC build.
- D-006: Proof, bounded formal, simulation, and synthesis evidence are kept at
  explicit correspondence boundaries.  The project must not be described as
  formally verified until frozen semantics, functional models, exact SV, and
  synthesized netlist are joined by the roadmap's required bridges.
