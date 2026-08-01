# Tiny Tapeout ICE40UP5K build evidence — 2026-08-01

This is local **build evidence**, not FPGA/emulator execution and not physical
silicon evidence. No hardware was connected, accessed, programmed, or flashed.

## Immutable inputs

- source before this validation slice: commit
  `054bf3731b802f3262c9d339c46a8835f32d17f3`, tree
  `71011100e86303b1b6d408a2f2313be70d7dcaaf`;
- active top: `tt_um_lfglabs_lsc1u` from `info.yaml`;
- official Tiny Tapeout action inspected at
  `TinyTapeout/tt-gds-action@651ea05e19e86a9c26d00307e8081ceb53d328d3`;
- official support tools used at
  `TinyTapeout/tt-support-tools@ff75e344cd8b65c744081e3719e0cb926203eb57`;
- comparison inspected at
  `Th0rgal/tt-myfirstchip@cc07d2c3e261231cfd6629d10db99fd3c9f9ba77`.

## Commands and results

The same `tt_tool.py --create-user-config` and `tt_fpga.py harden` commands
used by the official composite action were run from a Python virtual
environment containing its exact requirements plus `test/requirements.txt`.

```text
python /tmp/tt-support-tools/tt_tool.py --create-user-config
exit 0

/usr/bin/time -v python /tmp/tt-support-tools/tt_fpga.py harden
exit 0; elapsed 0:03.31; max RSS 96,312 KiB
```

The first hardening attempt reached successful SystemVerilog elaboration and
synthesis, then exited nonzero with exact blocker
`/bin/sh: 1: nextpnr-ice40: not found` / `placement failed`. Installing Ubuntu
24.04 packages `nextpnr-ice40` and `fpga-icestorm` was the smallest environment
fix; no RTL compatibility change was required. The retained
`local-build.log.gz` is the successful second run.

Tools in the successful local run:

```text
Python 3.12.3
Yosys 0.33 (git sha1 2584903a060)
nextpnr-ice40 0.6-3build5
fpga-icestorm 0~20230218gitd20a5e9-1
```

Result: 479 `SB_LUT4`, 283 flip-flops, 8 `SB_IO`; routed successfully. The
official support tool constrained this ASIC-simulator image at 12 MHz and
reported 46.46 MHz maximum, PASS. This is distinct from the ASIC project's
25 MHz `info.yaml` clock declaration.

The `.bin` itself is intentionally not committed. CI uploads it as an artifact
and uploads candidate commit/tree plus hashes separately. `artifact-SHA256SUMS`
records the locally reproduced build products, including the 104 KiB packed
image.
