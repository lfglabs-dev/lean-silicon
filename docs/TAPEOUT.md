# Tiny Tapeout target

The ttsky26c integration top is `tt_um_lfglabs_lsc1u` in `src/`.
It is a thin wrapper around the reduced, profile-specific `lsc1u_core`.
See [TINY_TAPEOUT_TTSKY26C](TINY_TAPEOUT_TTSKY26C.md) for the
complete pin map, workflow, source boundary, and limitations.

No LSC-1 PPA or routed tile-fit result exists yet. The ULX3S remains a separate
pin-accurate debug harness and is not included in the Tiny Tapeout source list.
