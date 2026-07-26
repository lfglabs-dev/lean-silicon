# ULX3S pin-accurate harness

This directory now contains a working ULX3S-85F debug target for the historical
MinCore seed implemented by `lean_silicon_lsc1`. It drives and samples the exact
LSC-1 8-bit ready/valid pins one accepted byte at a time through a transparent
115200-baud UART bridge; there is no wide compatibility bypass.

The bridge is diagnostic infrastructure, not a VM service owner. Mac-host
software still owns program storage, VM memory, hints, witnesses, pointer
resolution, deferred equality, inversion assistance, BLAKE3, traces, and
proofs. The v1 packet endpoint remains specified/modelled but not implemented
in RTL.

## Contents

| File | Purpose |
|---|---|
| [INVENTORY.md](INVENTORY.md) | What exists, what is absent, toolchain, pins/clocks/resets, explicit unknowns |
| [BOUNDARY.md](BOUNDARY.md) | Normative pin-accurate boundary and the prohibition on wide bypasses |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Ordered plan: what runs today, and the entry condition for each unimplemented stage |
| `rtl/ulx3s_lsc1_top.sv`, `rtl/uart_*.sv` | 25 MHz ULX3S top and UART/ready-valid bridge |
| `ulx3s_v308.lpf` | v3.x clock, FT231X serial, and LED constraints |
| `build_ulx3s.sh` | Yosys → nextpnr-ecp5 → ecppack build |
| `rtl/lean_silicon_lsc1_pins.sv` | Structural pin-boundary contract |
| `boundary_check.py` | Structural pin/no-bypass check, run by `make check` |
| `board_detect.py` | Layered board detection that never claims data-path validation |
| `test_boundary_check.py`, `test_board_detect.py` | Deterministic tests; no board required |

## Build and use

```sh
make fpga-boundary   # structural boundary check (gating)
make fpga-harness    # deterministic unit tests, no board (gating)
make fpga-detect     # local detection ladder, reporting only
make fpga-uart-sim   # UART-level STATUS/SET/XOR/MUL simulation
make fpga-build      # ULX3S-85F bitstream; requires the OSS CAD Suite
make fpga-load-sram  # volatile load only; does not write SPI flash
```

The host exchange is then, for example:

```sh
python3 fpga_harness/host/mincore_uart.py \
  --port /dev/cu.usbserial-D01623 --operation mul --vector mul128 --execute
```

The first physical run is recorded in
`results/fpga-lsc1-20260726/`: STATUS, SET128, XOR128, and MUL128 all returned
the expected bytes on one ULX3S-85F v3.0.8. This is real seed-0 datapath
evidence for that board/run, not evidence that the unimplemented v1 packet
executor exists and not the two-board reproducibility gate in `BUILD_PLAN.md`.
