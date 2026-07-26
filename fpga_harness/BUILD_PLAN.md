# Harness build and check plan

An ordered plan from board-free checks to reproducible hardware evidence.
Stages 0–4 are now implemented for the historical MinCore seed. A successful
single-board run is recorded in `results/fpga-lsc1-20260726/`; stage 5's second
board gate remains open. The v1 packet endpoint is a separate unimplemented RTL
milestone.

The milestone this serves is `ulx3s_pin_harness` in `planning/milestones.yaml`,
which depends on `host_packet_runtime`. That dependency still prevents this
harness from becoming a v1 packet endpoint; the completed diagnostic path
exercises `lean_silicon_lsc1` as protocol seed-0 only.

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
python3 fpga_harness/board_detect.py --require datapath    # detector does not ingest run evidence
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

`datapath` is not satisfied by this discovery-only script. It reports
`not-validated` unconditionally because it does not parse, authenticate, or
replay hardware run records. `--require datapath` therefore always exits
non-zero even though a separate recorded run may exist. This prevents USB/JTAG
visibility from being mistaken for behaviour; inspect the run record directly.

## Stage 2 — board top and constraints (implemented for ULX3S v3.x / 85F)

The chosen target is ULX3S v3.x with an ECP5-85F. `ulx3s_v308.lpf` maps the
25 MHz oscillator, onboard FT231X UART, and LEDs. `ulx3s_lsc1_top.sv`
instantiates `lean_silicon_lsc1`; every byte crosses its exact 8-bit
ready/valid interface internally. A 16-bit power-on counter holds the
synchronous ASIC reset active for about 2.6 ms after configuration.

## Stage 3 — synthesis and place/route (implemented)

Entry condition: stage 2 merged.

`yosys` → `nextpnr-ecp5` → `ecppack`, all three already present in the
OSS CAD Suite action the repository pins for `formal-and-lint`. The first honest
artefact from this stage is a timing report at 25 MHz, not a bitstream that
merely built. A build that produces a bitstream while failing timing is not a
pass.

## Stage 4 — host byte driver and functional exchange (implemented for seed-0)

Entry condition: stage 3 produces a timing-clean bitstream.

The transparent UART bridge converts serial bytes to the ready/valid lane and
naturally exercises backpressure while its transmitter is busy. The UART-level
simulation covers STATUS, SET128, XOR128, and MUL128; the physical run records
expected versus observed bytes for the same operations. `ABORT` remains tied
low because the raw serial contract has no abort control, and FAULT recovery is
still limited to the seed's raw CLEAR command.

## Stage 5 — two-board reproducibility (open)

Entry condition: stage 4 log reproduces on a second board.

Only at this point may the harness be described as reproducibly validated
across boards. The current record may say exactly what it proves: the named
bitstream and four exchanges worked on one named board.

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
