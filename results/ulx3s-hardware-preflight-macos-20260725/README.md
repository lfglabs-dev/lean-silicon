# ULX3S-85F hardware preflight, macOS: attested evidence

A physical ULX3S-85F was brought up on a Mac on 2026-07-25 and its visibility
captured. This directory records what that capture established.

## The one thing to read first

**This is an attestation, not a capture.** The run happened outside this
repository, on hardware this container cannot see. What is written here was
reported back together with an archive checksum; it was not re-derived here and
cannot be. Nothing in this directory is machine-checkable against the archive
from inside this repository.

**The archive is not committed.** A raw preflight archive carries a full USB
enumeration, and with it the board serial and every unrelated device attached to
the machine. Only the facts below are recorded, plus the checksum by which the
archive can be identified if it is produced again.

**No data path was tested.** Nothing was programmed, no bitstream was built or
loaded, and no byte crossed the LSC-1 8-bit ready/valid interface.

## Archive

| Field | Value |
|---|---|
| Name | `ulx3s-hardware-preflight-macos.zip` |
| SHA-256 | `eddca55e5ea70bcc31a60370cd73aeb137e812afd6be2f96d4211a6bb12a400f` |
| Members | 10 |
| Internal `SHA256SUMS` | independently verified, 8 of 8 |
| Path traversal check | clean |
| Source tree captured from | clean detached `c0397ca602679188e97791d774377da89fb058bc` |

The SHA-256 was computed independently of the producer. The archive itself is
not reachable from this container; the checksum is recorded so that a future
copy can be identified as the same bytes, not as proof that these bytes were
inspected here.

## Host

| Field | Value |
|---|---|
| OS | macOS 26.5.2 |
| Connection | US1, Micro-B, data-carrying cable |
| Second port | US2 present and visible, not connected during the capture |

## What was observed

### USB

| Probe | Result |
|---|---|
| `ioreg -p IOUSB -l`, filtered | FTDI at VID:PID `0403:6015` on US1 |
| `system_profiler SPUSBDataType -json` | **empty tree** with the board attached and enumerating |

The `system_profiler` result is the important one: it is a silent false
negative on this macOS version. A USB layer that trusts `system_profiler` alone
reports a healthy board absent. `tools/ulx3s_mac_preflight.py` therefore probes
`system_profiler` first but falls back to `ioreg` in both its plist and text
forms, always runs all three, and records which one answered.

The board serial number and every other device on the bus are deliberately not
recorded here.

### JTAG

| Probe | Result |
|---|---|
| `openFPGALoader -b ulx3s --detect` | exit 0 |
| `openFPGALoader --detect` (bare) | exit 1 |

| Field | Value |
|---|---|
| Vendor | Lattice |
| Model | `LFE5U-85` |
| IDCODE | `0x41113043` |
| IR length | 8 |
| JTAG clock | limited to 3 MHz |

The bare `--detect` failure is not a board fault: openFPGALoader defaults to an
FT2232 cable, which the ULX3S is not. The board profile has to be named.

An IDCODE identifies silicon. It says nothing about a loaded design.

### Physical, read from photographs

| Field | Value |
|---|---|
| PCB silkscreen revision | `v3.1.8` |
| USB product string | `v3.0.8` |
| FPGA marking | `LFE5U-85F` |
| SDRAM marking | Alliance Memory `AS4C16M16SB-6TIN` |
| SDRAM organisation | 16M x 16 = 256 Mibit = 32 MiB installed |
| US1 | Micro-USB, connected |

**The silkscreen supersedes the descriptor.** `v3.1.8` is the physical board
revision; `v3.0.8` is firmware in the FT231X EEPROM and lags the PCB. Any
document or artifact recording `v3.0.8` as the board revision is wrong.

### Repository checks on the capture host

| Command | Result |
|---|---|
| `make fpga-boundary` | passed |
| `make fpga-harness` | passed, 77 tests |

## What this establishes

- The ULX3S USB identity `0403:6015` and the ECP5 85F IDCODE `0x41113043` are
  now confirmed against hardware. Until this capture they were vendor-documented
  values in `fpga_harness/board_detect.py`, unconfirmed anywhere
  (`fpga_harness/INVENTORY.md` section 5).
- The board is physically an 85F: the IDCODE and the package marking agree.
- 32 MiB of SDRAM is installed. The LSC-1 harness must not use it; the figure is
  inventory, recorded so that no future stage silently assumes a different size.
- Two probes in `fpga_harness/board_detect.py` false-negative on macOS. Both are
  recorded as harness-lane follow-up in `docs/ULX3S_MAC_PREFLIGHT.md` section 9
  and are not fixed by this lane.

## What this does not establish

- **Nothing about the data path.** Not tested, not validated. No bitstream, no
  programming, no byte across the ready/valid pins. The data-path gate remains
  the official Rust comparison in `tools/host_upstream_comparison.py` against
  frozen leanVM-b `c308034ab78619b39a59d26f3dc60e7df5b52649`.
- **Nothing about the LSC-1 RTL.** No design was loaded, so no protocol
  behaviour and no timing closure was observed.
- **Nothing reproducible from this repository.** These are attested facts from a
  machine with hardware attached. Re-running anything checked in here on a
  machine without a board reproduces the refusal path, not this capture. See
  `results/ulx3s-mac-preflight-20260725/` for what the Linux container can
  actually run.

## Related

- `docs/ULX3S_MAC_PREFLIGHT.md`: the procedure this capture corrected.
- `results/ulx3s-mac-preflight-20260725/`: unfiltered output of the container
  runs, which are refusal-path only.
- `tools/ulx3s_mac_preflight.py`: the tool that produces an attachable artifact
  on a Mac with the board present.
