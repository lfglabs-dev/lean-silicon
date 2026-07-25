# ULX3S-85F preflight from macOS

Exact commands for bringing a physical ULX3S-85F up on a Mac, capturing what
is actually visible, and attaching that capture back to the repository.

This is a **visibility** procedure. Nothing in it is data-path evidence. A USB
descriptor, a JTAG IDCODE and a toolchain version say that a board exists and
answers; they say nothing about any design being loaded, correct, or driving
the LSC-1 8-bit ready/valid interface. The data-path gate remains the official
Rust comparison in `tools/host_upstream_comparison.py`
(`docs/HOST_RUNTIME.md` section 5), and it stays where it is until stage 4 of
`fpga_harness/BUILD_PLAN.md` produces a real byte log.

## 1. Why this is not just `board_detect.py`

`fpga_harness/board_detect.py` owns the four-level detection ladder
(`toolchain` -> `usb` -> `jtag` -> `datapath`). Two of its probes false-negative
on macOS with a healthy board attached. Both were observed on the real board
(section 7); neither is a board fault and neither may be read as one.

| Probe | Defect on macOS | Effect |
|---|---|---|
| `_enumerate_usb` | reads `/sys/bus/usb/devices`, which is **Linux sysfs and does not exist on macOS** | `usb` level reads absent while the board is enumerating |
| `_jtag_scan` | runs a bare `openFPGALoader --detect`, which defaults to an FT2232 cable and **exits 1 on a ULX3S** | `jtag` level reads absent while the TAP is answering |

`fpga_harness/` is owned by the ULX3S harness lane and is **not modified here**.
Section 9 records both defects as that lane's follow-up work, with the exact
call sites. What this lane does instead: `tools/ulx3s_mac_preflight.py` captures
the USB and JTAG layers with commands that work on Darwin and emits a fixture in
the exact shape `board_detect.py` already documents for `--fixture`, so the
ladder is replayed unmodified from a macOS capture.

The `toolchain` level of `board_detect.py` shells out to `shutil.which` and does
work on macOS.

## 2. Connect

The ULX3S has two USB ports. **US1** is the one wired to the FT231X bridge and
is the only one that gives JTAG and a serial console; on the v3.0.x and v3.1.x
revisions it is a Micro-B connector.

1. Power the board down and unplug everything.
2. Connect **US1** to the Mac with a **USB-C to Micro-B cable that carries
   data**.
3. Do not connect anything to the second port during preflight, so there is
   exactly one candidate device on the bus.

### The charge-only cable failure signature

Most bundled USB-C to Micro-B cables are power-only. With one of those:

- the board powers up and its LEDs light, so it looks alive;
- no USB probe lists anything at `0x0403:0x6015`;
- `openFPGALoader -b ulx3s --detect` reports no cable or no device.

Board LEDs are not enumeration evidence. If USB shows nothing, change the
cable before suspecting the board, and record which cable was used with
`--confirm cable_type=...`.

## 3. Capture

From the repository root on the Mac:

```sh
python3 tools/ulx3s_mac_preflight.py \
    --out results/ulx3s-preflight.json \
    --fixture-out results/ulx3s-board.fixture.json \
    --confirm board_revision="v3.1.8 (silkscreen)" \
    --confirm fpga_density="LFE5U-85F" \
    --confirm sdram_part="AS4C16M16SB-6TIN, 16Mx16 = 32 MiB" \
    --confirm us1_connector="Micro-B" \
    --confirm cable_type="USB-C to Micro-B, data" \
    --confirm power_source="US1 bus power only"
```

or via the Makefile, which writes to the same two paths:

```sh
make ulx3s-preflight
```

The tool runs, in order:

| Layer | Commands, in order | Recorded |
|---|---|---|
| USB | `system_profiler SPUSBDataType -json`, then `ioreg -p IOUSB -a -l -w 0`, then `ioreg -p IOUSB -l -w 0` | which probe answered, the device count, and which devices match `0x0403:0x6015` |
| toolchain | `openFPGALoader`, `fujprog`, `dfu-util`, `yosys`, `nextpnr-ecp5`, `ecppack` with `--Version`, `-V`, `--version` | path, the version flag that answered, the version text |
| JTAG | `openFPGALoader -b ulx3s --detect`, then `-c ft232 --detect`, then bare `--detect` | every IDCODE found, split into recognised ECP5 parts and unrecognised codes, plus which commands exited 0 |

Every probe in a layer is always run and every one is recorded; the first that
returns devices or IDCODEs sets `source`. The redundancy is not defensive
padding, it is three observed failures:

- **`system_profiler SPUSBDataType -json` returned an empty tree** on macOS
  26.5.2 with the board enumerating. `ioreg -p IOUSB` saw it. A single-probe
  USB layer would have reported the board absent.
