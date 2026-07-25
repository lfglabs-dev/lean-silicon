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
(`toolchain` -> `usb` -> `jtag` -> `datapath`). Its USB probe reads
`/sys/bus/usb/devices`. That path is **Linux sysfs and does not exist on
macOS**, so on Darwin the probe returns no devices and the ladder reports the
`usb` level absent *even with the board plugged in and enumerating*.

That is a false negative, not a board fault, and it must not be read as one.
The harness file is owned by another lane and is not modified here. Instead
`tools/ulx3s_mac_preflight.py` captures the USB layer with
`system_profiler SPUSBDataType` and emits a fixture in the exact shape
`board_detect.py` already documents for `--fixture`, so the ladder is replayed
unmodified from a macOS capture.

The `toolchain` and `jtag` levels of `board_detect.py` shell out to `shutil.which`
and `openFPGALoader` and do work on macOS. Only the `usb` level is affected.

## 2. Connect

The ULX3S has two USB ports. **US1** is the one wired to the FT231X bridge and
is the only one that gives JTAG and a serial console; on the v3.0.x revisions
it is a Micro-B connector.

1. Power the board down and unplug everything.
2. Connect **US1** to the Mac with a **USB-C to Micro-B cable that carries
   data**.
3. Do not connect anything to the second port during preflight, so there is
   exactly one candidate device on the bus.

### The charge-only cable failure signature

Most bundled USB-C to Micro-B cables are power-only. With one of those:

- the board powers up and its LEDs light, so it looks alive;
- `system_profiler SPUSBDataType` lists **nothing** at `0x0403:0x6015`;
- `openFPGALoader --detect` reports no cable or no device.

Board LEDs are not enumeration evidence. If USB shows nothing, change the
cable before suspecting the board, and record which cable was used with
`--confirm cable_type=...`.

## 3. Capture

From the repository root on the Mac:

```sh
python3 tools/ulx3s_mac_preflight.py \
    --out results/ulx3s-preflight.json \
    --fixture-out results/ulx3s-board.fixture.json \
    --confirm board_revision="ULX3S v3.0.8" \
    --confirm fpga_density="LFE5U-85F-6BG381C" \
    --confirm sdram_part="AS4C32M16SB-7TCN, 32Mx16 = 64 MiB" \
    --confirm us1_connector="Micro-B" \
    --confirm cable_type="Anker USB-C to Micro-B, data" \
    --confirm power_source="US1 bus power only"
```

or via the Makefile, which writes to the same two paths:

```sh
make ulx3s-preflight
```

The tool runs, in order:

| Layer | Command | Recorded |
|---|---|---|
| USB | `system_profiler SPUSBDataType -json` | every enumerated device, and which match `0x0403:0x6015` |
| toolchain | `openFPGALoader`, `fujprog`, `dfu-util`, `yosys`, `nextpnr-ecp5`, `ecppack` with `--Version`, `--version`, `-V` | path, first version flag that answered, full version text |
| JTAG | `openFPGALoader --detect`, then `openFPGALoader -c ft232 --detect` | every IDCODE found, split into recognised ECP5 parts and unrecognised codes |

Both probe forms are always run and both are recorded, because
`openFPGALoader` needs an explicit cable on some macOS/libftdi combinations
and the version flag it accepts differs across releases. Raw `stdout` and
`stderr` are embedded verbatim (clipped at 64 KiB and flagged if clipped), so
a parse this tool gets wrong is still reviewable from the artifact.

Run these by hand too if a capture looks wrong; the tool runs nothing else:

```sh
system_profiler SPUSBDataType | grep -A 8 -i ulx3s
openFPGALoader --detect
openFPGALoader --Version
```

An ULX3S-85F answers `--detect` with IDCODE `0x41113043`. The four codes the
harness recognises are `0x21111043` (12F), `0x41111043` (25F), `0x41112043`
(45F) and `0x41113043` (85F). An IDCODE identifies **silicon**, not a loaded
design.

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
| `board_revision` | e.g. `ULX3S v3.0.8` | silkscreen near the ULX3S logo |
| `fpga_density` | e.g. `LFE5U-85F-6BG381C` | marking on the large Lattice package; cross-check against the captured IDCODE |
| `sdram_part` | e.g. `AS4C32M16SB-7TCN` (32Mx16 = 64 MiB) | marking on the SDRAM chip |
| `us1_connector` | Micro-B on v3.0.x | connector nearest the FT231X, silkscreened US1 |
| `cable_type` | make, and whether it carries data | the cable in hand |
| `power_source` | US1 bus power, or external | jumper/switch position |

`sdram_part` is recorded for inventory only. The LSC-1 harness must not use
SDRAM; capturing it prevents a future stage from quietly assuming a size.

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

## 7. What this establishes, and what it does not

Establishes, when the capture is clean:

- which loader and build tools exist on this Mac, and at which versions;
- whether macOS enumerates a device at the ULX3S USB identity over US1;
- whether an ECP5 TAP answers `openFPGALoader --detect` with a known IDCODE.

Does not establish:

- that any bitstream is loaded, or correct;
- that a single host byte crossed the LSC-1 ready/valid pins;
- anything about the ASIC RTL, its protocol behaviour, or timing closure;
- any leanVM-b equivalence result.

The USB VID:PID and the ECP5 IDCODE table are vendor-documented values
imported from `fpga_harness/board_detect.py`. They are not confirmed against
hardware anywhere in this repository (`fpga_harness/INVENTORY.md` section 5);
a real capture from Thomas's board is what would confirm them, and the artifact
is the thing to attach back.

## 8. Tests

`sim/test_ulx3s_mac_preflight.py` runs under `make python` on any platform with
no board and no toolchain. Its USB and JTAG payloads are **synthetic**: text
hand-written in the shape the real tools emit. They cover parsing, the fixture
round-trip through `board_detect.detect`, the non-Darwin refusal and the
fail-closed next stage. They establish nothing about hardware, and the module
docstring says so.
