# Protocol status

The authoritative LSC-1 v1 contract is [LSC1_PROTOCOL](LSC1_PROTOCOL.md).
The sole ASIC top is `lean_silicon_lsc1`; it exposes the Tiny Tapeout 8+8+8
ready/valid pin interface. A future ULX3S harness must use those exact pins.

The old fixed command byte stream remains only as a **seed-0 compatibility
protocol** inside MinCore RTL, used by existing arithmetic tests. It is not an
LSC-1 packet protocol and does not imply autonomous fetch or FPGA services.
