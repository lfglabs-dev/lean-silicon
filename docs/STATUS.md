# Status ledger

The reduced **LSC-1u (LSC-1 Micro)** profile is on `main` at
`9f78b01c501b8cfd22760a35fe4cbd745865a31e`. On that exact head, GDS,
precheck, gate-level simulation, RTL simulation, and the FPGA ASIC-simulator
build are green. Phase C1 multiply equivalence was settled by PR #35. Phase C2
full-release equivalence is still open, and there is no silicon validation.
These statements do not apply to the full **LSC-1** packet executor except
where a row explicitly says so.

| Item | Status | Evidence |
|---|---|---|
| LSC-1u RTL on `main` | implemented and RTL-simulated | exact head `9f78b01c501b8cfd22760a35fe4cbd745865a31e`; Tiny Tapeout RTL run `30722147810` |
| LSC-1u hardening and precheck | GDS and precheck jobs passed | GDS run `30722147803`, jobs `91427563037` and `91428129783` |
| LSC-1u gate-level simulation | passed | GDS run `30722147803`, job `91428129794` |
| LSC-1u FPGA ASIC-simulator build | passed | checked-in evidence under `results/tt-fpga-asic-simulator-20260801/` |
| Phase C1 multiply equivalence | settled | PR #35 |
| Phase C2 full-release equivalence | in flight / not established | release blocker; no full-release equivalence claim |
| LSC-1u silicon validation | pending | no fabricated-device test evidence |
| LSC-1 boundary and pin top | established | `asic_core/rtl/lean_silicon_lsc1.sv` |
| MinCore arithmetic seed | historical/exercised seed | existing simulation/formal suites |
| v1 transaction protocol | specified and executably modelled | `docs/LSC1_TRANSACTION_PROTOCOL.md`, `sim/lsc1_transaction.py` |
| Lean v1 packet/transaction foundation | protocol-sized request/response round trips, request validation precedence, current-state index-range rejection, atomic staging, abort/reset, matching retirement and exactly-once behavior proved for a pure functional model | `lean/LeanVMBMinCore/{Packet,Transaction}.lean`; byte-stream/per-opcode decoding, instruction/next-state validation, CRC-32 instantiation, service states, and RTL/oracle refinement remain open |
| v1 scalar packet executor | SET/XOR/MUL/DEREF/JUMP and the delegated BLAKE3 request/response/retire lifecycle implemented in authored RTL | `asic_core/rtl/lsc1_packet_frontend.sv`, RTL differential tests |
| Host runtime, SET/XOR/MUL/DEREF/JUMP transactions | driven against the executable endpoint; frozen fixture reaches full `MATCH` | `docs/HOST_RUNTIME.md`, `host/`, `sim/test_host_runtime.py` |
| Host runtime, BLAKE3 | canonical service protocol and CPU implementation integrated through SERVICE_REQUIRED, bound response, result and retirement; exact-payload receipts and official low-level oracle differential tested; authored RTL implements the delegated lifecycle while compression remains host-owned | `host/{runtime,blake3_service}.py`, `sim/test_{host_runtime,blake3_service}.py` |
| lean_compiler integration | artifact exported from the frozen compiler; `hints`/`main_frame`/`witness`/`trace` are `pub(crate)` upstream | `tools/lean_compiler_export.py`, `docs/HOST_RUNTIME.md` section 4 |
| Host vs frozen Rust comparison | final memory for the 12 cells the fixture run touched and `cycles` compared when the run reaches the sentinel; every per-step field explicitly not compared | `tools/host_upstream_comparison.py`, `docs/HOST_RUNTIME.md` section 5 |
| Scalar packet subset | SET/XOR/MUL/DEREF/JUMP implemented in the executable model, host path and RTL; finite differential evidence only, with no full-scalar refinement theorem | `sim/test_packet_frontend_rtl_differential.py`, `docs/PROOF_BOUNDARIES.md` |
| ULX3S harness bitstreams | source-built and archived; not hardware-validated, with no current physical scalar-opcode validation claim | `docs/ULX3S_SMOKE_AND_UART.md`, `results/ulx3s-smoke-uart-20260725/` |
| Tiny Tapeout PPA / official zkDSL validation | not run for LSC-1 | planned graph |
| Full-controller SV-to-frozen-ISA theorem | not implemented | `docs/PROOF_BOUNDARIES.md` |
| Fixed LSC-1u RTL-to-netlist equivalence | bounded check established for the fixed v0.1 release netlist at the observable wrapper boundary; it is not unbounded sequential equivalence | `formal/lsc1u_netlist_eq.sby`, `formal/README.md`, `docs/PROOF_BOUNDARIES.md` |
| Unbounded RTL-to-netlist equivalence | not established | `docs/PROOF_BOUNDARIES.md` |
| Formal-verification marketing claim | prohibited pending bridges | `docs/PROOF_BOUNDARIES.md` |
