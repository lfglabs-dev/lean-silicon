# ULX3S/ECP5 harness inventory

Inventory of what the repository actually contains for a ULX3S/ECP5 harness,
taken from the tree at the commit this document was added on.  Everything below
is either a file path that exists, a literal read out of a source file, or an
explicitly labelled unknown.  No item here is hardware evidence: no bitstream
has been built and no board has been driven.  See [BUILD_PLAN](BUILD_PLAN.md)
for what would have to happen first, and [BOUNDARY](BOUNDARY.md) for the pin
rule the harness may not break.

## 1. Files that exist today

| Path | Lines | What it actually is |
|---|---|---|
| `fpga_harness/README.md` | 11 | Prose boundary statement; no build content |
| `fpga_harness/rtl/lean_silicon_lsc1_pins.sv` | 15 | Port-list-only pin contract, all outputs tied to constants |

That is the entire pre-existing harness. The RTL declares
`module lean_silicon_lsc1_pins` with `clk`, `rst_n`, and five 8-bit ASIC-facing
ports (`asic_ui_in`, `asic_uo_out`, `asic_uio_drive`, `asic_uio_sample`,
`asic_uio_oe`).  It assigns `8'b0` to each output and sinks the rest into an
`_unused` reduction.  It does **not** instantiate `lean_silicon_lsc1`, does not
implement a handshake, and does not contain a state element.  It is a
placeholder that pins down widths and direction intent, nothing more.

## 2. Files that do not exist

Each of these is genuinely absent, not located elsewhere under another name.
This is the honest gap list for a board build:

- no ECP5 constraint file (`.lpf`) anywhere in the tree;
- no `nextpnr-ecp5` / `ecppack` invocation, script, or Makefile target;
- no ULX3S board top level that instantiates the ASIC top;
- no clock generation (`PLL`/`EHXPLLL`) or reset synchroniser;
- no USB/UART/FTDI bridge RTL and no host-side byte-exchange driver;
- no bitstream, no packed artefact, and no programming recipe;
- no CI job that builds or loads anything for FPGA;
- no captured hardware log of any kind.

## 3. Toolchain

The repository already installs an ECP5-capable toolchain in CI, for a
different purpose. `.github/workflows/ci.yml` job `formal-and-lint` uses
`YosysHQ/setup-oss-cad-suite` pinned to
`aefa8397bbf8fc6670a0a62af9805a89738f3cde`.  OSS CAD Suite ships `yosys`,
`nextpnr-ecp5`, and `ecppack`, so the synthesis/place/pack path for ECP5 is
already reachable in CI and is currently used only for ASIC lint, synthesis,
and the bounded GF(2^8) proof.

Nothing pins a *loader*. `openFPGALoader` and `fujprog` are not installed by any
workflow and are not referenced anywhere in the tree.

Verified availability in the container this inventory was produced in:

| Tool | Status here |
|---|---|
| `python3` | present (3.12.3) |
| `yosys`, `nextpnr-ecp5`, `ecppack` | absent |
| `openFPGALoader`, `fujprog`, `dfu-util` | absent |
| `iverilog`, `sby` | absent |
| `lsusb` | absent |

So the board-detection script and its tests are the only parts of this lane
that can be exercised locally; every FPGA build step is unrunnable here and is
documented as such rather than reported as passing.

## 4. Pins, clocks, and resets

### Interface (known exactly)

The ASIC-facing interface is fixed and is read directly out of source. From
`asic_core/rtl/lean_silicon_lsc1.sv`: `ui_in`, `uo_out`, `uio_in`, `uio_out`,
and `uio_oe` are each `[7:0]`, and `assign uio_oe = 8'b10110110`.  The `uio`
role assignment is published in `info.yaml` and `docs/LSC1_PROTOCOL.md`:

| `uio` bit | Role | Direction (from `uio_oe`) |
|---|---|---|
| 0 | `RX_VALID` | host drives |
| 1 | `RX_READY` | ASIC drives |
| 2 | `TX_VALID` | ASIC drives |
| 3 | `TX_READY` | host drives |
| 4 | `BUSY` | ASIC drives |
| 5 | `FAULT` | ASIC drives |
| 6 | `ABORT` | host drives |
| 7 | `DONE_PULSE` (`DONE` in the protocol doc) | ASIC drives |

`boundary_check.py` re-derives this table from source on every `make check`.

### Clock (partly unknown)

`info.yaml` declares `clock_hz: 25000000`. `asic_core/rtl/leanvm_b_stream_alu.sv`
has exactly one clocked process, `always @(posedge clk)`, so the ASIC is
single-clock with no internal domain crossing.

Vendor documentation describes the ULX3S as carrying a 25 MHz oscillator, which
would match `clock_hz` without a PLL. **Unknown/unverified:** this has not been
confirmed against a board, no board revision is pinned, and whether the harness
ultimately needs an `EHXPLLL` depends on the board clock and on the host link
rate, neither of which is fixed yet.

### Reset (partly unknown)

The ASIC reset is `rst_n`, active low and **synchronous**: the single clocked
block begins `if (!rst_n)`. The placeholder harness exposes `rst_n` but does not
synchronise or debounce it.  **Unknown:** which ULX3S source drives reset (button
versus power-on versus host-commanded), and the release sequencing between the
ASIC reset and the host link.  `ena` exists on the ASIC top and is unused there.

## 5. Explicit unknowns

Recorded so they are not silently resolved by assumption later:

1. Board revision and exact FPGA density (`12F`/`25F`/`45F`/`85F`) are unpinned.
   The detection script recognises all four IDCODEs but no choice is committed.
2. The USB VID:PID `0x0403:0x6015` and the four ECP5 IDCODEs used by the
   detection script are vendor-documented values, **not confirmed here against
   hardware**.
3. Physical pin assignment for the 24 interface signals is entirely open; no
   `.lpf` exists and no candidate GPIO bank has been selected.
4. Host transport is undecided (FTDI serial versus JTAG-side channel), so the
   byte rate across the interface and any host-side clock crossing are unknown.
5. Timing closure at 25 MHz for a harness that wraps the ASIC top is unmeasured.
6. Whether a harness needs to buffer whole packets, and how deep, depends on the
   host packet lane's v1 schemas, which are not yet RTL.
7. `lean_silicon_lsc1` is protocol seed-0, not packet v1, so any harness built
   now would exercise the historical fixed command stream and not a v1 endpoint.

## 6. Evidence level

Source inspection and locally executed Python only. Nothing here is a hardware
result, a synthesis result, or a timing result.
