# ULX3S pin-accurate harness

The harness is a future board/debug target, not a VM service owner.  It must
drive and sample the exact LSC-1 8-bit ready/valid pins one byte per accepted
beat; internal wide datapaths may buffer packets but may not bypass those pins.
Mac-host software owns program storage, VM memory, hints, witnesses, pointer
resolution, deferred equality, inversion assistance, BLAKE3, traces, and proofs.

The directory intentionally contains an interface contract and no fabricated
ULX3S bitstream or USB implementation.

## Contents

| File | Purpose |
|---|---|
| [INVENTORY.md](INVENTORY.md) | What exists, what is absent, toolchain, pins/clocks/resets, explicit unknowns |
| [BOUNDARY.md](BOUNDARY.md) | Normative pin-accurate boundary and the prohibition on wide bypasses |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Ordered plan: what runs today, and the entry condition for each unimplemented stage |
| `rtl/lean_silicon_lsc1_pins.sv` | Port-list-only pin contract; no bitstream, no handshake yet |
| `boundary_check.py` | Structural pin/no-bypass check, run by `make check` |
| `board_detect.py` | Layered board detection that never claims data-path validation |
| `test_boundary_check.py`, `test_board_detect.py` | Deterministic tests; no board required |

## Status

No bitstream has been built and no board has been driven from this repository.
The data path is **unvalidated**, and `board_detect.py` reports it that way even
when a real board is visible over USB and JTAG — tool, USB, and JTAG visibility
are not evidence that bytes cross the interface correctly.

```sh
make fpga-boundary   # structural boundary check (gating)
make fpga-harness    # deterministic unit tests, no board (gating)
make fpga-detect     # local detection ladder, reporting only
```
