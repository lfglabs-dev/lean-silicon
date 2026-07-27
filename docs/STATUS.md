# Status ledger

| Item | Status | Evidence |
|---|---|---|
| LSC-1 boundary and pin top | established | `asic_core/rtl/lean_silicon_lsc1.sv` |
| MinCore arithmetic seed | historical/exercised seed | existing simulation/formal suites |
| v1 transaction protocol | specified and executably modelled | `docs/LSC1_TRANSACTION_PROTOCOL.md`, `sim/lsc1_transaction.py` |
| v1 scalar packet executor | SET/XOR/MUL/DEREF/JUMP implemented in RTL; BLAKE3 service pending | `asic_core/rtl/lsc1_packet_frontend.sv`, RTL differential tests |
| Host runtime, SET/XOR/MUL/DEREF/JUMP transactions | driven against the executable endpoint; frozen fixture reaches full `MATCH` | `docs/HOST_RUNTIME.md`, `host/`, `sim/test_host_runtime.py` |
| Host runtime, BLAKE3 | not implemented, explicit unsupported path | `host/lean_compiler_adapter.py` |
| lean_compiler integration | artifact exported from the frozen compiler; `hints`/`main_frame`/`witness`/`trace` are `pub(crate)` upstream | `tools/lean_compiler_export.py`, `docs/HOST_RUNTIME.md` section 4 |
| Host vs frozen Rust comparison | final memory only, for the 12 cells the fixture run touched; `cycles` and every per-step field explicitly not compared | `tools/host_upstream_comparison.py`, `docs/HOST_RUNTIME.md` section 5 |
| Scalar packet subset | SET/XOR/MUL/DEREF/JUMP implemented in the executable model, host path and RTL; finite differential evidence only, with no full-scalar refinement theorem | `sim/test_packet_frontend_rtl_differential.py`, `docs/PROOF_BOUNDARIES.md` |
| ULX3S harness bitstreams | source-built and archived; not hardware-validated, with no current physical scalar-opcode validation claim | `docs/ULX3S_SMOKE_AND_UART.md`, `results/ulx3s-smoke-uart-20260725/` |
| Tiny Tapeout PPA / official zkDSL validation | not run for LSC-1 | planned graph |
| Full-controller SV-to-frozen-ISA theorem | not implemented | `docs/PROOF_BOUNDARIES.md` |
| RTL-to-netlist equivalence | not implemented | `docs/PROOF_BOUNDARIES.md` |
| Formal-verification marketing claim | prohibited pending bridges | `docs/PROOF_BOUNDARIES.md` |
