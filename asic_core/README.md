# LSC-1 ASIC core

This is the sole Tiny Tapeout RTL boundary.  Its public top is
`lean_silicon_lsc1`, with `ui_in[7:0]`, `uo_out[7:0]`, and `uio[7:0]`.
There is no ASIC memory controller, autonomous fetch, USB/SDRAM controller,
BLAKE3 datapath, or field inverter.

The copied MinCore arithmetic RTL is a verified datapath seed.  The top is
pin-compatible and exercised today, but it implements only seed stream commands,
not the LSC-1 packet executor.  See `../docs/ROADMAP.md` for completion gates.
