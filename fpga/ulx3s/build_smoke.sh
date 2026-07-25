#!/bin/sh
# Reproducible ULX3S v3.1.8 smoke build.
# Requires: yosys, nextpnr-ecp5, ecppack from OSS CAD Suite (no -f ever).
set -eu
cd "$(dirname "$0")"

TOP=smoke_top
LPF=ulx3s_v318_smoke.lpf
OUTDIR=../../../results/ulx3s-smoke-uart-20260725
mkdir -p "$OUTDIR"

echo "=== TOOL VERSIONS ===" | tee "$OUTDIR/tool_versions.txt"
yosys -V 2>&1 | tee -a "$OUTDIR/tool_versions.txt"
nextpnr-ecp5 --version 2>&1 | tee -a "$OUTDIR/tool_versions.txt"
ecppack --help 2>&1 | head -1 | tee -a "$OUTDIR/tool_versions.txt"
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$OUTDIR/tool_versions.txt"

echo "=== SYNTH ==="
yosys -p "read_verilog -sv ${TOP}.sv; hierarchy -check -top ${TOP}; proc; check; synth_ecp5 -top ${TOP}; write_json ${TOP}.json" 2>&1 | tee "$OUTDIR/yosys.log"

echo "=== PLACE+ROUTE (25 MHz, no --timing-allow-fail) ==="
nextpnr-ecp5 --85k --package CABGA381 --json ${TOP}.json --lpf ${LPF} --textcfg ${TOP}.config 2>&1 | tee "$OUTDIR/nextpnr.log"

echo "=== PACK ==="
ecppack --svf ${TOP}.svf ${TOP}.config ${TOP}.bit 2>&1 | tee "$OUTDIR/ecppack.log"

sha256sum ${TOP}.bit ${TOP}.config ${TOP}.svf 2>/dev/null | tee "$OUTDIR/SHA256SUMS"

# Capture timing line for report
grep -E 'Max frequency|Slack' "$OUTDIR/nextpnr.log" | tail -5 | tee "$OUTDIR/timing.txt" || true

echo "=== BUILD COMPLETE ==="
ls -l ${TOP}.bit
echo "bitstream: $(pwd)/${TOP}.bit"
echo "sha256: $(sha256sum ${TOP}.bit | cut -d' ' -f1)"
