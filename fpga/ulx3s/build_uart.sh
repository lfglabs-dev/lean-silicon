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
STAGE=$(mktemp -d "$OUTDIR/.uart-build.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM

# Name the artifact is archived and checksummed under; must match the file
# committed under results/.
BIT_NAME=ulx3s_bridge.bit

OSS_CAD_BIN=${OSS_CAD_BIN:-/root/oss/bin}
if [ -d "$OSS_CAD_BIN" ]; then
    PATH="$OSS_CAD_BIN:$PATH"
    export PATH
fi

{
    echo "=== TOOL VERSIONS (UART) ==="
    yosys -V
    nextpnr-ecp5 --version
    ecppack --version
    echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$STAGE/tool_versions_uart.txt" 2>&1
cat "$STAGE/tool_versions_uart.txt"

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
" > "$STAGE/yosys_uart.log" 2>&1 || {
    status=$?
    cat "$STAGE/yosys_uart.log"
    exit "$status"
}
cat "$STAGE/yosys_uart.log"

echo "=== PLACE+ROUTE (25 MHz, no --timing-allow-fail) ==="
nextpnr-ecp5 --85k --package CABGA381 --json ${TOP}.json --lpf ${LPF} --textcfg ${TOP}.config \
    > "$STAGE/nextpnr_uart.log" 2>&1 || {
    status=$?
    cat "$STAGE/nextpnr_uart.log"
    exit "$status"
}
cat "$STAGE/nextpnr_uart.log"

echo "=== PACK ==="
ecppack --svf ${TOP}.svf ${TOP}.config ${TOP}.bit > "$STAGE/ecppack_uart.log" 2>&1 || {
    status=$?
    cat "$STAGE/ecppack_uart.log"
    exit "$status"
}
cat "$STAGE/ecppack_uart.log"

cp "${TOP}.bit" "$STAGE/$BIT_NAME"

( cd "$STAGE" && sha256sum "$BIT_NAME" > SHA256SUMS_bridge.txt )
( cd "$STAGE" && sha256sum -c SHA256SUMS_bridge.txt )

grep -E 'Max frequency|Slack' "$STAGE/nextpnr_uart.log" | tail -5 > "$STAGE/timing_uart.txt" || true

for artifact in tool_versions_uart.txt yosys_uart.log nextpnr_uart.log \
                ecppack_uart.log "$BIT_NAME" SHA256SUMS_bridge.txt timing_uart.txt; do
    mv "$STAGE/$artifact" "$OUTDIR/$artifact"
done
cat "$OUTDIR/timing_uart.txt"

echo "=== UART BUILD COMPLETE ==="
ls -l "$OUTDIR/$BIT_NAME"
echo "bitstream: $OUTDIR/$BIT_NAME"
echo "sha256: $(sha256sum "$OUTDIR/$BIT_NAME" | cut -d' ' -f1)"
