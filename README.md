# lean-silicon

`lean-silicon` is building a traceable assurance chain for a physical scalar
coprocessor for [leanVM-b](docs/SEMANTICS.md). The long-term target is **LSC-1**:
the complete leanVM-b host/FPGA coprocessor. Its small on-chip counterpart is
**LSC-1µ** (ASCII: `LSC-1u` / `lsc1u`), the Tiny Tapeout SKY130 profile.

The intended chain is: Lean model, handwritten SystemVerilog RTL, synthesis and
netlist, physical design, FPGA validation, and eventually fabricated silicon.
It is not yet an end-to-end proof.

## Profiles

- **LSC-1** is the complete profile. The host manages memory, instruction
  fetch, witnesses, and commit; the FPGA coprocessor implements a broader
  opcode set. See the [architecture](docs/ARCHITECTURE.md) and
  [transaction protocol](docs/LSC1_TRANSACTION_PROTOCOL.md).
- **LSC-1µ** is the reduced on-chip profile for Tiny Tapeout SKY130. It focuses
  on SET, XOR, and MUL; the other responsibilities remain off-chip. See the
  [LSC-1µ architecture contract](docs/LSC1U_ARCHITECTURE.md) and
  [tapeout notes](docs/TAPEOUT.md).

## Status

The [v0.1 release candidate](https://github.com/lfglabs-dev/lean-silicon/releases/tag/v0.1)
exists. Core arithmetic and protocol work, plus LSC-1µ wrapper composition,
have formal evidence within their stated boundaries. These are important
milestones, not an end-to-end proof; the release artifacts and their claim
boundary are in [`release/v0.1/`](release/v0.1/).

## What is proven / What remains

| What is established | What remains |
| --- | --- |
| Core arithmetic/protocol and LSC-1µ wrapper composition have formal evidence within their stated boundaries. | Lean-to-RTL correspondence remains future work. |
| The fixed v0.1 LSC-1µ netlist-to-RTL check is bounded. | Unbounded netlist equivalence is roadmap work. |
| The release candidate includes RTL, gate-level, and physical-flow evidence within its stated scope. | Physical FPGA validation, full LSC-1 equivalence, and fabricated-silicon bring-up are future work. |

Read the [proof-boundary matrix](docs/PROOF_BOUNDARIES.md),
[status ledger](docs/STATUS.md), [validation record](docs/VALIDATION.md), and
[roadmap](docs/ROADMAP.md) before relying on any result.

## Build and check

```sh
make check
make sim
make lean
make formal
```

Run the commands for which the corresponding tools are installed. `make
consistency` checks source/top consistency; `make checksum-check` verifies the
tracked checksum inventory.

## Layout

- `asic_core/` — LSC-1 RTL and packet boundary
- `fpga_harness/` — ULX3S harness and host-side checks
- `host/` — host runtime and transaction preparation
- `conformance/` — immutable corpus and schemas
- `formal/` — formal properties and harnesses
- `release/v0.1/` — release-candidate manifest, pinout, reproducibility record,
  claims, and artifacts
