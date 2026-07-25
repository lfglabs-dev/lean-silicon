# FPGA harness inventory and board detection — evidence

Evidence for the lane that added `fpga_harness/INVENTORY.md`,
`fpga_harness/BOUNDARY.md`, `fpga_harness/BUILD_PLAN.md`,
`fpga_harness/boundary_check.py`, and `fpga_harness/board_detect.py`.

Branch base: `main` at `40320dcfe56fad4d262d2a7ef08b6ed96a43dbf2` (merged in after PR #10).
Tested source: `fpga_harness/` tree object recorded in `tested-source-sha.txt`.
Environment: see `toolchain.txt`.

## No hardware was involved

**No bitstream was built and no board was attached or driven.** There is no
FPGA result here of any kind. The container had no ECP5 toolchain, no loader,
and no ULX3S device; `toolchain.txt` records that directly. Nothing in this
directory should be read as hardware validation.

## Results

| Log | Command | Exit | Meaning |
|---|---|---|---|
| `make-check.log` | `make check` | 0 | Full gating suite, including the two new targets |
| `fpga-boundary.log` | `python3 fpga_harness/boundary_check.py` | 0 | Pin/no-bypass structural check passes on current RTL |
| `fpga-harness-tests.log` | `unittest discover -s fpga_harness -v` | 0 | 48 deterministic tests, no board touched |
| `fpga-detect-real.log` | `board_detect.py` | 0 | Real probe of this container: every level absent |
| `fpga-detect-mock-full.log` | `board_detect.py --fixture ... --json` | 0 | Synthetic full visibility; `datapath_validated: false` |
| `fpga-detect-require-datapath.log` | `board_detect.py --fixture ... --require datapath` | 1 | Fails as designed even with full visibility |

The pair `fpga-detect-mock-full` and `fpga-detect-require-datapath` is the point
of the lane: build tools, a loader, the ULX3S USB identity, and a genuine
`LFE5U-85F` IDCODE are all satisfied, `highest_satisfied_level` is `jtag`, and
data-path behaviour is still reported as not validated. Visibility is not
behaviour.

## Recorded environment limitations

These three failed because the tool is not installed (exit 127, "not found").
They are pre-existing environment limits, unrelated to this change, and are kept
rather than omitted:

| Log | Command | Exit | Missing tool |
|---|---|---|---|
| `make-sim.log` | `make sim` | 2 | `iverilog` |
| `make-formal.log` | `make formal` | 2 | `sby` |
| `make-lean.log` | `make lean` | 2 | real `lake` (only a shim present) |

RTL simulation, the bounded proof, Yosys lint/synthesis, and the Lean build were
therefore **not** run locally. CI covers them.

## Evidence level

Source inspection plus locally executed Python. No hardware evidence, no
synthesis evidence, no timing evidence, no simulation evidence.
