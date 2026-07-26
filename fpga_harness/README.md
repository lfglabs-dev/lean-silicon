# FPGA harness and ULX3S integration

The harness is a future board/debug target, not a VM service owner.  It must
drive and sample the exact LSC-1 8-bit ready/valid pins one byte per accepted
beat; internal wide datapaths may buffer packets but may not bypass those pins.
Mac-host software owns program storage, VM memory, hints, witnesses, pointer
resolution, deferred equality, inversion assistance, BLAKE3, traces, and proofs.

The pin contract remains the architectural boundary. The maintained ULX3S
implementation and reproducible build artifacts live under `fpga/ulx3s/` and
are documented in `docs/ULX3S_SMOKE_AND_UART.md`; this directory owns the host
driver, structural checks and regression tests around that implementation.

## Contents

| File | Purpose |
|---|---|
| [INVENTORY.md](INVENTORY.md) | What exists, what is absent, toolchain, pins/clocks/resets, explicit unknowns |
| [BOUNDARY.md](BOUNDARY.md) | Normative pin-accurate boundary and the prohibition on wide bypasses |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Ordered plan: what runs today, and the entry condition for each unimplemented stage |
| `rtl/lean_silicon_lsc1_pins.sv` | Port-list-only pin contract; no bitstream, no handshake yet |
| `ulx3s_uart.py` | Maintained PR #16 1 Mbaud driver and reusable transaction adapter |
| `host/mincore_program.py` | Restricted leanVM-b SET/XOR/MUL program runner |
| `boundary_check.py` | Structural pin/no-bypass check, run by `make check` |
| `board_detect.py` | Layered board detection that never claims data-path validation |
| `test_boundary_check.py`, `test_board_detect.py` | Deterministic tests; no board required |

## Status

PR #16 provides reproducibly built smoke and MinCore UART bitstreams plus RTL
simulation. PR #19 now preserves both the older candidate run and a bounded
physical follow-up of the maintained 1 Mbaud path on one ULX3S-85F.
`board_detect.py` still distinguishes visibility from validation: only the
explicit recorded transactions establish the latter.

```sh
make fpga-boundary   # structural boundary check (gating)
make fpga-harness    # deterministic unit tests, no board (gating)
make fpga-detect     # local detection ladder, reporting only
```

The compiled-program runner now uses PR #16's maintained 1 Mbaud driver and
resynchronization contract:

```sh
make fpga-run-program FPGA_PORT=/dev/cu.usbserial-D01623
```

The runner checks STATUS first, preserves write-once VM memory on the Mac,
checks every FPGA result against the host oracle before committing it, and
stops before sending an unsupported instruction. The archived 12-operation
`PREFIX_MATCH` was reproduced on the maintained 1 Mbaud bitstream: 12 physical
SET/XOR/MUL transitions matched the upstream memory before the runner stopped
at the first unsupported JUMP.
