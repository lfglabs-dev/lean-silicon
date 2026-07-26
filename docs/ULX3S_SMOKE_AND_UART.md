# ULX3S v3.1.8 Smoke and UART Harness (Sprint Deliverable)

**Status**: Reviewable artefacts only. Never merged. Never programmed to hardware.

## Worktree and provenance
- Branch base: `03926bbbbdc907d74214e4004985d36055d93a76` (`origin/main`). This is
  the pre-feature revision the branch was cut from. It contains none of the
  `fpga/ulx3s` design or build files, so it cannot build or identify the
  artefacts and must not be read as their source.
- Artefact source revision: `a472265112bb0183587bfdd81e6a61312b048185`
  (clean tree, no uncommitted changes). This commit is preserved in the
  published PR ancestry: it is an ancestor of the pre-merge PR tip
  `135fdeaa72dc116e2541a8c0b937aa45ee2edbd7` and therefore of this branch
  after its merge of `main`. Both source manifests record this full object ID.
  A non-shallow clone of the PR head can resolve and check out that revision;
  CI fetches the full history and asserts this ancestry rather than skipping
  it.
  Rebuilding from a fresh checkout at that revision with the pinned toolchain
  below reproduces `ulx3s_smoke.bit`, `ulx3s_bridge.bit`, `smoke.config` and
  `smoke.svf` byte for byte, at the same reported Fmax.
- Design sources unchanged since `a472265112bb0183587bfdd81e6a61312b048185`:
  no commit after it touches the RTL,
  the LPF or the build recipes -- the whole set the manifests digest -- so every
  revision from `a472265112bb0183587bfdd81e6a61312b048185` onward emits these
  same bytes. The RTL and LPF alone
  have been unchanged since `01e7046`; `a472265` widened what provenance records
  and left every synthesis command untouched, so the emitted bytes did not move
  with it. The later commits on this branch carry host tooling, tests and
  evidence only.
- Branch: `fpga/ulx3s-smoke-uart-mincore`
- Ownership: PR #13 owns host runtime files; PR #15 owns `board_detect/tests/global` and SHA256SUMS. Those paths untouched.

## Board facts (confirmed)
- PCB: v3.1.8
- FPGA: LFE5U-85F, IDCODE 0x41113043
- Clock: 25 MHz onboard at G2
- LED0: B2 (active low)
- US1 FT231X UART:
  - FPGA RX (host TX): M1 (ftdi_txd)
  - FPGA TX (host RX): L4 (ftdi_rxd)
- SDRAM: unused
- macOS cu/tty pair for US1

**LPF note**: `fpga/ulx3s/ulx3s_v318_smoke.lpf` is a **pin-subset hypothesis** derived from ulx3s-misc v316 (v3.1.6/3.1.7). v3.1.8 applicability is unconfirmed beyond G2/B2/M1/L4 stability across v3.x. No full board LPF reproduced.

## P0 smoke (counter/LED heartbeat)
- RTL: [fpga/ulx3s/smoke_top.sv](../fpga/ulx3s/smoke_top.sv)
- Constraints: [fpga/ulx3s/ulx3s_v318_smoke.lpf](../fpga/ulx3s/ulx3s_v318_smoke.lpf)
- Build script: [fpga/ulx3s/build_smoke.sh](../fpga/ulx3s/build_smoke.sh)

### Toolchain (pinned OSS CAD Suite 2026-07-25)
Reproduced verbatim in `results/ulx3s-smoke-uart-20260725/tool_versions.txt`:
```
Yosys 0.67+94 (git sha1 7defa5186-dirty, Release, Clang /usr/bin/clang++ 18.1.8)
"nextpnr-ecp5" -- Next Generation Place and Route (Version nextpnr-0.10-100-gfb95bb8e)
Project Trellis ecppack Version 1.4-79-g56bb170
```

### Exact commands executed (no --timing-allow-fail)
```sh
make -C fpga/ulx3s smoke      # runs fpga/ulx3s/build_smoke.sh
```
The script resolves the repository root from its own location, so it may be run
from any working directory. It archives the bitstream, config and SVF into
`results/ulx3s-smoke-uart-20260725/` under the names the manifest lists, writes
`SHA256SUMS` there, and then re-verifies it with `sha256sum -c` before exiting.

### Post-route timing (captured)
The LPF carries `FREQUENCY PORT "clk" 25.000000 MHz`. Without it nextpnr falls
back to a 12 MHz default and a passing report says nothing about the real board
clock.
```
Info: Max frequency for clock '$glbnet$clk$TRELLIS_IO_IN': 291.97 MHz (PASS at 25.00 MHz)
```

### Bitstream artefacts
- `results/ulx3s-smoke-uart-20260725/ulx3s_smoke.bit`
- SHA256: `eb3d81acee7562549af79f6c6d03d713c86f5a46a0892b6fd056f2c073cb45d2`

