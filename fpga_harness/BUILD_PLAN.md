# Harness build and check plan

An ordered plan from what runs today to what would constitute real hardware
evidence. Stages 0–1 are executable now and are wired into `make check`.
Stages 2 onward are **not** implemented and are deliberately not faked; each
lists its entry condition so it cannot be skipped.

The milestone this serves is `ulx3s_pin_harness` in `planning/milestones.yaml`,
which depends on `host_packet_runtime`. That dependency is the reason this lane
stops at stage 1: the harness cannot be a v1 packet endpoint before the packet
runtime exists, and `lean_silicon_lsc1` is still protocol seed-0.

## Stage 0 — checks that run with no board and no FPGA toolchain

Runnable anywhere Python 3 and PyYAML are available.

```sh
make fpga-boundary     # structural pin/no-bypass check, fails the build on violation
make fpga-harness      # 30 deterministic unit tests, no board touched
make fpga-detect       # report the local detection ladder, never fails
make check             # includes fpga-boundary and fpga-harness
```

`make fpga-detect` is reporting-only by design. To gate on it, ask for a level
explicitly:

```sh
python3 fpga_harness/board_detect.py --require jtag        # needs a real board
python3 fpga_harness/board_detect.py --require datapath    # always fails, see below
```

Reproducible board-free runs use a fixture instead of the real machine:

```sh
python3 fpga_harness/board_detect.py --fixture <fixture.json> --json
```

where the fixture supplies `tools`, `versions`, `usb_devices`, and `jtag_scan`.

## Stage 1 — detection, and what each level is worth

`board_detect.py` reports four levels. The distinction is the point: the first
three are *visibility*, only the fourth is *behaviour*.

| Level | Question answered | What it does **not** show |
|---|---|---|
| `toolchain` | can this machine build or load a bitstream? | nothing about any board |
| `usb` | is a device with the ULX3S USB identity enumerated? | nothing about the FPGA fabric; a USB identity is a descriptor, not a working device |
| `jtag` | does an ECP5 TAP answer with a known IDCODE? | which design is loaded, or whether it works |
| `datapath` | did host bytes actually cross the 8-bit ready/valid pins and produce the expected responses? | — this is the only level that would be evidence |

`datapath` can never be satisfied by this script. It reports `not-validated`
unconditionally and names its four missing prerequisites, because the repository
contains no harness bitstream, no `.lpf`, no host byte driver, and no captured
byte log. `--require datapath` therefore always exits non-zero. A test asserts
this holds even when the toolchain, USB, and JTAG levels are all fully
satisfied, which is exactly the confusion this lane exists to prevent.

Raising `datapath` requires committing real hardware logs and the code that
produced them. It is not a code change to this script.

## Stage 2 — board top and constraints (not implemented)

Entry condition: a decision on host transport and board revision.

1. Pick the board revision and FPGA density; record it in this directory.
2. Write the `.lpf` mapping all 24 interface signals plus clock and reset to
   real ULX3S pins, respecting the `uio_oe` directions.
3. Write a board top that instantiates `lean_silicon_lsc1` and connects **only**
   the 8-bit interface, per [BOUNDARY](BOUNDARY.md).
4. Add the reset synchroniser the placeholder RTL currently lacks.

Blocking unknowns are itemised in [INVENTORY](INVENTORY.md) §5.

## Stage 3 — synthesis and place/route (not implemented)

Entry condition: stage 2 merged.

`yosys` → `nextpnr-ecp5` → `ecppack`, all three already present in the
OSS CAD Suite action the repository pins for `formal-and-lint`. The first honest
artefact from this stage is a timing report at 25 MHz, not a bitstream that
merely built. A build that produces a bitstream while failing timing is not a
pass.

## Stage 4 — host byte driver and loopback (not implemented)

Entry condition: stage 3 produces a timing-clean bitstream.

A host driver that performs the handshake one byte per beat, plus a loopback
that exercises `RX_READY` deassertion, `TX_VALID` stalling under `TX_READY` low,
`ABORT`, and `FAULT`. Deliverable is a recorded byte log with expected versus
observed bytes.

## Stage 5 — data-path validation (not implemented)

Entry condition: stage 4 log reproduces on a second board.

Only at this point may anything in this repository describe the harness as
validated, and only for the exact bitstream, board, and log committed. Until
then, every artefact in this directory says the data path is unvalidated.

## Explicit non-goals

Restating so a future stage does not quietly acquire them: no autonomous fetch,
no VM memory ownership, no SDRAM/PSRAM/USB ASIC controller, no pointer resolver,
no inverter, no BLAKE3 datapath, and no wide internal compatibility bypass. The
FPGA is only a pin-accurate harness.

## CI

`make check` runs stages 0–1 in the existing `executable-models` job, so the
boundary check and the harness tests gate every push and pull request. No CI job
builds a bitstream, because no CI runner has a board attached and a green build
job would misrepresent that.
