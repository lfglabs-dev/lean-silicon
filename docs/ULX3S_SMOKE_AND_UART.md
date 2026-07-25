# ULX3S v3.1.8 Smoke and UART Harness (Sprint Deliverable)

**Status**: Reviewable artefacts only. Never merged. Never programmed to hardware.

## Worktree and provenance
- Detached at exact `origin/main` 03926bbbbdc907d74214e4004985d36055d93a76
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
```
Yosys 0.67+94 (git sha1 7defa5186-dirty, Release, Clang /usr/bin/clang++ 18.1.8)
nextpnr-ecp5 --version: nextpnr-ecp5 0.7+75 (git sha1 ...)
ecppack from prjtrellis
```

### Exact commands executed (no --timing-allow-fail)
```sh
cd fpga/ulx3s
yosys -p 'read_verilog -sv smoke_top.sv; hierarchy -check -top smoke_top; proc; synth_ecp5 -top smoke_top; write_json smoke.json'
nextpnr-ecp5 --85k --package CABGA381 --json smoke.json --lpf ulx3s_v318_smoke.lpf --textcfg smoke.config
ecppack --svf smoke.svf smoke.config smoke.bit
```

### Post-route timing (captured)
```
Info: Max frequency for clock '$glbnet$clk$TRELLIS_IO_IN': 291.97 MHz (PASS at 12.00 MHz)
```

### Bitstream artefacts
- `results/ulx3s-smoke-uart-20260725/ulx3s_smoke.bit`
- SHA256: `96eb9eda7421bac902eacaeced21eee0db9a80b8f2f2effdb52b515d68e0b2e3`

## P1 UART + bridge (1 Mbaud)
- UART RX/TX: [fpga/ulx3s/uart_rx.sv](../fpga/ulx3s/uart_rx.sv), [uart_tx.sv](../fpga/ulx3s/uart_tx.sv)
  - 1 Mbaud at 25 MHz (DIV=25)
  - 2-flop synchroniser on RX
  - Framing error detection; byte dropped on error
- Bridge: [fpga/ulx3s/uart_bridge.sv](../fpga/ulx3s/uart_bridge.sv)
  - Instantiates **exact** `lean_silicon_lsc1` (MinCore seed, not v1 packet)
  - Byte buffering + backpressure: RX_VALID asserted only when core `rx_ready`
  - POR 2-flop reset synchroniser
  - TX_READY only when UART serializer idle
  - Framing error or 0x7f byte produces ABORT pulse
- Top: [fpga/ulx3s/ulx3s_top.sv](../fpga/ulx3s/ulx3s_top.sv) (USE_SMOKE=0 selects bridge)
- Build: [fpga/ulx3s/build_uart.sh](../fpga/ulx3s/build_uart.sh)

### Bridge post-route (same flow)
```
Info: Max frequency for clock '$glbnet$clk$TRELLIS_IO_IN': 160.26 MHz (PASS at 12.00 MHz)
```
- Bitstream: `results/ulx3s-smoke-uart-20260725/ulx3s_bridge.bit`
- SHA256: `0c190f247b9c7683e111d76bcd3c891b26fa27bbd1ad4477ede9b2b7598faccc`

## P1 Python driver (new harness-owned path)
- [fpga_harness/ulx3s_uart.py](../fpga_harness/ulx3s_uart.py)
- **Explicit serial path only**. No enumeration. No persistence. No auto-detect.
- Commands: `--tx set|xor|mul|status|clear --port /dev/... --payload <hex>`
- Independent expected constants for SET/XOR; MUL delegates to oracle.
- Stale-byte drain on open and between transactions.
- Timeout and clear/status support.

Example (never run on hardware without review):
```sh
python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx status
python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx set --payload 00000000000000000000000000000000
```

## P2 Tests
- Boundary: `make fpga-boundary` (and direct `python3 fpga_harness/boundary_check.py`) → OK
- Harness unit tests: `make fpga-harness` → 101 tests OK
- Sim: `make sim` (python) → 163 tests OK
- Icarus bridge TB: `test/tb_uart_bridge.sv` compiles and runs (liveness window; no full UART model in TB)

Run order used:
```sh
make fpga-boundary
make fpga-harness
python3 -m unittest discover -s sim -q
iverilog ... && vvp /tmp/tb_uart.vvp
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
- The artefacts prove: reproducible OSS flow from exact source at 03926bb, exact `lean_silicon_lsc1` pin contract instantiated, timing numbers at 25 MHz target, and clean tests.

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

## Artefact manifest (local)
```
results/ulx3s-smoke-uart-20260725/
  SHA256SUMS
  ulx3s_smoke.bit          # 96eb9eda...
  ulx3s_bridge.bit         # 0c190f24...
  tool_versions*.txt
  nextpnr_*.log (timing lines)
```

All deliverables stop at the verified boundary. No fabricated execution logs.