## P1 UART + bridge (1 Mbaud)
- UART RX/TX: [fpga/ulx3s/uart_rx.sv](../fpga/ulx3s/uart_rx.sv), [uart_tx.sv](../fpga/ulx3s/uart_tx.sv)
  - 1 Mbaud at 25 MHz (DIV=25)
  - 2-flop synchroniser on RX
  - Framing error detection; byte dropped on error
- Bridge: [fpga/ulx3s/uart_bridge.sv](../fpga/ulx3s/uart_bridge.sv)
  - Instantiates **exact** `lean_silicon_lsc1` (MinCore seed, not v1 packet)
  - One-deep skid buffer in each direction. Each buffer's ready signal deasserts
    on the same handshake that fills it, so no byte is presented to a side that
    has not signalled room for it and none is replaced before the far side took it.
  - `RX_VALID` is held until the core completes the handshake, rather than pulsed
    against a ready sampled a cycle earlier.
  - `TX_READY` is the transmit buffer's empty flag, not a mirror of the
    serialiser's ready one cycle late.
  - POR reset: a zero-initialised shift register, so `rst_n` is genuinely held
    low for 8 edges before release. A synchroniser that only ever shifts in ones
    never asserts reset at all and leaves the whole design at `x`.
  - Sticky `rx_overrun` observability probe: set if a byte arrives while the
    receive buffer is full and not draining. It drives no logic; the testbench
    asserts it stays clear.
  - Framing error or 0x7f byte produces ABORT pulse
- Top: [fpga/ulx3s/ulx3s_top.sv](../fpga/ulx3s/ulx3s_top.sv) (USE_SMOKE=0 selects bridge)
- Build: [fpga/ulx3s/build_uart.sh](../fpga/ulx3s/build_uart.sh)

### Bridge post-route (same flow)
Built with `make -C fpga/ulx3s uart`.
```
Info: Max frequency for clock '$glbnet$clk$TRELLIS_IO_IN': 154.37 MHz (PASS at 25.00 MHz)
```
Device utilisation confirms the core is really in the image, not optimised away:
703 TRELLIS_COMB and 402 TRELLIS_FF against 34/25 for the bare smoke design.
Only 4 TRELLIS_IO are used (`clk`, `led`, `uart_rx`, `uart_tx`), so the 8-bit
ASIC boundary is not widened out to pins.
- Bitstream: `results/ulx3s-smoke-uart-20260725/ulx3s_bridge.bit`
- SHA256: `7272b0d8f5ccbe5de328aa1f0d1461e6e35b58cc4a2e132e5024aedeed08c187`
- Byte-identical across two independent runs of the build script.

## P1 Python driver (new harness-owned path)
- [fpga_harness/ulx3s_uart.py](../fpga_harness/ulx3s_uart.py)
- **Explicit serial path only**. No enumeration. No persistence. No auto-detect.
- Commands: `--tx set|xor|mul|status|clear --port /dev/... --payload <hex>`
- Independent expected values for SET, XOR **and MUL**. The MUL expectation is
  computed locally by both oracles in `sim/model.py` (schoolbook carry-less
  multiply plus long reduction, and the LSB-first bit-serial recurrence) and
  cross-checked against each other. The process exit status depends on the
  comparison, so a complete but incorrect 16-byte product exits 1 rather than 0.
- STATUS is checked against the fixed `01 01 0f 08` signature the RTL emits, so
  four garbage bytes exit 1. This matters because `status` is the default `--tx`.
- Stale-byte drain on open and between transactions.
- Timeout and clear/status support.

### Known transport limitation: `0x7f` is not carried transparently

`uart_bridge.sv` raises its abort pulse on **any** received `0x7f`, not only on
one in command position, so a `0x7f` inside an operand tears the transaction
down mid-flight. Reproduced in simulation: a SET128 whose payload byte 5 is
`0x7f` returns 15 bytes, with `0xe0` from byte 5 onward instead of the echo.
A 128-bit operand is arbitrary data, so an unlucky vector hits this — roughly
6% of random SET payloads and 12% of random XOR/MUL operand pairs.

Until the bridge framing distinguishes payload bytes from command bytes, the
driver refuses such an operand and exits **2** (tooling limit) rather than 1
(board answered wrong), so it cannot be misread as a silicon fault. This is an
open design question on the bridge, not a property of `lean_silicon_lsc1`: the
ASIC takes ABORT on `uio_in[6]`, a pin, and has no in-band abort byte.

Example (never run on hardware without review):
```sh
python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx status
python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx set --payload 00000000000000000000000000000000
```

## P2 Tests
- Boundary: `make fpga-boundary` (and direct `python3 fpga_harness/boundary_check.py`) → OK
- Harness unit tests: `make fpga-harness` → 139 tests OK
- Sim: `make python` → 163 tests OK
- Icarus benches: `make sim` builds and runs both `test/tb_stream_alu.sv` and
  `test/tb_uart_bridge.sv`. The bridge bench is wired into the target rather
  than run by hand, so a regression in it fails the suite.

