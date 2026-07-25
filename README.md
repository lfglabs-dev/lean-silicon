# leanSilicon

**A formally verified physical scalar coprocessor for leanVM-b.**

LSC-1 receives one host-prepared instruction transaction at a time over an
8-bit ready/valid interface. The Mac owns compilation, program storage, VM
memory, hints/witnesses, pointer resolution, deferred equality, inversion
assistance, BLAKE3, traces, and proofs. The ASIC validates and executes the
non-BLAKE3 scalar transition, returning next pc/fp, writes, deferred events,
service requests, retirement, or fault.

The current RTL is an exercised MinCore arithmetic seed behind the final
`lean_silicon_lsc1` Tiny Tapeout top. It is not yet the LSC-1 v1 packet
executor; see [ROADMAP](docs/ROADMAP.md) and [STATUS](docs/STATUS.md).
Frozen leanVM-b evidence remains tied to
`c308034ab78619b39a59d26f3dc60e7df5b52649` and is never relabeled.

## Layout

- `asic_core/`: exact Tiny Tapeout LSC-1 RTL boundary.
- `fpga_harness/`: ULX3S pin-accurate harness boundary.
- `docs/LSC1_PROTOCOL.md`: versioned transport/packet contract.
- `planning/`: machine-readable milestones and file-lane ownership.
- `src/`: retained compatibility/historical MinCore and M2 sources.

Run `make check`, `make sim`, `make lean`, and `make formal` where the
corresponding tools are installed. `make consistency` rejects stale active
top names and missing declared ASIC sources.
