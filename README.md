<p align="center">
  <img src="docs/assets/lean-silicon-logo.svg" alt="leanSilicon — a scalar coprocessor for leanVM-b" width="520">
</p>

<h1 align="center">leanSilicon</h1>

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

The current RTL is an exercised MinCore arithmetic seed behind the final
`lean_silicon_lsc1` Tiny Tapeout top. It is not yet the LSC-1 v1 packet
executor. The project objective above is not a present-tense verification
claim: the repository is not currently marketed as formally verified. See
the [proof-boundary matrix](docs/PROOF_BOUNDARIES.md),
[ROADMAP](docs/ROADMAP.md), and [STATUS](docs/STATUS.md).
Frozen leanVM-b evidence remains tied to
`c308034ab78619b39a59d26f3dc60e7df5b52649` and is never relabeled.

## Layout

- `asic_core/`: exact Tiny Tapeout LSC-1 RTL boundary.
- `fpga_harness/`: ULX3S pin-accurate harness boundary.
- `docs/LSC1_PROTOCOL.md`: versioned transport/packet contract.
- `docs/LSC1_TRANSACTION_PROTOCOL.md`: normative transaction protocol v1,
  modelled executably by `sim/lsc1_transaction.py`.
- `host/`: Mac-side runtime that prepares transactions and owns VM state,
  documented in `docs/HOST_RUNTIME.md`.
- `planning/`: machine-readable milestones and file-lane ownership.
- `src/`: retained compatibility/historical MinCore and M2 sources.

Run `make check`, `make sim`, `make lean`, and `make formal` where the
corresponding tools are installed. `make consistency` rejects stale active
top names and missing declared ASIC sources.
