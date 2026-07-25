# ULX3S macOS preflight evidence

Unfiltered command output for the macOS ULX3S-85F preflight capture
(`tools/ulx3s_mac_preflight.py`, `docs/ULX3S_MAC_PREFLIGHT.md`).

Tested source: `tested-source-head.txt`. Host: `toolchain.txt`.

| Log | Command | Exit |
|---|---|---|
| `make-check.log` | `make check` | `make-check.status` |
| `preflight-tests.log` | `python3 -m unittest sim.test_ulx3s_mac_preflight -v` | `preflight-tests.status` |
| `preflight-linux.log` | `python3 tools/ulx3s_mac_preflight.py --out ... --fixture-out ...` | `preflight-linux.status` |
| `next-stage.log` | `python3 tools/ulx3s_mac_preflight.py --next-stage` | `next-stage.status` |
| `replay-linux.log` | `python3 fpga_harness/board_detect.py --fixture board-linux.fixture.json` | `replay-linux.status` |

`preflight-linux.json` is the emitted `leansilicon.hardware.preflight/1`
artifact and `board-linux.fixture.json` is the `board_detect.py --fixture`
document derived from it.

## The one thing to read first

**These runs are from a Linux container. No Mac and no ULX3S board were
present.** `preflight-linux.json` is therefore a capture of the *refusal*
path, not a board capture: its `usb` block is `"supported": false` and says so
in prose, no tool was on PATH, and no IDCODE was found. It is checked in as
evidence that the tool behaves correctly when it cannot see what it is looking
for, and as a shape reviewers can diff a real Mac capture against.

## What this run establishes

- `make check` is green with the preflight tests included (exit 0).
- The 36 unit tests pass. Their USB and JTAG payloads are **synthetic**: text
  hand-written in the shape `system_profiler` and `openFPGALoader` emit. They
  cover parsing, the fixture round-trip through `board_detect.detect`, the
  non-Darwin refusal and the fail-closed next stage.
- Off Darwin the USB layer reports `unsupported`, not `absent`, and names the
  `/sys/bus/usb/devices` limit of the harness probe as the reason.
- The emitted fixture is accepted by `fpga_harness/board_detect.py` unmodified;
  `replay-linux.log` shows the ladder consuming it and reporting
  `data-path behaviour validated: NO`.
- `--next-stage` exits 1 with all four prerequisites missing
  (`lpf_constraints`, `board_top`, `timing_clean_bitstream`,
  `host_byte_driver`).

## What this run does not establish

- **Nothing about hardware.** No board was attached, no USB device was
  enumerated, no JTAG chain answered. The synthetic fixtures are not captures.
- **Nothing about macOS.** The Darwin branch of `capture_usb` was not executed;
  only its refusal branch was. `system_profiler` was never run.
- **The vendor constants are unconfirmed.** The USB VID:PID and the ECP5
  IDCODE table are vendor-documented values imported from
  `fpga_harness/board_detect.py`, not confirmed against hardware anywhere in
  this repository (`fpga_harness/INVENTORY.md` section 5).
- **No data path.** No byte crossed the LSC-1 8-bit ready/valid pins. The
  data-path gate remains the official Rust comparison
  (`tools/host_upstream_comparison.py`), unchanged by this lane.

## Reproducing

```sh
make check
python3 -m unittest sim.test_ulx3s_mac_preflight -v
make ulx3s-preflight
make ulx3s-next-stage      # exits 1 by design
```

On a Mac with the board on US1, `make ulx3s-preflight` produces the real
artifact; `docs/ULX3S_MAC_PREFLIGHT.md` is the procedure and the checklist.
