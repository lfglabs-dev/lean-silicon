<p align="center">
  <img src="docs/assets/lean-silicon-logo.png" alt="Project logo" width="520">
</p>

<p align="center">
  A physical scalar coprocessor for leanVM-b, designed around an explicit
  hardware boundary and a verification-first implementation path.
</p>

> [!IMPORTANT]
> **Project objective:** a formally verified physical scalar coprocessor for
> leanVM-b. **Current status:** verification in progress; the current evidence
> does not establish that objective.

LSC-1 receives one host-prepared instruction transaction at a time over an
8-bit ready/valid interface. The host owns compilation, program storage, VM
memory, hints/witnesses, pointer resolution, deferred equality, inversion
assistance, BLAKE3, traces, and proofs. The ASIC validates and executes the
non-BLAKE3 scalar transition, returning next pc/fp, writes, deferred events,
service requests, retirement, or fault.

The reduced LSC-1u Tiny Tapeout RTL is now on `main`. At exact head
`9f78b01c501b8cfd22760a35fe4cbd745865a31e`, GDS, precheck, gate-level
Cocotb, RTL Cocotb, and the FPGA ASIC-simulator build pass. The GDS workflow's
viewer job on that run predates Pages enablement and is not part of those
engineering results. Phase C1 multiply equivalence was settled in PR #35;
full-release equivalence remains open and silicon validation remains pending.

The project objective above is not a present-tense verification claim: the
repository is not currently marketed as formally verified. See
the [proof-boundary matrix](docs/PROOF_BOUNDARIES.md),
[ROADMAP](docs/ROADMAP.md), and [STATUS](docs/STATUS.md).
Frozen leanVM-b evidence remains tied to
`c308034ab78619b39a59d26f3dc60e7df5b52649` and is never relabeled.

> [!IMPORTANT]
> **LSC-1µ (LSC-1 Micro) is the deliberately reduced Tiny Tapeout
> profile/sub-core of LSC-1. It is not “LSC-1/2”, LSC-2, or a second-generation
> architecture.** ASCII identifiers use `LSC-1u` / `lsc1u`. Full LSC-1 remains
> unchanged for FPGA and future larger ASIC targets. See the
> [LSC-1µ architecture contract](docs/LSC1U_ARCHITECTURE.md).

## Layout

- `asic_core/`: exact Tiny Tapeout LSC-1 RTL boundary.
- `fpga_harness/`: ULX3S pin-accurate harness boundary.
- `docs/LSC1_PROTOCOL.md`: versioned transport/packet contract.
- `docs/LSC1_TRANSACTION_PROTOCOL.md`: normative transaction protocol v1,
  modelled executably by `sim/lsc1_transaction.py`.
- `host/`: Mac-side runtime that prepares transactions and owns VM state,
  documented in `docs/HOST_RUNTIME.md`.
- `conformance/`: immutable LSC-1 corpus schema, v1 cases, and the official
  frozen-upstream Rust differential adapter.
- `planning/`: machine-readable milestones and file-lane ownership.
- `src/`: retained compatibility/historical MinCore and M2 sources.
- `src/lsc1u_core.sv`: profile-specific streamed LSC-1µ arithmetic kernel.
- `release/v0.1/`: immutable-source release-candidate manifest, pinout,
  reproducibility record, claim boundary, and exact-main CI artifacts.

Run `make check`, `make sim`, `make lean`, and `make formal` where the
corresponding tools are installed. `make consistency` rejects stale active
top names and missing declared ASIC sources.
