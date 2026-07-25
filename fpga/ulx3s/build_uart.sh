#!/bin/sh
# Build the UART bridge + lean_silicon_lsc1 for ULX3S v3.1.8.
# SRAM-only. Never use -f.
set -eu
cd "$(dirname "$0")"

TOP=ulx3s_top
LPF=ulx3s_v318_smoke.lpf
OUTDIR=../../../results/ulx3s-smoke-uart-20260725
mkdir -p "$OUTDIR"

export PATH=/root/oss/bin:$PATH

echo "=== TOOL VERSIONS (UART) ===" | tee "$OUTDIR/tool_versions_uart.txt"
yosys -V 2>&1 | tee -a "$OUTDIR/tool_versions_uart.txt"
nextpnr-ecp5 --version 2>&1 | tee -a "$OUTDIR/tool_versions_uart.txt"
ecppack --help 2>&1 | head -1 | tee -a "$OUTDIR/tool_versions_uart.txt"
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$OUTDIR/tool_versions_uart.txt"

# Collect sources: bridge + uart + exact ASIC top + MinCore + multiplier
SOURCES="ulx3s_top.sv uart_bridge.sv uart_rx.sv uart_tx.sv \
         ../../../asic_core/rtl/lean_silicon_lsc1.sv \
         ../../../asic_core/rtl/leanvm_b_stream_alu.sv \
         ../../../asic_core/rtl/gf128_mul_bitstream.sv \
         ../../../asic_core/rtl/gf2n_mul_bitstream.sv"

echo "=== SYNTH (full bridge + MinCore) ==="
yosys -p "
read_verilog -sv $SOURCES;
hierarchy -check -top ${TOP};
proc; check;
synth_ecp5 -top ${TOP};
write_json ${TOP}.json
" 2>&1 | tee "$OUTDIR/yosys_uart.log"

echo "=== PLACE+ROUTE (25 MHz, no --timing-allow-fail) ==="
nextpnr-ecp5 --85k --package CABGA381 --json ${TOP}.json --lpf ${LPF} --textcfg ${TOP}.config 2>&1 | tee "$OUTDIR/nextpnr_uart.log"

echo "=== PACK ==="
ecppack --svf ${TOP}.svf ${TOP}.config ${TOP}.bit 2>&1 | tee "$OUTDIR/ecppack_uart.log"

sha256sum ${TOP}.bit ${TOP}.config ${TOP}.svf 2>/dev/null | tee "$OUTDIR/SHA256SUMS"

grep -E 'Max frequency|Slack' "$OUTDIR/nextpnr_uart.log" | tail -5 | tee "$OUTDIR/timing_uart.txt" || true

echo "=== UART BUILD COMPLETE ==="
ls -l ${TOP}.bit
echo "bitstream: $(pwd)/${TOP}.bit"
echo "sha256: $(sha256sum ${TOP}.bit | cut -d' ' -f1)"
