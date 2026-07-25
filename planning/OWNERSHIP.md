# File ownership map

| Lane | Owns | Must not change without coordination |
|---|---|---|
| Host packet/runtime | `docs/LSC1_PROTOCOL.md`, future `host/` | ASIC pin mapping |
| LSC-1 RTL | `asic_core/` | host-owned VM state |
| ULX3S harness | `fpga_harness/` | wide ASIC bypasses |
| Differential tests | `sim/`, `test/` | protocol semantics |
| Lean refinement | `lean/` | executable oracle identity |
| Tiny Tapeout PPA | `info.yaml`, `asic_core/` constraints | protocol |
| zkDSL validation | `docs/semantics/`, future adapters | frozen source evidence |
