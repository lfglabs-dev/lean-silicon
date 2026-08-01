# ULX3S pin-accurate harness

The harness is a future board/debug target, not a VM service owner.  It must
drive and sample the exact LSC-1 8-bit ready/valid pins one byte per accepted
beat; internal wide datapaths may buffer packets but may not bypass those pins.
Mac-host software owns program storage, VM memory, hints, witnesses, pointer
resolution, deferred equality, inversion assistance, BLAKE3, traces, and proofs.

The directory contains the interface contract plus an archived source-built
ULX3S smoke/UART bitstream deliverable. It does not contain a USB implementation
or evidence of any board being programmed or validated.

## Contents

| File | Purpose |
|---|---|
| [INVENTORY.md](INVENTORY.md) | What exists, what is absent, toolchain, pins/clocks/resets, explicit unknowns |
| [BOUNDARY.md](BOUNDARY.md) | Normative pin-accurate boundary and the prohibition on wide bypasses |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Ordered plan: what runs today, and the entry condition for each unimplemented stage |
| `rtl/lean_silicon_lsc1_pins.sv` | Port-list-only pin contract; no handshake implementation in this harness path |
| [`../docs/ULX3S_SMOKE_AND_UART.md`](../docs/ULX3S_SMOKE_AND_UART.md) | Archived source-build artefacts, provenance, and explicit hardware limits |
| `boundary_check.py` | Structural pin/no-bypass check, run by `make check` |
| `board_detect.py` | Layered board detection that never claims data-path validation |
| `test_boundary_check.py`, `test_board_detect.py` | Deterministic tests; no board required |

## Status

Smoke and UART bitstreams have been source-built and archived; no board has been
driven or validated from this repository. The data path is **unvalidated**, and
`board_detect.py` reports it that way even when a real board is visible over USB
and JTAG — tool, USB, and JTAG visibility are not evidence that bytes cross the
interface correctly.

## Tiny Tapeout ICE40UP5K ASIC-simulator lane

`lsc1u_protocol.py` is a transport-neutral driver for the active
`tt_um_lfglabs_lsc1u` wrapper.  It drives only `ui_in`, `uio_in`, `ena`, and
`rst_n`; samples `uo_out`, `uio_out`, and `uio_oe`; enforces the exact
ready/valid handshakes and direction mask; and rejects values that cannot be
represented as known eight-bit integers.  A future FPGA bridge or demoboard
adapter implements its four-method `PinBackend` protocol without changing the
arithmetic oracle or vectors.

The shared `lsc1u_vectors.json` corpus covers SET/XOR/MUL identities, zero,
one, all-ones, low/top/unit bits, deterministic random values, long stalls, and
the little-endian `0x87` GF(2^128) reduction boundary.  RTL cocotb and the
post-synthesis Tiny Tapeout `gl_test` consume that same corpus.  Protocol tests
add reset and `ena` interruption, unsupported-opcode faulting, consecutive
commands, stable output under backpressure, known outputs, and latency bounds.

The `Tiny Tapeout FPGA ASIC simulator` workflow builds an ICE40UP5K `.bin` and
records hashes.  This proves only that the image synthesized, placed, routed,
and packed. It does **not** execute the image in an emulator, program an FPGA,
or validate physical silicon. No hardware is accessed by that workflow or by
the host-driver unit tests.

Pinned upstream comparison and authoritative inputs (inspected 2026-08-01):

- comparison: `Th0rgal/tt-myfirstchip@cc07d2c3e261231cfd6629d10db99fd3c9f9ba77`;
- official action tag `ttsky26c` resolved to
  `TinyTapeout/tt-gds-action@651ea05e19e86a9c26d00307e8081ceb53d328d3`;
- support tools are overridden from the official mutable `main` default to
  `TinyTapeout/tt-support-tools@ff75e344cd8b65c744081e3719e0cb926203eb57`.

The official composite itself contains nested `actions/checkout@v6`,
`actions/setup-python@v6`, `YosysHQ/setup-oss-cad-suite@v3`, and
`actions/upload-artifact@v7` references. Those nested refs cannot be overridden
by callers. The outer official action and every directly controlled workflow
action/input are immutable; eliminating the nested mutable refs would require
forking or vendoring the authoritative action.

```sh
make fpga-boundary   # structural boundary check (gating)
make fpga-harness    # deterministic unit tests, no board (gating)
make fpga-detect     # local detection ladder, reporting only
make fpga-preflight  # bounded USB/JTAG/UART preflight, never programs hardware
```

`hardware_preflight.py` writes a JSON evidence record of the exact commit and
clean state, tool versions, host boundary, USB identity, stable Linux serial
path/permissions, and a bounded `openFPGALoader -b ulx3s --detect` result. It
has no bitstream parameter and rejects flash/programming flags. Linux selects
`/dev/serial/by-id/*D01623*` before a bounded `/dev/ttyUSB*` fallback; macOS
keeps its `cu.usbserial` discovery. If a UART candidate exists, it is only
opened then closed in a deadline-bounded child process after the loader scan;
it sends no protocol bytes or BREAK.
