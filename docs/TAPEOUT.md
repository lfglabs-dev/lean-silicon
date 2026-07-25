# Tiny Tapeout target

The target top is `lean_silicon_lsc1` in `asic_core/rtl`, listed by
`info.yaml`. It has only the standard Tiny Tapeout `ui_in[7:0]`,
`uo_out[7:0]`, and `uio[7:0]` interface. uio transports byte ready/valid,
busy/fault, abort, and done as specified in [LSC1_PROTOCOL](LSC1_PROTOCOL.md).

Use the official flow only after the v1 packet executor is complete and
differentially validated. No LSC-1 PPA/tapeout-fit result exists yet. The
ULX3S is a pin-accurate debug harness; it must not introduce a wide internal
ASIC bypass.
