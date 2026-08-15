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
SUPPORT=../../tools/portable_build_support.py
mkdir -p "$OUTDIR"
LOCK="$ROOT/results/.ulx3s-smoke-uart.publish.lock"
if [ "${ULX3S_BUILD_LOCKED:-}" != 1 ]; then
    exec python3 "$SUPPORT" lock "$LOCK" -- "$0" "$@"
fi
STAGE=$(mktemp -d "$(dirname "$OUTDIR")/.uart-build.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
cp -a "$OUTDIR/." "$STAGE/"

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

# Collect sources: bridge + UART + packetized ASIC top + stream adapter,
# diagnostic MinCore top and the shared arithmetic datapath.
# Relative to this directory, which the cd above guarantees, so the paths that
# land in the archived yosys log are repository-relative and identical on any
# machine. The repository root is two levels up, not three.
SOURCES="ulx3s_top.sv uart_bridge.sv uart_rx.sv uart_tx.sv \
         ../../asic_core/rtl/lean_silicon_lsc1.sv \
         ../../asic_core/rtl/lean_silicon_lsc1_mincore.sv \
         ../../asic_core/rtl/lsc1_packet_frontend.sv \
         ../../asic_core/rtl/lsc1_field_encoder.sv \
         ../../asic_core/rtl/lsc1_blake3_lifecycle.sv \
         ../../asic_core/rtl/lsc1_packet_rx.sv \
         ../../asic_core/rtl/lsc1_packet_tx.sv \
         ../../asic_core/rtl/lsc1_stream_adapter.sv \
         ../../asic_core/rtl/leanvm_b_stream_alu.sv \
         ../../asic_core/rtl/gf128_mul_bitstream.sv \
         ../../asic_core/rtl/gf2n_mul_bitstream.sv"

for src in $SOURCES; do
    [ -f "$src" ] || { echo "missing source: $src" >&2; exit 1; }
done

# Record which revision these exact inputs came from, so the archive identifies
# its own source instead of relying on a hand-maintained note. The recipe is an
# input as much as the RTL is: changing a yosys or nextpnr flag here changes the
# bitstream, so a manifest that digests only $SOURCES and $LPF would still
# report a match for an artifact HEAD cannot reproduce.
RECIPE=$(basename -- "$0")
python3 "$ROOT/tools/source_provenance.py" "$STAGE/SOURCE_MANIFEST_uart.txt" \
    $SOURCES "$LPF" "$RECIPE" "$SUPPORT" "$ROOT/tools/atomic_publish.py" \
    "$ROOT/tools/source_provenance.py"

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

python3 "$SUPPORT" manifest "$STAGE" SHA256SUMS_bridge.txt "$BIT_NAME"
python3 "$SUPPORT" check "$STAGE" SHA256SUMS_bridge.txt

grep -E 'Max frequency|Slack' "$STAGE/nextpnr_uart.log" | tail -5 > "$STAGE/timing_uart.txt" || true

python3 "$ROOT/tools/source_provenance.py" --check "$STAGE/SOURCE_MANIFEST_uart.txt"
python3 "$ROOT/tools/atomic_publish.py" "$STAGE" "$OUTDIR"
cat "$OUTDIR/timing_uart.txt"

echo "=== UART BUILD COMPLETE ==="
ls -l "$OUTDIR/$BIT_NAME"
echo "bitstream: $OUTDIR/$BIT_NAME"
echo "sha256: $(python3 "$SUPPORT" digest "$OUTDIR/$BIT_NAME")"
