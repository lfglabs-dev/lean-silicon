# File ownership map

| Lane | Owns | Must not change without coordination |
|---|---|---|
| Host packet/runtime | `docs/LSC1_PROTOCOL.md`, `docs/LSC1_TRANSACTION_PROTOCOL.md`, `sim/lsc1_transaction.py`, `docs/HOST_RUNTIME.md`, `host/`, `tools/lean_compiler_export.py`, `tools/host_upstream_comparison.py`, `tools/ulx3s_mac_preflight.py`, `docs/ULX3S_MAC_PREFLIGHT.md` | ASIC pin mapping, and the `fpga_harness/` detection ladder: the macOS preflight only feeds `board_detect.py --fixture` and must not alter its levels or their meaning |
| LSC-1 RTL | `asic_core/` | host-owned VM state |
| ULX3S harness | `fpga_harness/` | wide ASIC bypasses |
| Differential tests | `sim/`, `test/` | protocol semantics |
| Lean refinement | `lean/` | executable oracle identity |
| Proof correspondence | `docs/PROOF_BOUNDARIES.md`, `formal/`, `lean/` | changing a boundary claim without updating its bridge gate |
| RTL/netlist equivalence | future `equiv/`, synthesis manifests | release RTL or synthesis configuration without rerunning equivalence |
| Tiny Tapeout PPA | `info.yaml`, `asic_core/` constraints | protocol |
| zkDSL validation | `docs/semantics/`, future adapters | frozen source evidence |