`tb_uart_bridge` contains a real 1 Mbaud 8N1 receiver, not a liveness window.
It fails on a response byte that is never serialised, on a stop bit that is not
high, on a final data bit not held for a full baud interval, on any byte that
differs from an independently computed expectation, on an unexpected extra byte,
and on `rx_overrun`. Covered transactions: STATUS, SET with an all-zero payload,
SET with a mixed payload, XOR, MUL against the `sim/model.py` vector, unknown
opcode → `0xe0`, and abort-then-recover.

Mutation testing was used to show the bench and the harness tests actually
discriminate, rather than passing because the code happens to be correct:

| Mutation | Reintroduced defect | Result |
| --- | --- | --- |
| M1 | `uart_tx` releases `tx_ready` at `bit_cnt == 8` | caught — `byte 0 is 81, expected 01` |
| M4 | POR shift register that only shifts in ones | caught |
| MA | Original `uart_bridge.sv` ready/valid logic verbatim | caught — STATUS receives 2 of 4 bytes, SET 8 of 16 |
| MB | `--tx mul` returns 0 without comparing | caught by 4 harness tests |

Run order used:
```sh
make check          # includes fpga-boundary, fpga-harness, checksum-check
make sim            # both Icarus benches
```

## Programming (SRAM-only, review gate)
**Never execute before independent review.**

```sh
# SRAM load only (volatile). Power cycle to recover.
openFPGALoader -b ulx3s results/ulx3s-smoke-uart-20260725/ulx3s_smoke.bit
# or for bridge:
openFPGALoader -b ulx3s results/ulx3s-smoke-uart-20260725/ulx3s_bridge.bit
```

**Explicit prohibition**: Do not pass `-f` (flash). This design is SRAM-only smoke. Flash would persist a partial harness across power cycles and violates the "review before any hardware" rule.

Power-cycle recovery: remove power or press reset; SRAM contents are lost.

## What this is not
- Not a CPU/ISA validation.
- Not a datapath validation on silicon.
- Not a claim that bytes crossed a physical ULX3S.
- The artefacts prove: reproducible OSS flow from the exact source recorded under "Worktree and provenance" above, exact `lean_silicon_lsc1` pin contract instantiated, post-route timing closed against an explicit 25 MHz constraint, and clean tests.

## Supported transaction sequence (MinCore protocol)
- SET128 (0x03): 1+16 bytes in → 16 bytes echo
- XOR128 (0x01): 1+32 bytes (A,B interleaved) → 16 bytes
- MUL128 (0x02): 1+32 bytes (A then B) → 16 bytes
- STATUS (0x7e): 1 byte → 4 status bytes
- CLEAR (0x7d): 1 byte, no response, clears sticky fault
- ABORT via uio_in[6] (from framing error or 0x7f byte)

All bytes traverse ui_in/uo_out/uio_* ready/valid. No wide bypass.

## Blockers / limits
- No physical ULX3S attached in sprint environment.
- No Verilator full bridge test (Icarus only; Verilator would require additional wrapper).
- Bridge driver lacks host-side flow control backpressure beyond TX_READY gating.
- LPF is hypothesis only for v3.1.8; full pin list and bank voltages unverified here.
- **0x7f cannot appear as a payload byte.** The bridge treats it as an abort at
  the byte layer, before any command framing, so a SET/XOR/MUL operand
  containing 0x7f aborts the transaction instead of being delivered. This is the
  documented ABORT contract, not a regression; escaping or framing the payload
  would change the wire protocol and is deliberately out of scope for this PR.
- The bridge is one byte deep in each direction. That is sufficient here because
  the host is slower than the core, but it is not a general flow-control layer.

## Artefact manifest (local)
Every file listed below is present in the committed results directory. Verify with
`cd results/ulx3s-smoke-uart-20260725 && sha256sum -c SHA256SUMS && sha256sum -c SHA256SUMS_bridge.txt`.
```
results/ulx3s-smoke-uart-20260725/
  SHA256SUMS               # ulx3s_smoke.bit, smoke.config, smoke.svf
  SHA256SUMS_bridge.txt    # ulx3s_bridge.bit
  ulx3s_smoke.bit          # eb3d81ac...
  ulx3s_bridge.bit         # 7272b0d8...
  smoke.config
  smoke.svf
  tool_versions.txt        tool_versions_uart.txt
  yosys.log                yosys_uart.log
  nextpnr.log              nextpnr_uart.log
  timing.txt               timing_uart.txt
```
`ecppack` emits nothing on success, so its log is not archived; an empty file
would not distinguish a silent run from a run that never happened.
The repository `.gitignore` excludes `*.log` globally; this directory is
exempted so the synthesis and route evidence is actually reviewable.

All deliverables stop at the verified boundary. No fabricated execution logs.
