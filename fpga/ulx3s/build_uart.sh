#!/bin/sh
# Build the UART bridge + lean_silicon_lsc1 for ULX3S v3.1.8.
# SRAM-only. Never use -f.
set -eu

# Resolve the repository root from this script's location. The RTL sources live
# under $ROOT/asic_core; a wrong number of ".." makes yosys read from outside
# the repository (or fail), and sends evidence outside the committed results
# directory.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
cd "$HERE"

TOP=ulx3s_top
LPF=ulx3s_v318_smoke.lpf
OUTDIR="$ROOT/results/ulx3s-smoke-uart-20260725"
mkdir -p "$OUTDIR"

# Name the artifact is archived and checksummed under; must match the file
# committed under results/.
BIT_NAME=ulx3s_bridge.bit

OSS_CAD_BIN=${OSS_CAD_BIN:-/root/oss/bin}
if [ -d "$OSS_CAD_BIN" ]; then
    PATH="$OSS_CAD_BIN:$PATH"
    export PATH
fi

echo "=== TOOL VERSIONS (UART) ===" | tee "$OUTDIR/tool_versions_uart.txt"
yosys -V 2>&1 | tee -a "$OUTDIR/tool_versions_uart.txt"
nextpnr-ecp5 --version 2>&1 | tee -a "$OUTDIR/tool_versions_uart.txt"
ecppack --version 2>&1 | tee -a "$OUTDIR/tool_versions_uart.txt"
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$OUTDIR/tool_versions_uart.txt"

# Collect sources: bridge + uart + exact ASIC top + MinCore + multiplier.
# Relative to this directory, which the cd above guarantees, so the paths that
# land in the archived yosys log are repository-relative and identical on any
# machine. The repository root is two levels up, not three.
SOURCES="ulx3s_top.sv uart_bridge.sv uart_rx.sv uart_tx.sv \
         ../../asic_core/rtl/lean_silicon_lsc1.sv \
         ../../asic_core/rtl/leanvm_b_stream_alu.sv \
         ../../asic_core/rtl/gf128_mul_bitstream.sv \
         ../../asic_core/rtl/gf2n_mul_bitstream.sv"

for src in $SOURCES; do
    [ -f "$src" ] || { echo "missing source: $src" >&2; exit 1; }
done

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

cp "${TOP}.bit" "$OUTDIR/$BIT_NAME"

( cd "$OUTDIR" && sha256sum "$BIT_NAME" > SHA256SUMS_bridge.txt )
( cd "$OUTDIR" && sha256sum -c SHA256SUMS_bridge.txt )

grep -E 'Max frequency|Slack' "$OUTDIR/nextpnr_uart.log" | tail -5 | tee "$OUTDIR/timing_uart.txt" || true

echo "=== UART BUILD COMPLETE ==="
ls -l "$OUTDIR/$BIT_NAME"
echo "bitstream: $OUTDIR/$BIT_NAME"
echo "sha256: $(sha256sum "$OUTDIR/$BIT_NAME" | cut -d' ' -f1)"