- **Bare `openFPGALoader --detect` exits 1** on a ULX3S: its default cable is
  FT2232. `openFPGALoader -b ulx3s --detect` exits 0 and reports the chain.
- **openFPGALoader 1.1.1 rejects `--version`** and answers `--Version`. When a
  build prints a version and *then* exits non-zero, the tool salvages the text
  and flags the entry `version_exit_nonzero` rather than discarding it.

Toolchain and JTAG captures embed raw `stdout`/`stderr` verbatim (clipped at
64 KiB and flagged if clipped), so a parse this tool gets wrong is still
reviewable from the artifact. **USB captures do not.** A raw USB enumeration
lists every device attached to the machine, serial numbers included, and the
artifact is meant to be attachable to a pull request. See section 8.

Run these by hand too if a capture looks wrong; the tool runs nothing else:

```sh
ioreg -p IOUSB -l -w 0 | grep -i -B 4 -A 12 '"idVendor" = 1027'
openFPGALoader -b ulx3s --detect
openFPGALoader --Version
```

An ULX3S-85F answers with IDCODE `0x41113043`, model `LFE5U-85`, IR length 8.
The four codes the harness recognises are `0x21111043` (12F), `0x41111043`
(25F), `0x41112043` (45F) and `0x41113043` (85F). An IDCODE identifies
**silicon**, not a loaded design.

## 4. Replay through the harness ladder

The emitted fixture feeds `board_detect.py` unmodified, on the Mac or on any
reviewer's machine with no board attached:

```sh
python3 fpga_harness/board_detect.py --fixture results/ulx3s-board.fixture.json --json
```

The `datapath` level can never be satisfied this way, and `board_detect.py`
will not report it as satisfied: `_probe_datapath` is hard-wired to
`not-validated`. Replay reproduces the `toolchain`, `usb` and `jtag` levels
from a real capture; it does not create evidence that does not exist.

## 5. Physical checklist

Six facts no software probe on the Mac can establish. Each stays
`unconfirmed` in the artifact until a human reads the board and passes
`--confirm KEY=VALUE`. **Unconfirmed means unknown, not absent.**

| Key | What to read | Where |
|---|---|---|
| `board_revision` | e.g. `v3.1.8` | silkscreen near the ULX3S logo |
| `fpga_density` | e.g. `LFE5U-85F` | marking on the large Lattice package; cross-check against the captured IDCODE |
| `sdram_part` | e.g. `AS4C16M16SB-6TIN` (16Mx16 = 32 MiB) | marking on the SDRAM chip |
| `us1_connector` | Micro-B on v3.0.x and v3.1.x | connector nearest the FT231X, silkscreened US1 |
| `cable_type` | make, and whether it carries data | the cable in hand |
| `power_source` | US1 bus power, or external | jumper/switch position |

**Read `board_revision` off the silkscreen, not off the USB product string.**
On the board captured in section 7 the two disagree: the descriptor says
`v3.0.8` while the PCB says `v3.1.8`. The silkscreen is the physical revision
and wins. The descriptor is firmware in the FT231X EEPROM and lags.

`sdram_part` is recorded for inventory only. The LSC-1 harness must not use
SDRAM; capturing it prevents a future stage from quietly assuming a size. Do
not infer it from the board revision either: the captured board carries a
32 MiB `AS4C16M16SB-6TIN`, while other ULX3S units of the same generation ship
64 MiB parts.

If the confirmed `fpga_density` and the captured IDCODE disagree, the artifact
records both and neither is silently preferred. Resolve it before building a
bitstream, because `nextpnr-ecp5 --85k` against a 45F part fails late and
confusingly.

## 6. Next stage, and why it is closed

```sh
make ulx3s-next-stage
```

prints the command shape for bitstream and byte-log work and **exits non-zero**
while any prerequisite is missing. In the tree today all four are missing:

| Prerequisite | Satisfied by |
|---|---|
| `lpf_constraints` | an ECP5 `.lpf` mapping all 24 interface signals |
| `board_top` | a ULX3S top instantiating `lean_silicon_lsc1` |
| `timing_clean_bitstream` | a bitstream with a passing 25 MHz timing report, not merely a build |
| `host_byte_driver` | a host-side byte-exchange driver for the ready/valid handshake |

The check is a presence test against the tree, so it cannot be satisfied by
editing prose. Satisfying all four still only opens stage 4; data-path
validation additionally requires a recorded byte log reproduced on a second
board (`fpga_harness/BUILD_PLAN.md` stage 5).

## 7. The board that has been captured

A physical ULX3S-85F has been brought up on macOS 26.5.2 and its visibility
captured. The facts below are **attested**: they were established outside this
repository and reported back with an archive checksum. They are recorded here
because they are what corrected this procedure. They are not re-derivable from
anything checked in, and the archive itself is not in this repository.

