#!/bin/sh
# Reproducible SRAM-only build of the packetized LSC-1 UART endpoint.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
SCRIPT="$HERE/$(basename -- "$0")"
cd "$HERE"

TOP=ulx3s_packet_top
LPF=ulx3s_v318_smoke.lpf
OUTDIR="$ROOT/results/ulx3s-lsc1-packet-20260726"
SUPPORT=../../tools/portable_build_support.py
LOCK="$ROOT/results/.ulx3s-lsc1-packet.publish.lock"
mkdir -p "$OUTDIR"
if [ "${ULX3S_PACKET_BUILD_LOCKED:-}" != 1 ]; then
    export ULX3S_PACKET_BUILD_LOCKED=1
    exec python3 "$SUPPORT" lock "$LOCK" -- "$SCRIPT" "$@"
fi
STAGE=$(mktemp -d "$(dirname "$OUTDIR")/.packet-build.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM

BIT_NAME=ulx3s_lsc1_packet.bit
CONFIG_NAME=ulx3s_lsc1_packet.config
SVF_NAME=ulx3s_lsc1_packet.svf
OSS_CAD_BIN=${OSS_CAD_BIN:-/root/oss/bin}
if [ -d "$OSS_CAD_BIN" ]; then
    PATH="$OSS_CAD_BIN:$PATH"
    export PATH
fi

YOSYS_VERSION=$(yosys -V)
NEXTPNR_VERSION=$(nextpnr-ecp5 --version 2>&1)
ECPPACK_VERSION=$(ecppack --version 2>&1)
[ "$YOSYS_VERSION" = "Yosys 0.33 (git sha1 2584903a060)" ] || {
    echo "unsupported yosys: $YOSYS_VERSION" >&2; exit 1;
}
[ "$NEXTPNR_VERSION" = '"nextpnr-ecp5" -- Next Generation Place and Route (Version nextpnr-0.11.1)' ] || {
    echo "unsupported nextpnr-ecp5: $NEXTPNR_VERSION" >&2; exit 1;
}
[ "$ECPPACK_VERSION" = "Project Trellis ecppack Version 1.4-2build4" ] || {
    echo "unsupported ecppack: $ECPPACK_VERSION" >&2; exit 1;
}
{
    echo "=== TOOL VERSIONS (LSC-1 PACKET UART) ==="
    echo "$YOSYS_VERSION"
    echo "$NEXTPNR_VERSION"
    echo "$ECPPACK_VERSION"
    echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$STAGE/tool_versions.txt" 2>&1
cat "$STAGE/tool_versions.txt"

SOURCES="ulx3s_packet_top.sv ulx3s_core_pll.sv uart_bridge.sv uart_rx.sv uart_tx.sv \
         ../../asic_core/rtl/lean_silicon_lsc1.sv \
         ../../asic_core/rtl/lean_silicon_lsc1_mincore.sv \
         ../../asic_core/rtl/lsc1_packet_frontend.sv \
         ../../asic_core/rtl/lsc1_packet_rx.sv \
         ../../asic_core/rtl/lsc1_packet_tx.sv \
         ../../asic_core/rtl/lsc1_stream_adapter.sv \
         ../../asic_core/rtl/lsc1_field_encoder.sv \
         ../../asic_core/rtl/lsc1_blake3_lifecycle.sv \
         ../../asic_core/rtl/lsc1_response_payload_mux.sv \
         ../../asic_core/rtl/lsc1_blake3_alias_check.sv \
         ../../asic_core/rtl/lsc1_request_validator.sv \
         ../../asic_core/rtl/lsc1_cell_alias_check.sv \
         ../../asic_core/rtl/leanvm_b_stream_alu.sv \
         ../../asic_core/rtl/gf128_mul_bitstream.sv \
         ../../asic_core/rtl/gf2n_mul_bitstream.sv"
for src in $SOURCES; do
    [ -f "$src" ] || { echo "missing source: $src" >&2; exit 1; }
done

python3 "$ROOT/tools/source_provenance.py" "$STAGE/SOURCE_MANIFEST.txt" \
    $SOURCES "$LPF" "$(basename -- "$0")" "$SUPPORT" \
    "$ROOT/tools/atomic_publish.py" "$ROOT/tools/source_provenance.py"

yosys -p "
read_verilog -lib +/ecp5/cells_sim.v +/ecp5/cells_bb.v;
read_verilog -sv $SOURCES;
hierarchy -check -top ${TOP};
proc; check;
synth_ecp5 -abc9 -nodffe -top ${TOP};
write_json ${TOP}.json
" > "$STAGE/yosys.log" 2>&1

nextpnr-ecp5 --85k --package CABGA381 --seed 2 --placer static \
    --no-tmdriv --router router1 \
    --json "${TOP}.json" --lpf "$LPF" --textcfg "${TOP}.config" \
    > "$STAGE/nextpnr.log" 2>&1 || {
    status=$?
    cat "$STAGE/nextpnr.log" >&2
    exit "$status"
}

ecppack --svf "${TOP}.svf" "${TOP}.config" "${TOP}.bit" \
    > "$STAGE/ecppack.log" 2>&1
cp "${TOP}.bit" "$STAGE/$BIT_NAME"
cp "${TOP}.config" "$STAGE/$CONFIG_NAME"
cp "${TOP}.svf" "$STAGE/$SVF_NAME"
grep -E 'Input frequency of PLL|Derived frequency constraint|Max frequency|Slack' \
    "$STAGE/nextpnr.log" | tail -8 \
    > "$STAGE/timing.txt" || true
python3 "$SUPPORT" manifest "$STAGE" SHA256SUMS \
    "$BIT_NAME" "$CONFIG_NAME" "$SVF_NAME"
python3 "$SUPPORT" check "$STAGE" SHA256SUMS
# The manifest was captured before synthesis. Refuse to publish if any tracked
# recipe, source or constraint changed while the tools were consuming it.
python3 "$ROOT/tools/source_provenance.py" --check "$STAGE/SOURCE_MANIFEST.txt"
python3 "$ROOT/tools/atomic_publish.py" "$STAGE" "$OUTDIR"

cat "$OUTDIR/timing.txt"
echo "bitstream: $OUTDIR/$BIT_NAME"
echo "sha256: $(python3 "$SUPPORT" digest "$OUTDIR/$BIT_NAME")"
