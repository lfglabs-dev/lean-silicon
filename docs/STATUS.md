# Status ledger

| Item | Status | Evidence |
|---|---|---|
| LSC-1 boundary and pin top | established | `asic_core/rtl/lean_silicon_lsc1.sv` |
| MinCore arithmetic seed | historical/exercised seed | existing simulation/formal suites |
| v1 transaction protocol | specified and executably modelled | `docs/LSC1_TRANSACTION_PROTOCOL.md`, `sim/lsc1_transaction.py` |
| v1 packet executor | not implemented | roadmap completion criteria |
| Host runtime, SET/XOR/MUL transactions | scaffold, driven against the executable endpoint | `docs/HOST_RUNTIME.md`, `host/`, `sim/test_host_runtime.py` |
| Host runtime, DEREF/JUMP/BLAKE3 | not implemented, explicit unsupported paths | `host/lean_compiler_adapter.py` |
| lean_compiler integration | artifact exported from the frozen compiler; `hints`/`main_frame`/`witness`/`trace` are `pub(crate)` upstream | `tools/lean_compiler_export.py`, `docs/HOST_RUNTIME.md` section 4 |
| Host vs frozen Rust comparison | final memory only, for the 12 cells the fixture run touched; `cycles` and every per-step field explicitly not compared | `tools/host_upstream_comparison.py`, `docs/HOST_RUNTIME.md` section 5 |
| Full scalar semantics | not implemented | planned graph |
| ULX3S smoke and MinCore UART bitstreams | built reproducibly and RTL-simulated in PR #16; PR #19 physically exercised the maintained UART image on one LFE5U-85F | `fpga/ulx3s/`, `docs/ULX3S_SMOKE_AND_UART.md` |
| ULX3S restricted program runner | maintained 1 Mbaud driver physically ran the 12-operation arithmetic prefix; stops before JUMP | `fpga_harness/host/mincore_program.py`, `results/fpga-pr16-pr19-20260726/` |
| Historical ULX3S restricted program run | 12-instruction SET/XOR/MUL prefix matches all 12 recorded upstream memory cells; stops before JUMP | `fpga_harness/host/mincore_program.py`, `results/fpga-lsc1-20260726/program-run.json` |
| ULX3S v1 packet endpoint | not implemented | v1 exists only as specification/executable model |
| Tiny Tapeout PPA / official zkDSL validation | not run for LSC-1 | planned graph |
| Full-controller SV-to-frozen-ISA theorem | not implemented | `docs/PROOF_BOUNDARIES.md` |
| RTL-to-netlist equivalence | not implemented | `docs/PROOF_BOUNDARIES.md` |
| Formal-verification marketing claim | prohibited pending bridges | `docs/PROOF_BOUNDARIES.md` |
