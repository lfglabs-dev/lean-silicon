# Tiny Tapeout ttsky26c integration

This lane is an experimental physical-integration surface for LSC-1. The
handwritten SystemVerilog and exact ASIC boundary remain in `asic_core/`.
`src/tt_um_lfglabs_lean_silicon_lsc1.sv` is only a Tiny Tapeout naming,
selection, and safe-output adapter around `lean_silicon_lsc1`.

## Pin contract

| Pins | Direction | Meaning |
| --- | --- | --- |
| `ui_in[7:0]` | host to ASIC | request byte, accepted on `REQUEST_VALID && REQUEST_READY` |
| `uo_out[7:0]` | ASIC to host | response byte, accepted on `RESPONSE_VALID && RESPONSE_READY` |
| `uio[0]` | input | `REQUEST_VALID` |
| `uio[1]` | output | `REQUEST_READY` |
| `uio[2]` | output | `RESPONSE_VALID` |
| `uio[3]` | input | `RESPONSE_READY` |
| `uio[4]` | output | `BUSY` |
| `uio[5]` | output | sticky `FAULT` |
| `uio[6]` | input | synchronous `ABORT` |
| `uio[7]` | output | one-cycle `DONE_PULSE` |
| `clk` | input | 25 MHz target clock |
| `rst_n` | input | active-low synchronous core reset |
| `ena` | input | TT project select; low blocks handshakes and disables/clamps outputs |

`uio_oe` is `8'b10110110` while selected and zero while deselected. Dedicated
and bidirectional output paths are assigned in every state.

## Source boundary

`info.yaml` paths are relative to `src/`. The `../asic_core/rtl/...` entries
make the Tiny Tapeout tooling compile the canonical sources in place. No FPGA
harness, UART, JTAG, flash, memory controller, or board RTL is part of this
integration.

## Evidence and limitations

The initial `2x2` selection is a conservative candidate inherited from the
repository design-space study, not a fit result. The study's 259-simple-gate
number covers only the radix-1 multiplier transition; it excludes registers,
packet/control logic, clocking, placement and routing overhead.

Local RTL lint/elaboration, cocotb, and repository regressions establish only
source-level behavior. The draft PR's `gds` workflow is authoritative for
LibreLane hardening and exposes separate `gds`, `precheck`, `gl_test`, and
`viewer` jobs. Until those jobs pass and their reports are inspected, GDS,
precheck, DRC/LVS, gate-level simulation, timing, area/tile fit, and PPA all
remain unresolved. A successful workflow still does not by itself establish
production ASIC readiness.

The workflow pins `TinyTapeout/tt-gds-action` (and its `precheck`, `gl_test`,
and `viewer` subactions) to commit
`30d38a7dfc6fda561d452b196fc822af0332ec23` (`ttsky26c`). Its documented GDS
action invokes `tt_tool.py --create-user-config` followed by LibreLane; it
does not document project inputs for `RUN_KLAYOUT_DRC`, `RUN_KLAYOUT_XOR`, or
routing-congestion overrides. Therefore this repository does not add or alter
such gates without a flow revision that documents their support and an
appropriate project-level rationale.

The reviewed external run at commit `7e30c885103024af1db6d3ef85051921fabd0cc0`
did not harden: LibreLane 3.0.3 stopped at global placement with
`[GPL-0301] Utilization 601.128 % exceeds ...`. Its `precheck` and `gl_test`
jobs were skipped, so it supplies no routed congestion report, no precheck
report, and no DRC or XOR result. Settlement requires a subsequent successful
pinned GDS run with its routing/congestion summary and produced GDS, followed
by a successful precheck report that explicitly records its DRC and XOR
outcomes; those artifacts must be inspected before making any DRC/XOR,
routeability, tile-fit, PPA, signoff, release-equivalence, or ASIC-readiness
claim.

The local support-tool metadata/config generation succeeds with
`tt_tool.py --create-user-config`. A local hardening attempt stops before
LibreLane with exit 1 and the exact blocker
`/tmp/lsc1-venv/bin/python: No module named librelane`; `PDK_ROOT` is also
unset. These are local-environment limitations, not physical-design results.
The draft PR workflow installs its pinned LibreLane and Sky130 PDK, so its jobs
are the authoritative external attempt.

Local integration evidence collected before the PR:

| Command | Exit | Result |
| --- | ---: | --- |
| Icarus `-g2012 -Wall` elaboration of the TT top and canonical source closure | 0 | PASS |
| Yosys `hierarchy -check; proc; check` on the same top | 0 | PASS |
| `make -C test` (cocotb TT pin/reset/enable/handshake test) | 0 | PASS |
| `make check` with repository/test dependencies | 0 | PASS |
| `make sim` | 0 | PASS |
| `tt_tool.py --create-user-config` | 0 | PASS |
| `make lean` | 2 | unresolved locally: `sandboxed lake shim: real Lake binary not found` |
| `make formal` | 2 | unresolved locally: `/bin/sh: 1: sby: not found` |
| `tt_tool.py --harden` | 1 | unresolved locally: LibreLane module absent as quoted above |