`results/ulx3s-hardware-preflight-macos-20260725/README.md` is the full record,
including the archive SHA-256 and what was and was not verified. In summary:

| Fact | Value |
|---|---|
| USB identity over US1 | `0403:6015`, seen by filtered `ioreg -p IOUSB -l` |
| `system_profiler SPUSBDataType -json` | **empty tree**, board attached and enumerating |
| `openFPGALoader -b ulx3s --detect` | exit 0 |
| bare `openFPGALoader --detect` | exit 1, defaults to FT2232 |
| JTAG | Lattice ECP5 `LFE5U-85`, IDCODE `0x41113043`, IR length 8, limited to 3 MHz |
| PCB silkscreen | `v3.1.8` |
| USB product string | `v3.0.8`, superseded by the silkscreen |
| FPGA marking | `LFE5U-85F` |
| SDRAM marking | `AS4C16M16SB-6TIN`, 16Mx16 = 256 Mibit = 32 MiB |
| Data path | **not tested, not validated** |

This confirms the USB VID:PID and the 85F IDCODE against hardware for the first
time. `fpga_harness/INVENTORY.md` section 5 still records them as unconfirmed;
updating it belongs to the harness lane (section 9).

It confirms nothing else. No bitstream was built or loaded, nothing was
programmed, and no byte crossed the LSC-1 ready/valid pins.

## 8. What the artifact deliberately withholds

The artifact is meant to be attachable to a pull request, so it must not carry
anything identifying the machine or its owner. By default:

- **raw USB output is not embedded.** Each USB probe records its byte length and
  a SHA-256 of its output instead, so the capture is still checkable against a
  local re-run without publishing the enumeration.
- **the board serial and its `locationID` are `<redacted>`.**
- **devices that are not the board keep only their VID and PID.** Name,
  manufacturer, serial, location and speed are dropped. A reviewer can still
  see how many devices were on the bus and that exactly one matched.

`--include-usb-detail` disables all three at once, for local debugging. Do not
pass it when producing an artifact to attach.

Toolchain and JTAG output is embedded verbatim. Neither names the machine.

## 9. Follow-up owned by the ULX3S harness lane

Two defects in `fpga_harness/board_detect.py` are confirmed by the section 7
capture. **They are not fixed here**; `fpga_harness/` belongs to the ULX3S
harness lane and this lane does not modify it. Recorded with exact call sites so
that lane can act:

| # | Site | Defect | Fix shape |
|---|---|---|---|
| 1 | `_enumerate_usb`, reading `/sys/bus/usb/devices` | Linux sysfs only; returns no devices on macOS with the board enumerating | branch on `platform.system() == "Darwin"` to an `ioreg -p IOUSB` probe; `tools/ulx3s_mac_preflight.py` has a tested parser for both the plist and text forms |
| 2 | `_jtag_scan`, the `openFPGALoader --detect` invocation near line 208 | no `-b` argument, so openFPGALoader defaults to FT2232 and exits 1 on a ULX3S | pass `-b ulx3s`, or try board profiles in order and record which answered |

Also for that lane: `fpga_harness/INVENTORY.md` section 5 marks the USB VID:PID
and the ECP5 IDCODE table unconfirmed against hardware. Section 7 confirms both
for the 85F. The inventory should be updated by its owner, not by this lane.

Until #1 and #2 land, a macOS user should read `usb` or `jtag` absent from
`board_detect.py` as **unknown, not absent**, and re-check with
`make ulx3s-preflight`.

## 10. What this establishes, and what it does not

Establishes, when the capture is clean:

- which loader and build tools exist on this Mac, and at which versions;
- whether macOS enumerates a device at the ULX3S USB identity over US1;
- whether an ECP5 TAP answers a board-qualified `--detect` with a known IDCODE.

Does not establish:

- that any bitstream is loaded, or correct;
- that a single host byte crossed the LSC-1 ready/valid pins;
- anything about the ASIC RTL, its protocol behaviour, or timing closure;
- any leanVM-b equivalence result.

The data-path gate is unchanged by anything in this document: it remains the
official Rust comparison in `tools/host_upstream_comparison.py` against frozen
leanVM-b `c308034ab78619b39a59d26f3dc60e7df5b52649`.

## 11. Tests

`sim/test_ulx3s_mac_preflight.py` runs under `make python` on any platform with
no board and no toolchain. Its USB and JTAG payloads are **synthetic**: text
hand-written in the shape the real tools emit, including an empty
`system_profiler` tree and a `--version` rejection. They cover parsing of all
three USB probe forms, the fallback order, version salvage, the fixture
round-trip through `board_detect.detect`, the non-Darwin refusal, the redaction
policy of section 8 and the fail-closed next stage. They establish nothing about
hardware, and the module docstring says so.
